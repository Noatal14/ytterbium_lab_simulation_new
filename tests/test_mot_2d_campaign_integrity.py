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
    root = tmp_path / "campaign"
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
    assert "#PBS -J 0-0%1" in pbs
    assert manifest["mot_seeds"]["sealed_validation"] == list(range(43015, 43035))


def test_frozen_ensemble_replacement_is_rejected(tmp_path):
    import studies.mot_2d_s0_campaign as campaign

    _ensemble(tmp_path)
    roles = {"discovery": [3000]}
    frozen = campaign.freeze_input_ensembles(tmp_path, campaign.DEFAULT_PROFILE, roles)
    manifest = {
        "seed_roles": roles,
        "input_ensembles": frozen,
        "ensemble_source": {"directory": str(tmp_path),
                            "zeeman_profile": campaign.DEFAULT_PROFILE},
    }
    path = next(tmp_path.glob("*.npy"))
    states = np.load(path)
    states[0, 0] = 1.0
    np.save(path, states)
    metadata_path = path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text())
    metadata["output_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(RuntimeError, match="Frozen Zeeman input changed"):
        campaign.stage_ensembles(manifest, "screen", 2)


def test_missing_required_ensemble_hash_is_rejected(tmp_path):
    import studies.mot_2d_s0_campaign as campaign

    path = _ensemble(tmp_path)
    metadata = json.loads(path.with_suffix(".json").read_text())
    metadata.pop("output_sha256")
    path.with_suffix(".json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Incomplete immutable provenance"):
        campaign.freeze_input_ensembles(
            tmp_path, campaign.DEFAULT_PROFILE, {"discovery": [3000]}
        )


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
    import studies.run_2d_mot_final_production as production

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
    from studies.run_2d_mot_final_production import summarize

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


def test_refinement_rounds_share_study_and_use_cumulative_targets(tmp_path, monkeypatch):
    import studies.mot_2d_s0_campaign as campaign

    root = tmp_path / "campaign"
    rows = [
        {"s0": 1.3, "detuning_gamma": -1.2 + index * 0.011,
         "magnet_radius": 0.048 + index * 0.000011,
         "mean_conditional_efficiency": 0.03 - index * 1e-5,
         "source": f"trial_{index}.json"}
        for index in range(3 * campaign.SCREEN_TRIALS)
    ]
    monkeypatch.setattr(campaign, "trial_rows", lambda *args: rows)
    manifest = {
        "name": "fixed_s0", "s0_values": [1.3], "stages": {},
        "provenance": {"git_commit": "abc"},
    }
    campaign.prepare_refine(root, manifest)
    saved = json.loads((root / "campaign.json").read_text())
    assert saved["stages"]["refine"]["cumulative_trial_targets"] == [3, 6, 9, 10]
    jobs = [Path(path) for path in saved["stages"]["refine"]["round_job_files"]]
    assert len(jobs) == 4
    for target, job in zip((3, 6, 9, 10), jobs):
        text = job.read_text()
        assert f"--target-trials {target}" in text
        assert "#PBS -l walltime=20:00:00" in text
        assert "--task-index $PBS_ARRAY_INDEX" in text
    submitter = Path(saved["stages"]["refine"]["submit_chain"]).read_text()
    assert submitter.count('depend=afterok:"${previous}"') == 3
    assert "afterokarray" not in submitter


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

    monkeypatch.setattr(
        campaign,
        "trial_rows",
        lambda *args: [{}] * (3 * campaign.REFINE_TRIALS - 1),
    )
    with pytest.raises(RuntimeError, match="Refinement incomplete"):
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
    from studies.optimize_2d_mot_joint import remaining_complete_trials
    states = [optuna.trial.TrialState.COMPLETE] * 7
    states += [optuna.trial.TrialState.FAIL, optuna.trial.TrialState.RUNNING]
    assert remaining_complete_trials(10, states) == 3
    assert remaining_complete_trials(7, states) == 0
    with pytest.raises(RuntimeError, match="exceeding target"):
        remaining_complete_trials(6, states)
