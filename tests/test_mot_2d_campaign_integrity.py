import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
    LABORATORY_PHYSICAL_SPECIFICATION,
)

_PROFILE = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]
_FIELD_CONFIG = {key: list(_PROFILE[key]) for key in ("radii_m", "positions_m", "tilt_angles_deg")}


def _ensemble(directory, seed=3000, profile="corrected_projectant_19ring_20261005", nonfinite=False):
    path = directory / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
    states = np.zeros((4, 6))
    if nonfinite:
        states[0, 0] = np.nan
    np.save(path, states)
    path.with_suffix(".json").write_text(json.dumps({
        "laboratory_spec_version": LABORATORY_SPEC_VERSION,
        "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
        "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
        "shape": [4, 6], "dtype": "float64", "n_survivors": 4,
        "survival_fraction": 4/50000,
        "output_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "parameters": {"seed": seed, "n_initial_atoms": 50000, "dt_s": 4e-5,
                       "stochastic": True, "collimation_angle_deg": 1.5,
                       "resolved_zeeman_magnet_profile": profile,
                       "zeeman_field_config": _FIELD_CONFIG},
        "software": {"git_commit": "source"},
    }))
    return path


def test_corrected_source_rejects_profile_mismatch_and_nonfinite(tmp_path):
    from utils.mot_2d_study import load_production_ensembles
    _ensemble(tmp_path, profile="wrong")
    with pytest.raises(ValueError, match="profile mismatch"):
        load_production_ensembles(directory=tmp_path, zeeman_seeds=[3000],
                                  expected_profile="corrected_projectant_19ring_20261005")
    _ensemble(tmp_path, profile="corrected_projectant_19ring_20261005", nonfinite=True)
    with pytest.raises(ValueError, match="Non-finite"):
        load_production_ensembles(directory=tmp_path, zeeman_seeds=[3000],
                                  expected_profile="corrected_projectant_19ring_20261005")


def test_campaign_manifest_has_nonoverlapping_roles_and_pinned_jobs(tmp_path, monkeypatch):
    import studies.mot_2d_s0_campaign as campaign
    root = tmp_path / "data/optimization/mot_2d/campaign"
    monkeypatch.setattr(campaign, "REPOSITORY_ROOT", tmp_path)
    (tmp_path / "data/particle_states/after_zeeman/corrected_projectant_19ring_20261005").mkdir(parents=True)
    args = campaign.parse_args(["create", "--name", "corrected", "--s0", "1.3",
        "--ensemble-dir", "data/particle_states/after_zeeman/corrected_projectant_19ring_20261005",
        "--zeeman-profile", "corrected_projectant_19ring_20261005",
        "--output-dir", str(root)])
    monkeypatch.setattr(campaign, "assert_relevant_worktree_clean", lambda: None)
    # Preserve the role structure while avoiding a dependency on real production data.
    monkeypatch.setattr(
        campaign,
        "freeze_input_ensembles",
        lambda directory, profile, roles: {
            role: [{"zeeman_seed": seed} for seed in seeds]
            for role, seeds in roles.items()
        },
    )
    campaign.create(args)
    manifest = json.loads((root / "campaign.json").read_text())
    seeds = [s for role in manifest["seed_roles"].values() for s in role]
    assert len(seeds) == len(set(seeds)) == 35
    assert manifest["fixed_design"]["particle_counts"]["refine"] == 10000
    pbs = (root / "jobs/01_smoke.pbs").read_text()
    assert "git rev-parse HEAD" in pbs and "Commit mismatch" in pbs
    assert "#PBS -J" not in pbs
    assert "export PBS_ARRAY_INDEX=0" in pbs
    assert "--s0-index $PBS_ARRAY_INDEX" in pbs
    assert manifest["mot_seeds"]["sealed_validation"] == list(range(43015, 43035))


def test_campaign_worker_commands_use_domain_module_paths(tmp_path, monkeypatch):
    import studies.mot_2d_s0_campaign as campaign

    root = tmp_path / "campaign"
    manifest = {
        "name": "paths",
        "seed_roles": {"discovery": [3000], "sealed_validation": [3015]},
        "mot_seeds": {"discovery": [43000], "sealed_validation": [43015]},
        "ensemble_source": {"directory": "ensembles", "zeeman_profile": "corrected"},
        "provenance": {
            "physical_model_sha256": "design",
            "git_commit": "abc123",
        },
    }
    (root / "campaign.json").parent.mkdir(parents=True)
    (root / "campaign.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(campaign, "assert_design", lambda value: None)
    monkeypatch.setattr(campaign, "stage_ensembles", lambda *args, **kwargs: [])
    monkeypatch.setattr(campaign, "repository_path", lambda value: Path("/runtime/ensembles"))
    commands = []
    monkeypatch.setattr(
        campaign.subprocess,
        "run",
        lambda command, check: commands.append(command),
    )

    campaign.optuna_task(
        root,
        "screen",
        {"s0": 1.3, "worker": 0},
        trials=1,
        particles=2,
        sampler_seed=137,
    )
    assert "studies.mot_2d.optimization" in commands[0]
    assert "studies.optimize_2d_mot_joint" not in commands[0]

    tasks = root / "production"
    tasks.mkdir()
    (tasks / "tasks.json").write_text(
        json.dumps(
            [
                {
                    "s0": 1.3,
                    "zeeman_seed": 3015,
                    "mot_seed": 43015,
                    "parameters": {"detuning_gamma": -1.0, "magnet_radius": 0.046},
                }
            ]
        )
    )
    campaign.production_task(
        type("Args", (), {"campaign": str(root), "task_index": 0})()
    )
    assert "studies.mot_2d.production" in commands[1]
    assert "studies.run_2d_mot_final_production" not in commands[1]


def test_frozen_ensemble_replacement_is_rejected(tmp_path):
    import studies.mot_2d_s0_campaign as campaign

    monkeypatch = pytest.MonkeyPatch()
    repository = tmp_path / "repo"
    directory = repository / "data/particle_states/after_zeeman/source"
    directory.mkdir(parents=True)
    monkeypatch.setattr(campaign, "REPOSITORY_ROOT", repository)
    _ensemble(directory)
    roles = {"discovery": [3000]}
    frozen = campaign.freeze_input_ensembles(directory, campaign.DEFAULT_PROFILE, roles)
    manifest = {
        "seed_roles": roles,
        "input_ensembles": frozen,
        "ensemble_source": {"directory": "data/particle_states/after_zeeman/source",
                            "zeeman_profile": campaign.DEFAULT_PROFILE},
        "provenance": {"path_contract": "repository-relative-v1"},
    }
    path = next(directory.glob("*.npy"))
    states = np.load(path)
    states[0, 0] = 1.0
    np.save(path, states)
    metadata_path = path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text())
    metadata["output_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(RuntimeError, match="Frozen Zeeman input changed"):
        campaign.stage_ensembles(manifest, "screen", 2)
    monkeypatch.undo()


def test_missing_required_ensemble_hash_is_rejected(tmp_path, monkeypatch):
    import studies.mot_2d_s0_campaign as campaign

    repository = tmp_path / "repo"
    directory = repository / "data/particle_states/after_zeeman/source"
    directory.mkdir(parents=True)
    monkeypatch.setattr(campaign, "REPOSITORY_ROOT", repository)
    path = _ensemble(directory)
    metadata = json.loads(path.with_suffix(".json").read_text())
    metadata.pop("output_sha256")
    path.with_suffix(".json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Missing SHA-256 provenance"):
        campaign.freeze_input_ensembles(
            directory, campaign.DEFAULT_PROFILE, {"discovery": [3000]}
        )


def test_frozen_ensemble_metadata_replacement_is_rejected(tmp_path, monkeypatch):
    import studies.mot_2d_s0_campaign as campaign

    repository = tmp_path / "repo"
    directory = repository / "data/particle_states/after_zeeman/source"
    directory.mkdir(parents=True)
    monkeypatch.setattr(campaign, "REPOSITORY_ROOT", repository)
    path = _ensemble(directory)
    roles = {"discovery": [3000]}
    frozen = campaign.freeze_input_ensembles(directory, campaign.DEFAULT_PROFILE, roles)
    manifest = {
        "seed_roles": roles,
        "input_ensembles": frozen,
        "ensemble_source": {
            "directory": "data/particle_states/after_zeeman/source",
            "zeeman_profile": campaign.DEFAULT_PROFILE,
        },
        "provenance": {"path_contract": "repository-relative-v1"},
    }
    metadata_path = path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text())
    metadata["unused_note"] = "changed without changing parsed scientific fields"
    metadata_path.write_text(json.dumps(metadata))

    with pytest.raises(RuntimeError, match="Frozen Zeeman input changed"):
        campaign.stage_ensembles(manifest, "screen", 2)


