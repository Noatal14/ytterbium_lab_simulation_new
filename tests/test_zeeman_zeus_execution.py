import hashlib
import os
from pathlib import Path
import threading
import json
import base64
import subprocess
import sys

import pytest
import numpy as np

from workflow_api.run_discovery import inspect_run
from workflow_api.run_execution import WorkerProduct, issue_execution_authority
from workflow_api.run_records import RunRecordStore, encode_record
from workflow_api.run_specification import INDIVIDUAL_RUN_SPECIFICATION
from workflow_api.zeeman_run_plan import build_zeeman_run_plan
from workflow_api.zeeman_zeus_execution import (
    IndividualZeemanZeusCoordinator,
    RemoteJobStatus,
    RemoteSubmission,
    ZeemanZeusError,
    PinnedSshZeemanTransport,
    _package_payload,
    build_frozen_package,
    ZeusBindingStore,
)
from workflow_api.mot_2d_zeus_execution import IndividualMot2DZeusCoordinator
from workflow_api.zeeman_zeus_worker import execute_package
from workflow_api.zeeman_local_execution import ZeemanLocalWorker
from workflow_api.zeus_snapshot import ZeusProfile


NOW = "2026-10-11T12:00:00+00:00"
PROFILE = ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new")


def _create(root: Path, *, retained=False):
    records = build_zeeman_run_plan(
        {
            "particle_count": 4,
            "seed": 71,
            "retain_particle_states": retained,
            "execution_mode": "zeus",
        },
        run_id="zeeman-zeus-001",
        git_revision="a" * 40,
        created_utc=NOW,
    ).storage_records()
    store = RunRecordStore(root)
    try:
        store.create(
            records["run"],
            records["configuration"],
            records["inputs"],
            records["status"],
        )
    finally:
        store.close()
    return records


def _product():
    receipt = {
        "schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"][
            "retention_receipt"
        ],
        "run_id": "zeeman-zeus-001",
        "created_utc": NOW,
        "reason": "particle_states_not_retained",
    }
    raw = encode_record("retention_receipt", receipt)
    return WorkerProduct(
        results={
            "schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"][
                "results"
            ],
            "run_id": "zeeman-zeus-001",
            "completed_utc": NOW,
            "states_retained": False,
            "suitability": "individual_only",
            "metrics": {
                "n_initial": 4,
                "n_survivors": 2,
                "captured": 2,
                "survival_fraction": 0.5,
                "elapsed_s": 1.0,
            },
            "artifacts": [
                {
                    "kind": "retention_receipt",
                    "path": "results/state_retention_receipt.json",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size_bytes": len(raw),
                }
            ],
        },
        receipt=receipt,
        artifacts={},
    )


class Transport:
    operations = frozenset({"inspect", "stage", "submit", "status", "retrieve"})

    def __init__(self):
        self.calls = []
        self.inspect_result = RemoteSubmission("absent")
        self.submit_result = RemoteSubmission(
            "submitted", "1" * 32, "12345.zeus-master"
        )
        self.remote_status = RemoteJobStatus("12345.zeus-master", "queued")
        self.product = _product()
        self.submit_error = None

    def inspect(self, **kwargs):
        self.calls.append(("inspect", kwargs))
        return self.inspect_result

    def submit(self, **kwargs):
        self.calls.append(("submit", kwargs))
        if self.submit_error:
            raise self.submit_error
        return self.submit_result

    def stage(self, **kwargs):
        self.calls.append(("stage", kwargs))
        return RemoteSubmission("absent", kwargs["nonce"], None)

    def status(self, **kwargs):
        self.calls.append(("status", kwargs))
        return self.remote_status

    def retrieve(self, **kwargs):
        self.calls.append(("retrieve", kwargs))
        return self.product


def _coordinator(root, transport, *, ticks=None):
    return IndividualZeemanZeusCoordinator(
        root,
        issue_execution_authority(),
        lambda _profile: transport,
        clock=(iter(ticks).__next__ if ticks else lambda: 100.0),
        utc_clock=lambda: NOW,
        token_factory=lambda: "preview-token",
        nonce_factory=lambda: "1" * 32,
    )


def _preview(coordinator, session="owner"):
    return coordinator.preview(
        run_id="zeeman-zeus-001", profile=PROFILE, session=session
    )


