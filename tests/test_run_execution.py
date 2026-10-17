from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import hashlib
import os
import sys
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

import workflow_api.run_execution as execution_module
from workflow_api.run_discovery import inspect_run
from workflow_api.run_execution import (
    ExecutionAuthority,
    ExecutorLifecycleStore,
    IndividualRunExecutionCoordinator,
    WorkerFailed,
    WorkerProduct,
    issue_execution_authority,
)
from workflow_api.run_records import (
    decode_record,
    RunRecordError,
    RunRecordStore,
    encode_record,
)
from workflow_api.zeeman_run_plan import build_zeeman_run_plan


NOW = "2026-10-11T12:00:00+00:00"
REQUEST = {
    "particle_count": 100,
    "seed": 71,
    "retain_particle_states": False,
    "execution_mode": "local",
}


def make_run(tmp_path: Path, *, retained=False, seed=71):
    root = tmp_path / "repo"
    root.mkdir()
    plan = build_zeeman_run_plan(
        {**REQUEST, "retain_particle_states": retained, "seed": seed},
        run_id="zeeman-run-001",
        git_revision="a" * 40,
        created_utc=NOW,
    )
    records = plan.storage_records()
    store = RunRecordStore(root)
    try:
        store.create(
            records["run"], records["configuration"], records["inputs"], records["status"]
        )
    finally:
        store.close()
    return root


def retained_product(captured=3):
    stream = BytesIO()
    np.save(stream, np.arange(captured * 6, dtype=np.float64).reshape(captured, 6))
    states = stream.getvalue()
    artifact = {
        "kind": "particle_states",
        "path": "results/states.npy",
        "sha256": hashlib.sha256(states).hexdigest(),
        "size_bytes": len(states),
    }
    return WorkerProduct(
        results={
            "schema_version": "run-results-v1",
            "run_id": "zeeman-run-001",
            "completed_utc": NOW,
            "states_retained": True,
            "suitability": "individual_only",
            "metrics": {
                "n_initial": 100,
                "n_survivors": captured,
                "captured": captured,
                "survival_fraction": captured / 100,
                "elapsed_s": 1.0,
            },
            "artifacts": [artifact],
        },
        receipt=None,
        artifacts={"results/states.npy": states},
    )


def discarded_product(captured=3):
    receipt = {
        "schema_version": "state-retention-receipt-v1",
        "run_id": "zeeman-run-001",
        "created_utc": NOW,
        "reason": "particle_states_not_retained",
    }
    raw = encode_record("retention_receipt", receipt)
    artifact = {
        "kind": "retention_receipt",
        "path": "results/state_retention_receipt.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    return WorkerProduct(
        results={
            "schema_version": "run-results-v1",
            "run_id": "zeeman-run-001",
            "completed_utc": NOW,
            "states_retained": False,
            "suitability": "individual_only",
            "metrics": {
                "n_initial": 100,
                "n_survivors": captured,
                "captured": captured,
                "survival_fraction": captured / 100,
                "elapsed_s": 1.0,
            },
            "artifacts": [artifact],
        },
        receipt=receipt,
        artifacts={},
    )


