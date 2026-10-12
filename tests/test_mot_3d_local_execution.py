import hashlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import workflow_api.mot_3d_run_plan as planning
from workflow_api.mot_3d_individual_api import IndividualMot3DApi
from workflow_api.mot_3d_individual_sources import ResolvedMot3DSource
from workflow_api.mot_3d_local_execution import Mot3DLocalWorker, _plain as local_plain
from workflow_api.mot_3d_run_plan import build_mot_3d_run_plan
from workflow_api.mot_3d_run_specification import MOT_3D_RUN_SPECIFICATION
from workflow_api.run_execution import (
    IndividualRunExecutionCoordinator,
    WorkerProductError,
    WorkerRequest,
    issue_execution_authority,
)
from workflow_api.run_records import RunRecordStore
from workflow_api.mot_3d_zeus_execution import (
    IndividualMot3DZeusCoordinator, _package_payload, build_frozen_mot_3d_package,
)
from workflow_api.mot_3d_zeus_worker import execute_package
from workflow_api.zeus_snapshot import ZeusProfile
from workflow_api.zeeman_zeus_execution import RemoteJobStatus, RemoteSubmission


NOW = "2026-10-12T10:00:00+00:00"
SOURCE_ID = "mot3d-source-" + "a" * 32


def _plan(root: Path, monkeypatch, *, retained=True, count=5, mode="local"):
    directory = root / "data/particle_states/after_2d_mot/source"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "states.npy"
    values = np.arange(60, dtype=np.float64).reshape(10, 6)
    np.save(path, values)
    relative = path.relative_to(root).as_posix()
    source = ResolvedMot3DSource(
        SOURCE_ID, "retained_individual_mot_2d", "verified_individual_result",
        10, "f" * 64,
        ({"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
          "size_bytes": path.stat().st_size, "shape": [10, 6],
          "dtype": "float64", "survivor_count": 10},),
    )
    monkeypatch.setattr(planning, "resolve_individual_mot_3d_source", lambda *_: source)
    request = {
        "source_id": SOURCE_ID, "geometry_family": "angled_donut",
        "particle_count": count, "selection_seed": 7, "simulation_seed": 11,
        "parameters": dict(MOT_3D_RUN_SPECIFICATION["defaults"]["angled_donut"]),
        "npools": 8 if mode == "local" else 200,
        "retain_particle_states": retained, "execution_mode": mode,
    }
    return build_mot_3d_run_plan(
        request, repository_root=root, run_id="mot3d-local-1",
        git_revision="b" * 40, created_utc=NOW,
    )


class Engine:
    def __init__(self): self.calls = []
    def __call__(self, states, **kwargs):
        self.calls.append((states.copy(), kwargs))
        trajectories = [
            SimpleNamespace(t=np.array([0.0, 0.1]), y=np.column_stack((state, state)))
            for state in states
        ]
        return trajectories, np.ascontiguousarray(states[:1])


def _analysis(trajectories, time_points, *, capture_config=None):
    count = len(trajectories); width = len(time_points)
    usable = np.zeros((count, width), dtype=bool)
    residence = np.zeros((count, width), dtype=bool)
    usable[:2, -1] = True; residence[:1, -1] = True
    return {"eligible_masks": usable, "residence_eligible_masks": residence}


def _request(plan):
    return WorkerRequest(plan.run, plan.configuration, plan.inputs)


def test_worker_executes_exact_frozen_plan_and_labels_both_outcomes(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root, monkeypatch)
    engine = Engine()
    product = Mot3DLocalWorker(
        root, engine=engine, analyzer=_analysis,
        monotonic=iter((1.0, 2.5)).__next__, clock=lambda: NOW,
    ).run(_request(plan))
    assert len(engine.calls) == 1
    states, kwargs = engine.calls[0]
    assert states.shape == (5, 6)
    assert kwargs["_3d_mot_config"] == local_plain(plan.configuration["resolved"]["mot_3d"]["resolved_profile"])
    assert kwargs["dt"] == 1e-5 and kwargs["t_max"] == 0.1
    assert kwargs["npools"] == 8 and kwargs["seed"] == 11
    assert kwargs["gravity_enabled"] is plan.configuration["resolved"]["simulation"]["gravity_enabled"]
    assert kwargs["capture_config"] == plan.configuration["resolved"]["mot_3d"]["capture"]
    metrics = product.results["metrics"]
    assert metrics["usable_at_end_count"] == 2
    assert metrics["usable_at_end_fraction"] == 0.4
    assert metrics["residence_qualified_captured_count"] == 1
    assert metrics["residence_qualified_captured_fraction"] == 0.2
    assert metrics["provenance"]["convergence_claim"] == "not_established"