def test_pre_c2_campaign_stage_resumes_without_rewriting_inputs(tmp_path, monkeypatch):
    import studies.mot_2d_s0_campaign as campaign

    repository = tmp_path / "repo"
    directory = repository / "data/particle_states/after_zeeman/source"
    directory.mkdir(parents=True)
    monkeypatch.setattr(campaign, "REPOSITORY_ROOT", repository)
    path = _ensemble(directory)
    roles = {"discovery": [3000]}
    frozen = campaign.freeze_input_ensembles(directory, campaign.DEFAULT_PROFILE, roles)
    metadata_path = path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text())
    laboratory_keys = (
        "laboratory_spec_version", "laboratory_spec_sha256", "zeeman_profile_sha256"
    )
    for key in laboratory_keys:
        metadata.pop(key)
        frozen["discovery"][0].pop(key)
    metadata_path.write_text(json.dumps(metadata))
    frozen["discovery"][0]["metadata_sha256"] = hashlib.sha256(
        metadata_path.read_bytes()
    ).hexdigest()
    manifest = {
        "seed_roles": roles, "input_ensembles": frozen,
        "ensemble_source": {
            "directory": "data/particle_states/after_zeeman/source",
            "zeeman_profile": campaign.DEFAULT_PROFILE,
        },
        "provenance": {"path_contract": "repository-relative-v1"},
    }
    before_manifest = json.dumps(manifest, sort_keys=True).encode()
    before_metadata = metadata_path.read_bytes()
    ensembles = campaign.stage_ensembles(manifest, "screen", 2)
    assert len(ensembles) == 1
    assert json.dumps(manifest, sort_keys=True).encode() == before_manifest
    assert metadata_path.read_bytes() == before_metadata


@pytest.mark.parametrize("failure", ["retired", "tampered"])
def test_pre_c2_campaign_stage_rejects_unattested_profile(tmp_path, monkeypatch, failure):
    import studies.mot_2d_s0_campaign as campaign

    repository = tmp_path / "repo"
    directory = repository / "data/particle_states/after_zeeman/source"
    directory.mkdir(parents=True)
    monkeypatch.setattr(campaign, "REPOSITORY_ROOT", repository)
    path = _ensemble(directory)
    metadata_path = path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text())
    for key in ("laboratory_spec_version", "laboratory_spec_sha256", "zeeman_profile_sha256"):
        metadata.pop(key)
    if failure == "retired":
        metadata["parameters"]["resolved_zeeman_magnet_profile"] = "active"
    else:
        metadata["parameters"]["zeeman_field_config"]["radii_m"][0] += 1e-6
    metadata_path.write_text(json.dumps(metadata))
    manifest = {
        "seed_roles": {"discovery": [3000]},
        "input_ensembles": {"discovery": []},
        "ensemble_source": {
            "directory": "data/particle_states/after_zeeman/source",
            "zeeman_profile": campaign.DEFAULT_PROFILE,
        },
        "provenance": {"path_contract": "repository-relative-v1"},
    }
    with pytest.raises(ValueError):
        campaign.stage_ensembles(manifest, "screen", 2)


def test_dirty_relevant_code_is_rejected(monkeypatch):
    import studies.mot_2d_s0_campaign as campaign

    monkeypatch.setattr(
        campaign.subprocess,
        "check_output",
        lambda *args, **kwargs: " M config.py\n",
    )
    with pytest.raises(RuntimeError, match="dirty"):
        campaign.assert_relevant_worktree_clean()


def test_final_prediction_legacy_import_is_exact_shared_derivation():
    from studies.mot_2d.production import final_prediction as legacy_prediction
    from workflow_api.mot_2d_prediction import final_prediction as shared_prediction

    replicates = [
        {"n_input": 10_000 + index, "captured": 200 + index}
        for index in range(5)
    ]
    assert legacy_prediction is shared_prediction
    assert legacy_prediction(replicates) == shared_prediction(replicates)


def test_force_override_is_not_supported():
    import studies.mot_2d_s0_campaign as campaign

    with pytest.raises(SystemExit):
        campaign.parse_args(["status", "--campaign", "x", "--force"])


def test_production_records_exact_manifest_seed_pair(tmp_path, monkeypatch):
    import studies.mot_2d.production as production

    output = tmp_path / "output"
    states = tmp_path / "states"
    args = SimpleNamespace(
        s0=1.3, detuning_gamma=-1.1, magnet_radius_mm=49.0,
        zeeman_seeds=[3015], mot_seeds=[43015], ensemble_dir=tmp_path,
        expected_zeeman_profile="profile", expected_git_commit="commit",
        npools=1, save_survivor_states=True, output_dir=output,
        states_dir=states,
    )
    monkeypatch.setattr(production.subprocess, "check_output", lambda *a, **k: "commit\n")
    monkeypatch.setattr(
        production,
        "load_production_ensembles",
        lambda **kwargs: [{"zeeman_seed": 3015}],
    )
    monkeypatch.setattr(
        production,
        "evaluate_configuration",
        lambda **kwargs: {
            "replicates": [{"zeeman_seed": 3015, "mot_seed": kwargs["mot_seeds"][0],
                            "ensemble_file": "source.npy", "n_input": 10,
                            "captured": 2, "conditional_efficiency": 0.2}],
            "survivor_state_ensembles": [np.zeros((2, 6))],
        },
    )
    production.run_seeds(args)
    replicate = json.loads((output / "replicates" / "zeeman_seed3015.json").read_text())
    metadata = json.loads(next(states.glob("*.json")).read_text())
    assert replicate["replicate"]["mot_seed"] == 43015
    assert metadata["zeeman_seed"] == 3015
    assert metadata["mot_seed"] == 43015


def test_status_uses_manifest_sealed_seed_count(tmp_path, capsys):
    import studies.mot_2d_s0_campaign as campaign

    root = tmp_path / "campaign"
    (root / "production" / campaign.key(1.3) / "replicates").mkdir(parents=True)
    (root / "campaign.json").write_text(json.dumps({
        "kind": "mot_2d_s0_campaign", "name": "test", "stage": "production", "s0_values": [1.3],
        "seed_roles": {"sealed_validation": [91, 92, 93]},
    }))
    campaign.status(SimpleNamespace(campaign=str(root)))
    assert "0/3 production ensembles" in capsys.readouterr().out