class FakeWorker:
    def __init__(self, product=None, error=None):
        self.product = product
        self.error = error
        self.calls = 0
        self.requests = []

    def run(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.product


class MutatingWorker(FakeWorker):
    def __init__(self, product, mutation):
        super().__init__(product)
        self.mutation = mutation

    def run(self, request):
        product = super().run(request)
        self.mutation()
        return product


def execution_target(root: Path, target: str) -> Path:
    run = root / "data/runs/zeeman/zeeman-run-001"
    return {
        "root": root,
        "data": root / "data",
        "runs": root / "data/runs",
        "family": root / "data/runs/zeeman",
        "run": run,
    }[target]


def replace_with_copy(path: Path) -> Path:
    displaced = path.with_name(f"{path.name}.displaced")
    path.rename(displaced)
    shutil.copytree(displaced, path)
    return displaced


def aba_restore(path: Path) -> None:
    displaced = path.with_name(f"{path.name}.displaced")
    path.rename(displaced)
    shutil.copytree(displaced, path)
    shutil.rmtree(path)
    displaced.rename(path)


def prepare_running(root: Path):
    authority = issue_execution_authority()
    store = ExecutorLifecycleStore(root)
    current = store.read("zeeman", "zeeman-run-001", "status")
    for state in ("validated", "reviewed", "running"):
        current = store.transition(
            authority,
            "zeeman",
            "zeeman-run-001",
            expected_revision=current["revision"],
            target_state=state,
            updated_utc=NOW,
        )
    lease = store.execution_lease(
        authority,
        "zeeman",
        "zeeman-run-001",
        expected_revision=current["revision"],
    )
    return store, authority, current, lease


@pytest.mark.parametrize(
    "retained,product_factory",
    [(False, discarded_product), (True, retained_product)],
)
def test_fake_worker_success_is_d3_verified_before_terminal_state(
    tmp_path, retained, product_factory
):
    root = make_run(tmp_path, retained=retained)
    worker = FakeWorker(product_factory())
    coordinator = IndividualRunExecutionCoordinator(
        root, worker, issue_execution_authority(), clock=lambda: NOW
    )
    result = coordinator.execute("zeeman", "zeeman-run-001")

    assert result == {"state": "succeeded", "recovered": False, "worker_started": True}
    assert worker.calls == 1
    inspected = inspect_run(root, "zeeman", "zeeman-run-001")
    assert inspected.state == "succeeded"
    assert inspected.integrity == "complete_verified"
    assert inspected.results["states_retained"] is retained
    assert inspected.results["metrics"]["captured"] == 3
    assert worker.requests[0].run["suitability"] == "individual_only"
    with pytest.raises(TypeError):
        worker.requests[0].configuration["resolved"] = {}


def test_separate_authority_and_cas_do_not_broaden_d2_cancellation(tmp_path):
    root = make_run(tmp_path)
    with pytest.raises(PermissionError):
        ExecutionAuthority(object())
    executor = ExecutorLifecycleStore(root)
    d2 = RunRecordStore(root)
    authority = issue_execution_authority()
    try:
        with pytest.raises(PermissionError):
            executor.transition(
                object(), "zeeman", "zeeman-run-001",
                expected_revision=0, target_state="validated", updated_utc=NOW,
            )
        with pytest.raises(RunRecordError, match="invalid"):
            executor.transition(
                authority, "zeeman", "zeeman-run-001",
                expected_revision=0, target_state="cancelled", updated_utc=NOW,
            )
        current = d2.read("zeeman", "zeeman-run-001", "status")
        cancelled = {**current, "revision": 1, "state": "cancelled"}
        d2.update_status("zeeman", "zeeman-run-001", cancelled)
        assert d2.read("zeeman", "zeeman-run-001", "status")["state"] == "cancelled"
        assert not hasattr(d2, "publish_success")
        assert not hasattr(d2, "transition")
    finally:
        executor.close()
        d2.close()


def test_executor_transition_is_compare_and_swap_under_concurrency(tmp_path):
    root = make_run(tmp_path)
    authority = issue_execution_authority()

    def transition(_index):
        store = ExecutorLifecycleStore(root)
        try:
            store.transition(
                authority, "zeeman", "zeeman-run-001",
                expected_revision=0, target_state="validated", updated_utc=NOW,
            )
            return "ok"
        except RunRecordError:
            return "rejected"
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(transition, range(8)))
    assert outcomes.count("ok") == 1
    assert outcomes.count("rejected") == 7


def test_invalid_worker_product_never_reaches_success(tmp_path):
    root = make_run(tmp_path, retained=True)
    bad = discarded_product()
    worker = FakeWorker(bad)
    coordinator = IndividualRunExecutionCoordinator(
        root, worker, issue_execution_authority(), clock=lambda: NOW
    )
    assert coordinator.execute("zeeman", "zeeman-run-001")["state"] == "failed"
    inspected = inspect_run(root, "zeeman", "zeeman-run-001")
    assert inspected.state == "failed"
    assert inspected.results is None
    assert not (root / "data/runs/zeeman/zeeman-run-001/results/summary.json").exists()


