import base64
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import numpy as np
import pytest

from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME, CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_PHYSICAL_SPECIFICATION, LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
)
from workflow_api.mot_2d_individual_sources import list_individual_mot_2d_sources
from workflow_api.mot_2d_local_execution import Mot2DLocalWorker
from workflow_api.mot_2d_run_plan import build_mot_2d_run_plan
from workflow_api.mot_2d_zeus_execution import (
    IndividualMot2DZeusCoordinator, build_frozen_mot_2d_package,
    PinnedSshMot2DTransport, _package_payload, _render_pbs,
)
from workflow_api.mot_2d_zeus_worker import execute_package
from workflow_api.mot_2d_zeus_worker import MAX_PRODUCT
from workflow_api.pinned_ssh import PinnedSshProcessError, PinnedSshRunner
from workflow_api.run_discovery import inspect_run
from workflow_api.run_execution import WorkerRequest, issue_execution_authority
from workflow_api.run_records import RunRecordStore
from workflow_api.zeeman_zeus_execution import RemoteJobStatus, RemoteSubmission
from workflow_api.zeus_snapshot import ZeusProfile


NOW = "2026-10-11T12:00:00+00:00"
PROFILE = ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new")


def _source(root: Path):
    directory = root / "data/particle_states/after_zeeman/source"; directory.mkdir(parents=True)
    profile = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]
    field = {key: list(profile[key]) for key in ("radii_m", "positions_m", "tilt_angles_deg")}
    for seed in range(3000, 3035):
        state = directory / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
        np.save(state, np.arange(24, dtype=np.float64).reshape(4, 6) + seed)
        state.with_suffix(".json").write_text(json.dumps({
            "shape": [4, 6], "dtype": "float64", "n_survivors": 4,
            "output_sha256": hashlib.sha256(state.read_bytes()).hexdigest(),
            "laboratory_spec_version": LABORATORY_SPEC_VERSION,
            "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
            "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
            "parameters": {"seed": seed, "resolved_zeeman_magnet_profile": CANONICAL_ZEEMAN_PROFILE_NAME,
                           "n_initial_atoms": 50000, "dt_s": 4e-5, "zeeman_field_config": field},
            "software": {"git_commit": "a" * 40},
        }))
    return list_individual_mot_2d_sources(root)["sources"][0]["id"]


def _create(root: Path, retained=False):
    plan = build_mot_2d_run_plan({
        "source_id": _source(root), "particle_count": 20,
        "selection_seed": 12, "mot_seed": 34, "s0": 1.3,
        "detuning_gamma": -0.9196610026631429,
        "magnet_radius_m": 0.04676406447474441,
        "retain_particle_states": retained, "execution_mode": "zeus",
    }, repository_root=root, run_id="mot2d-zeus-001", git_revision="b" * 40,
       created_utc=NOW)
    records = plan.storage_records(); store = RunRecordStore(root)
    try: store.create(records["run"], records["configuration"], records["inputs"], records["status"])
    finally: store.close()
    return records


class Engine:
    def __init__(self): self.calls = []
    def __call__(self, states, **kwargs):
        self.calls.append((states.copy(), kwargs))
        return [], 2, np.ascontiguousarray(states[:2])


class Transport:
    operations = frozenset({"inspect", "stage", "submit", "status", "retrieve"})
    def __init__(self):
        self.calls = []; self.inspect_result = RemoteSubmission("absent")
        self.remote_status = RemoteJobStatus("12345.zeus-master", "queued")
        self.product = None
    def inspect(self, **kwargs): self.calls.append(("inspect", kwargs)); return self.inspect_result
    def stage(self, **kwargs): self.calls.append(("stage", kwargs)); return RemoteSubmission("absent", kwargs["nonce"], None)
    def submit(self, **kwargs): self.calls.append(("submit", kwargs)); return RemoteSubmission("submitted", kwargs["nonce"], "12345.zeus-master")
    def status(self, **kwargs): self.calls.append(("status", kwargs)); return self.remote_status
    def retrieve(self, **kwargs): self.calls.append(("retrieve", kwargs)); return self.product


def _coordinator(root, transport):
    return IndividualMot2DZeusCoordinator(
        root, issue_execution_authority(), lambda _profile: transport,
        clock=lambda: 100.0, utc_clock=lambda: NOW,
        token_factory=lambda: "preview", nonce_factory=lambda: "1" * 32,
    )


