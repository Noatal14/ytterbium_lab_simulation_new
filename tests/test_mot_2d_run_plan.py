import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from lab_setup.physical_specification import CANONICAL_ZEEMAN_PROFILE_NAME, CANONICAL_ZEEMAN_PROFILE_SHA256, LABORATORY_PHYSICAL_SPECIFICATION, LABORATORY_SPEC_SHA256, LABORATORY_SPEC_VERSION
from workflow_api.mot_2d_individual_sources import ResolvedMot2DSource, list_individual_mot_2d_sources
from workflow_api.mot_2d_run_plan import _sample, build_mot_2d_run_plan, validate_mot_2d_run_request
from workflow_api.run_records import validate_record


NOW = "2026-10-11T10:00:00+00:00"


def _source(root: Path, rows=4):
    directory = root / "data/particle_states/after_zeeman/source"
    directory.mkdir(parents=True)
    profile = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]
    field = {key: list(profile[key]) for key in ("radii_m", "positions_m", "tilt_angles_deg")}
    for seed in range(3000, 3035):
        state = directory / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
        np.save(state, np.arange(rows * 6, dtype=np.float64).reshape(rows, 6) + seed)
        digest = hashlib.sha256(state.read_bytes()).hexdigest()
        state.with_suffix(".json").write_text(json.dumps({
            "shape": [rows, 6], "dtype": "float64", "n_survivors": rows,
            "output_sha256": digest, "laboratory_spec_version": LABORATORY_SPEC_VERSION,
            "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
            "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
            "parameters": {"seed": seed, "resolved_zeeman_magnet_profile": CANONICAL_ZEEMAN_PROFILE_NAME, "n_initial_atoms": 50000, "dt_s": 4e-5, "zeeman_field_config": field},
            "software": {"git_commit": "a" * 40},
        }))
    return list_individual_mot_2d_sources(root)["sources"][0]["id"]


def _request(source_id, **updates):
    value = {"source_id": source_id, "particle_count": 20, "selection_seed": 123, "mot_seed": 456, "s0": 1.3, "detuning_gamma": -0.9196610026631429, "magnet_radius_m": 0.04676406447474441, "retain_particle_states": True, "execution_mode": "local"}
    value.update(updates)
    return value


def _plan(root, request):
    return build_mot_2d_run_plan(request, repository_root=root, run_id="mot2d-run-1", git_revision="b" * 40, created_utc=NOW)


def test_plan_freezes_exact_source_sampling_and_final_science(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); source_id = _source(root)
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    plan = _plan(root, _request(source_id))
    after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert before == after
    resolved = plan.storage_records()["configuration"]["resolved"]
    assert resolved["input_source"]["pooled_particle_count"] == 140
    assert len(resolved["input_source"]["records"]) == 35
    assert [row["zeeman_seed"] for row in resolved["input_source"]["records"]] == list(range(3000, 3035))
    sampling = resolved["sampling"]
    observed_global = [record * 4 + row for record, row in sampling["selected_identities"]]
    # Golden vector is intentionally hard-coded rather than derived through
    # the implementation under test.
    assert observed_global == [4, 8, 17, 31, 33, 42, 44, 46, 61, 62, 74, 79, 81, 83, 84, 112, 115, 122, 137, 138]
    assert len(set(map(tuple, sampling["selected_identities"]))) == 20
    assert resolved["numerical_policy"]["solver"] == "RK4StHybridCustom"
    assert resolved["numerical_policy"]["dt_s"] == 0.625e-6
    assert resolved["mot_2d"]["capture_criterion_version"] == "mot_2d_extract_survivors_v1"
    assert plan.run["suitability"] == "individual_only"
    assert plan.review.source_qualification == "canonical_campaign_source"
    for kind, record in plan.storage_records().items():
        validate_record(kind, record)