def test_final_summary_rejects_wrong_manifest_mot_seed(tmp_path):
    from studies.mot_2d.production import summarize

    directory = tmp_path / "replicates"
    directory.mkdir()
    payload = {
        "parameters": {"s0": 1.3},
        "design": {"dt_s": 6.25e-7},
        "replicate": {
            "zeeman_seed": 3015, "mot_seed": 18015, "n_input": 100,
            "captured": 2, "conditional_efficiency": 0.02,
            "estimated_total_efficiency": 0.01,
        },
    }
    (directory / "zeeman_seed3015.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="seed-pair mismatch"):
        summarize(
            tmp_path,
            expected_seeds=[3015],
            expected_seed_pairs={3015: 43015},
        )


def test_final_summary_uses_frozen_reporting_population_and_precision_target(tmp_path):
    from studies.mot_2d.production import summarize

    replicates = tmp_path / "replicates"
    replicates.mkdir()
    for seed, captured in ((3015, 2), (3016, 3)):
        payload = {
            "parameters": {"s0": 1.3},
            "design": {"dt_s": 6.25e-7},
            "replicate": {
                "zeeman_seed": seed,
                "mot_seed": 40000 + seed,
                "n_input": 100,
                "captured": captured,
                "conditional_efficiency": captured / 100,
                "estimated_total_efficiency": captured / 200,
            },
        }
        (replicates / f"zeeman_seed{seed}.json").write_text(json.dumps(payload))

    canonical_default = summarize(tmp_path)
    canonical_explicit = summarize(
        tmp_path,
        reporting_survivors=10_000_000,
        target_half_width_fraction=0.0005,
    )
    assert canonical_explicit == canonical_default

    frozen = summarize(
        tmp_path,
        reporting_survivors=1_000_000,
        target_half_width_fraction=0.25,
    )
    assert frozen["prediction_for_10m_zeeman_survivors"][
        "reporting_zeeman_survivors"
    ] == 1_000_000
    assert frozen["target_95_half_width_fraction"] == 0.25
    assert frozen["target_95_half_width_percentage_points"] == 25.0
    assert frozen["stopping_rule_passes"] is True


def test_campaign_finish_forwards_frozen_prediction_settings(tmp_path, monkeypatch):
    import studies.mot_2d_s0_campaign as campaign

    root = tmp_path / "campaign"
    root.mkdir()
    parameters = {
        "s0": 1.3,
        "detuning_gamma": -0.9,
        "magnet_radius": 0.046,
    }
    sensitivity = {
        "s0_1p300000": {
            "production_selection": {"parameters": parameters},
            "robustness_status": "not_established_pending_adaptive_challenger_validation",
            "near_optimality_status": "not_established_pending_domain_challenger_elimination",
        }
    }
    (root / "sensitivity_summary.json").write_text(json.dumps(sensitivity))
    manifest = {
        "stage": "production",
        "s0_values": [1.3],
        "seed_roles": {"sealed_validation": [3015]},
        "mot_seeds": {"sealed_validation": [43015]},
        "fixed_design": {
            "reporting_zeeman_survivors": 1_000_000,
            "target_95_half_width_fraction": 0.25,
        },
        "ensemble_source": {"directory": "source", "zeeman_profile": "profile"},
        "provenance": {"git_commit": "abc"},
        "stages": {},
    }
    observed = {}

    def fake_render_finalization(frozen, *_args):
        observed["reporting_survivors"] = frozen["fixed_design"][
            "reporting_zeeman_survivors"
        ]
        observed["target_half_width_fraction"] = frozen["fixed_design"][
            "target_95_half_width_fraction"
        ]
        return {"final_report.json": b"{}", "campaign.json": b"{}"}, []

    monkeypatch.setattr(campaign, "assert_design", lambda _manifest: None)
    monkeypatch.setattr(
        "workflow_api.mot_2d_plan.render_finalization", fake_render_finalization
    )
    campaign.finish(root, manifest)
    assert observed["reporting_survivors"] == 1_000_000
    assert observed["target_half_width_fraction"] == 0.25


def _write_portable_sealed_campaign(repository_root):
    from studies.mot_2d.production import final_prediction
    from utils.mot_2d_study import summarize_replicates
    from workflow_api.mot_2d_validation import CANONICAL_ROLE_SEEDS

    campaign_root = repository_root / "data/optimization/mot_2d/fixed_s0"
    source_root = repository_root / "data/particle_states/after_zeeman/source"
    states_root = repository_root / "data/particle_states/after_2d_mot/fixed_s0/s0_1p300000"
    source_root.mkdir(parents=True)
    states_root.mkdir(parents=True)
    (campaign_root / "production/s0_1p300000").mkdir(parents=True)

    seeds = CANONICAL_ROLE_SEEDS["sealed_validation"]
    mot_seeds = list(range(43015, 43035))
    parameters = {"s0": 1.3, "detuning_gamma": -0.9, "magnet_radius": 0.046}
    design = {
        "dt_s": 0.625e-6,
        "stochastic_solver": "RK4StHybridCustom",
        "uses_all_available_particles": True,
        "npools": 150,
        "ensemble_dir": "data/particle_states/after_zeeman/source",
        "zeeman_profile": "profile",
        "laboratory_spec_version": "test-v2",
        "laboratory_spec_sha256": "a" * 64,
        "zeeman_profile_sha256": "b" * 64,
        "git_commit": "abc",
    }
    tasks, replicates, frozen = [], [], []
    for seed, mot_seed in zip(seeds, mot_seeds):
        source = source_root / f"zeeman_seed{seed}.npy"
        np.save(source, np.zeros((2, 6)))
        source_metadata = source.with_suffix(".json")
        source_metadata.write_text(json.dumps({"seed": seed}))
        source_identity = source.relative_to(repository_root).as_posix()
        frozen.append({
            "zeeman_seed": seed, "path": source_identity,
            "metadata_path": source_metadata.relative_to(repository_root).as_posix(),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "metadata_sha256": hashlib.sha256(
                source_metadata.read_bytes()
            ).hexdigest(),
            "survivor_count": 2,
            "generation": {"n_initial_atoms": 4},
        })
        tasks.append({"s0": 1.3, "zeeman_seed": seed, "mot_seed": mot_seed,
                      "parameters": parameters})
        replicate = {
            "ensemble_file": source.name,
            "zeeman_seed": seed, "mot_seed": mot_seed,
            "n_available": 2, "selection_method": "all_particles",
            "subset_seed": 100000 + seed,
            "n_input": 2, "captured": 1,
            "conditional_efficiency": 0.5,
            "estimated_total_efficiency": 0.25,
            "batch_elapsed_seconds": 1.0,
        }
        replicates.append(replicate)
        replicate_path = (
            campaign_root / "production/s0_1p300000/replicates"
            / f"zeeman_seed{seed}.json"
        )
        replicate_path.parent.mkdir(parents=True, exist_ok=True)
        replicate_path.write_text(json.dumps({
            "kind": "mot_2d_final_production_replicate",
            "parameters": parameters,
            "design": design,
            "replicate": replicate,
        }))
        state = states_root / f"mot_2d_survivors_zeeman_seed{seed}_mot_seed{mot_seed}.npy"
        np.save(state, np.zeros((1, 6)))
        state.with_suffix(".json").write_text(json.dumps({
            "kind": "mot_2d_final_survivor_ensemble",
            "zeeman_seed": seed, "mot_seed": mot_seed,
            "n_input": 2, "n_survivors": 1,
            "shape": [1, 6], "dtype": "float64",
            "output_sha256": hashlib.sha256(state.read_bytes()).hexdigest(),
            "parameters": parameters, "design": design,
            "source_zeeman_ensemble": source_identity,
        }))

    prediction = final_prediction(replicates)
    stopping_rule_passes = prediction["predicted_95_half_width_fraction"] <= 0.0005
    sensitivity = {
        "reference": parameters,
        "points": [],
        "production_selection": {"parameters": parameters},
        "robustness_status": "not_established_pending_adaptive_challenger_validation",
        "near_optimality_status": "not_established_pending_domain_challenger_elimination",
    }
    (campaign_root / "sensitivity_summary.json").write_text(json.dumps({
        "s0_1p300000": sensitivity,
    }))
    (campaign_root / "production/tasks.json").write_text(json.dumps(tasks))
    (campaign_root / "production/s0_1p300000/summary.json").write_text(json.dumps({
        "kind": "mot_2d_final_production_summary",
        "zeeman_seeds": seeds, "design": design, "parameters": parameters,
        "replicates": replicates,
        "replicate_statistics": summarize_replicates(replicates),
        "target_95_half_width_fraction": 0.0005,
        "target_95_half_width_percentage_points": 0.05,
        "stopping_rule_passes": stopping_rule_passes,
        "prediction_for_10m_zeeman_survivors": prediction,
    }))
    (campaign_root / "final_report.json").write_text(json.dumps({
        "kind": "mot_2d_s0_campaign_final_report",
        "always_returns_best_tested_result": True,
        "results": [{
            "s0": 1.3,
            "recommended_parameters": parameters,
            "prediction": prediction,
            "sensitivity": sensitivity,
            "target_uncertainty_passes": stopping_rule_passes,
            "warnings": (
                ([] if stopping_rule_passes else [
                    "target_95_prediction_half_width_not_met"
                ])
                + [
                    "robust_operating_region_not_established",
                    "epsilon_near_optimality_not_established",
                ]
            ),
            "survivor_states_directory": states_root.relative_to(repository_root).as_posix(),
        }],
    }))
    manifest = {
        "stage": "complete", "s0_values": [1.3],
        "seed_roles": {"sealed_validation": seeds},
        "mot_seeds": {"sealed_validation": mot_seeds},
        "input_ensembles": {"sealed_validation": frozen},
        "fixed_design": {
            "final_dt_s": 0.625e-6,
            "target_95_half_width_fraction": 0.0005,
            "reporting_zeeman_survivors": 10_000_000,
            "detuning_bounds_gamma": [-1.55, -0.85],
            "magnet_radius_bounds_m": [0.045, 0.051],
            "detuning_resolution_gamma": 0.01,
            "magnet_radius_resolution_m": 1e-5,
        },
        "ensemble_source": {
            "directory": "data/particle_states/after_zeeman/source",
            "zeeman_profile": "profile",
            "laboratory_spec_version": "test-v2",
            "laboratory_spec_sha256": "a" * 64,
            "zeeman_profile_sha256": "b" * 64,
        },
        "provenance": {"git_commit": "abc"},
        "stages": {"final_report": "data/optimization/mot_2d/fixed_s0/final_report.json"},
    }
    return campaign_root, manifest


def _patch_portable_production_transition(monkeypatch):
    import workflow_api.mot_2d_validation as validation

    def validated_transition(root, _manifest):
        return (
            json.loads((root / "sensitivity_summary.json").read_text()),
            json.loads((root / "production/tasks.json").read_text()),
        )

    monkeypatch.setattr(
        validation, "validated_production_transition", validated_transition
    )


def test_sealed_final_validation_survives_repository_relocation(tmp_path, monkeypatch):
    from workflow_api.models import StageProgress
    from workflow_api.mot_2d_validation import sealed_final_is_valid

    _patch_portable_production_transition(monkeypatch)
    outcomes = []
    for directory in ("checkout_a", "a-different-checkout-root"):
        repository_root = tmp_path / directory
        campaign_root, manifest = _write_portable_sealed_campaign(repository_root)
        outcomes.append(sealed_final_is_valid(
            campaign_root,
            manifest,
            (
                StageProgress("sensitivity", 17, 17, "complete"),
                StageProgress("production", 20, 20, "complete"),
            ),
            repository_root,
        ))
    assert outcomes == [True, True]


def test_finalization_is_derived_from_raw_sealed_evidence(tmp_path, monkeypatch):
    from workflow_api.mot_2d_plan import render_finalization
    from workflow_api.mot_2d_prediction import final_prediction
    from utils.mot_2d_study import summarize_replicates

    _patch_portable_production_transition(monkeypatch)
    repository_root = tmp_path / "checkout"
    root, manifest = _write_portable_sealed_campaign(repository_root)
    old_states = (
        repository_root
        / "data/particle_states/after_2d_mot/fixed_s0/s0_1p300000"
    )
    states = (
        repository_root
        / "data/particle_states/after_2d_mot/final_ensemble_s0_1.3"
    )
    states.parent.mkdir(parents=True, exist_ok=True)
    old_states.rename(states)
    manifest["stage"] = "production"
    manifest["stages"] = {"production": {"tasks": 20}}
    (root / "final_report.json").unlink()
    (root / "production/s0_1p300000/summary.json").unlink()

    files, public = render_finalization(manifest, root, repository_root)

    assert set(files) == {
        "production/s0_1p300000/summary.json",
        "final_report.json",
        "campaign.json",
    }
    summary = json.loads(files["production/s0_1p300000/summary.json"])
    report = json.loads(files["final_report.json"])
    assert summary["replicate_statistics"] == summarize_replicates(
        summary["replicates"]
    )
    assert summary["prediction_for_10m_zeeman_survivors"] == final_prediction(
        summary["replicates"]
    )
    assert report["results"][0]["prediction"] == (
        summary["prediction_for_10m_zeeman_survivors"]
    )
    assert report["results"][0]["warnings"][-2:] == [
        "robust_operating_region_not_established",
        "epsilon_near_optimality_not_established",
    ]
    assert public[0]["n_ensembles"] == 20
    assert public[0]["total_input"] == 40
    assert public[0]["total_survivors"] == 20
    assert public[0]["output_suitability"] == "eligible_as_3d_campaign_input"


def test_finalization_rejects_tampered_survivor_state(tmp_path, monkeypatch):
    from workflow_api.mot_2d_plan import render_finalization

    _patch_portable_production_transition(monkeypatch)
    repository_root = tmp_path / "checkout"
    root, manifest = _write_portable_sealed_campaign(repository_root)
    old_states = (
        repository_root
        / "data/particle_states/after_2d_mot/fixed_s0/s0_1p300000"
    )
    states = (
        repository_root
        / "data/particle_states/after_2d_mot/final_ensemble_s0_1.3"
    )
    states.parent.mkdir(parents=True, exist_ok=True)
    old_states.rename(states)
    manifest["stage"] = "production"
    target = states / "mot_2d_survivors_zeeman_seed3015_mot_seed43015.npy"
    target.write_bytes(target.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="digest mismatch"):
        render_finalization(manifest, root, repository_root)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reporting_zeeman_survivors", 1_000_000),
        ("target_95_half_width_fraction", 0.25),
    ],
)
def test_sealed_final_rejects_prediction_settings_not_matching_frozen_manifest(
    tmp_path, monkeypatch, field, value
):
    from workflow_api.models import StageProgress
    from workflow_api.mot_2d_validation import sealed_final_is_valid

    _patch_portable_production_transition(monkeypatch)
    repository_root = tmp_path / "checkout"
    root, manifest = _write_portable_sealed_campaign(repository_root)
    manifest["fixed_design"][field] = value
    assert not sealed_final_is_valid(
        root,
        manifest,
        (
            StageProgress("sensitivity", 17, 17, "complete"),
            StageProgress("production", 20, 20, "complete"),
        ),
        repository_root,
    )


