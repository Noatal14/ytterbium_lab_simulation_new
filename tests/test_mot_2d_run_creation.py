from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading

import numpy as np
import pytest

from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_PHYSICAL_SPECIFICATION,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
)
from workflow_api.mot_2d_individual_sources import list_individual_mot_2d_sources
from workflow_api.mot_2d_run_creation import Mot2DRunCreationService
from workflow_api.mot_2d_run_plan import build_mot_2d_run_plan
from workflow_api.repository_snapshot import (
    MOT_2D_INDIVIDUAL_RELEVANT_FILES,
    RepositorySnapshot,
)
from workflow_api.run_records import RunRecordError, RunRecordStore


COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
CREATED = "2026-10-11T12:00:00+00:00"


class Clock:
    def __init__(self): self.value = 10.0
    def __call__(self): return self.value


class Snapshots:
    def __init__(self, commit=COMMIT_A):
        self.value = RepositorySnapshot(commit); self.values = []
    def capture(self):
        return self.values.pop(0) if self.values else self.value


def _source(root: Path, rows: int = 4) -> str:
    directory = root / "data/particle_states/after_zeeman/source"
    directory.mkdir(parents=True)
    profile = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]
    field = {
        key: list(profile[key])
        for key in ("radii_m", "positions_m", "tilt_angles_deg")
    }
    for seed in range(3000, 3035):
        state = directory / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
        np.save(state, np.arange(rows * 6, dtype=np.float64).reshape(rows, 6) + seed)
        state.with_suffix(".json").write_text(json.dumps({
            "shape": [rows, 6], "dtype": "float64", "n_survivors": rows,
            "output_sha256": hashlib.sha256(state.read_bytes()).hexdigest(),
            "laboratory_spec_version": LABORATORY_SPEC_VERSION,
            "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
            "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
            "parameters": {
                "seed": seed,
                "resolved_zeeman_magnet_profile": CANONICAL_ZEEMAN_PROFILE_NAME,
                "n_initial_atoms": 50_000, "dt_s": 4e-5,
                "zeeman_field_config": field,
            },
            "software": {"git_commit": COMMIT_A},
        }))
    return list_individual_mot_2d_sources(root)["sources"][0]["id"]


def _request(source_id: str) -> dict:
    return {
        "source_id": source_id, "particle_count": 20,
        "selection_seed": 123, "mot_seed": 456, "s0": 1.3,
        "detuning_gamma": -0.9196610026631429,
        "magnet_radius_m": 0.04676406447474441,
        "npools": 1,
        "retain_particle_states": True, "execution_mode": "local",
    }


def _service(root: Path, snapshots=None, **kwargs):
    return Mot2DRunCreationService(
        root, snapshots or Snapshots(),
        clock=kwargs.pop("clock", Clock()),
        token_factory=kwargs.pop("token_factory", lambda: "opaque-token"),
        run_id_factory=kwargs.pop("run_id_factory", lambda: "mot2d-run-001"),
        created_utc_factory=kwargs.pop("created_utc_factory", lambda: CREATED),
        **kwargs,
    )


def test_preview_is_pure_and_has_strict_detached_review_dto(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); request = _request(_source(root))
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    creator = _service(root, store_factory=lambda _root: (_ for _ in ()).throw(AssertionError()))
    response = creator.preview(request, "session-a")
    after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert before == after
    assert set(response) == {"preview_token", "expires_in_seconds", "plan"}
    assert set(response["plan"]) == {
        "run_id", "family", "source", "selection", "controls", "execution",
        "retention", "suitability", "output_disposition", "locked_settings",
        "lifecycle_state", "laboratory_specification", "numerical_policy",
        "plan_sha256", "execution_started", "submitted_to_zeus",
    }
    assert response["plan"]["family"] == "mot_2d"
    assert response["plan"]["suitability"] == "individual_only"
    assert response["plan"]["lifecycle_state"] == "configured"
    assert response["plan"]["execution_started"] is False
    assert response["plan"]["source"] == {
        "id": request["source_id"], "kind": "canonical_folder",
        "qualification": "canonical_campaign_source",
        "fingerprint": response["plan"]["source"]["fingerprint"],
        "pooled_particle_count": 140,
    }
    assert response["plan"]["selection"]["selected_count"] == 20
    assert response["plan"]["selection"]["seed"] == 123
    assert set(response["plan"]["selection"]) == {
        "algorithm", "version", "seed", "selected_count",
        "selected_identities_sha256",
    }
    expected = build_mot_2d_run_plan(
        request, repository_root=root, run_id="mot2d-run-001",
        git_revision=COMMIT_A, created_utc=CREATED,
    )
    assert expected.configuration["resolved"]["sampling"]["selection_seed"] == 123

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                assert key not in {"path", "metadata_path", "records", "selected_identities"}
                visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
        elif isinstance(value, str):
            lowered = value.lower()
            assert "data/" not in lowered
            assert "production_zeeman" not in lowered
            assert "private-run-name" not in lowered
    visit(response["plan"])


def test_confirm_creates_exact_configured_d2_records_only(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); request = _request(_source(root))
    expected = build_mot_2d_run_plan(
        request, repository_root=root, run_id="mot2d-run-001",
        git_revision=COMMIT_A, created_utc=CREATED,
    ).storage_records()
    creator = _service(root)
    result = creator.confirm(creator.preview(request, "session-a")["preview_token"], "session-a")
    assert result == {
        "status": "created", "run_id": "mot2d-run-001", "family": "mot_2d",
        "path": "data/runs/mot_2d/mot2d-run-001",
        "lifecycle_state": "configured", "execution_started": False,
        "submitted_to_zeus": False,
    }
    store = RunRecordStore(root)
    try:
        observed = {kind: store.read("mot_2d", "mot2d-run-001", kind)
                    for kind in ("run", "configuration", "inputs", "status")}
    finally:
        store.close()
    assert observed == expected
    destination = root / result["path"]
    assert not list((destination / "results").iterdir())
    assert not list((destination / "logs").iterdir())