def test_preview_packages_exact_selected_rows_and_scalar_pbs_without_submission(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); records = _create(root)
    transport = Transport(); coordinator = _coordinator(root, transport)
    preview = coordinator.preview(run_id="mot2d-zeus-001", profile=PROFILE, session="owner")
    package = transport.calls[0][1]["package"]
    assert preview["job"]["array"] is False and b"#PBS -J" not in package.pbs
    assert package.pbs.count(b"#PBS -q zeus_combined_q\n") == 1
    selected = np.load(BytesIO(package.selected_states), allow_pickle=False)
    frozen = records["configuration"]["resolved"]["sampling"]
    assert selected.shape == (20, 6)
    assert package.selection_sha256 == frozen["selected_identities_sha256"]
    assert hashlib.sha256(package.selected_states).hexdigest() == package.selected_states_sha256
    assert [name for name, _ in transport.calls] == ["inspect"]
    assert inspect_run(root, "mot_2d", "mot2d-zeus-001").status["state"] == "configured"


def test_confirm_is_session_bound_and_submits_exactly_once(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); _create(root)
    transport = Transport(); coordinator = _coordinator(root, transport)
    token = coordinator.preview(run_id="mot2d-zeus-001", profile=PROFILE, session="owner")["preview_token"]
    with pytest.raises(RuntimeError, match="confirmation_invalid"):
        coordinator.confirm(preview_token=token, session="other")
    first = coordinator.confirm(preview_token=token, session="owner")
    assert coordinator.confirm(preview_token=token, session="owner") == first
    assert [name for name, _ in transport.calls].count("submit") == 1
    assert inspect_run(root, "mot_2d", "mot2d-zeus-001").status["state"] == "queued"


def test_fixed_worker_validates_package_and_uses_same_adapter_once(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); records = _create(root, retained=True)
    package = build_frozen_mot_2d_package(root, records, PROFILE)
    directory = root / ".workflow/individual-mot-2d" / package.package_sha256
    directory.mkdir(parents=True); path = directory / "package.json"
    path.write_bytes(json.dumps(_package_payload(package), sort_keys=True, separators=(",", ":")).encode())
    engine = Engine(); monkeypatch.chdir(root); monkeypatch.setenv("PBS_JOBID", "12345.zeus-master")
    result = execute_package(path.relative_to(root), package.package_sha256,
        worker_factory=lambda: Mot2DLocalWorker(root, engine=engine,
            monotonic=iter((1.0, 2.0)).__next__, clock=lambda: NOW))
    assert result["run_id"] == "mot2d-zeus-001" and len(engine.calls) == 1
    assert engine.calls[0][1]["npools"] == 200
    assert execute_package(path.relative_to(root), package.package_sha256,
        worker_factory=lambda: (_ for _ in ()).throw(AssertionError())) == result


def test_successful_retrieval_is_d3_validated_before_success(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); records = _create(root)
    transport = Transport(); coordinator = _coordinator(root, transport)
    token = coordinator.preview(run_id="mot2d-zeus-001", profile=PROFILE, session="owner")["preview_token"]
    package = transport.calls[0][1]["package"]
    selected = np.load(BytesIO(package.selected_states), allow_pickle=False)
    transport.product = Mot2DLocalWorker(root, engine=Engine(),
        monotonic=iter((1.0, 2.0)).__next__, clock=lambda: NOW).run_materialized(
            WorkerRequest(records["run"], records["configuration"], records["inputs"]), selected)
    coordinator.confirm(preview_token=token, session="owner")
    transport.remote_status = RemoteJobStatus("12345.zeus-master", "succeeded", 0)
    assert coordinator.refresh(run_id="mot2d-zeus-001", profile=PROFILE)["state"] == "succeeded"
    inspected = inspect_run(root, "mot_2d", "mot2d-zeus-001")
    assert inspected.integrity == "complete_verified"
    status_call = next(payload for name, payload in transport.calls if name == "status")
    assert status_call["job_id"] == "12345.zeus-master"


