from pathlib import Path
import copy
import os
import socket
import threading

import numpy as np
import pytest

from workflow_api.run_discovery import inspect_run
from workflow_api.run_execution import (
    IndividualRunExecutionCoordinator,
    WorkerProductError,
    WorkerRequest,
    issue_execution_authority,
)
from workflow_api.run_records import RunRecordStore
from workflow_api.zeeman_local_execution import (
    BoundedLocalExecutionPool,
    ZeemanLocalWorker,
)
from workflow_api.zeeman_run_plan import build_zeeman_run_plan


NOW = "2026-10-11T12:00:00+00:00"


def plan(*, retained=True, count=4):
    return build_zeeman_run_plan(
        {
            "particle_count": count,
            "seed": 71,
            "mot_2d_s0": 1.3,
            "mot_2d_detuning_gamma": -0.9196610026631429,
            "mot_2d_magnet_radius_m": 0.04676406447474441,
            "npools": min(8, count),
            "retain_particle_states": retained,
            "execution_mode": "local",
        },
        run_id="zeeman-local-001",
        git_revision="a" * 40,
        created_utc=NOW,
    )


def request(*, retained=True, count=4):
    records = plan(retained=retained, count=count).storage_records()
    return WorkerRequest(
        run=records["run"],
        configuration=records["configuration"],
        inputs=records["inputs"],
    )


class Engine:
    def __init__(self, survivors=None, indices=None):
        self.survivors = (
            np.arange(12, dtype=np.float64).reshape(2, 6)
            if survivors is None
            else survivors
        )
        self.indices = np.array([0, 3], dtype=np.int64) if indices is None else indices
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return object(), self.survivors, self.indices


@pytest.mark.parametrize("retained", [False, True])
def test_local_worker_calls_trusted_engine_once_and_builds_exact_metrics(retained):
    engine = Engine()
    ticks = iter([10.0, 11.25])
    worker = ZeemanLocalWorker(
        engine=engine, monotonic=lambda: next(ticks), clock=lambda: NOW
    )
    product = worker.run(request(retained=retained))

    assert len(engine.calls) == 1
    call = engine.calls[0]
    assert call["N_particles"] == 4
    assert call["seed"] == 71
    assert call["npools"] == 4
    assert call["dt"] == 4e-5
    assert call["stochastic"] is True
    resolved = request(retained=retained).configuration["resolved"]
    assert set(call) == {
        "N_particles", "_2d_mot_config", "zeeman_config",
        "zeeman_field_config", "magnet_radius", "gravity_enabled", "npools",
        "stochastic", "dt", "collimation_angle_deg",
        "angular_broadening_factor", "seed", "t_max_s", "start_distance_m",
        "cutoff_distance_m",
    }
    assert call["zeeman_field_config"] == dict(resolved["zeeman"]["field"])
    assert call["zeeman_config"] == {
        "s0": resolved["zeeman"]["laser"]["s0"],
        "detuning_gamma": resolved["zeeman"]["laser"]["detuning_gamma"],
        "polarization": resolved["zeeman"]["laser"]["polarization"],
    }
    assert call["_2d_mot_config"] == dict(
        resolved["downstream_boundary"]["mot_2d_laser"]
    )
    assert set(product.results["metrics"]) == {
        "n_initial", "n_survivors", "captured", "survival_fraction", "elapsed_s"
    }
    assert product.results["metrics"] == {
        "n_initial": 4,
        "n_survivors": 2,
        "captured": 2,
        "survival_fraction": 0.5,
        "elapsed_s": 1.25,
    }
    assert product.results["states_retained"] is retained
    assert ("results/states.npy" in product.artifacts) is retained
    assert (product.receipt is None) is retained


@pytest.mark.parametrize(
    "survivors,indices",
    [
        (np.ones((2, 6), dtype=np.float32), np.array([0, 1])),
        (np.ones((2, 5), dtype=np.float64), np.array([0, 1])),
        (np.array([[np.nan] * 6], dtype=np.float64), np.array([0])),
        (np.ones((2, 6), dtype=np.float64), np.array([0])),
        (np.ones((2, 6), dtype=np.float64), np.array([0, 0])),
        (np.ones((2, 6), dtype=np.float64), np.array([0, 4])),
    ],
)
def test_local_worker_rejects_invalid_state_or_index_evidence(survivors, indices):
    worker = ZeemanLocalWorker(
        engine=Engine(survivors, indices),
        monotonic=iter([1.0, 2.0]).__next__,
        clock=lambda: NOW,
    )
    with pytest.raises(WorkerProductError):
        worker.run(request())


