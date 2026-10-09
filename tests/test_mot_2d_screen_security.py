"""Independent adversarial tests for the shared Screening validator."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import optuna
import pytest

from utils.mot_2d_study import summarize_replicates
from workflow_api.mot_2d_screen import ScreenValidationError, validate_screen_outputs
from workflow_api.zeus_refinement import (
    RemoteScreenState,
    ZeusRefinementCoordinator,
    ZeusRefinementError,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def valid_screen(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "campaign"
    seeds = list(range(3000, 3005))
    mot_seeds = list(range(43000, 43005))
    frozen = [
        {
            "path": f"data/particle_states/after_zeeman/source/seed{seed}.npy",
            "survivor_count": 30000 + index,
            "generation": {"n_initial_atoms": 50000},
        }
        for index, seed in enumerate(seeds)
    ]
    manifest = {
        "kind": "mot_2d_s0_campaign",
        "stage": "screen",
        "name": "security_fixture",
        "s0_values": [1.3],
        "fixed_design": {
            "working_dt_s": 1.25e-6,
            "particle_counts": {"screen": 20},
            "detuning_bounds_gamma": [-2.0, -0.5],
            "magnet_radius_bounds_m": [0.045, 0.052],
        },
        "ensemble_source": {"directory": "data/particle_states/after_zeeman/source"},
        "seed_roles": {"discovery": seeds},
        "mot_seeds": {"discovery": mot_seeds},
        "input_ensembles": {"discovery": frozen},
        "provenance": {"git_commit": "a" * 40, "physical_model_sha256": "b" * 64},
    }
    tasks = [{"s0": 1.3, "worker": worker} for worker in range(3)]
    _write_json(root / "screen/tasks.json", tasks)

    for worker in range(3):
        directory = root / "screen/s0_1p300000" / f"worker{worker}"
        trials: list[dict] = []
        design = {
            "fixed_s0": 1.3,
            "dt_s": 1.25e-6,
            "solver": "RK4StHybridCustom",
            "ensemble_dir": manifest["ensemble_source"]["directory"],
            "zeeman_seeds": seeds,
            "mot_seeds": mot_seeds,
            "particles_per_ensemble": 20,
            "sampler_seed": 137 + worker,
            "bounds": {
                "s0": [1.3, 1.3],
                "detuning_gamma": [-2.0, -0.5],
                "magnet_radius_m": [0.045, 0.052],
            },
            "git_commit": "a" * 40,
            "campaign_design_id": "b" * 64,
        }
        design_id = hashlib.sha256(json.dumps(design, sort_keys=True).encode()).hexdigest()
        study_name = f"security_fixture_screen_s0_1p300000_w{worker}"
        storage = f"sqlite:///{directory / 'joint_screening.db'}"
        directory.mkdir(parents=True)
        study = optuna.create_study(study_name=study_name, storage=storage, direction="maximize")
        study.set_user_attr("scientific_design", design)
        study.set_user_attr("design_id", design_id)
        parameters = []
        for number in range(17):
            detuning = -1.95 + 0.08 * number
            radius = 0.0451 + 0.0004 * number
            parameters.append((detuning, radius))
            study.enqueue_trial({"detuning_gamma": detuning, "magnet_radius": radius})

        def objective(trial: optuna.Trial) -> float:
            detuning = trial.suggest_float("detuning_gamma", -2.0, -0.5)
            radius = trial.suggest_float("magnet_radius", 0.045, 0.052)
            return (trial.number + worker + 1) / 20

        study.optimize(objective, n_trials=17)
        for number, (detuning, radius) in enumerate(parameters):
            captured = number + worker + 1
            replicates = []
            for index, seed in enumerate(seeds):
                conditional = captured / 20
                replicates.append({
                    "ensemble_file": f"seed{seed}.npy",
                    "zeeman_seed": seed,
                    "mot_seed": mot_seeds[index],
                    "n_available": 30000 + index,
                    "selection_method": "deterministic_random_without_replacement",
                    "subset_seed": 100000 + seed,
                    "n_input": 20,
                    "captured": captured,
                    "conditional_efficiency": conditional,
                    "estimated_total_efficiency": conditional * ((30000 + index) / 50000),
                    "batch_elapsed_seconds": 1.0,
                })
            row = {
                "kind": "mot_2d_joint_optimization_trial",
                "trial_number": number,
                "parameters": {"s0": 1.3, "detuning_gamma": detuning, "magnet_radius": radius},
                "design": {
                    "dt_s": 1.25e-6,
                    "n_ensembles": 5,
                    "particles_per_ensemble": 20,
                    "mot_seed_start": 24000,
                    "stochastic_solver": "RK4StHybridCustom",
                    "design_id": design_id,
                    "git_commit": "a" * 40,
                    "ensemble_dir": manifest["ensemble_source"]["directory"],
                    "zeeman_seeds": seeds,
                    "mot_seeds": mot_seeds,
                },
                "batch_elapsed_seconds": 1.0,
                "replicates": replicates,
                "statistics": summarize_replicates(replicates),
            }
            trials.append(row)
            _write_json(directory / f"trials/trial_{number:04d}.json", row)
        ranked = sorted(trials, key=lambda row: (-row["statistics"]["mean_conditional_efficiency"], row["trial_number"]))
        _write_json(directory / "summary.json", {
            "kind": "mot_2d_joint_optimization_summary",
            "study_name": study_name,
            "objectives": ["maximize_mean_conditional_efficiency"],
            "fixed_s0": 1.3,
            "n_registered_trials": 17,
            "n_finished_trials": 17,
            "ranked_trials": [{
                "trial_number": row["trial_number"],
                "mean_conditional_efficiency": row["statistics"]["mean_conditional_efficiency"],
                "parameters": row["parameters"],
            } for row in ranked],
            "pareto_front": [],
            "design": {
                "dt_s": 1.25e-6,
                "n_ensembles": 5,
                "particles_per_ensemble": 20,
                "mot_seed_start": 24000,
                "stochastic_solver": "RK4StHybridCustom",
                "ensemble_dir": manifest["ensemble_source"]["directory"],
                "zeeman_seeds": seeds,
                "sampler_seed": 137 + worker,
                "bounds": design["bounds"],
            },
        })
    return root, manifest


def test_valid_complete_screen_is_accepted(valid_screen):
    root, manifest = valid_screen
    assert len(validate_screen_outputs(root, manifest)) == 51


@pytest.mark.parametrize("mutation", ["nan", "seed", "solver", "dt", "ranking", "extra"])
def test_trial_and_summary_tampering_is_rejected(valid_screen, mutation):
    root, manifest = valid_screen
    trial_path = root / "screen/s0_1p300000/worker0/trials/trial_0000.json"
    summary_path = root / "screen/s0_1p300000/worker0/summary.json"
    if mutation == "ranking":
        payload = json.loads(summary_path.read_text())
        payload["ranked_trials"].reverse()
        _write_json(summary_path, payload)
    elif mutation == "extra":
        _write_json(trial_path.parent / "unexpected.json", {})
    else:
        payload = json.loads(trial_path.read_text())
        if mutation == "nan": payload["statistics"]["mean_conditional_efficiency"] = float("nan")
        elif mutation == "seed": payload["replicates"][0]["mot_seed"] += 1
        elif mutation == "solver": payload["design"]["stochastic_solver"] = "wrong"
        elif mutation == "dt": payload["design"]["dt_s"] *= 2
        _write_json(trial_path, payload)
    with pytest.raises(ScreenValidationError):
        validate_screen_outputs(root, manifest)


def test_optuna_distribution_tampering_is_rejected(valid_screen):
    root, manifest = valid_screen
    database = root / "screen/s0_1p300000/worker0/joint_screening.db"
    with sqlite3.connect(database) as connection:
        distribution = json.loads(connection.execute(
            "SELECT distribution_json FROM trial_params LIMIT 1"
        ).fetchone()[0])
        distribution["attributes"]["log"] = True
        connection.execute(
            "UPDATE trial_params SET distribution_json=? WHERE rowid=(SELECT rowid FROM trial_params LIMIT 1)",
            (json.dumps(distribution),),
        )
    with pytest.raises(ScreenValidationError):
        validate_screen_outputs(root, manifest)


def test_symlinked_worker_artifact_is_rejected(valid_screen, tmp_path):
    root, manifest = valid_screen
    summary = root / "screen/s0_1p300000/worker0/summary.json"
    external = tmp_path / "external.json"
    external.write_bytes(summary.read_bytes())
    summary.unlink()
    summary.symlink_to(external)
    with pytest.raises(ScreenValidationError):
        validate_screen_outputs(root, manifest)


def test_remote_receiver_has_no_scheduler_submission_capability():
    source = (Path(__file__).parents[1] / "workflow_api/zeus_refinement_remote.py").read_text()
    assert "/usr/local/bin/qsub" not in source
    assert "subprocess.Popen" not in source
    assert "os.system" not in source


@pytest.mark.parametrize(
    "state",
    [
        RemoteScreenState("screen_running", "1[].zeus-master", "R", None, 3,
                          {"queued": 0, "running": "3", "held": 0, "succeeded": 0, "failed": 0}),
        RemoteScreenState("ready_to_prepare_refinement", "1[].zeus-master", "F", 0, 3,
                          {"queued": 1, "running": 0, "held": 0, "succeeded": 2, "failed": 0},
                          tuple({} for _ in range(51))),
        RemoteScreenState("screen_failed", "1[].zeus-master", "F", 0, 3,
                          {"queued": 0, "running": 0, "held": 0, "succeeded": 3, "failed": 0}),
    ],
)
def test_coordinator_rejects_forged_scheduler_coherence(tmp_path, monkeypatch, state):
    campaign = tmp_path / "data/optimization/mot_2d/campaign"
    campaign.mkdir(parents=True)
    executable = Path(sys.executable)
    coordinator = ZeusRefinementCoordinator(tmp_path, executable, executable,
        transport_factory=lambda profile: type("Transport", (), {"inspect": lambda self, **kwargs: state})())
    plan = (campaign, {"s0_values": [1.3]}, {}, "a" * 40, {}, {}, "b" * 64, "c" * 64)
    monkeypatch.setattr(coordinator, "_plan", lambda campaign_id: plan)
    monkeypatch.setattr(coordinator, "_revision", lambda: ("a" * 40, True))
    with pytest.raises(ZeusRefinementError) as error:
        coordinator._inspect({
            "campaign_id": "mot_2d-campaign",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        })
    assert error.value.code == "remote_response_invalid"


def test_receiver_revalidates_under_lock_and_recovery_is_canonical():
    source = (Path(__file__).parents[1] / "workflow_api/zeus_refinement_remote.py").read_text()
    assert source.count("validate_screen_outputs(") >= 3
    assert source.count("['/usr/local/bin/qstat','-x','-t','-f',job_id]") == 2
    assert "canonical_refine=render_refine_transition" in source
    assert "canonical_rows!=record['rows']" in source


def test_refinement_revision_maps_public_service_oserror_to_stable_code(tmp_path, monkeypatch):
    executable = Path(sys.executable)
    coordinator = ZeusRefinementCoordinator(tmp_path, executable, executable)
    monkeypatch.setattr(
        "workflow_api.zeus_refinement.RepositoryRevisionService.inspect",
        lambda self: (_ for _ in ()).throw(OSError("redacted operating-system detail")),
    )

    with pytest.raises(ZeusRefinementError) as caught:
        coordinator._revision()

    assert caught.value.code == "local_repository_unavailable"
    assert str(caught.value) == "local_repository_unavailable"
    assert isinstance(caught.value.__cause__, OSError)