def test_staged_selected_payload_or_record_drift_is_rejected_before_engine(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); records = _create(root)
    package = build_frozen_mot_2d_package(root, records, PROFILE)
    directory = root / ".workflow/individual-mot-2d" / package.package_sha256
    directory.mkdir(parents=True); path = directory / "package.json"
    payload = _package_payload(package)
    selected = bytearray(base64.b64decode(payload["selected_states"])); selected[-1] ^= 1
    payload["selected_states"] = base64.b64encode(selected).decode()
    path.write_text(json.dumps(payload)); monkeypatch.chdir(root); monkeypatch.setenv("PBS_JOBID", "12345.zeus-master")
    with pytest.raises(ValueError, match="digest"):
        execute_package(path.relative_to(root), package.package_sha256,
            worker_factory=lambda: (_ for _ in ()).throw(AssertionError()))


def test_no_cancellation_surface():
    assert not hasattr(IndividualMot2DZeusCoordinator, "cancel")
    assert "qdel" not in Path(__file__).parents[1].joinpath(
        "workflow_api/mot_2d_zeus_execution.py").read_text()


def _receiver_harness(tmp_path, records, *, qsub_exit=0):
    project = tmp_path / "project"; project.mkdir()
    package = build_frozen_mot_2d_package(tmp_path / "local", records, PROFILE)
    qsub = tmp_path / "qsub"; calls = tmp_path / "qsub.calls"
    qsub.write_text("#!/bin/sh\nprintf x >> " + str(calls) + "\ncat >/dev/null\n" +
                    ("echo 43210.zeus-master\n" if qsub_exit == 0 else "") +
                    f"exit {qsub_exit}\n"); qsub.chmod(0o700)
    qstat = tmp_path / "qstat"
    qstat.write_text("#!/bin/sh\nprintf 'Job Id: 43210.zeus-master\\n    job_state = R\\n'\n")
    qstat.chmod(0o700)
    source = Path(__file__).parents[1].joinpath("workflow_api/mot_2d_zeus_remote.py").read_text()
    repository_code = Path(__file__).parents[1]
    source = source.replace(
        'allowed = {Path("/home") / username / name for name in ("ytterbium_lab_simulation_new", "ytterbium_lab_simulation_ui_test")}',
        "allowed = {project}",
    ).replace(
        'sys.path.insert(0, str(project))', f'sys.path.insert(0, {str(repository_code)!r})'
    ).replace(
        'value["project_directory"] != str(project)',
        'value["project_directory"] != "/home/tal.noa/ytterbium_lab_simulation_new"',
    ).replace(
        'receipt.get("project_directory") != str(project)',
        'receipt.get("project_directory") != "/home/tal.noa/ytterbium_lab_simulation_new"',
    ).replace(
        '"project_directory": str(project)',
        '"project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"',
    ).replace(
        'verify_commit(project, value["commit"])', "None"
    ).replace(
        'verify_commit(project, receipt["commit"])', "None"
    ).replace('"/usr/local/bin/qsub"', repr(str(qsub))).replace(
        '"/usr/local/bin/qstat"', repr(str(qstat))
    )
    source = source.replace("_render_pbs(run, package_hash, str(project))", "_render_pbs(run, package_hash)")
    script = tmp_path / "receiver.py"; script.write_text(source)
    def invoke(operation, identity=None, request=None):
        request = request or {"identity": identity or _package_payload(package), "nonce": "1" * 32}
        return subprocess.run([sys.executable, str(script), operation, "tal.noa", str(project), "-"],
                              input=json.dumps(request), text=True, capture_output=True, check=False)
    return package, calls, invoke