def test_later_stage_pbs_is_byte_identical_across_repository_roots(tmp_path, monkeypatch):
    import studies.mot_2d_s0_campaign as campaign

    artifacts = []
    for directory in ("checkout_a", "a-different-checkout-root"):
        repository_root = tmp_path / directory
        root = repository_root / "data/optimization/mot_2d/fixed_s0"
        (root / "jobs").mkdir(parents=True)
        monkeypatch.setattr(campaign, "REPOSITORY_ROOT", repository_root)
        manifest = {
            "name": "fixed_s0", "s0_values": [1.3], "stages": {},
            "provenance": {"git_commit": "abc"},
        }
        campaign.prepare(
            root,
            manifest,
            "sensitivity",
            [{"s0": 1.3, "point_index": 0}],
            "05",
            200,
            "10:00:00",
        )
        artifacts.append({
            "pbs": (root / "jobs/05_sensitivity.pbs").read_bytes(),
            "tasks": (root / "sensitivity/tasks.json").read_bytes(),
            "manifest": (root / "campaign.json").read_bytes(),
        })

    assert artifacts[0] == artifacts[1]
    pbs = artifacts[0]["pbs"].decode()
    assert str(tmp_path) not in pbs
    assert "--campaign data/optimization/mot_2d/fixed_s0" in pbs
    saved = json.loads(artifacts[0]["manifest"])
    assert saved["stages"]["sensitivity"]["job_file"] == (
        "data/optimization/mot_2d/fixed_s0/jobs/05_sensitivity.pbs"
    )


