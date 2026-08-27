"""Screen timestep convergence with exact low-count photon recoil."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from config import DEFAULT_NUM_POOLS
from simulations.mot_2d import mot_simulation_paired_ensembles
from studies.validate_2d_mot_production import MOT_SEED_OFFSET
from studies.validate_2d_mot_robustness import SELECTED_PARAMETERS
from utils.RK4StHybridCustom import (
    DEFAULT_POISSON_THRESHOLD,
    RK4StHybridCustom,
)
from utils.data_paths import MOT_2D_VALIDATION_DIR
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles, student_mean_interval


DEFAULT_OUTPUT = MOT_2D_VALIDATION_DIR / "hybrid_timestep_screening_v11.json"


def run_screening(args):
    ensembles = load_production_ensembles(
        particles_per_ensemble=args.particles_per_ensemble,
        zeeman_seeds=args.zeeman_seeds,
    )
    mot_seeds = [seed + MOT_SEED_OFFSET for seed in args.zeeman_seeds]
    rows = []

    for dt_s in args.timesteps:
        started = time.time()
        grouped = mot_simulation_paired_ensembles(
            survivor_state_ensembles=[row["states"] for row in ensembles],
            seeds=mot_seeds,
            _2d_mot_config={
                "s0": SELECTED_PARAMETERS["s0"],
                "detuning_gamma": SELECTED_PARAMETERS["detuning_gamma"],
                "swap_polarization": False,
            },
            magnet_radius=SELECTED_PARAMETERS["magnet_radius"],
            npools=args.npools,
            stochastic=True,
            dt=dt_s,
            stochastic_sim_function=RK4StHybridCustom,
        )
        elapsed = time.time() - started
        for ensemble, mot_seed, (_, captured, _) in zip(ensembles, mot_seeds, grouped):
            rows.append(
                {
                    "dt_s": float(dt_s),
                    "dt_us": float(dt_s * 1e6),
                    "zeeman_seed": int(ensemble["zeeman_seed"]),
                    "mot_seed": int(mot_seed),
                    "n_input": int(len(ensemble["states"])),
                    "captured": int(captured),
                    "conditional_efficiency": float(captured / len(ensemble["states"])),
                    "batch_elapsed_seconds": float(elapsed),
                }
            )
        print(
            f"HYBRID_DT_RESULT dt_us={dt_s * 1e6:g} "
            f"captured={[row[1] for row in grouped]} "
            f"elapsed_seconds={elapsed:.1f}"
        )

    finest_dt = min(args.timesteps)
    by_key = {(row["dt_s"], row["zeeman_seed"]): row for row in rows}
    comparisons = []
    for dt_s in sorted(args.timesteps):
        if dt_s == finest_dt:
            continue
        differences = [
            by_key[(dt_s, seed)]["conditional_efficiency"]
            - by_key[(finest_dt, seed)]["conditional_efficiency"]
            for seed in args.zeeman_seeds
        ]
        mean, low, high, half_width = student_mean_interval(differences)
        comparisons.append(
            {
                "dt_s": float(dt_s),
                "reference_dt_s": float(finest_dt),
                "paired_differences_fraction": differences,
                "mean_paired_difference_fraction": mean,
                "paired_95_ci_fraction": [low, high],
                "paired_95_ci_half_width_fraction": half_width,
            }
        )

    payload = {
        "kind": "mot_2d_hybrid_timestep_screening",
        "parameters": SELECTED_PARAMETERS,
        "solver": {
            "name": "RK4StHybridCustom",
            "poisson_below_expected_photons": DEFAULT_POISSON_THRESHOLD,
            "gaussian_at_or_above_expected_photons": DEFAULT_POISSON_THRESHOLD,
        },
        "design": {
            "timesteps_s": args.timesteps,
            "zeeman_seeds": args.zeeman_seeds,
            "mot_seeds": mot_seeds,
            "particles_per_ensemble": args.particles_per_ensemble,
            "npools": args.npools,
        },
        "replicates": rows,
        "paired_comparisons_to_finest_dt": comparisons,
    }
    save_file_json(Path(args.output), payload)
    print(f"Hybrid timestep screening saved to: {args.output}")
    return payload


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timesteps",
        type=float,
        nargs="+",
        default=[2.5e-6, 5e-6, 10e-6],
    )
    parser.add_argument(
        "--zeeman-seeds",
        type=int,
        nargs="+",
        default=[3000, 3001, 3002],
    )
    parser.add_argument("--particles-per-ensemble", type=int, default=2000)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_screening(parse_args())