@pytest.mark.skipif(os.name == "nt", reason="POSIX receiver and shell scheduler fixture executes on Zeus; native client contracts remain separate")
def test_receiver_at_most_once_across_restart_and_ambiguous_outcome(tmp_path, monkeypatch):
    local = tmp_path / "local"; local.mkdir(); records = _create(local)
    package, calls, invoke = _receiver_harness(tmp_path, records)
    original_run = subprocess.run
    receiver_requests = []

    def observe_receiver(argv, **kwargs):
        if len(argv) > 1 and argv[0] == sys.executable and str(argv[1]).endswith("receiver.py"):
            # The real frozen package exceeds Linux's 128 KiB single-argument
            # limit in the legacy encoding; production sends it over stdin.
            raw_request = kwargs["input"]
            assert len(base64.urlsafe_b64encode(raw_request.encode())) > 128 * 1024
            assert argv[-1] == "-"
            assert max(len(str(arg).encode()) for arg in argv) < 4096
            receiver_requests.append(json.loads(raw_request))
        return original_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", observe_receiver)
    assert invoke("stage").returncode == 0
    first = invoke("submit"); second = invoke("submit")
    assert first.returncode == second.returncode == 0
    assert json.loads(first.stdout) == json.loads(second.stdout)
    assert calls.read_text() == "x"
    assert len(receiver_requests) == 3
    assert (tmp_path / "project/.workflow/individual-mot-2d/submissions" /
            f"{package.submission_key}.json").is_file()

    other = tmp_path / "ambiguous"; other.mkdir()
    # A separate harness with failed qsub leaves durable pending intent.
    tmp2 = tmp_path / "second"; tmp2.mkdir()
    local2 = tmp2 / "local"; local2.mkdir(); records2 = _create(local2)
    _package, failed_calls, failed_invoke = _receiver_harness(tmp2, records2, qsub_exit=1)
    assert failed_invoke("stage").returncode == 0
    assert failed_invoke("submit").returncode != 0
    assert failed_invoke("submit").returncode != 0
    assert failed_calls.read_text() == "x"


