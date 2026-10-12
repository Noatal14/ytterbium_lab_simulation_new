from pathlib import Path

import pytest

import workflow_api.mot_3d_run_plan as planning
from workflow_api.mot_3d_individual_sources import ResolvedMot3DSource
from workflow_api.mot_3d_run_plan import build_mot_3d_run_plan, validate_mot_3d_run_request
from workflow_api.mot_3d_run_specification import MOT_3D_RUN_SPECIFICATION
from workflow_api.run_records import validate_record


NOW = "2026-10-12T10:00:00+00:00"
SOURCE_ID = "mot3d-source-" + "a" * 32


def _source(fingerprint="f" * 64):
    return ResolvedMot3DSource(
        SOURCE_ID, "canonical_2d_campaign", "canonical_campaign_source", 10,
        fingerprint,
        (
            {"path": "data/particle_states/after_2d_mot/a.npy", "metadata_path": "data/particle_states/after_2d_mot/a.json", "sha256": "1" * 64, "metadata_sha256": "2" * 64, "size_bytes": 608, "metadata_size_bytes": 200, "shape": [3, 6], "dtype": "float64", "survivor_count": 3},
            {"path": "data/particle_states/after_2d_mot/b.npy", "sha256": "3" * 64, "size_bytes": 1472, "shape": [7, 6], "dtype": "float64", "survivor_count": 7},
        ),
    )


def _request(family="angled_donut", **updates):
    value = {
        "source_id": SOURCE_ID, "geometry_family": family, "particle_count": 5,
        "selection_seed": 7, "simulation_seed": 11,
        "parameters": dict(MOT_3D_RUN_SPECIFICATION["defaults"][family]),
        "retain_particle_states": True, "execution_mode": "local",
    }
    value.update(updates); return value


def _plan(root: Path, request, monkeypatch, source=None):
    monkeypatch.setattr(planning, "resolve_individual_mot_3d_source", lambda *_: source or _source())
    return build_mot_3d_run_plan(request, repository_root=root, run_id="mot3d-run-001", git_revision="b" * 40, created_utc=NOW)


@pytest.mark.parametrize("family", ["angled_donut", "single_pass"])
def test_plan_freezes_exact_family_science_sampling_and_d2_records(tmp_path, monkeypatch, family):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root, _request(family), monkeypatch)
    records = plan.storage_records(); resolved = records["configuration"]["resolved"]
    assert resolved["mot_3d"]["geometry_family"] == family
    assert set(resolved["mot_3d"]["parameters"]) == set(MOT_3D_RUN_SPECIFICATION["defaults"][family])
    assert resolved["numerical_policy"] == {"solver": "RK4StHybridCustom", "dt_s": 1e-5, "t_max_s": 0.1, "convergence_claim": "not_established"}
    assert resolved["sampling"]["selected_identities"] == [[1, 0], [1, 1], [1, 2], [1, 3], [1, 6]]
    assert plan.run["suitability"] == "individual_only"
    assert plan.review.source_qualification == "canonical_campaign_source"
    for kind, record in records.items(): validate_record(kind, record)


def test_plan_is_deterministic_and_seed_roles_are_independent(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); first = _plan(root, _request(), monkeypatch)
    assert _plan(root, _request(), monkeypatch).plan_sha256 == first.plan_sha256
    simulation = _plan(root, _request(simulation_seed=12), monkeypatch)
    assert simulation.configuration["resolved"]["sampling"] == first.configuration["resolved"]["sampling"]
    selected = _plan(root, _request(selection_seed=8), monkeypatch)
    assert selected.configuration["resolved"]["sampling"] != first.configuration["resolved"]["sampling"]


def test_request_is_exact_family_specific_and_mode_bounded():
    validate_mot_3d_run_request(_request())
    validate_mot_3d_run_request(_request(execution_mode="zeus", particle_count=50_000))
    mutations = [
        lambda row: row.update(extra=True), lambda row: row.pop("simulation_seed"),
        lambda row: row.update(particle_count=1001), lambda row: row.update(selection_seed=True),
        lambda row: row.update(geometry_family="other"),
        lambda row: row["parameters"].update(blue_crossing_angle_deg=45.0),
        lambda row: row["parameters"].update(green_s0=float("nan")),
    ]
    for mutate in mutations:
        row = _request(); mutate(row)
        with pytest.raises(ValueError): validate_mot_3d_run_request(row)


def test_count_cannot_exceed_fresh_source_and_plan_is_immutable(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir()
    with pytest.raises(ValueError, match="exceeds"):
        _plan(root, _request(particle_count=11), monkeypatch)
    plan = _plan(root, _request(), monkeypatch)
    detached = plan.storage_records(); detached["run"]["seed"] = 1
    assert plan.run["seed"] == 11
    with pytest.raises(TypeError): plan.configuration["resolved"]["mot_3d"]["parameters"]["green_s0"] = 1