def test_refinement_chain_is_byte_identical_across_repository_roots(tmp_path, monkeypatch):
    import studies.mot_2d_s0_campaign as campaign

    rows = [
        {"s0": 1.3, "detuning_gamma": -1.2 + index * 0.011,
         "magnet_radius": 0.048 + index * 0.000011,
         "mean_conditional_efficiency": 0.03 - index * 1e-5,
         "source": f"trial_{index}.json"}
        for index in range(3 * campaign.SCREEN_TRIALS)
    ]
    monkeypatch.setattr(campaign, "validate_screen_outputs", lambda *args: rows)
    artifacts = []
    for directory in ("checkout_a", "a-different-checkout-root"):
        repository_root = tmp_path / directory
        root = repository_root / "data/optimization/mot_2d/fixed_s0"
        (root / "jobs").mkdir(parents=True)
        monkeypatch.setattr(campaign, "REPOSITORY_ROOT", repository_root)
        manifest = {
            "kind": "mot_2d_s0_campaign", "stage": "screen",
            "name": "fixed_s0", "s0_values": [1.3], "stages": {},
            "fixed_design": {"detuning_bounds_gamma": [-2.0, -0.5],
                             "magnet_radius_bounds_m": [0.045, 0.052]},
            "provenance": {"git_commit": "abc"},
        }
        campaign.prepare_refine(root, manifest)
        artifacts.append({
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()
        })

    assert artifacts[0] == artifacts[1]
    for payload in artifacts[0].values():
        assert str(tmp_path).encode() not in payload

    root = tmp_path / "checkout_a/data/optimization/mot_2d/fixed_s0"
    saved = json.loads((root / "campaign.json").read_text())
    assert saved["stages"]["refine"]["cumulative_trial_targets"] == [3, 6, 9, 10]
    repository_root = tmp_path / "checkout_a"
    jobs = [repository_root / path for path in saved["stages"]["refine"]["round_job_files"]]
    assert len(jobs) == 4
    for target, job in zip((3, 6, 9, 10), jobs):
        text = job.read_text()
        assert f"--target-trials {target}" in text
        assert "#PBS -l walltime=20:00:00" in text
        assert "--task-index $PBS_ARRAY_INDEX" in text
    submitter = (repository_root / saved["stages"]["refine"]["submit_chain"]).read_text()
    assert submitter.count('depend=afterok:"${previous}"') == 3
    assert "afterokarray" not in submitter
    assert "--campaign data/optimization/mot_2d/fixed_s0" in jobs[0].read_text()


def test_write_pbs_uses_array_only_for_multiple_tasks(tmp_path):
    import studies.mot_2d_s0_campaign as campaign

    scalar = tmp_path / "scalar.pbs"
    campaign.write_pbs(
        scalar,
        "scalar",
        "4-4",
        1,
        "00:05:00",
        "python worker.py --task-index ${PBS_ARRAY_INDEX:-0}",
        revision="abc",
    )
    scalar_text = scalar.read_text()
    assert "#PBS -J" not in scalar_text
    assert "export PBS_ARRAY_INDEX=4" in scalar_text
    assert "--task-index ${PBS_ARRAY_INDEX:-0}" in scalar_text

    array = tmp_path / "array.pbs"
    campaign.write_pbs(
        array,
        "array",
        "0-2",
        200,
        "01:00:00",
        "python worker.py --task-index $PBS_ARRAY_INDEX",
        revision="abc",
    )
    array_text = array.read_text()
    assert "#PBS -J 0-2%3" in array_text
    assert "--task-index $PBS_ARRAY_INDEX" in array_text


