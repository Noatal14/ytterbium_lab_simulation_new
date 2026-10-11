from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import subprocess
import threading

import pytest

import workflow_api.zeeman_run_plan as zeeman_run_plan
from workflow_api.repository_snapshot import RepositorySnapshot
from workflow_api.run_records import RunRecordError, RunRecordStore
from workflow_api.zeeman_run_creation import ZeemanRunCreationService
from workflow_api.zeeman_run_plan import build_zeeman_run_plan


COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
CREATED = "2026-10-11T12:00:00+00:00"
REQUEST = {
    "particle_count": 1_000,
    "seed": 73,
    "retain_particle_states": True,
    "execution_mode": "local",
}


class Clock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        return self.value


class Snapshots:
    def __init__(self, commit=COMMIT_A):
        self.value = RepositorySnapshot(commit)
        self.values = []

    def capture(self):
        if self.values:
            return self.values.pop(0)
        return self.value


def service(tmp_path, snapshots=None, **kwargs):
    return ZeemanRunCreationService(
        tmp_path,
        snapshots or Snapshots(),
        clock=kwargs.pop("clock", Clock()),
        token_factory=kwargs.pop("token_factory", lambda: "opaque-token"),
        run_id_factory=kwargs.pop("run_id_factory", lambda: "zeeman-run-001"),
        created_utc_factory=kwargs.pop("created_utc_factory", lambda: CREATED),
        **kwargs,
    )


def test_preview_is_pure_and_returns_only_reviewable_configured_plan(tmp_path):
    def forbidden_store(_root):
        raise AssertionError("preview crossed the persistence boundary")

    creator = service(tmp_path, store_factory=forbidden_store)
    response = creator.preview(REQUEST, "session-a")

    assert response["preview_token"] == "opaque-token"
    assert response["expires_in_seconds"] == 300
    assert response["plan"] == {
        **response["plan"],
        "run_id": "zeeman-run-001",
        "family": "zeeman",
        "execution_mode": "local",
        "particle_count": 1_000,
        "seed": 73,
        "retain_particle_states": True,
        "suitability": "individual_only",
        "output_disposition": "retain_survivor_states",
        "lifecycle_state": "configured",
        "execution_started": False,
        "submitted_to_zeus": False,
    }
    assert len(response["plan"]["plan_sha256"]) == 64
    assert response["plan"]["locked_settings"]["solver"] == "RK4StCustom"
    expected = build_zeeman_run_plan(
        REQUEST,
        run_id="zeeman-run-001",
        git_revision=COMMIT_A,
        created_utc=CREATED,
    )
    assert response["plan"]["resolved_configuration"] == expected.storage_records()[
        "configuration"
    ]["resolved"]
    response["plan"]["resolved_configuration"]["simulation"]["seed"] = -1
    assert expected.configuration["resolved"]["simulation"]["seed"] == 73
    assert not (tmp_path / "data").exists()


def test_confirm_atomically_creates_only_configured_d2_package(tmp_path):
    creator = service(tmp_path)
    token = creator.preview(REQUEST, "session-a")["preview_token"]
    result = creator.confirm(token, "session-a")

    assert result == {
        "status": "created",
        "run_id": "zeeman-run-001",
        "family": "zeeman",
        "path": "data/runs/zeeman/zeeman-run-001",
        "lifecycle_state": "configured",
        "execution_started": False,
        "submitted_to_zeus": False,
    }
    destination = tmp_path / result["path"]
    assert sorted(path.name for path in destination.iterdir()) == [
        "configuration.json", "inputs.json", "logs", "results", "run.json", "status.json"
    ]
    store = RunRecordStore(tmp_path)
    try:
        assert store.read("zeeman", "zeeman-run-001", "status")["state"] == "configured"
        assert store.read("zeeman", "zeeman-run-001", "run")["suitability"] == "individual_only"
    finally:
        store.close()
    assert not list((destination / "results").iterdir())
    assert not list((destination / "logs").iterdir())


def test_confirm_stores_exactly_the_fixed_e1_plan_records(tmp_path):
    expected = build_zeeman_run_plan(
        REQUEST,
        run_id="zeeman-run-001",
        git_revision=COMMIT_A,
        created_utc=CREATED,
    ).storage_records()
    creator = service(tmp_path)
    token = creator.preview(REQUEST, "session-a")["preview_token"]
    creator.confirm(token, "session-a")

    store = RunRecordStore(tmp_path)
    try:
        observed = {
            kind: store.read("zeeman", "zeeman-run-001", kind)
            for kind in ("run", "configuration", "inputs", "status")
        }
    finally:
        store.close()
    assert observed == expected