def test_preview_is_immutable_scalar_and_has_no_submission_side_effect(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    coordinator = _coordinator(root, transport)
    preview = _preview(coordinator)

    assert preview["job"] == {
        "kind": "scalar",
        "array": False,
        "pbs_sha256": preview["job"]["pbs_sha256"],
        "resources": {
            "queue": "zeus_combined_q",
            "cores": 200,
            "memory_bytes": 68719476736,
            "walltime_seconds": 86400,
        },
    }
    assert preview["effects"] == {
        "submit_one_job": True,
        "reconcile_existing_job": False,
        "cancel_job": False,
    }
    assert [name for name, _ in transport.calls] == ["inspect"]
    package = transport.calls[0][1]["package"]
    assert b"#PBS -J" not in package.pbs
    assert package.pbs.count(b"#PBS -q zeus_combined_q\n") == 1
    assert hashlib.sha256(package.pbs).hexdigest() == package.pbs_sha256
    assert package.package_sha256 == preview["package_sha256"]
    assert (
        inspect_run(root, "zeeman", "zeeman-zeus-001").status["state"] == "configured"
    )


def test_confirm_is_session_bound_at_most_once_and_binds_canonical_job_id(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    coordinator = _coordinator(root, transport)
    token = _preview(coordinator)["preview_token"]
    with pytest.raises(ZeemanZeusError, match="confirmation_invalid"):
        coordinator.confirm(preview_token=token, session="other")

    first = coordinator.confirm(preview_token=token, session="owner")
    second = coordinator.confirm(preview_token=token, session="owner")
    assert first == second
    assert [name for name, _ in transport.calls].count("submit") == 1
    assert [name for name, _ in transport.calls].count("stage") == 1
    status = inspect_run(root, "zeeman", "zeeman-zeus-001").status
    assert status["state"] == "queued"
    assert status["execution"]["zeus_job_id"] == "12345.zeus-master"


@pytest.mark.parametrize(
    "job_id",
    [
        "12345[] .zeus-master",
        "12345[].zeus-master",
        "12345[0].zeus-master",
        "abc.zeus-master",
    ],
)
def test_non_scalar_or_noncanonical_job_id_is_terminal_unknown(tmp_path, job_id):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    transport.submit_result = RemoteSubmission("submitted", "1" * 32, job_id)
    coordinator = _coordinator(root, transport)
    token = _preview(coordinator)["preview_token"]
    with pytest.raises(ZeemanZeusError, match="submission_outcome_unknown"):
        coordinator.confirm(preview_token=token, session="owner")
    assert (
        inspect_run(root, "zeeman", "zeeman-zeus-001").status["state"]
        == "outcome_unknown"
    )
    with pytest.raises(ZeemanZeusError, match="submission_outcome_unknown"):
        coordinator.confirm(preview_token=token, session="owner")
    assert [name for name, _ in transport.calls].count("submit") == 1


def test_transport_exception_blocks_retry_and_marks_unknown(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    transport.submit_error = TimeoutError()
    coordinator = _coordinator(root, transport)
    token = _preview(coordinator)["preview_token"]
    with pytest.raises(ZeemanZeusError, match="submission_outcome_unknown"):
        coordinator.confirm(preview_token=token, session="owner")
    assert (
        inspect_run(root, "zeeman", "zeeman-zeus-001").status["state"]
        == "outcome_unknown"
    )


def test_status_targets_only_frozen_job_and_d3_validates_before_success(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    coordinator = _coordinator(root, transport)
    token = _preview(coordinator)["preview_token"]
    submitted = coordinator.confirm(preview_token=token, session="owner")
    transport.remote_status = RemoteJobStatus(submitted["job_id"], "succeeded", 0)

    result = coordinator.refresh(run_id="zeeman-zeus-001", profile=PROFILE)
    assert result == {"state": "succeeded", "job_id": "12345.zeus-master"}
    status_call = next(payload for name, payload in transport.calls if name == "status")
    retrieve_call = next(
        payload for name, payload in transport.calls if name == "retrieve"
    )
    assert status_call["job_id"] == "12345.zeus-master"
    assert set(status_call) == {"job_id", "submission_key"}
    assert retrieve_call["job_id"] == "12345.zeus-master"
    inspected = inspect_run(root, "zeeman", "zeeman-zeus-001")
    assert inspected.integrity == "complete_verified"
    assert inspected.results["metrics"]["n_survivors"] == 2


def test_failed_scheduler_state_never_retrieves(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    coordinator = _coordinator(root, transport)
    coordinator.confirm(
        preview_token=_preview(coordinator)["preview_token"], session="owner"
    )
    transport.remote_status = RemoteJobStatus("12345.zeus-master", "failed", 1)
    assert (
        coordinator.refresh(run_id="zeeman-zeus-001", profile=PROFILE)["state"]
        == "failed"
    )
    assert "retrieve" not in [name for name, _ in transport.calls]


def test_fake_transport_must_expose_exact_allowlist_and_no_cancel(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    transport.operations = frozenset(
        {"inspect", "stage", "submit", "status", "retrieve", "cancel"}
    )
    with pytest.raises(ZeemanZeusError, match="transport_not_allowlisted"):
        _preview(_coordinator(root, transport))


def test_expired_preview_does_not_submit(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    coordinator = _coordinator(root, transport, ticks=[0.0, 0.0, 301.0])
    token = _preview(coordinator)["preview_token"]
    with pytest.raises(ZeemanZeusError, match="confirmation_expired"):
        coordinator.confirm(preview_token=token, session="owner")
    assert [name for name, _ in transport.calls] == ["inspect"]


def test_preview_rejects_ambiguous_existing_submission(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    transport.inspect_result = RemoteSubmission("ambiguous")
    with pytest.raises(ZeemanZeusError, match="submission_outcome_unknown"):
        _preview(_coordinator(root, transport))
    assert [name for name, _ in transport.calls] == ["inspect"]


def test_nonce_mismatch_is_terminal_and_never_retried(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    transport.submit_result = RemoteSubmission(
        "submitted", "2" * 32, "12345.zeus-master"
    )
    coordinator = _coordinator(root, transport)
    token = _preview(coordinator)["preview_token"]
    for _ in range(2):
        with pytest.raises(ZeemanZeusError, match="submission_outcome_unknown"):
            coordinator.confirm(preview_token=token, session="owner")
    assert [name for name, _ in transport.calls].count("submit") == 1


def test_changed_local_evidence_after_preview_prevents_qsub(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    coordinator = _coordinator(root, transport)
    token = _preview(coordinator)["preview_token"]
    # A legitimate lifecycle mutation is enough to stale the reviewed package.
    authority = coordinator.authority
    store = coordinator.store_factory(root)
    try:
        evidence, lease = store.evidence_snapshot(
            authority, "zeeman", "zeeman-zeus-001"
        )
        store.transition(
            authority,
            "zeeman",
            "zeeman-zeus-001",
            expected_revision=0,
            target_state="validated",
            updated_utc=NOW,
            lease=lease,
        )
    finally:
        store.close()
    with pytest.raises(ZeemanZeusError, match="run_not_submittable"):
        coordinator.confirm(preview_token=token, session="owner")
    assert [name for name, _ in transport.calls].count("submit") == 0


def test_concurrent_double_confirm_invokes_qsub_once(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    coordinator = _coordinator(root, transport)
    token = _preview(coordinator)["preview_token"]
    barrier = threading.Barrier(3)
    results = []

    def invoke():
        barrier.wait()
        results.append(coordinator.confirm(preview_token=token, session="owner"))

    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)
    assert len(results) == 2 and results[0] == results[1]
    assert [name for name, _ in transport.calls].count("submit") == 1


def test_status_response_for_another_job_is_rejected_without_retrieval(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    coordinator = _coordinator(root, transport)
    coordinator.confirm(
        preview_token=_preview(coordinator)["preview_token"], session="owner"
    )
    transport.remote_status = RemoteJobStatus("99999.zeus-master", "succeeded", 0)
    with pytest.raises(ZeemanZeusError, match="remote_status_invalid"):
        coordinator.refresh(run_id="zeeman-zeus-001", profile=PROFILE)
    assert "retrieve" not in [name for name, _ in transport.calls]


def test_invalid_retrieved_metrics_fail_before_success(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    coordinator = _coordinator(root, transport)
    coordinator.confirm(
        preview_token=_preview(coordinator)["preview_token"], session="owner"
    )
    transport.remote_status = RemoteJobStatus("12345.zeus-master", "succeeded", 0)
    valid = _product()
    broken_results = dict(valid.results)
    broken_results["metrics"] = {**broken_results["metrics"], "n_survivors": 5}
    transport.product = WorkerProduct(broken_results, valid.receipt, valid.artifacts)
    assert (
        coordinator.refresh(run_id="zeeman-zeus-001", profile=PROFILE)["state"]
        == "failed"
    )
    inspected = inspect_run(root, "zeeman", "zeeman-zeus-001")
    assert inspected.status["state"] == "failed"
    assert inspected.results is None


def test_contract_contains_no_cancellation_surface():
    assert not hasattr(IndividualZeemanZeusCoordinator, "cancel")
    source = (
        Path(__file__)
        .parents[1]
        .joinpath("workflow_api/zeeman_zeus_execution.py")
        .read_text()
    )
    assert "qdel" not in source


def test_real_worker_validates_frozen_package_and_invokes_adapter_once(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    root.mkdir()
    records = _create(root)
    package = build_frozen_package(records, PROFILE)
    package_dir = root / ".workflow/individual-zeeman" / package.package_sha256
    package_dir.mkdir(parents=True)
    path = package_dir / "package.json"
    path.write_bytes(
        json.dumps(
            _package_payload(package), sort_keys=True, separators=(",", ":")
        ).encode()
    )
    monkeypatch.chdir(root)
    calls = []

    class Worker:
        def run(self, request):
            calls.append(request)
            return _product()

    first = execute_package(
        path.relative_to(root), package.package_sha256, worker_factory=lambda: Worker()
    )
    # Resolve relative package exactly as PBS does from the project root.
    assert first["run_id"] == "zeeman-zeus-001"
    assert first["package_sha256"] == package.package_sha256
    assert len(calls) == 1
    second = execute_package(
        path.relative_to(root), package.package_sha256, worker_factory=lambda: Worker()
    )
    assert second == first and len(calls) == 1


def test_real_worker_rejects_package_digest_drift_before_adapter(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    records = _create(root)
    package = build_frozen_package(records, PROFILE)
    package_dir = root / ".workflow/individual-zeeman" / package.package_sha256
    package_dir.mkdir(parents=True)
    path = package_dir / "package.json"
    payload = _package_payload(package)
    payload["commit"] = "b" * 40
    path.write_bytes(json.dumps(payload).encode())
    monkeypatch.chdir(root)
    with pytest.raises(ValueError, match="digest"):
        execute_package(
            path.relative_to(root),
            package.package_sha256,
            worker_factory=lambda: (_ for _ in ()).throw(AssertionError()),
        )


def test_zeus_worker_uses_same_e4_adapter_with_frozen_server_worker_count(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    root.mkdir()
    records = _create(root)
    package = build_frozen_package(records, PROFILE)
    directory = root / ".workflow/individual-zeeman" / package.package_sha256
    directory.mkdir(parents=True)
    path = directory / "package.json"
    path.write_bytes(
        json.dumps(
            _package_payload(package), sort_keys=True, separators=(",", ":")
        ).encode()
    )
    calls = []

    def engine(**kwargs):
        calls.append(kwargs)
        return (
            object(),
            np.empty((0, 6), dtype=np.float64),
            np.array([], dtype=np.int64),
        )

    monkeypatch.chdir(root)
    execute_package(
        path.relative_to(root),
        package.package_sha256,
        worker_factory=lambda: ZeemanLocalWorker(
            engine=engine, monotonic=iter([1.0, 2.0]).__next__, clock=lambda: NOW
        ),
    )
    assert len(calls) == 1 and calls[0]["npools"] == 200
    assert calls[0]["N_particles"] == 4 and calls[0]["seed"] == 71


def test_pinned_transport_uses_only_dedicated_receiver_operations(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    records = _create(root)
    ssh = tmp_path / "ssh"
    ssh.write_text("")
    ssh.chmod(0o700)
    transport = PinnedSshZeemanTransport(root, ssh, PROFILE)
    package = build_frozen_package(records, PROFILE)
    calls = []

    class Completed:
        returncode = 0
        stderr = b""
        stdout = b'{"state":"absent","nonce":null,"job_id":null}'

    def run(operation, profile, payload):
        calls.append((operation.value, profile, payload))
        return Completed()

    transport.runner.run = run
    assert transport.inspect(package=package, nonce="1" * 32).state == "absent"
    assert calls[0][0] == "inspect"
    assert calls[0][1] == PROFILE
    assert set(calls[0][2]) == {"identity", "nonce"}


def test_receiver_source_has_fixed_qsub_and_targeted_qstat_only():
    source = (
        Path(__file__)
        .parents[1]
        .joinpath("workflow_api/zeeman_zeus_remote.py")
        .read_text()
    )
    assert '["/usr/local/bin/qsub"]' in source
    assert '["/usr/local/bin/qstat", "-x", "-t", "-f", request["job_id"]]' in source
    assert "qdel" not in source and "shell=False" in source


def _receiver_repository_root():
    # The temporary standalone script needs the real package for its native
    # Windows locking fallback; no ambient PYTHONPATH authority is inherited.
    return Path(sys.modules[IndividualZeemanZeusCoordinator.__module__].__file__).resolve().parents[1]


def _receiver_harness(tmp_path, records, *, qsub_exit=0):
    project = tmp_path / "project"
    project.mkdir()
    package = build_frozen_package(records, PROFILE)
    qsub = tmp_path / "qsub"
    calls = tmp_path / "qsub.calls"
    qsub.write_text(
        "#!/bin/sh\nprintf x >> "
        + str(calls)
        + "\ncat >/dev/null\n"
        + ("echo 43210.zeus-master\n" if qsub_exit == 0 else "")
        + f"exit {qsub_exit}\n"
    )
    qsub.chmod(0o700)
    source = (
        _receiver_repository_root()
        .joinpath("workflow_api/zeeman_zeus_remote.py")
        .read_text()
    )
    source = (
        source.replace(
            'allowed = {Path("/home") / username / name for name in ("ytterbium_lab_simulation_new", "ytterbium_lab_simulation_ui_test")}',
            "allowed = {project}",
        )
        .replace(
            '"project_directory": str(project)',
            '"project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"',
        )
        .replace(
            'value["project_directory"] != str(project)',
            'value["project_directory"] != "/home/tal.noa/ytterbium_lab_simulation_new"',
        )
        .replace(
            'verify_commit(identity["commit"])',
            "None",
        )
        .replace(
            'verify_commit(receipt.get("commit"))',
            "None",
        )
        .replace('"/usr/local/bin/qsub"', repr(str(qsub)))
    )
    script = tmp_path / "receiver.py"
    script.write_text(source)

    def invoke(operation):
        request = {"identity": _package_payload(package), "nonce": "1" * 32}
        encoded = base64.urlsafe_b64encode(json.dumps(request).encode()).decode()
        return subprocess.run(
            [sys.executable, str(script), operation, "tal.noa", str(project), encoded],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "PYTHONPATH": str(_receiver_repository_root())},
        )

    return package, calls, invoke


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_receiver_is_at_most_once_across_process_restarts(tmp_path):
    root = tmp_path / "local"
    root.mkdir()
    records = _create(root)
    package, calls, invoke = _receiver_harness(tmp_path, records)
    assert invoke("stage").returncode == 0
    first = invoke("submit")
    second = invoke("submit")
    assert first.returncode == second.returncode == 0
    assert json.loads(first.stdout)["job_id"] == "43210.zeus-master"
    assert json.loads(second.stdout) == json.loads(first.stdout)
    assert calls.read_text() == "x"
    receipt = tmp_path / "project/.workflow/individual-zeeman/submissions"
    assert (receipt / f"{package.submission_key}.json").is_file()


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_receiver_durable_pending_blocks_retry_after_ambiguous_qsub(tmp_path):
    root = tmp_path / "local"
    root.mkdir()
    records = _create(root)
    _package, calls, invoke = _receiver_harness(tmp_path, records, qsub_exit=1)
    assert invoke("stage").returncode == 0
    first = invoke("submit")
    second = invoke("submit")
    assert first.returncode != 0 and second.returncode != 0
    assert json.loads(first.stdout) == {"error": "submission_outcome_unknown"}
    assert json.loads(second.stdout) == {"error": "submission_outcome_unknown"}
    assert calls.read_text() == "x"


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_receiver_concurrent_submit_processes_invoke_qsub_at_most_once(tmp_path):
    root = tmp_path / "local"
    root.mkdir()
    records = _create(root)
    _package, calls, invoke = _receiver_harness(tmp_path, records)
    assert invoke("stage").returncode == 0
    barrier = threading.Barrier(3)
    completed = []

    def submit():
        barrier.wait()
        completed.append(invoke("submit"))

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10)
    assert len(completed) == 2
    assert calls.read_text() == "x"
    assert any(result.returncode == 0 for result in completed)
    assert all(
        result.returncode == 0
        or json.loads(result.stdout)["error"] == "submission_busy"
        for result in completed
    )


def test_receiver_rejects_malicious_package_before_qsub(tmp_path):
    root = tmp_path / "local"
    root.mkdir()
    records = _create(root)
    package, calls, invoke = _receiver_harness(tmp_path, records)
    # Build the receiver invocation directly with a forged digest and command-like id.
    project = tmp_path / "project"
    script = tmp_path / "receiver.py"
    identity = _package_payload(package)
    identity["package_sha256"] = "0" * 64
    identity["run_id"] = "x; qsub evil"
    request = {"identity": identity, "nonce": "1" * 32}
    encoded = base64.urlsafe_b64encode(json.dumps(request).encode()).decode()
    result = subprocess.run(
        [sys.executable, str(script), "submit", "tal.noa", str(project), encoded],
        text=True,
        capture_output=True,
        check=False,
            env={**os.environ, "PYTHONPATH": str(_receiver_repository_root())},
    )
    assert result.returncode != 0
    assert json.loads(result.stdout) == {"error": "remote_package_invalid"}
    assert not calls.exists()


def test_fresh_coordinator_reconciles_post_qsub_pre_local_cas_crash_without_resubmit(
    tmp_path,
):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)

    class Durable(Transport):
        def __init__(self):
            super().__init__()
            self.receipt = None
            self.crash = True

        def inspect(self, **kwargs):
            self.calls.append(("inspect", kwargs))
            return self.receipt or RemoteSubmission("absent")

        def submit(self, **kwargs):
            self.calls.append(("submit", kwargs))
            self.receipt = RemoteSubmission(
                "submitted", kwargs["nonce"], "12345.zeus-master"
            )
            if self.crash:
                raise KeyboardInterrupt("simulated process death after qsub")
            return self.receipt

    transport = Durable()
    first = _coordinator(root, transport)
    token = _preview(first)["preview_token"]
    with pytest.raises(KeyboardInterrupt):
        first.confirm(preview_token=token, session="owner")
    assert (
        inspect_run(root, "zeeman", "zeeman-zeus-001").status["state"] == "configured"
    )

    transport.crash = False
    restarted = IndividualZeemanZeusCoordinator(
        root,
        issue_execution_authority(),
        lambda _profile: transport,
        clock=lambda: 100.0,
        utc_clock=lambda: NOW,
        token_factory=lambda: "recovery-token",
        nonce_factory=lambda: "2" * 32,
    )
    recovery = _preview(restarted)
    assert recovery["effects"]["reconcile_existing_job"] is True
    result = restarted.confirm(preview_token=recovery["preview_token"], session="owner")
    assert result["job_id"] == "12345.zeus-master"
    assert [name for name, _ in transport.calls].count("submit") == 1
    assert inspect_run(root, "zeeman", "zeeman-zeus-001").status["state"] == "queued"


def test_wrong_profile_is_rejected_after_restart_before_status_query(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    first = _coordinator(root, transport)
    first.confirm(preview_token=_preview(first)["preview_token"], session="owner")
    restarted = _coordinator(root, transport)
    wrong = ZeusProfile("other", "/home/other/ytterbium_lab_simulation_new")
    before = len(transport.calls)
    with pytest.raises(
        ZeemanZeusError, match="profile_or_submission_identity_mismatch"
    ):
        restarted.refresh(run_id="zeeman-zeus-001", profile=wrong)
    assert len(transport.calls) == before


def test_fresh_coordinator_turns_durable_remote_pending_into_outcome_unknown(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)

    class Pending(Transport):
        def __init__(self):
            super().__init__()
            self.pending = False

        def inspect(self, **kwargs):
            self.calls.append(("inspect", kwargs))
            if self.pending:
                raise ZeemanZeusError("submission_outcome_unknown")
            return RemoteSubmission("absent")

        def submit(self, **kwargs):
            self.calls.append(("submit", kwargs))
            self.pending = True
            raise KeyboardInterrupt("process death with remote pending ledger")

    transport = Pending()
    first = _coordinator(root, transport)
    with pytest.raises(KeyboardInterrupt):
        first.confirm(preview_token=_preview(first)["preview_token"], session="owner")
    assert (
        inspect_run(root, "zeeman", "zeeman-zeus-001").status["state"] == "configured"
    )
    restarted = _coordinator(root, transport)
    with pytest.raises(ZeemanZeusError, match="submission_outcome_unknown"):
        _preview(restarted)
    assert (
        inspect_run(root, "zeeman", "zeeman-zeus-001").status["state"]
        == "outcome_unknown"
    )
    assert [name for name, _ in transport.calls].count("submit") == 1


def test_recovery_also_handles_crash_after_partial_local_admission(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    records = _create(root)
    authority = issue_execution_authority()
    store = ZeusBindingStore(root)
    package = build_frozen_package(records, PROFILE)
    try:
        evidence, lease = store.evidence_snapshot(
            authority, "zeeman", "zeeman-zeus-001"
        )
        store.bind(authority, package, "1" * 32, lease)
        evidence, lease = store.evidence_snapshot(
            authority,
            "zeeman",
            "zeeman-zeus-001",
            prior_lease=lease,
            allow_run_metadata_change=True,
        )
        store.transition(
            authority,
            "zeeman",
            "zeeman-zeus-001",
            expected_revision=0,
            target_state="validated",
            updated_utc=NOW,
            lease=lease,
        )
    finally:
        store.close()
    transport = Transport()
    transport.inspect_result = RemoteSubmission(
        "submitted", "1" * 32, "12345.zeus-master"
    )
    coordinator = IndividualZeemanZeusCoordinator(
        root,
        authority,
        lambda _profile: transport,
        clock=lambda: 100.0,
        utc_clock=lambda: NOW,
        token_factory=lambda: "partial-recovery",
        nonce_factory=lambda: "2" * 32,
    )
    preview = _preview(coordinator)
    assert preview["effects"]["reconcile_existing_job"] is True
    coordinator.confirm(preview_token=preview["preview_token"], session="owner")
    assert inspect_run(root, "zeeman", "zeeman-zeus-001").status["state"] == "queued"
    assert [name for name, _ in transport.calls].count("submit") == 0


def _submitted_for_read_only_recovery(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _create(root)
    transport = Transport()
    coordinator = _coordinator(root, transport)
    confirmed = coordinator.confirm(
        preview_token=_preview(coordinator)["preview_token"], session="owner"
    )
    return root, transport, coordinator, confirmed


@pytest.mark.parametrize(
    ("remote_state", "exit_status"),
    [
        ("queued", None),
        ("held", -10),
        ("running", None),
        ("succeeded", 0),
        ("failed", 7),
    ],
)
def test_read_only_recovery_reports_scheduler_without_mutating_run(
    tmp_path, remote_state, exit_status
):
    root, transport, coordinator, confirmed = _submitted_for_read_only_recovery(
        tmp_path
    )
    transport.remote_status = RemoteJobStatus(
        confirmed["job_id"], remote_state, exit_status
    )
    run_dir = root / "data/runs/zeeman/zeeman-zeus-001"
    before = {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    recovered = coordinator.recover(
        run_id="zeeman-zeus-001",
        profile=PROFILE,
        session="fresh-browser-session",
    )
    after = {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    assert recovered == {
        "run_id": "zeeman-zeus-001",
        "family": "zeeman",
        "job_id": confirmed["job_id"],
        "scheduler_state": remote_state,
        "exit_status": exit_status,
        "local_state": "queued",
        "read_only": True,
    }
    assert after == before
    assert [name for name, _ in transport.calls].count("submit") == 1
    assert [name for name, _ in transport.calls].count("status") == 1


@pytest.mark.parametrize("field", ["profile", "session"])
def test_read_only_recovery_rejects_wrong_context_before_status(tmp_path, field):
    _root, transport, coordinator, confirmed = _submitted_for_read_only_recovery(
        tmp_path
    )
    request = {
        "run_id": "zeeman-zeus-001",
        "profile": PROFILE,
        "session": "fresh-browser-session",
    }
    request[field] = {
        "profile": ZeusProfile("other", "/home/other/ytterbium_lab_simulation_new"),
        "session": "",
    }[field]
    before = len(transport.calls)
    with pytest.raises(ZeemanZeusError):
        coordinator.recover(**request)
    assert len(transport.calls) == before


def test_read_only_recovery_rejects_malformed_durable_binding(tmp_path):
    root, transport, coordinator, confirmed = _submitted_for_read_only_recovery(
        tmp_path
    )
    binding_path = root / "data/runs/zeeman/zeeman-zeus-001/.zeus-execution.json"
    binding = json.loads(binding_path.read_text())
    binding["version"] = True
    binding_path.write_text(json.dumps(binding))
    before = len(transport.calls)
    with pytest.raises(ZeemanZeusError, match="submission_identity_invalid"):
        coordinator.recover(
            run_id="zeeman-zeus-001",
            profile=PROFILE,
            session="fresh-browser-session",
        )
    assert len(transport.calls) == before


def test_read_only_recovery_rejects_missing_durable_binding(tmp_path):
    root, transport, coordinator, confirmed = _submitted_for_read_only_recovery(
        tmp_path
    )
    (root / "data/runs/zeeman/zeeman-zeus-001/.zeus-execution.json").unlink()
    before = len(transport.calls)
    with pytest.raises(
        ZeemanZeusError, match="profile_or_submission_identity_mismatch"
    ):
        coordinator.recover(
            run_id="zeeman-zeus-001",
            profile=PROFILE,
            session="fresh-browser-session",
        )
    assert len(transport.calls) == before


def test_read_only_recovery_rejects_wrong_family_path(tmp_path):
    root, transport, _coordinator_value, confirmed = _submitted_for_read_only_recovery(
        tmp_path
    )
    wrong_family = IndividualMot2DZeusCoordinator(
        root,
        issue_execution_authority(),
        lambda _profile: transport,
    )
    before = len(transport.calls)
    with pytest.raises(
        ZeemanZeusError, match="profile_or_submission_identity_mismatch"
    ):
        wrong_family.recover(
            run_id="zeeman-zeus-001",
            profile=PROFILE,
            session="fresh-browser-session",
        )
    assert len(transport.calls) == before


def test_reservation_review_reads_the_exact_pbs_instead_of_ui_defaults():
    from workflow_api.zeeman_zeus_execution import _reviewed_pbs_resources

    pbs = (
        b"#PBS -q test_q\n#PBS -l select=1:ncpus=3:mem=7gb\n#PBS -l walltime=01:02:03\n"
    )
    assert _reviewed_pbs_resources(pbs) == dict(
        queue="test_q", cores=3, memory_bytes=7 * 1024**3, walltime_seconds=3723
    )
    with pytest.raises(ZeemanZeusError, match="run_evidence_invalid"):
        _reviewed_pbs_resources(b"not a scalar reservation")


@pytest.mark.parametrize("family", ["zeeman", "mot_2d", "mot_3d"])
def test_individual_jobs_reserve_24_hours_without_changing_cpu_or_memory(family):
    import importlib

    module = importlib.import_module(f"workflow_api.{family}_zeus_execution")
    pbs = module._render_pbs(
        {"run_id": "individual-walltime-check", "git_revision": "a" * 40}, "b" * 64
    )
    assert b"#PBS -l walltime=24:00:00\n" in pbs
    assert b"#PBS -l select=1:ncpus=200:mem=64gb\n" in pbs


@pytest.mark.parametrize("family", ["zeeman", "mot_2d", "mot_3d"])
def test_only_individual_test_checkout_pins_reviewed_compute_node(family):
    import importlib
    from workflow_api.zeeman_zeus_execution import _reviewed_pbs_resources

    module = importlib.import_module(f"workflow_api.{family}_zeus_execution")
    run = {"run_id": "acceptance-placement", "git_revision": "a" * 40}
    normal = module._render_pbs(
        run, "b" * 64, "/home/tal.noa/ytterbium_lab_simulation_new"
    )
    isolated = module._render_pbs(
        run, "b" * 64, "/home/tal.noa/ytterbium_lab_simulation_ui_test"
    )
    assert b":vnode=" not in normal
    assert b"#PBS -l select=1:ncpus=200:mem=64gb:vnode=gd002\n" in isolated
    assert "vnode" not in _reviewed_pbs_resources(normal)
    assert _reviewed_pbs_resources(isolated)["vnode"] == "gd002"
    with pytest.raises(ZeemanZeusError):
        module._render_pbs(
            run, "b" * 64, "/home/tal.noa/ytterbium_lab_simulation_ui_acceptance"
        )


def test_held_scheduler_refresh_preserves_local_queued_record(tmp_path):
    root, transport, coordinator, confirmed = _submitted_for_read_only_recovery(
        tmp_path
    )
    run_dir = root / "data/runs/zeeman/zeeman-zeus-001"
    before = {
        p.relative_to(run_dir): p.read_bytes()
        for p in run_dir.rglob("*")
        if p.is_file()
    }
    transport.remote_status = RemoteJobStatus(confirmed["job_id"], "held", -10)
    assert coordinator.refresh(run_id="zeeman-zeus-001", profile=PROFILE) == {
        "state": "held",
        "job_id": confirmed["job_id"],
    }
    assert {
        p.relative_to(run_dir): p.read_bytes()
        for p in run_dir.rglob("*")
        if p.is_file()
    } == before
    assert [name for name, _ in transport.calls].count("submit") == 1
    assert "retrieve" not in [name for name, _ in transport.calls]
