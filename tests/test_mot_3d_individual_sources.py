import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
)
import workflow_api.mot_3d_individual_sources as catalog
from workflow_api.run_discovery import DiscoverySnapshot, DiscoveredRun


def _canonical_source(root: Path, *, name: str = "finished", rows: int = 3):
    survivor = root / "data/particle_states/after_2d_mot" / f"{name}-states"
    survivor.mkdir(parents=True)
    parameters = {"s0": 1.3, "detuning_gamma": -0.92, "magnet_radius": 0.0467}
    design = {
        "git_commit": "a" * 40,
        "dt_s": 0.625e-6,
        "stochastic_solver": "RK4StHybridCustom",
        "ensemble_dir": "zeeman-source",
        "zeeman_profile": CANONICAL_ZEEMAN_PROFILE_NAME,
        "laboratory_spec_version": LABORATORY_SPEC_VERSION,
        "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
        "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
    }
    seeds = list(range(3015, 3035))
    mot_seeds = [43000 + seed for seed in seeds]
    for seed, mot_seed in zip(seeds, mot_seeds):
        state = survivor / f"mot_2d_survivors_zeeman_seed{seed}_mot_seed{mot_seed}.npy"
        np.save(state, np.full((rows, 6), seed, dtype=np.float64))
        state.with_suffix(".json").write_text(json.dumps({
            "kind": "mot_2d_final_survivor_ensemble",
            "zeeman_seed": seed,
            "mot_seed": mot_seed,
            "n_survivors": rows,
            "shape": [rows, 6],
            "dtype": "float64",
            "output_sha256": hashlib.sha256(state.read_bytes()).hexdigest(),
            "parameters": parameters,
            "design": design,
        }))
    campaign = root / "data/optimization/mot_2d" / name
    campaign.mkdir(parents=True)
    report = campaign / "final_report.json"
    report.write_text(json.dumps({
        "kind": "mot_2d_s0_campaign_final_report",
        "results": [{
            "s0": 1.3,
            "survivor_states_directory": str(survivor.resolve()),
            "recommended_parameters": parameters,
        }],
    }))
    campaign_record = {
        "kind": "mot_2d_s0_campaign",
        "name": name,
        "stage": "complete",
        "seed_roles": {"sealed_validation": seeds},
        "mot_seeds": {"sealed_validation": mot_seeds},
        "provenance": {"git_commit": "a" * 40, "physical_model_sha256": "b" * 64},
        "stages": {"final_report": str(report.resolve())},
        "s0_values": [1.3],
        "fixed_design": {"final_dt_s": 0.625e-6, "solver": "RK4StHybridCustom"},
        "ensemble_source": {
            "directory": "zeeman-source",
            "zeeman_profile": CANONICAL_ZEEMAN_PROFILE_NAME,
            "laboratory_spec_version": LABORATORY_SPEC_VERSION,
            "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
            "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
        },
        "input_ensembles": {"sealed_validation": [
            {
                "zeeman_seed": seed,
                "laboratory_spec_version": LABORATORY_SPEC_VERSION,
                "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
                "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
            }
            for seed in seeds
        ]},
    }
    (campaign / "campaign.json").write_text(json.dumps(campaign_record))
    return campaign, survivor


def _retained_inspection(*, survivors=7, retained=True, suitability="individual_only"):
    state = SimpleNamespace(
        path="results/states.npy",
        sha256="d" * 64,
        size_bytes=1024,
        shape=(survivors, 6),
        dtype="float64",
        survivor_count=survivors,
    )
    return SimpleNamespace(
        family="mot_2d",
        run_id="private-2d-run",
        state="succeeded",
        integrity="complete_verified",
        run={
            "configuration_sha256": "b" * 64,
            "inputs_sha256": "c" * 64,
            "retention": {"particle_states": retained},
        },
        results={
            "states_retained": retained,
            "suitability": suitability,
            "completed_utc": "2026-10-12T10:00:00+00:00",
            "metrics": {"n_survivors": survivors},
        },
        publication=SimpleNamespace(results_sha256="e" * 64, state_array=state),
        configuration={"resolved": {"mot_2d": {
            "laser": {"s0": 1.3, "detuning_gamma": -0.92},
            "magnet_radius_m": 0.0467,
        }}},
    )