def test_refinement_task_keeps_same_study_and_exact_total_target(tmp_path, monkeypatch):
    import studies.mot_2d_s0_campaign as campaign

    root = tmp_path / "campaign"
    (root / "refine").mkdir(parents=True)
    (root / "refine" / "tasks.json").write_text(json.dumps([{
        "s0": 1.3, "worker": 2,
        "bounds": {"detuning": [-1.3, -1.1], "radius": [0.048, 0.049]},
    }]))
    calls = []
    monkeypatch.setattr(
        campaign,
        "optuna_task",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    for target in campaign.REFINEMENT_CUMULATIVE_TARGETS:
        campaign.refine_task(SimpleNamespace(
            campaign=str(root), task_index=0, target_trials=target
        ))
    assert [call[0][3] for call in calls] == [3, 6, 9, 10]
    assert all(call[0][1] == "refine" for call in calls)
    assert all(call[0][2]["worker"] == 2 for call in calls)


def test_confirmation_refuses_incomplete_refinement(tmp_path, monkeypatch):
    import studies.mot_2d_s0_campaign as campaign
    import workflow_api.mot_2d_screen as validation

    monkeypatch.setattr(
        validation,
        "validate_refine_outputs",
        lambda *args: (_ for _ in ()).throw(validation.ScreenValidationError("Refinement incomplete")),
    )
    with pytest.raises(validation.ScreenValidationError, match="Refinement incomplete"):
        campaign.prepare_confirmation(
            tmp_path, {"s0_values": [1.3]}
        )


def test_boundary_sensitivity_points_are_deduplicated(tmp_path, monkeypatch):
    import studies.mot_2d_s0_campaign as campaign
    root = tmp_path / "campaign"
    folder = root / "confirmation" / campaign.key(1.3)
    folder.mkdir(parents=True)
    for index in range(campaign.CONFIRMATION_CANDIDATES):
        efficiency = .02 + index/10000
        payload = {"s0": 1.3, "candidate_index": index,
          "parameters": {"s0": 1.3, "detuning_gamma": -1.55,
                         "magnet_radius": .045},
          "evaluation": {"replicates": [{"zeeman_seed": 3010+i,
            "mot_seed": 43010+i, "n_input": 10000, "subset_seed": i,
            "conditional_efficiency": efficiency} for i in range(5)],
            "statistics": {"mean_conditional_efficiency": efficiency,
                           "conditional_95_ci": [efficiency-.001, efficiency+.001]}}}
        (folder/f"point_{index:02d}.json").write_text(json.dumps(payload))
    captured = {}
    monkeypatch.setattr(campaign, "prepare", lambda *a: captured.update(specs=a[3]))
    monkeypatch.setattr(
        campaign,
        "validated_evaluation_outputs",
        lambda *args: [json.loads(path.read_text()) for path in sorted(folder.glob("point_*.json"))],
    )
    campaign.prepare_sensitivity(root, {
        "s0_values": [1.3],
        "fixed_design": {
            "detuning_bounds_gamma": [-1.55, -0.85],
            "magnet_radius_bounds_m": [0.045, 0.051],
            "control_resolution": {
                "detuning_gamma": 0.01, "magnet_radius_m": 1e-5,
            },
            "stress_test_offsets": {
                "detuning_gamma": 0.02, "magnet_radius_m": 0.0001,
            },
        },
    })
    identities = [(x["parameters"]["detuning_gamma"], x["parameters"]["magnet_radius"])
                  for x in captured["specs"]]
    assert len(identities) == len(set(identities))


def test_paired_comparison_rejects_unequal_or_misaligned_replicates():
    import studies.mot_2d_s0_campaign as campaign

    def record(seeds):
        return {"evaluation": {"replicates": [
            {"zeeman_seed": seed, "mot_seed": 43000 + seed,
             "n_input": 10000, "subset_seed": 100000 + seed,
             "conditional_efficiency": 0.02}
            for seed in seeds
        ]}}

    with pytest.raises(ValueError, match="not paired"):
        campaign.paired(record([3010, 3011]), record([3010]))
    with pytest.raises(ValueError, match="not paired"):
        campaign.paired(record([3010, 3011]), record([3011, 3010]))


def _write_strict_evaluation_campaign(tmp_path):
    from utils.mot_2d_study import summarize_replicates

    root = tmp_path / "campaign"
    folder = root / "confirmation" / "s0_1p300000"
    folder.mkdir(parents=True)
    parameters = {"s0": 1.3, "detuning_gamma": -0.9, "magnet_radius": 0.046}
    tasks = [
        {"s0": 1.3, "candidate_index": index, "parameters": parameters}
        for index in range(5)
    ]
    (root / "confirmation" / "tasks.json").write_text(json.dumps(tasks))
    replicates = []
    frozen = []
    for offset, seed in enumerate(range(3010, 3015)):
        frozen.append({
            "zeeman_seed": seed,
            "path": f"data/particle_states/after_zeeman/source/seed{seed}.npy",
            "survivor_count": 20000,
            "generation": {"n_initial_atoms": 50000},
        })
        replicates.append({
            "ensemble_file": f"seed{seed}.npy", "zeeman_seed": seed,
            "mot_seed": 43010 + offset, "n_available": 20000,
            "selection_method": "deterministic_random_without_replacement",
            "subset_seed": 100000 + seed, "n_input": 10000,
            "captured": 100, "conditional_efficiency": 0.01,
            "estimated_total_efficiency": 0.004,
            "batch_elapsed_seconds": 1.0,
        })
    manifest = {
        "s0_values": [1.3],
        "stages": {"confirmation": {"tasks": 5}},
        "seed_roles": {"held_out_confirmation": list(range(3010, 3015))},
        "mot_seeds": {"held_out_confirmation": list(range(43010, 43015))},
        "input_ensembles": {"held_out_confirmation": frozen},
        "fixed_design": {
            "final_dt_s": 0.625e-6,
            "target_95_half_width_fraction": 0.0005,
            "particle_counts": {"confirmation": 10000, "sensitivity": 10000},
            "detuning_bounds_gamma": [-1.55, -0.85],
            "magnet_radius_bounds_m": [0.045, 0.051],
            "control_resolution": {
                "detuning_gamma": 0.01, "magnet_radius_m": 1e-5,
            },
            "stress_test_offsets": {
                "detuning_gamma": 0.02, "magnet_radius_m": 0.0001,
            },
        },
        "ensemble_source": {"directory": "source", "zeeman_profile": "profile"},
        "provenance": {"git_commit": "abc", "physical_model_sha256": "physics"},
    }
    record = {
        "kind": "mot_2d_campaign_confirmation", "s0": 1.3,
        "candidate_index": 0, "parameters": parameters,
        "design": {
            "physical_model_sha256": "physics", "git_commit": "abc",
            "solver": "RK4StHybridCustom", "dt_s": 0.625e-6,
            "n_ensembles": 5, "particles_per_ensemble": 10000,
            "zeeman_seeds": list(range(3010, 3015)),
            "mot_seeds": list(range(43010, 43015)),
            "ensemble_source": manifest["ensemble_source"],
        },
        "evaluation": {
            "batch_elapsed_seconds": 1.0,
            "replicates": replicates,
            "statistics": summarize_replicates(replicates),
        },
    }
    for index in range(5):
        candidate = json.loads(json.dumps(record))
        candidate["candidate_index"] = index
        (folder / f"point_{index:02d}.json").write_text(json.dumps(candidate))
    path = folder / "point_00.json"
    return root, manifest, path, record


def test_advancement_validation_rejects_tampered_evaluation_content(tmp_path, monkeypatch):
    import workflow_api.mot_2d_validation as validation

    root, manifest, path, record = _write_strict_evaluation_campaign(tmp_path)
    tasks = json.loads((root / "confirmation/tasks.json").read_text())
    monkeypatch.setattr(validation, "_expected_confirmation_tasks", lambda *args: tasks)
    assert len(validation.validated_evaluation_outputs(root, manifest, "confirmation")) == 5
    record["evaluation"]["statistics"]["mean_conditional_efficiency"] = 0.9
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="aggregate statistics"):
        validation.validated_evaluation_outputs(root, manifest, "confirmation")


def test_confirmation_registry_rejects_coordinated_task_and_result_tamper(
    tmp_path, monkeypatch
):
    import workflow_api.mot_2d_validation as validation

    root, manifest, path, record = _write_strict_evaluation_campaign(tmp_path)
    expected_tasks = json.loads((root / "confirmation/tasks.json").read_text())
    monkeypatch.setattr(
        validation, "_expected_confirmation_tasks", lambda *args: expected_tasks
    )
    tampered_tasks = json.loads(json.dumps(expected_tasks))
    tampered_tasks[0]["parameters"]["detuning_gamma"] = -1.0
    (root / "confirmation/tasks.json").write_text(json.dumps(tampered_tasks))
    record["parameters"]["detuning_gamma"] = -1.0
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="task registry is not canonical"):
        validation.validated_evaluation_outputs(root, manifest, "confirmation")