@pytest.mark.parametrize(
    "error,expected",
    [(WorkerFailed("safe"), "failed"), (RuntimeError("secret path"), "outcome_unknown")],
)
def test_worker_failure_classification_is_safe_and_terminal(tmp_path, error, expected):
    root = make_run(tmp_path)
    worker = FakeWorker(error=error)
    coordinator = IndividualRunExecutionCoordinator(
        root, worker, issue_execution_authority(), clock=lambda: NOW
    )
    assert coordinator.execute("zeeman", "zeeman-run-001")["state"] == expected
    status = inspect_run(root, "zeeman", "zeeman-run-001").status
    assert status["state"] == expected
    assert "secret" not in status["error"]["message"]


def test_crash_while_running_is_not_replayed_and_becomes_outcome_unknown(tmp_path):
    root = make_run(tmp_path)
    crashing = FakeWorker(error=KeyboardInterrupt())
    first = IndividualRunExecutionCoordinator(
        root, crashing, issue_execution_authority(), clock=lambda: NOW
    )
    with pytest.raises(KeyboardInterrupt):
        first.execute("zeeman", "zeeman-run-001")
    assert inspect_run(root, "zeeman", "zeeman-run-001").state == "running"

    replacement = FakeWorker(discarded_product())
    second = IndividualRunExecutionCoordinator(
        root, replacement, issue_execution_authority(), clock=lambda: NOW
    )
    result = second.execute("zeeman", "zeeman-run-001")
    assert result == {"state": "outcome_unknown", "recovered": True, "worker_started": False}
    assert replacement.calls == 0


def test_crash_after_durable_d3_publication_recovers_without_worker_replay(
    tmp_path, monkeypatch
):
    root = make_run(tmp_path)
    worker = FakeWorker(discarded_product())
    real_replace = execution_module._replace_at
    failed = {"value": False}

    def crash_before_success(parent, name, content):
        proposed_state = (
            decode_record("status", content)["state"]
            if name == "status.json"
            else None
        )
        if (
            name == "status.json"
            and proposed_state == "succeeded"
            and not failed["value"]
        ):
            failed["value"] = True
            raise OSError("simulated crash")
        return real_replace(parent, name, content)

    monkeypatch.setattr(execution_module, "_replace_at", crash_before_success)
    first = IndividualRunExecutionCoordinator(
        root, worker, issue_execution_authority(), clock=lambda: NOW
    )
    with pytest.raises(OSError, match="simulated crash"):
        first.execute("zeeman", "zeeman-run-001")
    assert failed["value"] is True
    incomplete = inspect_run(root, "zeeman", "zeeman-run-001")
    assert incomplete.state == "running"
    assert incomplete.integrity == "incomplete_publication"

    monkeypatch.setattr(execution_module, "_replace_at", real_replace)
    replacement = FakeWorker(error=AssertionError("must not replay"))
    second = IndividualRunExecutionCoordinator(
        root, replacement, issue_execution_authority(), clock=lambda: NOW
    )
    result = second.execute("zeeman", "zeeman-run-001")
    assert result == {"state": "succeeded", "recovered": True, "worker_started": False}
    assert replacement.calls == 0
    assert inspect_run(root, "zeeman", "zeeman-run-001").integrity == "complete_verified"


