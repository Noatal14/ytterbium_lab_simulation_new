from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import threading

import pytest

import workflow_api.mot_3d_run_plan as planning
from studies.mot_3d.discovery.optimize import build_profile_from_parameters
from workflow_api.mot_3d_individual_sources import ResolvedMot3DSource
from workflow_api.mot_3d_run_creation import Mot3DRunCreationService
from workflow_api.mot_3d_run_specification import MOT_3D_RUN_SPECIFICATION
from workflow_api.repository_snapshot import (
    MOT_3D_INDIVIDUAL_RELEVANT_FILES,
    RepositorySnapshot,
)
from workflow_api.run_records import RunRecordStore


COMMIT = "a" * 40; CREATED = "2026-10-12T12:00:00+00:00"; SOURCE_ID = "mot3d-source-" + "a" * 32


class Clock:
    def __init__(self): self.value = 10.0
    def __call__(self): return self.value


class Snapshots:
    def __init__(self): self.value = RepositorySnapshot(COMMIT); self.values = []
    def capture(self): return self.values.pop(0) if self.values else self.value


def _source(fingerprint="f" * 64):
    return ResolvedMot3DSource(SOURCE_ID, "retained_individual_mot_2d", "verified_individual_result", 5, fingerprint, ({"path": "data/runs/mot_2d/upstream/results/states.npy", "sha256": "1" * 64, "size_bytes": 368, "shape": [5, 6], "dtype": "float64", "survivor_count": 5},))


def _request():
    return {"source_id": SOURCE_ID, "geometry_family": "angled_donut", "particle_count": 5, "selection_seed": 7, "simulation_seed": 11, "parameters": dict(MOT_3D_RUN_SPECIFICATION["defaults"]["angled_donut"]), "npools": 1, "retain_particle_states": True, "execution_mode": "local"}


def _service(root, **kwargs):
    return Mot3DRunCreationService(root, kwargs.pop("snapshots", Snapshots()), clock=kwargs.pop("clock", Clock()), token_factory=kwargs.pop("token_factory", lambda: "opaque-token"), run_id_factory=lambda: "mot3d-run-001", created_utc_factory=lambda: CREATED, **kwargs)


@pytest.fixture(autouse=True)
def source(monkeypatch):
    current = {"value": _source()}
    monkeypatch.setattr(planning, "resolve_individual_mot_3d_source", lambda *_: current["value"])
    return current


def test_preview_is_pure_private_evidence_is_hidden_and_confirm_only_configures(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); creator = _service(root)
    preview = creator.preview(_request(), "session-a")
    assert json.loads(json.dumps(preview)) == preview
    assert set(preview["plan"]) == {"run_id", "family", "source", "selection", "geometry", "execution", "retention", "suitability", "output_disposition", "locked_settings", "lifecycle_state", "laboratory_specification", "numerical_policy", "plan_sha256", "execution_started", "submitted_to_zeus"}
    assert preview["plan"]["geometry"] == {
        "family": "angled_donut",
        "parameters": dict(MOT_3D_RUN_SPECIFICATION["defaults"]["angled_donut"]),
        "derived_parameters": {},
    }
    assert "path" not in str(preview["plan"])
    result = creator.confirm(preview["preview_token"], "session-a")
    assert result == {"status": "created", "run_id": "mot3d-run-001", "family": "mot_3d", "path": "data/runs/mot_3d/mot3d-run-001", "lifecycle_state": "configured", "execution_started": False, "submitted_to_zeus": False}
    store = RunRecordStore(root)
    try:
        assert store.read("mot_3d", "mot3d-run-001", "status")["state"] == "configured"
    finally: store.close()
    assert not list((root / result["path"] / "results").iterdir())


def test_single_pass_preview_publishes_canonical_derived_geometry(tmp_path):
    root = tmp_path / "repo"; root.mkdir()
    request = _request()
    request["geometry_family"] = "single_pass"
    request["parameters"] = dict(MOT_3D_RUN_SPECIFICATION["defaults"]["single_pass"])
    preview = _service(root).preview(request, "session-a")
    assert json.loads(json.dumps(preview)) == preview
    _, _, expected = build_profile_from_parameters("single_pass", request["parameters"])
    assert preview["plan"]["geometry"]["derived_parameters"] == expected
    assert set(expected) == {
        "blue_detuning_gamma",
        "effective_slowing_z_offset_m",
        "effective_slowing_field_G",
        "reference_slowing_field_G",
    }


def test_session_expiry_repository_race_and_source_drift_fail_closed(tmp_path, source):
    root = tmp_path / "repo"; root.mkdir(); clock = Clock(); creator = _service(root, clock=clock)
    token = creator.preview(_request(), "a")["preview_token"]
    with pytest.raises(PermissionError): creator.confirm(token, "b")
    source["value"] = _source("e" * 64)
    with pytest.raises(RuntimeError, match="stale"): creator.confirm(token, "a")
    assert not (root / "data/runs").exists()
    root2 = tmp_path / "repo2"; root2.mkdir(); clock2 = Clock(); expired = _service(root2, clock=clock2)
    token2 = expired.preview(_request(), "a")["preview_token"]; clock2.value += 300
    with pytest.raises(PermissionError): expired.confirm(token2, "a")


def test_concurrent_double_confirm_is_idempotent(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); creator = _service(root); token = creator.preview(_request(), "a")["preview_token"]
    barrier = threading.Barrier(2)
    def click(): barrier.wait(); return creator.confirm(token, "a")
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: click(), range(2)))
    assert results[0] == results[1]
    assert [path.name for path in (root / "data/runs/mot_3d").iterdir() if not path.name.startswith(".")] == ["mot3d-run-001"]


def test_preview_repository_race_and_store_are_bounded(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); snapshots = Snapshots(); snapshots.values = [RepositorySnapshot(COMMIT), RepositorySnapshot("b" * 40)]
    with pytest.raises(RuntimeError, match="during preview"): _service(root, snapshots=snapshots).preview(_request(), "a")
    assert not (root / "data/runs").exists()


def test_snapshot_ledger_includes_transitive_source_admission_authorities():
    assert "workflow_api/mot_2d_individual_sources.py" in MOT_3D_INDIVIDUAL_RELEVANT_FILES
    assert "workflow_api/run_results.py" in MOT_3D_INDIVIDUAL_RELEVANT_FILES
    assert "workflow_api/mot_2d_local_execution.py" in MOT_3D_INDIVIDUAL_RELEVANT_FILES
    assert "workflow_api/mot_3d_local_execution.py" in MOT_3D_INDIVIDUAL_RELEVANT_FILES
    assert "workflow_api/run_execution.py" in MOT_3D_INDIVIDUAL_RELEVANT_FILES
    assert "workflow_api/zeeman_local_execution.py" in MOT_3D_INDIVIDUAL_RELEVANT_FILES
    assert len(MOT_3D_INDIVIDUAL_RELEVANT_FILES) == len(
        set(MOT_3D_INDIVIDUAL_RELEVANT_FILES)
    )
