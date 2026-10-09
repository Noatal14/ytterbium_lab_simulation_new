import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


def _ensemble(directory, seed=3000, profile="corrected_projectant_19ring_20261005", nonfinite=False):
    path = directory / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
    states = np.zeros((4, 6))
    if nonfinite:
        states[0, 0] = np.nan
    np.save(path, states)
    path.with_suffix(".json").write_text(json.dumps({
        "shape": [4, 6], "dtype": "float64", "n_survivors": 4,
        "survival_fraction": 4/50000,
        "output_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "parameters": {"seed": seed, "n_initial_atoms": 50000, "dt_s": 4e-5,
                       "stochastic": True, "collimation_angle_deg": 1.5,
                       "resolved_zeeman_magnet_profile": profile},
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
    with pytest.raises(ValueError, match="Incomplete immutable provenance"):
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


def test_dirty_relevant_code_is_rejected(monkeypatch):
    import studies.mot_2d_s0_campaign as campaign

    monkeypatch.setattr(
        campaign.subprocess,
        "check_output",
        lambda *args, **kwargs: " M config.py\n",
    )
    with pytest.raises(RuntimeError, match="dirty"):
        campaign.assert_relevant_worktree_clean()


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
        "name": "test", "stage": "production", "s0_values": [1.3],
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


def _write_portable_sealed_campaign(repository_root):
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
        "git_commit": "abc",
    }
    tasks, replicates, frozen = [], [], []
    for seed, mot_seed in zip(seeds, mot_seeds):
        source = source_root / f"zeeman_seed{seed}.npy"
        np.save(source, np.zeros((2, 6)))
        source_identity = source.relative_to(repository_root).as_posix()
        frozen.append({"zeeman_seed": seed, "path": source_identity})
        tasks.append({"s0": 1.3, "zeeman_seed": seed, "mot_seed": mot_seed,
                      "parameters": parameters})
        replicates.append({"zeeman_seed": seed, "mot_seed": mot_seed,
                           "n_input": 2, "captured": 1})
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

    prediction = {"mean": 0.5}
    (campaign_root / "production/tasks.json").write_text(json.dumps(tasks))
    (campaign_root / "production/s0_1p300000/summary.json").write_text(json.dumps({
        "kind": "mot_2d_final_production_summary",
        "zeeman_seeds": seeds, "design": design, "parameters": parameters,
        "replicates": replicates,
        "prediction_for_10m_zeeman_survivors": prediction,
    }))
    (campaign_root / "final_report.json").write_text(json.dumps({
        "kind": "mot_2d_s0_campaign_final_report",
        "results": [{
            "s0": 1.3,
            "recommended_parameters": parameters,
            "prediction": prediction,
            "survivor_states_directory": states_root.relative_to(repository_root).as_posix(),
        }],
    }))
    manifest = {
        "stage": "complete", "s0_values": [1.3],
        "seed_roles": {"sealed_validation": seeds},
        "mot_seeds": {"sealed_validation": mot_seeds},
        "input_ensembles": {"sealed_validation": frozen},
        "fixed_design": {"final_dt_s": 0.625e-6},
        "ensemble_source": {
            "directory": "data/particle_states/after_zeeman/source",
            "zeeman_profile": "profile",
        },
        "provenance": {"git_commit": "abc"},
        "stages": {"final_report": "data/optimization/mot_2d/fixed_s0/final_report.json"},
    }
    return campaign_root, manifest


def test_sealed_final_validation_survives_repository_relocation(tmp_path):
    from workflow_api.models import StageProgress
    from workflow_api.mot_2d_validation import sealed_final_is_valid

    outcomes = []
    for directory in ("checkout_a", "a-different-checkout-root"):
        repository_root = tmp_path / directory
        campaign_root, manifest = _write_portable_sealed_campaign(repository_root)
        outcomes.append(sealed_final_is_valid(
            campaign_root,
            manifest,
            (StageProgress("production", 20, 20, "complete"),),
            repository_root,
        ))
    assert outcomes == [True, True]


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
        payload = {"candidate_index": index,
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
    campaign.prepare_sensitivity(root, {"s0_values": [1.3]})
    identities = [(x["parameters"]["detuning_gamma"], x["parameters"]["magnet_radius"])
                  for x in captured["specs"]]
    assert len(identities) == len(set(identities))


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