def test_confirm_has_no_simulation_worker_zeus_network_or_job_submission_effect(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); request = _request(_source(root))
    creator = _service(root)
    result = creator.confirm(creator.preview(request, "session-a")["preview_token"], "session-a")
    assert result["execution_started"] is result["submitted_to_zeus"] is False
    assert not list(root.rglob("*.pbs"))


def test_source_change_between_preview_and_confirm_is_terminal(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); request = _request(_source(root))
    creator = _service(root); token = creator.preview(request, "session-a")["preview_token"]
    state = root / "data/particle_states/after_zeeman/source/production_zeeman_n50000_dt40us_seed3000.npy"
    np.save(state, np.full((4, 6), 7.0, dtype=np.float64))
    metadata = json.loads(state.with_suffix(".json").read_text())
    metadata["output_sha256"] = hashlib.sha256(state.read_bytes()).hexdigest()
    state.with_suffix(".json").write_text(json.dumps(metadata))
    with pytest.raises((RuntimeError, ValueError)):
        creator.confirm(token, "session-a")
    with pytest.raises(RuntimeError, match="no longer"):
        creator.confirm(token, "session-a")
    assert not (root / "data/runs").exists()


def test_wrong_session_does_not_consume_and_expired_preview_never_writes(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); request = _request(_source(root))
    clock = Clock(); creator = _service(root, clock=clock)
    token = creator.preview(request, "session-a")["preview_token"]
    with pytest.raises(PermissionError): creator.confirm(token, "session-b")
    assert creator.confirm(token, "session-a")["status"] == "created"
    root2 = tmp_path / "repo2"; root2.mkdir(); request2 = _request(_source(root2))
    clock2 = Clock(); expired = _service(root2, clock=clock2)
    token2 = expired.preview(request2, "session-a")["preview_token"]
    clock2.value += 300
    with pytest.raises(PermissionError): expired.confirm(token2, "session-a")
    assert not (root2 / "data/runs").exists()


def test_repository_change_and_preview_race_are_rejected(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); request = _request(_source(root))
    snapshots = Snapshots(); creator = _service(root, snapshots)
    token = creator.preview(request, "session-a")["preview_token"]
    snapshots.value = RepositorySnapshot(COMMIT_B)
    with pytest.raises(RuntimeError, match="stale"): creator.confirm(token, "session-a")
    assert not (root / "data/runs").exists()
    root2 = tmp_path / "repo2"; root2.mkdir(); request2 = _request(_source(root2))
    raced_snapshots = Snapshots(); raced_snapshots.values = [RepositorySnapshot(COMMIT_A), RepositorySnapshot(COMMIT_B)]
    with pytest.raises(RuntimeError, match="during preview"):
        _service(root2, raced_snapshots).preview(request2, "session-a")


def test_concurrent_double_confirm_publishes_once_and_is_idempotent(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); request = _request(_source(root))
    creator = _service(root); token = creator.preview(request, "session-a")["preview_token"]
    barrier = threading.Barrier(2)
    def click(): barrier.wait(); return creator.confirm(token, "session-a")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: click(), range(2)))
    assert results[0] == results[1]
    assert [p.name for p in (root / "data/runs/mot_2d").iterdir() if not p.name.startswith(".")] == ["mot2d-run-001"]


def test_cross_service_same_identity_and_store_failure_are_terminal(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); request = _request(_source(root))
    first = _service(root, token_factory=lambda: "one")
    second = _service(root, token_factory=lambda: "two")
    first.confirm(first.preview(request, "a")["preview_token"], "a")
    token = second.preview(request, "b")["preview_token"]
    with pytest.raises(RunRecordError, match="already exists"): second.confirm(token, "b")
    with pytest.raises(RuntimeError, match="no longer"): second.confirm(token, "b")


def test_invalid_dto_session_token_and_rate_limit_fail_closed(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); request = _request(_source(root))
    creator = _service(root, token_factory=lambda: __import__("secrets").token_urlsafe(24), run_id_factory=lambda: "mot2d-" + __import__("secrets").token_hex(8))
    with pytest.raises(ValueError): creator.preview({**request, "command": "qsub x"}, "a")
    for value in ("", "bad\nsession", "x" * 513):
        with pytest.raises(PermissionError): creator.preview(request, value)
        with pytest.raises(PermissionError): creator.confirm(value, "a")
    outcomes = []
    def attempt(_index):
        try: creator.preview(request, "rate-session"); outcomes.append("allowed")
        except BlockingIOError: outcomes.append("blocked")
    with ThreadPoolExecutor(max_workers=16) as pool: list(pool.map(attempt, range(20)))
    assert outcomes.count("allowed") == 12
    assert outcomes.count("blocked") == 8


def test_repository_snapshot_ledger_covers_admission_and_runtime_dependencies():
    paths = MOT_2D_INDIVIDUAL_RELEVANT_FILES
    assert len(paths) == len(set(paths))
    assert {
        "simulations/mot_2d.py",
        "lab_setup/config_builder.py",
        "utils/RK4StHybridCustom.py",
        "utils/RK4StCustom.py",
        "utils/ScipyIVP_3DCustom.py",
        "workflow_api/mot_2d_individual_sources.py",
        "workflow_api/mot_2d_run_creation.py",
        "workflow_api/mot_2d_run_plan.py",
        "workflow_api/specifications/mot_2d_individual_v1.json",
        "workflow_api/repository_paths.py",
        "workflow_api/run_discovery.py",
        "workflow_api/run_results.py",
    }.issubset(paths)