@pytest.mark.parametrize(
    "path,value",
    [
        (("zeeman", "laser", "waist_m"), 0.008),
        (("zeeman", "field", "magnet_polarization_T"), -1.0),
        (("numerical_policy", "solver"), "other"),
        (("numerical_policy", "dt_s"), 5e-5),
        (("numerical_policy", "t_max_s"), 0.03),
        (("simulation", "start_distance_m"), 0.4),
        (("simulation", "cutoff_distance_m"), 0.2),
        (("simulation", "force_scale_N"), 1.0),
    ],
)
def test_reviewed_construction_drift_fails_before_engine_call(path, value):
    base = request()
    configuration = copy.deepcopy(dict(base.configuration))
    cursor = configuration["resolved"]
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    altered = WorkerRequest(base.run, configuration, base.inputs)
    engine = Engine()
    worker = ZeemanLocalWorker(
        engine=engine, monotonic=iter([1.0, 2.0]).__next__, clock=lambda: NOW
    )
    with pytest.raises(WorkerProductError, match="trusted runtime"):
        worker.run(altered)
    assert engine.calls == []


def test_worker_rechecks_current_host_cpu_limit_before_engine_call(monkeypatch):
    import workflow_api.zeeman_run_specification as specification

    reviewed = request(count=12)
    monkeypatch.setattr(specification.os, "cpu_count", lambda: 4)
    engine = Engine()
    worker = ZeemanLocalWorker(
        engine=engine, monotonic=iter([1.0, 2.0]).__next__, clock=lambda: NOW
    )
    with pytest.raises(WorkerProductError, match="worker count"):
        worker.run(reviewed)
    assert engine.calls == []


def test_worker_rejects_more_processes_than_particles_before_engine_call():
    base = request(count=4)
    configuration = copy.deepcopy(dict(base.configuration))
    configuration["resolved"]["execution"]["workers"] = 5
    altered = WorkerRequest(base.run, configuration, base.inputs)
    engine = Engine()
    worker = ZeemanLocalWorker(
        engine=engine, monotonic=iter([1.0, 2.0]).__next__, clock=lambda: NOW
    )
    with pytest.raises(WorkerProductError, match="worker count"):
        worker.run(altered)
    assert engine.calls == []


def test_live_runtime_policy_drift_fails_before_engine_call(monkeypatch):
    import workflow_api.zeeman_local_execution as module

    engine = Engine()
    reviewed = request()
    monkeypatch.setitem(module.ZEEMAN_SIM_CONFIG, "dt_s", 9e-5)
    worker = ZeemanLocalWorker(
        engine=engine, monotonic=iter([1.0, 2.0]).__next__, clock=lambda: NOW
    )
    with pytest.raises(WorkerProductError, match="trusted runtime"):
        worker.run(reviewed)
    assert engine.calls == []