@pytest.mark.skipif(os.name == "nt", reason="POSIX receiver and shell scheduler fixture executes on Zeus; native client contracts remain separate")
def test_receiver_reconstructs_pbs_and_rejects_tampering_before_qsub(tmp_path):
    local = tmp_path / "local"; local.mkdir(); records = _create(local)
    package, calls, invoke = _receiver_harness(tmp_path, records)
    identity = _package_payload(package)
    malicious = base64.b64encode(package.pbs + b"qsub /tmp/evil\n").decode()
    identity["pbs"] = malicious
    identity["pbs_sha256"] = hashlib.sha256(base64.b64decode(malicious)).hexdigest()
    identity["submission_key"] = hashlib.sha256(json.dumps({
        "package_sha256": identity["package_sha256"],
        "pbs_sha256": identity["pbs_sha256"], "run_id": identity["run_id"],
        "commit": identity["commit"], "username": identity["username"],
        "project_directory": identity["project_directory"],
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result = invoke("submit", identity)
    assert result.returncode != 0
    assert json.loads(result.stdout) == {"error": "remote_package_invalid"}
    assert not calls.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX receiver and shell scheduler fixture executes on Zeus; native client contracts remain separate")
def test_receiver_strict_decodes_records_even_with_recomputed_outer_hashes(tmp_path):
    local = tmp_path / "local"; local.mkdir(); records = _create(local)
    package, calls, invoke = _receiver_harness(tmp_path, records)
    identity = _package_payload(package)
    decoded_records = {name: base64.b64decode(value) for name, value in identity["records"].items()}
    configuration = json.loads(decoded_records["configuration"])
    configuration["unexpected"] = "must fail strict D2 decoding"
    decoded_records["configuration"] = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()
    identity["records"] = {name: base64.b64encode(value).decode() for name, value in decoded_records.items()}
    selected = base64.b64decode(identity["selected_states"])
    manifest = {"version": 1, "family": "mot_2d", "run_id": identity["run_id"],
        "commit": identity["commit"], "username": identity["username"],
        "project_directory": identity["project_directory"],
        "records": {name: hashlib.sha256(value).hexdigest() for name, value in decoded_records.items()},
        "selected_states_sha256": hashlib.sha256(selected).hexdigest(),
        "selected_states_size": len(selected), "selection_sha256": identity["selection_sha256"]}
    identity["package_sha256"] = hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    pbs = _render_pbs(records["run"], identity["package_sha256"])
    identity["pbs"] = base64.b64encode(pbs).decode(); identity["pbs_sha256"] = hashlib.sha256(pbs).hexdigest()
    identity["submission_key"] = hashlib.sha256(json.dumps({
        "package_sha256": identity["package_sha256"], "pbs_sha256": identity["pbs_sha256"],
        "run_id": identity["run_id"], "commit": identity["commit"],
        "username": identity["username"], "project_directory": identity["project_directory"],
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result = invoke("submit", identity)
    assert result.returncode != 0
    assert json.loads(result.stdout) == {"error": "remote_package_invalid"}
    assert not calls.exists()


def test_fixed_pbs_contains_exact_runtime_bootstrap_once(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); records = _create(root)
    pbs = build_frozen_mot_2d_package(root, records, PROFILE).pbs.decode()
    for line in (
        "module load SPACK/apps", "module load gcc/14.1.0",
        "module load python/3.14.2",
        'source "${HOME}/venvs/atomsmltr/bin/activate"',
    ):
        assert pbs.count(line) == 1


def test_pinned_transport_streams_bounded_package_over_stdin_not_argv(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); records = _create(root)
    package = build_frozen_mot_2d_package(root, records, PROFILE)
    ssh = tmp_path / "ssh"; ssh.write_text(""); ssh.chmod(0o700)
    calls = []
    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0,
            stdout=b'{"state":"absent","nonce":null,"job_id":null}', stderr=b"")
    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", fake_run)
    transport = PinnedSshMot2DTransport(root, ssh, PROFILE)
    assert transport.inspect(package=package, nonce="1" * 32).state == "absent"
    argv, kwargs = calls[0]
    assert package.package_sha256 not in " ".join(argv)
    remote = argv[-1]
    assert remote.startswith(
        "cd -- /home/tal.noa/ytterbium_lab_simulation_new && exec "
        "/home/tal.noa/venvs/atomsmltr/bin/python -c "
    )
    assert "python3" not in remote
    assert kwargs.get("stdin") is None
    receiver_line, request_bytes = kwargs["input"].split(b"\n", 1)
    assert base64.urlsafe_b64decode(json.loads(receiver_line)[0]) == (Path(__file__).parents[1] / "workflow_api/mot_2d_zeus_remote.py").read_bytes()
    request = json.loads(request_bytes)
    assert request["identity"]["package_sha256"] == package.package_sha256


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_generic_pinned_runner_terminates_oversized_stream_without_unbounded_capture(
    tmp_path, stream,
):
    statement = (
        "import sys;"
        f"sys.{stream}.buffer.write(b'x' * (9 * 1024 * 1024));"
        f"sys.{stream}.flush()"
    )
    with pytest.raises(PinnedSshProcessError, match="exceeded"):
        PinnedSshRunner._run_bounded(
            [sys.executable, "-c", statement],
            {"cwd": tmp_path, "timeout": 10, "shell": False, "close_fds": True},
        )


def test_worker_rejects_oversized_stale_product_before_worker_or_json_allocation(
    tmp_path, monkeypatch,
):
    root = tmp_path / "repo"; root.mkdir(); records = _create(root)
    package = build_frozen_mot_2d_package(root, records, PROFILE)
    directory = root / ".workflow/individual-mot-2d" / package.package_sha256
    directory.mkdir(parents=True); path = directory / "package.json"
    path.write_bytes(json.dumps(
        _package_payload(package), sort_keys=True, separators=(",", ":")
    ).encode())
    stale = directory / "worker_product.json"
    with stale.open("wb") as stream:
        stream.truncate(MAX_PRODUCT + 1)
    monkeypatch.chdir(root); monkeypatch.setenv("PBS_JOBID", "12345.zeus-master")
    with pytest.raises(ValueError, match="Existing worker product"):
        execute_package(
            path.relative_to(root), package.package_sha256,
            worker_factory=lambda: (_ for _ in ()).throw(
                AssertionError("worker must not start")
            ),
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX receiver and shell scheduler fixture executes on Zeus; native client contracts remain separate")
def test_receiver_rejects_mismatched_retrieval_product(tmp_path):
    local = tmp_path / "local"; local.mkdir(); records = _create(local)
    package, calls, invoke = _receiver_harness(tmp_path, records)
    assert invoke("stage").returncode == 0
    submitted = json.loads(invoke("submit").stdout)
    product_path = tmp_path / "project/.workflow/individual-mot-2d" / package.package_sha256 / "worker_product.json"
    product_path.write_text(json.dumps({
        "version": 1, "run_id": package.run_id, "job_id": "99999.zeus-master",
        "package_sha256": package.package_sha256,
        "submission_key": package.submission_key,
        "results": {}, "receipt": None, "artifacts": {},
    }))
    result = invoke("retrieve", request={
        "job_id": submitted["job_id"], "submission_key": package.submission_key,
        "package_sha256": package.package_sha256,
    })
    assert result.returncode != 0
    assert json.loads(result.stdout) == {"error": "result_unavailable"}
    assert calls.read_text() == "x"


@pytest.mark.skipif(os.name == "nt", reason="POSIX receiver and shell scheduler fixture executes on Zeus; native client contracts remain separate")
def test_receiver_requires_exact_qstat_job_identity(tmp_path):
    local = tmp_path / "local"; local.mkdir(); records = _create(local)
    package, calls, invoke = _receiver_harness(tmp_path, records)
    assert invoke("stage").returncode == 0
    submitted = json.loads(invoke("submit").stdout)
    qstat = tmp_path / "qstat"
    qstat.write_text("#!/bin/sh\nprintf 'Job Id: 99999.zeus-master\\n    job_state = R\\n'\n")
    qstat.chmod(0o700)
    result = invoke("status", request={
        "job_id": submitted["job_id"], "submission_key": package.submission_key,
    })
    assert result.returncode != 0
    assert json.loads(result.stdout) == {"error": "job_status_unavailable"}
    assert calls.read_text() == "x"


def test_concurrent_confirm_and_restart_reconciliation_never_duplicate_qsub(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); _create(root)
    transport = Transport(); coordinator = _coordinator(root, transport)
    token = coordinator.preview(run_id="mot2d-zeus-001", profile=PROFILE, session="owner")["preview_token"]
    barrier = threading.Barrier(3); outcomes = []
    def invoke():
        barrier.wait(); outcomes.append(coordinator.confirm(preview_token=token, session="owner"))
    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads: thread.start()
    barrier.wait()
    for thread in threads: thread.join(timeout=5)
    assert len(outcomes) == 2 and outcomes[0] == outcomes[1]
    assert [name for name, _ in transport.calls].count("submit") == 1


def test_source_change_after_preview_blocks_submission(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); records = _create(root)
    transport = Transport(); coordinator = _coordinator(root, transport)
    token = coordinator.preview(run_id="mot2d-zeus-001", profile=PROFILE, session="owner")["preview_token"]
    artifact = records["inputs"]["artifacts"][0]
    target = root / artifact["path"]; target.write_bytes(b"x" * artifact["size_bytes"])
    with pytest.raises(Exception):
        coordinator.confirm(preview_token=token, session="owner")
    assert [name for name, _ in transport.calls].count("submit") == 0


def test_restart_reconciles_post_qsub_crash_without_resubmission(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); _create(root)
    class Durable(Transport):
        def __init__(self): super().__init__(); self.receipt = None; self.crash = True
        def inspect(self, **kwargs):
            self.calls.append(("inspect", kwargs)); return self.receipt or RemoteSubmission("absent")
        def submit(self, **kwargs):
            self.calls.append(("submit", kwargs))
            self.receipt = RemoteSubmission("submitted", kwargs["nonce"], "12345.zeus-master")
            if self.crash: raise KeyboardInterrupt("after qsub")
            return self.receipt
    transport = Durable(); first = _coordinator(root, transport)
    token = first.preview(run_id="mot2d-zeus-001", profile=PROFILE, session="owner")["preview_token"]
    with pytest.raises(KeyboardInterrupt):
        first.confirm(preview_token=token, session="owner")
    transport.crash = False
    restarted = IndividualMot2DZeusCoordinator(
        root, issue_execution_authority(), lambda _profile: transport,
        clock=lambda: 100.0, utc_clock=lambda: NOW,
        token_factory=lambda: "recovery", nonce_factory=lambda: "2" * 32,
    )
    preview = restarted.preview(run_id="mot2d-zeus-001", profile=PROFILE, session="owner")
    assert preview["effects"]["reconcile_existing_job"] is True
    restarted.confirm(preview_token=preview["preview_token"], session="owner")
    assert [name for name, _ in transport.calls].count("submit") == 1
    assert inspect_run(root, "mot_2d", "mot2d-zeus-001").status["state"] == "queued"


def test_wrong_profile_after_restart_is_rejected_before_status(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); _create(root)
    transport = Transport(); first = _coordinator(root, transport)
    token = first.preview(run_id="mot2d-zeus-001", profile=PROFILE, session="owner")["preview_token"]
    first.confirm(preview_token=token, session="owner")
    before = len(transport.calls)
    wrong = ZeusProfile("other", "/home/other/ytterbium_lab_simulation_new")
    with pytest.raises(RuntimeError, match="profile_or_submission_identity_mismatch"):
        _coordinator(root, transport).refresh(run_id="mot2d-zeus-001", profile=wrong)
    assert len(transport.calls) == before


def test_local_and_zeus_adapters_have_identical_science_for_same_frozen_states(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); records = _create(root)
    package = build_frozen_mot_2d_package(root, records, PROFILE)
    selected = np.load(BytesIO(package.selected_states), allow_pickle=False)
    local_engine = Engine(); zeus_engine = Engine()
    # The local adapter is exercised with the exact immutable rows that cross
    # the Zeus boundary; only the server-owned worker count may differ.
    local_records = json.loads(json.dumps(records))
    local_records["run"]["execution_mode"] = "local"
    local_records["configuration"]["resolved"]["execution"] = {"mode": "local", "workers": 1}
    local_product = Mot2DLocalWorker(root, engine=local_engine,
        monotonic=iter((1.0, 2.0)).__next__, clock=lambda: NOW)._run(
            WorkerRequest(local_records["run"], local_records["configuration"], local_records["inputs"]),
            selected_states=None,
        )
    zeus_product = Mot2DLocalWorker(root, engine=zeus_engine,
        monotonic=iter((1.0, 2.0)).__next__, clock=lambda: NOW).run_materialized(
            WorkerRequest(records["run"], records["configuration"], records["inputs"]), selected)
    np.testing.assert_array_equal(local_engine.calls[0][0], zeus_engine.calls[0][0])
    local_kwargs = {key: value for key, value in local_engine.calls[0][1].items() if key != "npools"}
    zeus_kwargs = {key: value for key, value in zeus_engine.calls[0][1].items() if key != "npools"}
    assert local_kwargs == zeus_kwargs
    assert local_product.results["metrics"]["conditional_efficiency"] == zeus_product.results["metrics"]["conditional_efficiency"]


def test_read_only_retrieval_failure_can_be_retried_without_resubmission(tmp_path):
    from workflow_api.zeeman_zeus_execution import ZeemanZeusError
    root = tmp_path / "repo"; root.mkdir(); records = _create(root)
    transport = Transport(); coordinator = _coordinator(root, transport)
    token = coordinator.preview(run_id="mot2d-zeus-001", profile=PROFILE, session="owner")["preview_token"]
    package = transport.calls[0][1]["package"]
    selected = np.load(BytesIO(package.selected_states), allow_pickle=False)
    transport.product = Mot2DLocalWorker(root, engine=Engine(), monotonic=iter((1.0, 2.0)).__next__, clock=lambda: NOW).run_materialized(
        WorkerRequest(records["run"], records["configuration"], records["inputs"]), selected)
    coordinator.confirm(preview_token=token, session="owner")
    transport.remote_status = RemoteJobStatus("12345.zeus-master", "succeeded", 0)
    original = transport.retrieve
    attempts = iter((True, False))
    def retrieve(**kwargs):
        if next(attempts):
            raise ZeemanZeusError("result_unavailable")
        return original(**kwargs)
    transport.retrieve = retrieve
    with pytest.raises(ZeemanZeusError, match="result_unavailable"):
        coordinator.refresh(run_id="mot2d-zeus-001", profile=PROFILE)
    assert inspect_run(root, "mot_2d", "mot2d-zeus-001").status["state"] == "running"
    assert coordinator.refresh(run_id="mot2d-zeus-001", profile=PROFILE)["state"] == "succeeded"
    assert [name for name, _ in transport.calls].count("submit") == 1


def test_transport_reports_remote_code_mismatch_without_submitting(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    package = build_frozen_mot_2d_package(root, _create(root), PROFILE)
    ssh = tmp_path / "ssh"
    ssh.write_text("")
    ssh.chmod(0o700)
    transport = PinnedSshMot2DTransport(root, ssh, PROFILE)
    calls = []
    def response(operation, profile, payload):
        calls.append(operation.value)
        return subprocess.CompletedProcess([], 21, stdout=b'{"error":"remote_code_mismatch"}', stderr=b"")
    monkeypatch.setattr(transport.runner, "run", response)
    with pytest.raises(RuntimeError, match="remote_code_mismatch"):
        transport.inspect(package=package, nonce="1" * 32)
    assert calls == ["inspect"]