def test_confirmation_progress_allows_partial_results_but_rejects_coordinated_tamper(
    tmp_path, monkeypatch
):
    import workflow_api.mot_2d_validation as validation

    root, manifest, path, record = _write_strict_evaluation_campaign(tmp_path)
    expected_tasks = json.loads((root / "confirmation/tasks.json").read_text())
    monkeypatch.setattr(
        validation, "_expected_confirmation_tasks", lambda *args: expected_tasks
    )
    path.unlink()
    progress = validation.validated_progress(root, manifest)
    confirmation = next(row for row in progress if row.stage == "confirmation")
    assert confirmation.status == "in-progress"
    assert confirmation.completed == 4

    tampered_tasks = json.loads(json.dumps(expected_tasks))
    tampered_tasks[0]["parameters"]["detuning_gamma"] = -1.0
    (root / "confirmation/tasks.json").write_text(json.dumps(tampered_tasks))
    record["parameters"]["detuning_gamma"] = -1.0
    path.write_text(json.dumps(record))
    progress = validation.validated_progress(root, manifest)
    confirmation = next(row for row in progress if row.stage == "confirmation")
    assert confirmation.status == "inconsistent"


def _write_strict_sensitivity_campaign(tmp_path, monkeypatch):
    import workflow_api.mot_2d_validation as validation

    root, manifest, _, base_record = _write_strict_evaluation_campaign(tmp_path)
    confirmation_tasks = json.loads((root / "confirmation/tasks.json").read_text())
    monkeypatch.setattr(
        validation, "_expected_confirmation_tasks", lambda *args: confirmation_tasks
    )
    confirmation_rows = validation.validated_evaluation_outputs(
        root, manifest, "confirmation"
    )
    tasks = validation.expected_sensitivity_tasks(manifest, confirmation_rows)
    manifest["stages"]["sensitivity"] = {"tasks": len(tasks)}
    (root / "sensitivity").mkdir()
    (root / "sensitivity/tasks.json").write_text(json.dumps(tasks))
    for task in tasks:
        record = json.loads(json.dumps(base_record))
        record.pop("candidate_index")
        record.update(task)
        record["kind"] = "mot_2d_campaign_sensitivity"
        folder = root / "sensitivity" / "s0_1p300000"
        folder.mkdir(exist_ok=True)
        (folder / f"point_{task['point_index']:02d}.json").write_text(
            json.dumps(record)
        )
    return root, manifest, tasks


def test_sensitivity_result_cannot_relabel_noncenter_as_center(tmp_path, monkeypatch):
    import workflow_api.mot_2d_validation as validation

    root, manifest, tasks = _write_strict_sensitivity_campaign(tmp_path, monkeypatch)
    assert validation.validated_evaluation_outputs(root, manifest, "sensitivity")
    noncenter = next(task for task in tasks if any(task["offsets"].values()))
    path = (
        root / "sensitivity/s0_1p300000"
        / f"point_{noncenter['point_index']:02d}.json"
    )
    record = json.loads(path.read_text())
    record["offsets"] = {"detuning_gamma": 0.0, "magnet_radius_m": 0.0}
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="offsets differ"):
        validation.validated_evaluation_outputs(root, manifest, "sensitivity")


def test_sensitivity_registry_rejects_coordinated_task_and_result_tamper(
    tmp_path, monkeypatch
):
    import workflow_api.mot_2d_validation as validation

    root, manifest, tasks = _write_strict_sensitivity_campaign(tmp_path, monkeypatch)
    tasks[0]["parameters"]["detuning_gamma"] += 0.001
    (root / "sensitivity/tasks.json").write_text(json.dumps(tasks))
    path = root / "sensitivity/s0_1p300000/point_00.json"
    record = json.loads(path.read_text())
    record["parameters"] = tasks[0]["parameters"]
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="task registry is not canonical"):
        validation.validated_evaluation_outputs(root, manifest, "sensitivity")


def test_sensitivity_progress_allows_partial_results_but_rejects_coordinated_tamper(
    tmp_path, monkeypatch
):
    import workflow_api.mot_2d_validation as validation

    root, manifest, tasks = _write_strict_sensitivity_campaign(tmp_path, monkeypatch)
    last = tasks[-1]
    last_path = (
        root / "sensitivity/s0_1p300000"
        / f"point_{last['point_index']:02d}.json"
    )
    last_record = json.loads(last_path.read_text())
    last_path.unlink()
    progress = validation.validated_progress(root, manifest)
    sensitivity = next(row for row in progress if row.stage == "sensitivity")
    assert sensitivity.status == "in-progress"
    assert sensitivity.completed == len(tasks) - 1

    tampered_tasks = json.loads(json.dumps(tasks))
    tampered_tasks[-1]["parameters"]["detuning_gamma"] += 0.001
    (root / "sensitivity/tasks.json").write_text(json.dumps(tampered_tasks))
    last_record["parameters"] = tampered_tasks[-1]["parameters"]
    last_path.write_text(json.dumps(last_record))
    progress = validation.validated_progress(root, manifest)
    sensitivity = next(row for row in progress if row.stage == "sensitivity")
    assert sensitivity.status == "inconsistent"


def test_production_transition_rejects_coordinated_downstream_relabeling(
    tmp_path, monkeypatch
):
    import workflow_api.mot_2d_validation as validation
    from workflow_api.mot_2d_late_stage import derive_production_transition

    root, manifest, _ = _write_strict_sensitivity_campaign(tmp_path, monkeypatch)
    manifest["seed_roles"]["sealed_validation"] = [3015]
    manifest["mot_seeds"]["sealed_validation"] = [43015]
    confirmation_rows = validation.validated_evaluation_outputs(
        root, manifest, "confirmation"
    )
    sensitivity_rows = validation.validated_evaluation_outputs(
        root, manifest, "sensitivity"
    )
    expected_summary, expected_tasks = derive_production_transition(
        manifest, confirmation_rows, sensitivity_rows
    )
    (root / "sensitivity_summary.json").write_text(json.dumps(expected_summary))
    production = root / "production"
    production.mkdir()
    (production / "tasks.json").write_text(json.dumps(expected_tasks))
    assert validation.validated_production_transition(root, manifest) == (
        expected_summary,
        expected_tasks,
    )

    forged_summary = json.loads(json.dumps(expected_summary))
    key = "s0_1p300000"
    forged_parameters = json.loads(json.dumps(
        forged_summary[key]["production_selection"]["parameters"]
    ))
    forged_parameters["detuning_gamma"] += 0.001
    forged_summary[key]["production_selection"]["parameters"] = forged_parameters
    forged_tasks = json.loads(json.dumps(expected_tasks))
    forged_tasks[0]["parameters"] = forged_parameters
    (root / "sensitivity_summary.json").write_text(json.dumps(forged_summary))
    (production / "tasks.json").write_text(json.dumps(forged_tasks))

    # Even if every downstream copy agrees with the forged label, the label
    # remains unauthorized because it is not derived from the frozen evidence.
    replicates = production / key / "replicates"
    replicates.mkdir(parents=True)
    (replicates / "zeeman_seed3015.json").write_text(json.dumps({
        "parameters": forged_parameters,
    }))
    (root / "final_report.json").write_text(json.dumps({
        "results": [{"recommended_parameters": forged_parameters}],
    }))
    with pytest.raises(ValueError, match="not canonical"):
        validation.validated_production_transition(root, manifest)


