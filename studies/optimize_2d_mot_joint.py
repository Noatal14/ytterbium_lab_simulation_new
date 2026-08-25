"""Jointly optimize s0, detuning, and magnet radius for the 2D MOT.

Every trial uses the same Zeeman ensembles, particle subsets, and MOT seeds so
that candidate comparisons are paired.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import optuna

from config import DEFAULT_NUM_POOLS, DEFAULT_RANDOM_SEED, MOT_2D_SIM_CONFIG
from simulations.mot_2d import mot_simulation_paired_ensembles
from utils.data_paths import MOT_2D_OPTIMIZATION_DIR
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles, summarize_replicates

BOUNDS_S0 = (0.8, 1.5)
BOUNDS_DETUNING = (-2.0, -0.6)
BOUNDS_MAGNET_RADIUS_M = (0.045, 0.054)


def evaluate_configuration(
    s0, detuning_gamma, magnet_radius, ensembles, mot_seed_start, npools, dt_s,
):
    """Evaluate one point on fixed paired replicates and return its summary."""
    mot_seeds = [mot_seed_start + index for index in range(len(ensembles))]
    started = time.time()
    grouped_results = mot_simulation_paired_ensembles(
        survivor_state_ensembles=[row["states"] for row in ensembles],
        seeds=mot_seeds,
        _2d_mot_config={
            "s0": s0,
            "detuning_gamma": detuning_gamma,
            "swap_polarization": False,
        },
        magnet_radius=magnet_radius,
        stochastic=True,
        npools=npools,
        dt=dt_s,
    )
    batch_elapsed = time.time() - started

    replicates = []
    for index, (ensemble, result) in enumerate(zip(ensembles, grouped_results)):
        _, captured, _ = result
        mot_seed = mot_seeds[index]
        n_input = len(ensemble["states"])
        conditional = captured / n_input
        replicates.append(
            {
                "ensemble_file": ensemble["path"].name,
                "zeeman_seed": ensemble["zeeman_seed"],
                "mot_seed": mot_seed,
                "n_available": ensemble["n_available"],
                "selection_method": ensemble["selection_method"],
                "subset_seed": ensemble["subset_seed"],
                "n_input": n_input,
                "captured": int(captured),
                "conditional_efficiency": float(conditional),
                "estimated_total_efficiency": float(
                    conditional * ensemble["zeeman_survival_fraction"]
                ),
                "batch_elapsed_seconds": float(batch_elapsed),
            }
        )
    return {
        "batch_elapsed_seconds": float(batch_elapsed),
        "replicates": replicates,
        "statistics": summarize_replicates(replicates),
    }


def optimize_mot(args):
    ensembles = load_production_ensembles(
        max_ensembles=args.n_ensembles,
        particles_per_ensemble=args.particles_per_ensemble,
    )
    output_dir = Path(args.output_dir)
    trials_dir = output_dir / "trials"
    trials_dir.mkdir(parents=True, exist_ok=True)

    def objective(trial):
        parameters = {
            "s0": trial.suggest_float("s0", *BOUNDS_S0),
            "detuning_gamma": trial.suggest_float(
                "detuning_gamma", *BOUNDS_DETUNING
            ),
            "magnet_radius": trial.suggest_float(
                "magnet_radius", *BOUNDS_MAGNET_RADIUS_M
            ),
        }
        evaluation = evaluate_configuration(
            **parameters,
            ensembles=ensembles,
            mot_seed_start=args.mot_seed_start,
            npools=args.npools,
            dt_s=args.dt,
        )
        payload = {
            "kind": "mot_2d_joint_optimization_trial",
            "trial_number": trial.number,
            "parameters": parameters,
            "design": {
                "dt_s": args.dt,
                "n_ensembles": len(ensembles),
                "particles_per_ensemble": args.particles_per_ensemble,
                "mot_seed_start": args.mot_seed_start,
            },
            **evaluation,
        }
        save_file_json(trials_dir / f"trial_{trial.number:04d}.json", payload)
        value = evaluation["statistics"]["mean_conditional_efficiency"]
        print(
            "MOT_2D_OPTUNA_RESULT "
            f"trial={trial.number} s0={parameters['s0']:.8f} "
            f"detuning_gamma={parameters['detuning_gamma']:.8f} "
            f"magnet_radius={parameters['magnet_radius']:.8f} "
            f"mean_conditional_percent={100 * value:.6f}"
        )
        return value

    study = optuna.create_study(
        study_name=args.study_name,
        storage=f"sqlite:///{output_dir / 'joint_screening.db'}",
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=DEFAULT_RANDOM_SEED),
        # The three paired replicates share one worker pool and complete as a
        # single batch. Pruning after a partial replicate would require
        # rebuilding that expensive pool, so it is deliberately disabled.
        pruner=optuna.pruners.NopPruner(),
        load_if_exists=True,
    )
    study.optimize(objective, n_trials=args.n_trials)
    summary = {
        "kind": "mot_2d_joint_optimization_summary",
        "study_name": args.study_name,
        "n_finished_trials": len(study.trials),
        "best_value": float(study.best_value),
        "best_parameters": study.best_params,
        "design": {
            "dt_s": args.dt,
            "n_ensembles": len(ensembles),
            "particles_per_ensemble": args.particles_per_ensemble,
            "mot_seed_start": args.mot_seed_start,
            "bounds": {
                "s0": BOUNDS_S0,
                "detuning_gamma": BOUNDS_DETUNING,
                "magnet_radius_m": BOUNDS_MAGNET_RADIUS_M,
            },
        },
    }
    save_file_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    return study


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-trials", type=int, default=50)
    parser.add_argument("--n-ensembles", type=int, default=3)
    parser.add_argument("--particles-per-ensemble", type=int, default=2000)
    parser.add_argument("--mot-seed-start", type=int, default=4000)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--dt", type=float, default=MOT_2D_SIM_CONFIG["dt_s"])
    parser.add_argument("--study-name", default="mot_2d_joint_screening_v1")
    parser.add_argument(
        "--output-dir", default=str(MOT_2D_OPTIMIZATION_DIR / "joint_screening_v1")
    )
    return parser.parse_args()


if __name__ == "__main__":
    optimize_mot(parse_args())