def test_fake_engine_integrates_through_e3_publication(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    records = plan(retained=True).storage_records()
    store = RunRecordStore(root)
    try:
        store.create(
            records["run"], records["configuration"], records["inputs"], records["status"]
        )
    finally:
        store.close()
    worker = ZeemanLocalWorker(
        engine=Engine(), monotonic=iter([1.0, 2.0]).__next__, clock=lambda: NOW
    )
    coordinator = IndividualRunExecutionCoordinator(
        root, worker, issue_execution_authority(), clock=lambda: NOW
    )

    assert coordinator.execute("zeeman", "zeeman-local-001")["state"] == "succeeded"
    inspected = inspect_run(root, "zeeman", "zeeman-local-001")
    assert inspected.integrity == "complete_verified"
    assert inspected.results["metrics"]["n_initial"] == 4
    assert inspected.results["metrics"]["n_survivors"] == 2
    assert not (root / "data/runs/zeeman/zeeman-local-001/logs/run.log").exists()


class BlockingCoordinator:
    entered = threading.Event()
    release = threading.Event()

    def __init__(self, _root, _worker, _authority):
        pass

    def execute(self, family, run_id):
        self.entered.set()
        self.release.wait(timeout=5)
        return {"state": "succeeded", "family": family, "run_id": run_id}


def test_background_pool_is_bounded_and_cancels_only_proven_queued_work(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    records = plan(retained=False).storage_records()
    store = RunRecordStore(root)
    try:
        store.create(
            records["run"], records["configuration"], records["inputs"], records["status"]
        )
        second = build_zeeman_run_plan(
            {
                "particle_count": 4,
                "seed": 72,
                "mot_2d_s0": 1.3,
                "mot_2d_detuning_gamma": -0.9196610026631429,
                "mot_2d_magnet_radius_m": 0.04676406447474441,
                "npools": 4,
                "retain_particle_states": False,
                "execution_mode": "local",
            },
            run_id="zeeman-local-002",
            git_revision="a" * 40,
            created_utc=NOW,
        ).storage_records()
        store.create(
            second["run"], second["configuration"], second["inputs"], second["status"]
        )
    finally:
        store.close()

    BlockingCoordinator.entered.clear()
    BlockingCoordinator.release.clear()
    pool = BoundedLocalExecutionPool(
        root,
        issue_execution_authority(),
        max_concurrent=1,
        max_pending=2,
        coordinator_factory=BlockingCoordinator,
    )
    try:
        first = pool.submit("zeeman", "zeeman-local-001")
        assert BlockingCoordinator.entered.wait(timeout=2)
        pool.submit("zeeman", "zeeman-local-002")
        with pytest.raises(RuntimeError, match="full"):
            pool.submit("zeeman", "zeeman-local-003")
        assert pool.cancel_queued(
            "zeeman", "zeeman-local-001", updated_utc=NOW
        ) is False
        assert pool.cancel_queued(
            "zeeman", "zeeman-local-002", updated_utc=NOW
        ) is True
        assert inspect_run(root, "zeeman", "zeeman-local-002").state == "cancelled"
        BlockingCoordinator.release.set()
        assert first.future.result(timeout=2)["state"] == "succeeded"
        assert ("zeeman", "zeeman-local-001") not in pool._handles
        assert ("zeeman", "zeeman-local-002") not in pool._handles
    finally:
        BlockingCoordinator.release.set()
        pool.close()


def test_worker_has_no_shell_network_ssh_or_zeus_path(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("external side effect forbidden")

    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    engine = Engine()
    product = ZeemanLocalWorker(
        engine=engine, monotonic=iter([1.0, 2.0]).__next__, clock=lambda: NOW
    ).run(request())
    assert product.results["metrics"]["n_survivors"] == 2
    assert len(engine.calls) == 1


def test_cancelled_key_cannot_be_resubmitted_before_durable_cancel_cas(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    root.mkdir()
    store = RunRecordStore(root)
    try:
        for run_id, seed in (("zeeman-local-001", 71), ("zeeman-local-002", 72)):
            records = build_zeeman_run_plan(
                {
                    "particle_count": 4,
                    "seed": seed,
                    "mot_2d_s0": 1.3,
                    "mot_2d_detuning_gamma": -0.9196610026631429,
                    "mot_2d_magnet_radius_m": 0.04676406447474441,
                    "npools": 4,
                    "retain_particle_states": False,
                    "execution_mode": "local",
                },
                run_id=run_id,
                git_revision="a" * 40,
                created_utc=NOW,
            ).storage_records()
            store.create(
                records["run"], records["configuration"],
                records["inputs"], records["status"]
            )
    finally:
        store.close()

    BlockingCoordinator.entered.clear()
    BlockingCoordinator.release.clear()
    update_entered = threading.Event()
    allow_update = threading.Event()
    original_update = RunRecordStore.update_status

    def paused_update(self, family, run_id, proposed):
        if run_id == "zeeman-local-002":
            update_entered.set()
            assert allow_update.wait(timeout=5)
        return original_update(self, family, run_id, proposed)

    monkeypatch.setattr(RunRecordStore, "update_status", paused_update)
    pool = BoundedLocalExecutionPool(
        root,
        issue_execution_authority(),
        max_concurrent=1,
        max_pending=2,
        coordinator_factory=BlockingCoordinator,
    )
    outcome = {}
    try:
        first = pool.submit("zeeman", "zeeman-local-001")
        assert BlockingCoordinator.entered.wait(timeout=2)
        pool.submit("zeeman", "zeeman-local-002")

        thread = threading.Thread(
            target=lambda: outcome.setdefault(
                "cancelled",
                pool.cancel_queued(
                    "zeeman", "zeeman-local-002", updated_utc=NOW
                ),
            )
        )
        thread.start()
        assert update_entered.wait(timeout=2)
        with pytest.raises(RuntimeError, match="already scheduled"):
            pool.submit("zeeman", "zeeman-local-002")
        allow_update.set()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert outcome == {"cancelled": True}
        assert inspect_run(root, "zeeman", "zeeman-local-002").state == "cancelled"
        BlockingCoordinator.release.set()
        first.future.result(timeout=2)
    finally:
        allow_update.set()
        BlockingCoordinator.release.set()
        pool.close()


@pytest.fixture(autouse=True)
def fixed_cpu_budget(monkeypatch):
    # These fixtures explicitly request eight workers. Model a known host;
    # CPU-limit tests override this again to exercise smaller hosts.
    import workflow_api.zeeman_run_specification as specification
    monkeypatch.setattr(specification.os, "cpu_count", lambda: 16)