def test_executor_never_uses_process_network_ssh_or_qsub(tmp_path, monkeypatch):
    root = make_run(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("external execution is forbidden in E3")

    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    coordinator = IndividualRunExecutionCoordinator(
        root, FakeWorker(discarded_product()), issue_execution_authority(), clock=lambda: NOW
    )
    assert coordinator.execute("zeeman", "zeeman-run-001")["state"] == "succeeded"
    assert not list(root.rglob("*.pbs"))


def test_concurrent_coordinators_start_at_most_one_worker(tmp_path):
    root = make_run(tmp_path)
    authority = issue_execution_authority()
    worker = FakeWorker(discarded_product())

    def execute(_index):
        coordinator = IndividualRunExecutionCoordinator(
            root, worker, authority, clock=lambda: NOW
        )
        try:
            return coordinator.execute("zeeman", "zeeman-run-001")["state"]
        except RunRecordError:
            return "cas_rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(execute, range(2)))
    assert worker.calls <= 1
    assert "succeeded" in outcomes or inspect_run(root, "zeeman", "zeeman-run-001").state == "succeeded"


@pytest.mark.parametrize("target", ["root", "data", "runs", "family", "run"])
def test_execution_lease_rejects_canonical_tree_replacement_by_worker(
    tmp_path, target
):
    root = make_run(tmp_path)
    path = execution_target(root, target)
    worker = MutatingWorker(discarded_product(), lambda: replace_with_copy(path))
    coordinator = IndividualRunExecutionCoordinator(
        root, worker, issue_execution_authority(), clock=lambda: NOW
    )

    with pytest.raises(RunRecordError):
        coordinator.execute("zeeman", "zeeman-run-001")

    replacement = inspect_run(root, "zeeman", "zeeman-run-001")
    assert replacement.state == "running"
    assert replacement.results is None
    assert worker.calls == 1


@pytest.mark.parametrize("target", ["root", "data", "runs", "family", "run"])
def test_execution_lease_detects_aba_during_worker_without_mutating_run(
    tmp_path, target
):
    root = make_run(tmp_path)
    path = execution_target(root, target)
    worker = MutatingWorker(discarded_product(), lambda: aba_restore(path))
    coordinator = IndividualRunExecutionCoordinator(
        root, worker, issue_execution_authority(), clock=lambda: NOW
    )

    with pytest.raises(RunRecordError, match="lease"):
        coordinator.execute("zeeman", "zeeman-run-001")

    inspected = inspect_run(root, "zeeman", "zeeman-run-001")
    assert inspected.state == "running"
    assert inspected.results is None
    assert worker.calls == 1


@pytest.mark.parametrize("target", ["root", "data", "runs", "family", "run"])
@pytest.mark.skipif(sys.platform == "win32", reason="Windows blocks rename while publication locks are held; covered by native rejection test")
def test_swap_during_artifact_publication_never_marks_replacement_failed(
    tmp_path, monkeypatch, target
):
    root = make_run(tmp_path, retained=True)
    path = execution_target(root, target)
    real_publish = ExecutorLifecycleStore._publish_or_verify
    swapped = {"value": False}

    def publish_then_swap(parent, name, content):
        real_publish(parent, name, content)
        if not swapped["value"]:
            replace_with_copy(path)
            swapped["value"] = True

    monkeypatch.setattr(
        ExecutorLifecycleStore, "_publish_or_verify", staticmethod(publish_then_swap)
    )
    coordinator = IndividualRunExecutionCoordinator(
        root, FakeWorker(retained_product()), issue_execution_authority(), clock=lambda: NOW
    )

    with pytest.raises(RunRecordError):
        coordinator.execute("zeeman", "zeeman-run-001")

    inspected = inspect_run(root, "zeeman", "zeeman-run-001")
    assert swapped["value"] is True
    assert inspected.state == "running"


@pytest.mark.parametrize("target", ["root", "data", "runs", "family", "run"])
@pytest.mark.skipif(sys.platform == "win32", reason="Windows blocks rename while publication locks are held; covered by native rejection test")
def test_swap_during_success_publication_leaves_replacement_running(
    tmp_path, monkeypatch, target
):
    root = make_run(tmp_path)
    path = execution_target(root, target)
    real_publish = ExecutorLifecycleStore._publish_or_verify
    calls = {"count": 0}

    def publish_then_swap(parent, name, content):
        real_publish(parent, name, content)
        calls["count"] += 1
        if calls["count"] == 1:
            replace_with_copy(path)

    monkeypatch.setattr(
        ExecutorLifecycleStore, "_publish_or_verify", staticmethod(publish_then_swap)
    )
    coordinator = IndividualRunExecutionCoordinator(
        root, FakeWorker(discarded_product()), issue_execution_authority(), clock=lambda: NOW
    )

    with pytest.raises(RunRecordError):
        coordinator.execute("zeeman", "zeeman-run-001")

    assert calls["count"] >= 1
    assert inspect_run(root, "zeeman", "zeeman-run-001").state == "running"


@pytest.mark.parametrize("target", ["root", "data", "runs", "family", "run"])
@pytest.mark.skipif(sys.platform == "win32", reason="Windows blocks rename while publication locks are held; covered by native rejection test")
def test_aba_during_artifact_publication_is_rejected_before_success(
    tmp_path, monkeypatch, target
):
    root = make_run(tmp_path, retained=True)
    path = execution_target(root, target)
    real_publish = ExecutorLifecycleStore._publish_or_verify
    changed = {"value": False}

    def publish_then_aba(parent, name, content):
        real_publish(parent, name, content)
        if not changed["value"]:
            aba_restore(path)
            changed["value"] = True

    monkeypatch.setattr(
        ExecutorLifecycleStore, "_publish_or_verify", staticmethod(publish_then_aba)
    )
    coordinator = IndividualRunExecutionCoordinator(
        root, FakeWorker(retained_product()), issue_execution_authority(), clock=lambda: NOW
    )

    with pytest.raises(RunRecordError, match="lease"):
        coordinator.execute("zeeman", "zeeman-run-001")

    assert changed["value"] is True
    assert inspect_run(root, "zeeman", "zeeman-run-001").state == "running"


@pytest.mark.parametrize("target", ["root", "data", "runs", "family", "run"])
@pytest.mark.skipif(sys.platform == "win32", reason="Windows blocks rename while publication locks are held; covered by native rejection test")
def test_recovery_swap_never_finalizes_or_mutates_replacement(
    tmp_path, monkeypatch, target
):
    root = make_run(tmp_path)
    real_replace = execution_module._replace_at

    def crash_before_success(parent, name, content):
        if name == "status.json" and decode_record("status", content)["state"] == "succeeded":
            raise OSError("durable publication crash")
        return real_replace(parent, name, content)

    monkeypatch.setattr(execution_module, "_replace_at", crash_before_success)
    first = IndividualRunExecutionCoordinator(
        root, FakeWorker(discarded_product()), issue_execution_authority(), clock=lambda: NOW
    )
    with pytest.raises(OSError, match="durable publication crash"):
        first.execute("zeeman", "zeeman-run-001")
    assert inspect_run(root, "zeeman", "zeeman-run-001").integrity == "incomplete_publication"

    monkeypatch.setattr(execution_module, "_replace_at", real_replace)
    real_validate = execution_module._validate_publication_plan_at
    path = execution_target(root, target)
    changed = {"value": False}

    def validate_then_swap(*args, **kwargs):
        plan = real_validate(*args, **kwargs)
        if not changed["value"]:
            replace_with_copy(path)
            changed["value"] = True
        return plan

    monkeypatch.setattr(
        execution_module, "_validate_publication_plan_at", validate_then_swap
    )
    second = IndividualRunExecutionCoordinator(
        root, FakeWorker(error=AssertionError("must not replay")),
        issue_execution_authority(), clock=lambda: NOW
    )
    with pytest.raises(RunRecordError):
        second.execute("zeeman", "zeeman-run-001")

    replacement = inspect_run(root, "zeeman", "zeeman-run-001")
    assert changed["value"] is True
    assert replacement.state == "running"
    assert replacement.integrity == "incomplete_publication"


def test_symlinked_results_directory_is_rejected_without_publication(tmp_path):
    root = make_run(tmp_path, retained=True)
    store, authority, current, lease = prepare_running(root)
    results = root / "data/runs/zeeman/zeeman-run-001/results"
    outside = tmp_path / "outside"
    outside.mkdir()
    results.rmdir()
    results.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises((OSError, RunRecordError)):
            store.publish_worker_artifacts(
                authority,
                "zeeman",
                "zeeman-run-001",
                expected_revision=current["revision"],
                product=retained_product(),
                lease=lease,
            )
        assert not list(outside.iterdir())
    finally:
        store.close()


def test_fifo_artifact_is_rejected_without_blocking_or_replacement(tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO unavailable")
    root = make_run(tmp_path, retained=True)
    store, authority, current, lease = prepare_running(root)
    fifo = root / "data/runs/zeeman/zeeman-run-001/results/states.npy"
    os.mkfifo(fifo)
    try:
        with pytest.raises(RunRecordError):
            store.publish_worker_artifacts(
                authority,
                "zeeman",
                "zeeman-run-001",
                expected_revision=current["revision"],
                product=retained_product(),
                lease=lease,
            )
        assert fifo.is_fifo()
    finally:
        store.close()


def test_mixed_configuration_snapshot_is_rejected_before_success(
    tmp_path, monkeypatch
):
    root = make_run(tmp_path)
    store, authority, current, lease = prepare_running(root)
    product = discarded_product()
    original_read = execution_module._read_record_at
    changed = {"value": False}

    def read_then_replace(parent, name, kind):
        value = original_read(parent, name, kind)
        if name == "configuration.json" and not changed["value"]:
            alternate = dict(value)
            alternate["laboratory_spec"] = {
                **value["laboratory_spec"],
                "sha256": "b" * 64,
            }
            execution_module._replace_at(
                parent, name, encode_record("configuration", alternate)
            )
            changed["value"] = True
        return value

    monkeypatch.setattr(execution_module, "_read_record_at", read_then_replace)
    try:
        with pytest.raises(RunRecordError):
            store.publish_success(
                authority,
                "zeeman",
                "zeeman-run-001",
                product=product,
                updated_utc=NOW,
                lease=lease,
            )
        assert changed["value"] is True
        assert store.read("zeeman", "zeeman-run-001", "status")["state"] == "running"
    finally:
        store.close()


def test_valid_alternate_run_swapped_after_inspection_never_starts_worker(
    tmp_path, monkeypatch
):
    root = make_run(tmp_path, seed=71)
    alternate_parent = tmp_path / "alternate"
    alternate_parent.mkdir()
    alternate_root = make_run(alternate_parent, seed=99)
    canonical_run = root / "data/runs/zeeman/zeeman-run-001"
    alternate_run = alternate_root / "data/runs/zeeman/zeeman-run-001"
    displaced = canonical_run.with_name("zeeman-run-001.inspected")
    real_inspect = execution_module.inspect_run
    swapped = {"value": False}

    def inspect_then_swap(*args, **kwargs):
        inspected = real_inspect(*args, **kwargs)
        if not swapped["value"]:
            canonical_run.rename(displaced)
            shutil.copytree(alternate_run, canonical_run)
            swapped["value"] = True
        return inspected

    monkeypatch.setattr(execution_module, "inspect_run", inspect_then_swap)
    worker = FakeWorker(discarded_product())
    coordinator = IndividualRunExecutionCoordinator(
        root, worker, issue_execution_authority(), clock=lambda: NOW
    )

    with pytest.raises(RunRecordError, match="changed after inspection"):
        coordinator.execute("zeeman", "zeeman-run-001")

    assert swapped["value"] is True
    assert worker.calls == 0
    replacement = real_inspect(root, "zeeman", "zeeman-run-001")
    assert replacement.state == "configured"
    assert replacement.configuration["resolved"]["simulation"]["seed"] == 99


@pytest.mark.skipif(sys.platform != "win32", reason="Windows lock/rename semantics")
@pytest.mark.parametrize("target", ["root", "data", "runs", "family", "run"])
def test_windows_blocks_publication_directory_replacement(tmp_path, monkeypatch, target):
    root = make_run(tmp_path)
    path = execution_target(root, target)
    real_publish = ExecutorLifecycleStore._publish_or_verify
    blocked = []

    def attempt_swap(parent, name, content):
        real_publish(parent, name, content)
        with pytest.raises(PermissionError):
            path.rename(path.with_name(path.name + "-replaced"))
        blocked.append(True)
        raise RunRecordError("Publication mutation was blocked")

    monkeypatch.setattr(ExecutorLifecycleStore, "_publish_or_verify", staticmethod(attempt_swap))
    coordinator = IndividualRunExecutionCoordinator(
        root, FakeWorker(discarded_product()), issue_execution_authority(), clock=lambda: NOW
    )
    with pytest.raises(RunRecordError):
        coordinator.execute("zeeman", "zeeman-run-001")
    assert blocked
    assert inspect_run(root, "zeeman", "zeeman-run-001").state == "running"
    assert not path.with_name(path.name + "-replaced").exists()