@pytest.mark.parametrize("retained", [True, False])
def test_coordinator_atomically_publishes_states_or_receipt(tmp_path, monkeypatch, retained):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root, monkeypatch, retained=retained)
    records = plan.storage_records(); store = RunRecordStore(root)
    try: store.create(records["run"], records["configuration"], records["inputs"], records["status"])
    finally: store.close()
    engine = Engine(); worker = Mot3DLocalWorker(root, engine=engine, analyzer=_analysis, clock=lambda: NOW)
    coordinator = IndividualRunExecutionCoordinator(root, worker, issue_execution_authority(), clock=lambda: NOW)
    assert coordinator.execute("mot_3d", "mot3d-local-1") == {"state": "succeeded", "recovered": False, "worker_started": True}
    assert coordinator.execute("mot_3d", "mot3d-local-1") == {"state": "succeeded", "recovered": True, "worker_started": False}
    run = root / "data/runs/mot_3d/mot3d-local-1/results"
    assert (run / "summary.json").is_file()
    assert (run / "states.npy").is_file() is retained
    assert (run / "state_retention_receipt.json").is_file() is (not retained)
    assert len(engine.calls) == 1


def test_worker_rejects_wrong_family_cap_and_mutated_selection(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root, monkeypatch); engine = Engine()
    records = plan.storage_records(); records["run"]["family"] = "mot_2d"
    with pytest.raises(WorkerProductError, match="wrong run family"):
        Mot3DLocalWorker(root, engine=engine).run(WorkerRequest(records["run"], records["configuration"], records["inputs"]))
    records = plan.storage_records(); records["configuration"]["resolved"]["sampling"]["selected_identities_sha256"] = "0" * 64
    with pytest.raises(WorkerProductError, match="selection digest"):
        Mot3DLocalWorker(root, engine=engine).run(WorkerRequest(records["run"], records["configuration"], records["inputs"]))
    assert engine.calls == []


def test_worker_rejects_source_mutation_before_physics_starts(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root, monkeypatch)
    source_path = root / plan.inputs["artifacts"][0]["path"]
    values = np.load(source_path, allow_pickle=False)
    values[0, 0] += 1.0
    np.save(source_path, values, allow_pickle=False)
    engine = Engine()
    with pytest.raises(WorkerProductError, match="changed|digest|attestation"):
        Mot3DLocalWorker(root, engine=engine).run(_request(plan))
    assert engine.calls == []


def test_worker_rejects_inconsistent_residence_analysis(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root, monkeypatch)
    engine = Engine()

    def inconsistent(trajectories, time_points, *, capture_config=None):
        count = len(trajectories); width = len(time_points)
        usable = np.zeros((count, width), dtype=bool)
        residence = np.zeros((count, width), dtype=bool)
        residence[0, -1] = True
        return {"eligible_masks": usable, "residence_eligible_masks": residence}

    with pytest.raises(WorkerProductError, match="scientifically inconsistent"):
        Mot3DLocalWorker(root, engine=engine, analyzer=inconsistent).run(_request(plan))


def test_worker_rejects_correct_length_wrong_captured_states(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root, monkeypatch)

    class WrongStates(Engine):
        def __call__(self, states, **kwargs):
            trajectories, captured = super().__call__(states, **kwargs)
            return trajectories, captured + 1.0

    with pytest.raises(WorkerProductError, match="scientifically inconsistent"):
        Mot3DLocalWorker(root, engine=WrongStates(), analyzer=_analysis).run(_request(plan))


def test_worker_uses_frozen_capture_despite_runtime_global_drift(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root, monkeypatch)
    monkeypatch.setitem(
        __import__("config").MOT_3D_CAPTURE_CONFIG, "capture_radius_m", 999.0
    )
    observed = {}

    def analyzer(trajectories, time_points, *, capture_config=None):
        observed.update(capture_config)
        return _analysis(trajectories, time_points, capture_config=capture_config)

    Mot3DLocalWorker(root, engine=Engine(), analyzer=analyzer).run(_request(plan))
    assert observed == plan.configuration["resolved"]["mot_3d"]["capture"]


def test_worker_binds_gravity_to_reviewed_policy(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root, monkeypatch)
    records = plan.storage_records()
    records["configuration"]["resolved"]["simulation"]["gravity_enabled"] = False
    engine = Engine()
    with pytest.raises(WorkerProductError, match="trusted runtime"):
        Mot3DLocalWorker(root, engine=engine).run(
            WorkerRequest(records["run"], records["configuration"], records["inputs"])
        )
    assert engine.calls == []