def test_catalog_lists_completed_campaign_without_exposing_paths(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _canonical_source(root)

    result = catalog.list_individual_mot_3d_sources(root)

    assert result["contract_version"] == catalog.CATALOG_VERSION
    assert result["total"] == 1
    assert result["invalid_count"] == 0
    assert result["truncated"] is False
    source = result["sources"][0]
    assert source["source_kind"] == "canonical_2d_campaign"
    assert source["source_qualification"] == "canonical_campaign_source"
    assert source["result_suitability"] == "individual_only"
    assert source["ensemble_count"] == 20
    assert source["available_particle_count"] == {
        "pooled": 60,
        "minimum_per_ensemble": 3,
        "maximum_per_ensemble": 3,
    }
    rendered = json.dumps(result)
    assert "data/particle_states" not in rendered
    assert "mot_2d_survivors" not in rendered

    resolved = catalog.resolve_individual_mot_3d_source(root, source["id"])
    assert resolved.pooled_particle_count == 60
    assert len(resolved.records) == 20
    assert [record["zeeman_seed"] for record in resolved.records] == list(
        range(3015, 3035)
    )


@pytest.mark.parametrize("attack", ["state_hash", "metadata_hash", "symlink"])
def test_campaign_source_drift_or_symlink_is_rejected(tmp_path, attack):
    root = tmp_path / "repo"
    root.mkdir()
    _campaign, survivor = _canonical_source(root)
    before = catalog.list_individual_mot_3d_sources(root)
    source_id = before["sources"][0]["id"]
    state = next(survivor.glob("*.npy"))
    if attack == "state_hash":
        state.write_bytes(state.read_bytes() + b"tamper")
    elif attack == "metadata_hash":
        metadata = state.with_suffix(".json")
        value = json.loads(metadata.read_text())
        value["n_survivors"] += 1
        metadata.write_text(json.dumps(value))
    else:
        backup = state.with_name("backup.npy")
        state.rename(backup)
        state.symlink_to(backup.name)
    assert catalog.list_individual_mot_3d_sources(root)["sources"] == []
    with pytest.raises(ValueError, match="unavailable or changed"):
        catalog.resolve_individual_mot_3d_source(root, source_id)


def test_catalog_admits_only_complete_retained_individual_2d_results(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    record = DiscoveredRun(
        "mot_2d", "private-2d-run", "data/runs/mot_2d/private-2d-run",
        "succeeded", "complete_verified", None,
    )
    monkeypatch.setattr(
        catalog,
        "discover_run_snapshot",
        lambda _root, *, maximum_runs: DiscoverySnapshot((record,), False),
    )
    monkeypatch.setattr(catalog, "inspect_run", lambda *_args: _retained_inspection())

    result = catalog.list_individual_mot_3d_sources(root)
    assert result["total"] == 1
    source = result["sources"][0]
    assert source["source_kind"] == "retained_individual_mot_2d"
    assert source["source_qualification"] == "verified_individual_result"
    assert source["provenance"]["scientific_summary"] == {
        "s0": 1.3,
        "detuning_gamma": -0.92,
        "magnet_radius_m": 0.0467,
    }
    assert "private-2d-run" not in json.dumps(result)
    resolved = catalog.resolve_individual_mot_3d_source(root, source["id"])
    assert resolved.pooled_particle_count == 7

    monkeypatch.setattr(
        catalog, "inspect_run", lambda *_args: _retained_inspection(retained=False)
    )
    assert catalog.list_individual_mot_3d_sources(root)["sources"] == []


def test_source_id_changes_with_attested_individual_result(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    record = DiscoveredRun(
        "mot_2d", "private-2d-run", "data/runs/mot_2d/private-2d-run",
        "succeeded", "complete_verified", None,
    )
    monkeypatch.setattr(
        catalog,
        "discover_run_snapshot",
        lambda _root, *, maximum_runs: DiscoverySnapshot((record,), False),
    )
    current = _retained_inspection()
    monkeypatch.setattr(catalog, "inspect_run", lambda *_args: current)
    first = catalog.list_individual_mot_3d_sources(root)["sources"][0]["id"]
    current.publication.state_array.sha256 = "f" * 64
    second = catalog.list_individual_mot_3d_sources(root)["sources"][0]["id"]
    assert first != second
    with pytest.raises(ValueError, match="unavailable or changed"):
        catalog.resolve_individual_mot_3d_source(root, first)


def test_discovery_is_bounded_and_malformed_ids_fail_closed(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    seen = {}

    def snapshot(_root, *, maximum_runs):
        seen["limit"] = maximum_runs
        return DiscoverySnapshot((), False)

    monkeypatch.setattr(catalog, "discover_run_snapshot", snapshot)
    assert catalog.list_individual_mot_3d_sources(root)["sources"] == []
    assert seen == {"limit": catalog.MAX_INDIVIDUAL_RUNS}
    for value in ("", "mot3d-source-short", "../mot3d-source-" + "a" * 32):
        with pytest.raises(ValueError, match="identifier"):
            catalog.resolve_individual_mot_3d_source(root, value)


def test_campaign_discovery_fails_closed_when_directory_budget_is_exceeded(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    campaign_root = root / "data/optimization/mot_2d"
    campaign_root.mkdir(parents=True)
    for index in range(catalog.MAX_CAMPAIGNS + 1):
        (campaign_root / f"campaign-{index:04d}").mkdir()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("overflow entries must not be parsed")

    monkeypatch.setattr(catalog, "_bounded_json", forbidden)
    first = catalog.list_individual_mot_3d_sources(root)
    second = catalog.list_individual_mot_3d_sources(root)

    assert first == second
    assert first["sources"] == []
    assert first["invalid_count"] == 0
    assert first["truncated"] is True
