"""
mot_seed_scan.py

Estimate the stochastic uncertainty of the 2D-MOT capture efficiency
by repeating the same MOT simulation for different RNG seeds.

The Zeeman-survivor ensemble is kept fixed between all runs.
Only the stochastic MOT realization changes.
"""

import argparse
from pathlib import Path

import numpy as np

from config import MOT_2D_SIM_CONFIG
from mot_2d_simulation import mot_simulation
from utils.data_paths import SEED_SCAN_DIR, production_zeeman_states_file
from utils.file_helpers import save_file_json


# ============================================================
# Fixed production input
# ============================================================

ZEEMAN_SURVIVORS_FILE = production_zeeman_states_file()



# ============================================================
# Command-line arguments
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--s0",
        type=float,
        required=True,
        help="Fixed MOT saturation parameter",
    )

    parser.add_argument(
        "--detuning_gamma",
        type=float,
        required=True,
        help="MOT detuning in units of Gamma",
    )

    parser.add_argument(
        "--magnet_radius",
        type=float,
        required=True,
        help="Magnet radius in meters",
    )

    parser.add_argument(
        "--seed_start",
        type=int,
        default=0,
        help="First RNG seed",
    )

    parser.add_argument(
        "--n_seeds",
        type=int,
        default=10,
        help="Number of different RNG seeds to run",
    )

    parser.add_argument(
        "--npools",
        type=int,
        default=8,
        help="Number of multiprocessing workers",
    )

    parser.add_argument(
        "--output",
        type=str,
        default=str(SEED_SCAN_DIR / "mot_seed_scan.json"),
        help="Output JSON file",
    )

    return parser.parse_args()


# ============================================================
# One seed
# ============================================================

def run_one_seed(
    survivor_states,
    s0,
    detuning_gamma,
    magnet_radius,
    seed,
    npools,
):
    """
    Run the same MOT configuration for one RNG seed.
    """

    n_survivors = len(survivor_states)

    print()
    print("========================================")
    print("MOT SEED TEST")
    print("========================================")
    print(f"seed = {seed}")
    print(f"s0 = {s0}")
    print(f"detuning_gamma = {detuning_gamma}")
    print(f"magnet_radius = {magnet_radius}")
    print(f"N_zeeman_survivors = {n_survivors}")
    print(f"MOT dt = {MOT_2D_SIM_CONFIG['dt_s']:.2e} s")
    print(f"npools = {npools}")
    print("========================================")

    _, success_count, _ = mot_simulation(
        survivor_states=survivor_states,
        _2d_mot_config={
            "s0": s0,
            "detuning_gamma": detuning_gamma,
            "swap_polarization": False,
        },
        magnet_radius=magnet_radius,
        stochastic=True,
        npools=npools,
        dt=MOT_2D_SIM_CONFIG["dt_s"],
        seed=seed,
    )

    capture_efficiency = (
        success_count / n_survivors
    )

    print(
        f"MOT_SEED_RESULT "
        f"seed={seed} "
        f"success_count={success_count} "
        f"capture_efficiency={capture_efficiency:.8f}"
    )

    return {
        "seed": int(seed),
        "success_count": int(success_count),
        "capture_efficiency": float(capture_efficiency),
        "capture_efficiency_percent": float(
            100.0 * capture_efficiency
        ),
    }


# ============================================================
# Seed scan
# ============================================================

def run_seed_scan(
    s0,
    detuning_gamma,
    magnet_radius,
    seed_start,
    n_seeds,
    npools,
    output_file,
):
    """
    Repeat one fixed MOT parameter point for several RNG seeds.
    """

    survivor_states = np.load(
        ZEEMAN_SURVIVORS_FILE
    )

    n_survivors = len(
        survivor_states
    )

    seeds = range(
        seed_start,
        seed_start + n_seeds,
    )

    results = []

    for seed in seeds:

        result = run_one_seed(
            survivor_states=survivor_states,
            s0=s0,
            detuning_gamma=detuning_gamma,
            magnet_radius=magnet_radius,
            seed=seed,
            npools=npools,
        )

        results.append(
            result
        )

        # Save after every seed so partial results survive
        # even if the job reaches walltime.
        efficiencies = np.array(
            [
                r["capture_efficiency"]
                for r in results
            ]
        )

        summary = {
            "configuration": {
                "s0": float(s0),
                "detuning_gamma": float(detuning_gamma),
                "magnet_radius": float(magnet_radius),
                "N_zeeman_survivors": int(n_survivors),
                "mot_dt_s": float(
                    MOT_2D_SIM_CONFIG["dt_s"]
                ),
            },

            "results": results,

            "statistics": {
                "n_completed_seeds": len(results),
                "mean_capture_efficiency": float(
                    np.mean(efficiencies)
                ),
                "mean_capture_efficiency_percent": float(
                    100.0 * np.mean(efficiencies)
                ),
                "std_capture_efficiency": float(
                    np.std(
                        efficiencies,
                        ddof=1,
                    )
                )
                if len(results) > 1
                else None,
                "std_capture_efficiency_percent": float(
                    100.0
                    * np.std(
                        efficiencies,
                        ddof=1,
                    )
                )
                if len(results) > 1
                else None,
                "sem_capture_efficiency": float(
                    np.std(
                        efficiencies,
                        ddof=1,
                    )
                    / np.sqrt(len(results))
                )
                if len(results) > 1
                else None,
                "sem_capture_efficiency_percent": float(
                    100.0
                    * np.std(
                        efficiencies,
                        ddof=1,
                    )
                    / np.sqrt(len(results))
                )
                if len(results) > 1
                else None,
            },
        }

        save_file_json(
            output_file,
            summary,
        )

    # ========================================================
    # Final summary
    # ========================================================

    efficiencies_percent = np.array(
        [
            r["capture_efficiency_percent"]
            for r in results
        ]
    )

    print()
    print("========================================")
    print("MOT SEED SCAN FINISHED")
    print("========================================")

    print(
        f"N seeds = {len(results)}"
    )

    print(
        f"Mean capture efficiency = "
        f"{np.mean(efficiencies_percent):.4f}%"
    )

    if len(results) > 1:

        std = np.std(
            efficiencies_percent,
            ddof=1,
        )

        sem = (
            std / np.sqrt(len(results))
        )

        print(
            f"Standard deviation = "
            f"{std:.4f}%"
        )

        print(
            f"SEM = "
            f"{sem:.4f}%"
        )

    print(
        f"Results saved to: "
        f"{output_file}"
    )


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    args = parse_args()

    output_path = Path(
        args.output
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_seed_scan(
        s0=args.s0,
        detuning_gamma=args.detuning_gamma,
        magnet_radius=args.magnet_radius,
        seed_start=args.seed_start,
        n_seeds=args.n_seeds,
        npools=args.npools,
        output_file=output_path,
    )