def test_api_local_start_requires_verified_configured_local_run(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root, monkeypatch)
    records = plan.storage_records(); store = RunRecordStore(root)
    try: store.create(records["run"], records["configuration"], records["inputs"], records["status"])
    finally: store.close()
    class Creation: pass
    class Local:
        def __init__(self): self.calls = []
        def submit(self, family, run_id):
            self.calls.append((family, run_id))
            return type("Handle", (), {"run_id": run_id})()
    local = Local(); api = IndividualMot3DApi(root, Creation(), local)
    assert api.start_local({"run_id": "mot3d-local-1"}, session_id="session") == {"status": "queued", "run_id": "mot3d-local-1", "execution_mode": "local"}
    assert local.calls == [("mot_3d", "mot3d-local-1")]
    with pytest.raises(ValueError): api.start_local({"run_id": "missing"}, session_id="session")


def test_frozen_zeus_package_is_scalar_and_worker_reuses_same_science_adapter(
    tmp_path, monkeypatch,
):
    root = tmp_path / "repo"; root.mkdir()
    plan = _plan(root, monkeypatch, mode="zeus")
    records = plan.storage_records()
    package = build_frozen_mot_3d_package(
        root, records,
        ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new"),
    )
    assert b"#PBS -J" not in package.pbs
    assert b"mot_3d_zeus_worker" in package.pbs
    assert len(package.selected_states) < 3 * 1024 * 1024
    package_dir = root / ".workflow/individual-mot-3d" / package.package_sha256
    package_dir.mkdir(parents=True)
    path = package_dir / "package.json"
    path.write_text(json.dumps(_package_payload(package), sort_keys=True, separators=(",", ":")))
    monkeypatch.chdir(root); monkeypatch.setenv("PBS_JOBID", "502.zeus-master")
    product = execute_package(
        path.relative_to(root), package.package_sha256,
        worker_factory=lambda: Mot3DLocalWorker(
            root, engine=Engine(), analyzer=_analysis, clock=lambda: NOW,
        ),
    )
    assert product["job_id"] == "502.zeus-master"
    assert product["results"]["metrics"]["residence_qualified_captured_count"] == 1
    assert execute_package(
        path.relative_to(root), package.package_sha256,
        worker_factory=lambda: (_ for _ in ()).throw(AssertionError("must not rerun")),
    ) == product


def test_zeus_preview_confirm_refresh_is_idempotent_and_publishes_results(
    tmp_path, monkeypatch,
):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root, monkeypatch, mode="zeus")
    records = plan.storage_records(); store = RunRecordStore(root)
    try: store.create(records["run"], records["configuration"], records["inputs"], records["status"])
    finally: store.close()

    class Transport:
        operations = frozenset({"inspect", "stage", "submit", "status", "retrieve"})
        def __init__(self): self.calls = []; self.package = None
        def inspect(self, **kwargs): self.calls.append(("inspect", kwargs)); return RemoteSubmission("absent")
        def stage(self, **kwargs): self.calls.append(("stage", kwargs)); return RemoteSubmission("absent", kwargs["nonce"], None)
        def submit(self, **kwargs): self.calls.append(("submit", kwargs)); self.package = kwargs["package"]; return RemoteSubmission("submitted", kwargs["nonce"], "502.zeus-master")
        def status(self, **kwargs): self.calls.append(("status", kwargs)); return RemoteJobStatus("502.zeus-master", "succeeded", 0)
        def retrieve(self, **kwargs):
            self.calls.append(("retrieve", kwargs))
            selected = np.load(BytesIO(self.package.selected_states), allow_pickle=False)
            return Mot3DLocalWorker(root, engine=Engine(), analyzer=_analysis, clock=lambda: NOW).run_materialized(
                WorkerRequest(records["run"], records["configuration"], records["inputs"]), selected
            )

    transport = Transport()
    coordinator = IndividualMot3DZeusCoordinator(
        root, issue_execution_authority(), lambda _profile: transport,
        clock=lambda: 100.0, utc_clock=lambda: NOW,
        token_factory=lambda: "preview", nonce_factory=lambda: "1" * 32,
    )
    profile = ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new")
    preview = coordinator.preview(run_id="mot3d-local-1", profile=profile, session="owner")
    assert preview["job"]["array"] is False
    with pytest.raises(RuntimeError, match="confirmation_invalid"):
        coordinator.confirm(preview_token="preview", session="other")
    submitted = coordinator.confirm(preview_token="preview", session="owner")
    assert coordinator.confirm(preview_token="preview", session="owner") == submitted
    assert [name for name, _ in transport.calls].count("submit") == 1
    assert coordinator.refresh(run_id="mot3d-local-1", profile=profile)["state"] == "succeeded"
    inspected = __import__("workflow_api.run_discovery", fromlist=["inspect_run"]).inspect_run(
        root, "mot_3d", "mot3d-local-1"
    )
    assert inspected.integrity == "complete_verified"