def test_confirm_never_starts_process_or_contacts_ssh_or_qsub(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("confirmation attempted process execution")

    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    monkeypatch.setattr(os, "system", forbidden)

    creator = service(tmp_path)
    token = creator.preview(REQUEST, "session-a")["preview_token"]
    result = creator.confirm(token, "session-a")
    assert result["execution_started"] is False
    assert result["submitted_to_zeus"] is False
    assert not list(tmp_path.rglob("*.pbs"))


def test_repeat_confirm_is_idempotent_and_returns_detached_result(tmp_path):
    creator = service(tmp_path)
    token = creator.preview(REQUEST, "session-a")["preview_token"]
    first = creator.confirm(token, "session-a")
    first["path"] = "tampered"
    second = creator.confirm(token, "session-a")
    assert second["path"] == "data/runs/zeeman/zeeman-run-001"
    assert [
        path.name
        for path in (tmp_path / "data/runs/zeeman").iterdir()
        if not path.name.startswith(".")
    ] == ["zeeman-run-001"]


def test_wrong_session_does_not_consume_preview(tmp_path):
    creator = service(tmp_path)
    token = creator.preview(REQUEST, "session-a")["preview_token"]
    with pytest.raises(PermissionError):
        creator.confirm(token, "session-b")
    assert creator.confirm(token, "session-a")["status"] == "created"


def test_expiry_boundary_rejects_and_never_writes(tmp_path):
    clock = Clock()
    creator = service(tmp_path, clock=clock)
    token = creator.preview(REQUEST, "session-a")["preview_token"]
    clock.value += 300
    with pytest.raises(PermissionError):
        creator.confirm(token, "session-a")
    assert not (tmp_path / "data").exists()


def test_repository_change_is_terminal_even_if_commit_changes_back(tmp_path):
    snapshots = Snapshots()
    creator = service(tmp_path, snapshots)
    token = creator.preview(REQUEST, "session-a")["preview_token"]
    snapshots.value = RepositorySnapshot(COMMIT_B)
    with pytest.raises(RuntimeError, match="stale"):
        creator.confirm(token, "session-a")
    snapshots.value = RepositorySnapshot(COMMIT_A)
    with pytest.raises(RuntimeError, match="no longer"):
        creator.confirm(token, "session-a")
    assert not (tmp_path / "data").exists()


def test_change_between_rebuild_and_final_snapshot_is_terminal(tmp_path):
    snapshots = Snapshots()
    creator = service(tmp_path, snapshots)
    token = creator.preview(REQUEST, "session-a")["preview_token"]
    snapshots.values = [RepositorySnapshot(COMMIT_A), RepositorySnapshot(COMMIT_B)]
    with pytest.raises(RuntimeError, match="changed before"):
        creator.confirm(token, "session-a")
    assert not (tmp_path / "data").exists()


def test_scientific_plan_drift_after_preview_is_terminal(tmp_path, monkeypatch):
    creator = service(tmp_path)
    token = creator.preview(REQUEST, "session-a")["preview_token"]
    monkeypatch.setitem(
        zeeman_run_plan.ZEEMAN_LASER_CONFIG,
        "s0",
        zeeman_run_plan.ZEEMAN_LASER_CONFIG["s0"] + 0.01,
    )
    with pytest.raises((RuntimeError, ValueError)):
        creator.confirm(token, "session-a")
    assert not (tmp_path / "data").exists()


def test_double_click_is_serialized_and_publishes_once(tmp_path):
    creator = service(tmp_path)
    token = creator.preview(REQUEST, "session-a")["preview_token"]
    barrier = threading.Barrier(2)

    def click():
        barrier.wait()
        return creator.confirm(token, "session-a")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: click(), range(2)))
    assert results[0] == results[1]
    assert [
        path.name
        for path in (tmp_path / "data/runs/zeeman").iterdir()
        if not path.name.startswith(".")
    ] == ["zeeman-run-001"]


def test_two_services_cannot_publish_same_run_identity(tmp_path):
    first = service(tmp_path, token_factory=lambda: "token-one")
    second = service(tmp_path, token_factory=lambda: "token-two")
    token_one = first.preview(REQUEST, "session-a")["preview_token"]
    token_two = second.preview(REQUEST, "session-b")["preview_token"]
    assert first.confirm(token_one, "session-a")["status"] == "created"
    with pytest.raises(RunRecordError, match="already exists"):
        second.confirm(token_two, "session-b")
    with pytest.raises(RuntimeError, match="no longer"):
        second.confirm(token_two, "session-b")


def test_store_failure_closes_store_and_makes_token_terminal(tmp_path):
    stores = []

    class FailingStore:
        def __init__(self, _root):
            self.closed = False
            stores.append(self)

        def create(self, *_records):
            raise OSError("injected failure")

        def close(self):
            self.closed = True

    creator = service(tmp_path, store_factory=FailingStore)
    token = creator.preview(REQUEST, "session-a")["preview_token"]
    with pytest.raises(OSError, match="injected"):
        creator.confirm(token, "session-a")
    assert stores[0].closed is True
    with pytest.raises(RuntimeError, match="no longer"):
        creator.confirm(token, "session-a")


@pytest.mark.parametrize("value", ["", "bad\nsession", "x" * 513])
def test_session_and_token_inputs_are_bounded(tmp_path, value):
    creator = service(tmp_path)
    with pytest.raises(PermissionError):
        creator.preview(REQUEST, value)
    with pytest.raises(PermissionError):
        creator.confirm(value, "session-a")


def test_invalid_request_and_preview_repository_race_never_register_or_write(tmp_path):
    creator = service(tmp_path)
    with pytest.raises(ValueError):
        creator.preview({**REQUEST, "command": "qsub bad.pbs"}, "session-a")

    snapshots = Snapshots()
    snapshots.values = [RepositorySnapshot(COMMIT_A), RepositorySnapshot(COMMIT_B)]
    raced = service(tmp_path, snapshots)
    with pytest.raises(RuntimeError, match="during preview"):
        raced.preview(REQUEST, "session-a")
    assert not (tmp_path / "data").exists()


def test_per_session_rate_limit_is_thread_safe(tmp_path):
    creator = service(
        tmp_path,
        token_factory=lambda: __import__("secrets").token_urlsafe(24),
        run_id_factory=lambda: "zeeman-" + __import__("secrets").token_hex(8),
    )
    outcomes = []

    def attempt(_index):
        try:
            creator.preview(REQUEST, "one-session")
            outcomes.append("allowed")
        except BlockingIOError:
            outcomes.append("blocked")

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(attempt, range(20)))
    assert outcomes.count("allowed") == 12
    assert outcomes.count("blocked") == 8