@pytest.mark.parametrize("field", ["warnings", "target_uncertainty_passes", "sensitivity"])
def test_sealed_final_rejects_unvalidated_scientific_claims(tmp_path, monkeypatch, field):
    from workflow_api.models import StageProgress
    from workflow_api.mot_2d_validation import sealed_final_is_valid

    _patch_portable_production_transition(monkeypatch)
    repository_root = tmp_path / "checkout"
    root, manifest = _write_portable_sealed_campaign(repository_root)
    report_path = root / "final_report.json"
    report = json.loads(report_path.read_text())
    result = report["results"][0]
    if field == "warnings":
        result[field] = []
    elif field == "target_uncertainty_passes":
        result[field] = not result[field]
    else:
        result[field] = {"robustness_status": "established"}
    report_path.write_text(json.dumps(report))
    assert not sealed_final_is_valid(
        root, manifest,
        (
            StageProgress("sensitivity", 17, 17, "complete"),
            StageProgress("production", 20, 20, "complete"),
        ),
        repository_root,
    )


def test_sealed_final_recomputes_prediction_from_raw_replicates(tmp_path, monkeypatch):
    from workflow_api.models import StageProgress
    from workflow_api.mot_2d_validation import sealed_final_is_valid

    _patch_portable_production_transition(monkeypatch)
    repository_root = tmp_path / "checkout"
    root, manifest = _write_portable_sealed_campaign(repository_root)
    summary_path = root / "production/s0_1p300000/summary.json"
    report_path = root / "final_report.json"
    summary = json.loads(summary_path.read_text())
    report = json.loads(report_path.read_text())
    forged = json.loads(json.dumps(summary["prediction_for_10m_zeeman_survivors"]))
    forged["pooled_conditional_efficiency"] = 0.75
    summary["prediction_for_10m_zeeman_survivors"] = forged
    report["results"][0]["prediction"] = forged
    summary_path.write_text(json.dumps(summary))
    report_path.write_text(json.dumps(report))
    progress = (
        StageProgress("sensitivity", 17, 17, "complete"),
        StageProgress("production", 20, 20, "complete"),
    )
    assert not sealed_final_is_valid(root, manifest, progress, repository_root)


def test_atomic_json_does_not_leave_temporary_file(tmp_path):
    from utils.file_helpers import save_file_json
    path = tmp_path / "result.json"
    save_file_json(path, {"complete": True})
    assert json.loads(path.read_text()) == {"complete": True}
    assert not list(tmp_path.glob("*.tmp"))


def test_optuna_resume_targets_total_complete_trials():
    import optuna
    from studies.mot_2d.optimization import remaining_complete_trials
    states = [optuna.trial.TrialState.COMPLETE] * 7
    states += [optuna.trial.TrialState.FAIL, optuna.trial.TrialState.RUNNING]
    assert remaining_complete_trials(10, states) == 3
    assert remaining_complete_trials(7, states) == 0
    with pytest.raises(RuntimeError, match="exceeding target"):
        remaining_complete_trials(6, states)


@pytest.mark.parametrize('acceptance', [False, True], ids=['scientific', 'TEST-ONLY'])
def test_catalog_frozen_inputs_match_real_subset_stage_loader(tmp_path, monkeypatch, acceptance):
    import copy
    import studies.mot_2d_s0_campaign as campaign
    from workflow_api.acceptance_profile import load_acceptance_profile
    from workflow_api.mot_2d_sources import inspect_source
    from workflow_api.mot_2d_spec import ROLE_SEEDS, build_manifest
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(campaign, 'REPOSITORY_ROOT', tmp_path)
    profile = load_acceptance_profile() if acceptance else None
    relative = 'data/particle_states/after_zeeman/' + ('ui_acceptance/source' if acceptance else 'source')
    directory = tmp_path / relative
    directory.mkdir(parents=True)
    for seed in range(3000, 3035):
        path = _ensemble(directory, seed=seed)
        if profile:
            renamed = path.with_name(path.name.replace('n50000', 'n32'))
            path.rename(renamed)
            metadata = json.loads(path.with_suffix('.json').read_text())
            path.with_suffix('.json').unlink()
            metadata['parameters']['n_initial_atoms'] = 32
            metadata['survival_fraction'] = 4 / 32
            metadata['acceptance'] = profile.provenance()
            renamed.with_suffix('.json').write_text(json.dumps(metadata))
    source = inspect_source(directory, tmp_path, include_records=True,
                            acceptance_profile_id=profile.profile_id if profile else None)
    records = {row['zeeman_seed']: row for row in source['records']}
    frozen = {role: [records[seed] for seed in seeds] for role, seeds in ROLE_SEEDS.items()}
    manifest = build_manifest(name='catalog_stage', s0_values=[1.3], ensemble_directory=relative,
                              zeeman_profile=campaign.DEFAULT_PROFILE, frozen_inputs=frozen,
                              git_commit='a' * 40, physical_model_sha256='b' * 64, hashed_files=[],
                              acceptance_profile_id=profile.profile_id if profile else None)
    rows = campaign.stage_ensembles(manifest, 'smoke', 2)
    assert len(rows) == 5
    assert all(row['states'].shape == (2, 6) and row['shape'] == [4, 6] for row in rows)
    for field in ['sha256', 'metadata_sha256', 'size_bytes', 'metadata_size_bytes', 'legacy_attested_profile']:
        changed = copy.deepcopy(manifest)
        record = changed['input_ensembles']['discovery'][0]
        record[field] = (not record[field] if isinstance(record[field], bool) else
                         record[field] + 1 if isinstance(record[field], int) else '0' * 64)
        with pytest.raises(RuntimeError, match='Frozen Zeeman input changed'):
            campaign.stage_ensembles(changed, 'smoke', 2)
    changed = copy.deepcopy(manifest)
    changed['input_ensembles']['discovery'][0].pop('size_bytes')
    with pytest.raises(RuntimeError, match='Frozen Zeeman input changed'):
        campaign.stage_ensembles(changed, 'smoke', 2)


@pytest.mark.parametrize("field,value", [("legacy_attested_profile", 0), ("size_bytes", True), ("metadata_size_bytes", False), ("size_bytes", 0), ("metadata_size_bytes", -1)])
def test_catalog_frozen_identity_rejects_noncanonical_scalar_types(tmp_path, monkeypatch, field, value):
    import studies.mot_2d_s0_campaign as campaign
    monkeypatch.setattr(campaign, "validate_campaign_policy", lambda manifest: None)
    monkeypatch.setattr(campaign, "repository_path", lambda path: tmp_path)
    monkeypatch.setattr(campaign, "load_production_ensembles", lambda **kwargs: [{"zeeman_seed": 3000}])
    record = {"zeeman_seed": 3000, "size_bytes": 1, "metadata_size_bytes": 1, "legacy_attested_profile": False}
    record[field] = value
    manifest = {"provenance": {"path_contract": "repository-relative-v1"}, "seed_roles": {"discovery": [3000]},
                "input_ensembles": {"discovery": [record]}, "ensemble_source": {"directory": "source", "zeeman_profile": "corrected"}}
    with pytest.raises(RuntimeError, match="Frozen Zeeman input changed"):
        campaign.stage_ensembles(manifest, "smoke", 2)