def test_plan_is_deterministic_and_two_seed_roles_are_independent(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); source_id = _source(root)
    first = _plan(root, _request(source_id))
    assert _plan(root, _request(source_id)).plan_sha256 == first.plan_sha256
    mot_changed = _plan(root, _request(source_id, mot_seed=999))
    assert mot_changed.configuration["resolved"]["sampling"] == first.configuration["resolved"]["sampling"]
    selection_changed = _plan(root, _request(source_id, selection_seed=999))
    assert selection_changed.configuration["resolved"]["sampling"]["selected_identities"] != first.configuration["resolved"]["sampling"]["selected_identities"]
    assert selection_changed.run["seed"] == first.run["seed"] == 456


def test_stable_sampler_has_golden_vector_and_maps_imbalanced_pool_globally():
    source = ResolvedMot2DSource(
        "mot2d-source-" + "a" * 32,
        "canonical_folder",
        "canonical_campaign_source",
        10,
        "f" * 64,
        ({"survivor_count": 1}, {"survivor_count": 9}),
    )
    golden = _sample(source, 5, 7)
    assert golden["selected_identities"] == [[1, 2], [1, 3], [1, 4], [1, 5], [1, 8]]
    assert golden["algorithm"] == "pcg64-raw-partial-fisher-yates-unbiased"
    imbalanced = _sample(source, 5, 0)
    assert imbalanced["selected_identities"] == [[0, 0], [1, 0], [1, 1], [1, 6], [1, 7]]


@pytest.mark.parametrize("field,value", [
    ("particle_count", 0), ("particle_count", 1001), ("selection_seed", -1),
    ("mot_seed", 2**32), ("s0", 3.01), ("detuning_gamma", -1.56),
    ("magnet_radius_m", 0.052), ("execution_mode", "shell"),
    ("retain_particle_states", 1),
])
def test_request_rejects_out_of_policy_values(field, value):
    with pytest.raises(ValueError):
        validate_mot_2d_run_request(_request("mot2d-source-" + "a" * 32, **{field: value}))


def test_local_and_zeus_operational_caps_are_distinct():
    source = "mot2d-source-" + "a" * 32
    validate_mot_2d_run_request(_request(source, particle_count=1000))
    validate_mot_2d_run_request(_request(source, execution_mode="zeus", particle_count=50000))
    with pytest.raises(ValueError):
        validate_mot_2d_run_request(_request(source, particle_count=1001))
    with pytest.raises(ValueError):
        validate_mot_2d_run_request(_request(source, execution_mode="zeus", particle_count=50001))


def test_unknown_extra_missing_bool_nan_and_infinite_are_rejected():
    source = "mot2d-source-" + "a" * 32
    for mutation in (
        lambda row: row.update(secret="x"),
        lambda row: row.pop("mot_seed"),
        lambda row: row.update(particle_count=True),
        lambda row: row.update(s0=float("nan")),
        lambda row: row.update(detuning_gamma=float("inf")),
    ):
        row = _request(source); mutation(row)
        with pytest.raises(ValueError):
            validate_mot_2d_run_request(row)


def test_count_cannot_exceed_freshly_resolved_pool(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); source_id = _source(root, rows=1)
    with pytest.raises(ValueError, match="exceeds"):
        _plan(root, _request(source_id, particle_count=36))


def test_content_drift_invalidates_old_opaque_source_id(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); source_id = _source(root)
    state = root / "data/particle_states/after_zeeman/source/production_zeeman_n50000_dt40us_seed3000.npy"
    np.save(state, np.ones((4, 6), dtype=np.float64))
    metadata = json.loads(state.with_suffix(".json").read_text())
    metadata["output_sha256"] = hashlib.sha256(state.read_bytes()).hexdigest()
    state.with_suffix(".json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="unavailable or changed"):
        _plan(root, _request(source_id))


def test_storage_records_are_detached_and_plan_is_immutable(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root, _request(_source(root)))
    records = plan.storage_records(); records["run"]["seed"] = 1
    assert plan.run["seed"] == 456
    with pytest.raises(TypeError):
        plan.configuration["resolved"]["simulation"]["mot_seed"] = 1
