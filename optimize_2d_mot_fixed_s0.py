"""Run a fixed-s0 Optuna scan for the 2D MOT using a stored Zeeman-survivor ensemble.

This is a companion workflow to optimize_2d_mot.py and keeps the same physical
setup and solver behavior; it only fixes the saturation parameter s0 for a
narrower search over detuning and magnet radius.
"""

import argparse
from pathlib import Path

import numpy as np
import optuna

from config import (
    COLLIMATION_ANGLE_DEG,
    DEFAULT_NUM_POOLS,
    DEFAULT_RANDOM_SEED,
    MOT_2D_SIM_CONFIG,
    ZEEMAN_SIM_CONFIG,
)

from utils.file_helpers import update_json_file
from mot_2d_simulation import mot_simulation
from utils.data_paths import OPTIMIZATION_DIR, production_zeeman_states_file


# ============================================================
# Fixed production inputs
# ============================================================

ZEEMAN_SURVIVORS_FILE = production_zeeman_states_file()
# This total-efficiency denominator must match the initial ensemble used to
# generate ZEEMAN_SURVIVORS_FILE.
ZEEMAN_SURVIVORS_INITIAL_NUM_PARTICLES = 50_000

MOT_DT = MOT_2D_SIM_CONFIG["dt_s"]  # seconds


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
        "--npools",
        type=int,
        default=DEFAULT_NUM_POOLS,
        help="Number of worker processes used for each MOT simulation",
    )

    parser.add_argument(
        "--n_trials",
        type=int,
        default=50,
        help="Number of Optuna trials",
    )

    return parser.parse_args()


# ============================================================
# Run one MOT parameter point
# ============================================================

def run_mot(
    s0,
    detuning_gamma,
    magnet_radius,
    npools=DEFAULT_NUM_POOLS,
):
    """
    Run one stochastic 2D-MOT simulation using the fixed production
    Zeeman-survivor ensemble and a fixed value of s0.
    """

    survivors = np.load(ZEEMAN_SURVIVORS_FILE)
    n_survivors = len(survivors)

    print()
    print("========================================")
    print("2D MOT FIXED-s0 OPTIMIZATION TRIAL")
    print("========================================")
    print(f"s0 = {s0}")
    print(f"detuning_gamma = {detuning_gamma}")
    print(f"magnet_radius = {magnet_radius}")
    print(f"N_zeeman_survivors = {n_survivors}")
    print(f"MOT dt = {MOT_DT:.2e} s")
    print(f"npools = {npools}")
    print("========================================")

    _, success_count, _ = mot_simulation(
        survivor_states=survivors,
        _2d_mot_config={
            "s0": s0,
            "detuning_gamma": detuning_gamma,
            "swap_polarization": False,
        },
        magnet_radius=magnet_radius,
        stochastic=True,
        npools=npools,
        dt=MOT_DT,
    )

    mot_given_zeeman_efficiency = (
        success_count / n_survivors
        if n_survivors > 0
        else np.nan
    )

    total_efficiency = (
        success_count / ZEEMAN_SURVIVORS_INITIAL_NUM_PARTICLES
    )

    print()
    print(f"Success count = {success_count}")
    print(
        "MOT given Zeeman efficiency = "
        f"{mot_given_zeeman_efficiency:.8f}"
    )
    print(
        "Total efficiency = "
        f"{total_efficiency:.8f}"
    )

    data_to_push = {
        "s0": float(s0),
        "detuning_gamma": float(detuning_gamma),
        "magnet_radius": float(magnet_radius),
        "success_count": int(success_count),
        "mot_given_zeeman_efficiency": float(
            mot_given_zeeman_efficiency
        ),
        "total_efficiency": float(total_efficiency),
    }

    save_path = OPTIMIZATION_DIR
    save_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    key = (
        f"s0_{s0:.8f}_"
        f"detuning_gamma_{detuning_gamma:.8f}_"
        f"magnet_radius_{magnet_radius:.8f}"
    )

    update_json_file(
        save_path / f"mot_optimization_fixed_s0_{s0:.6f}_summary.json",
        key,
        data_to_push,
    )

    return success_count


# ============================================================
# Optuna optimization
# ============================================================

def optimize_mot_fixed_s0(
    fixed_s0,
    detuning_gamma_range,
    magnet_radius_range,
    n_trials=50,
    npools=DEFAULT_NUM_POOLS,
):
    """
    Optimize detuning and magnet radius for a fixed s0.
    """

    def objective(trial):
        detuning_gamma = trial.suggest_float(
            "detuning_gamma",
            detuning_gamma_range[0],
            detuning_gamma_range[1],
        )

        magnet_radius = trial.suggest_float(
            "magnet_radius",
            magnet_radius_range[0],
            magnet_radius_range[1],
        )

        success_count = run_mot(
            s0=fixed_s0,
            detuning_gamma=detuning_gamma,
            magnet_radius=magnet_radius,
            npools=npools,
        )

        print(
            f"OPTUNA_FIXED_S0_RESULT "
            f"trial={trial.number} "
            f"s0={fixed_s0:.8f} "
            f"detuning_gamma={detuning_gamma:.8f} "
            f"magnet_radius={magnet_radius:.8f} "
            f"success_count={success_count}"
        )

        return success_count

    # Use a stable textual representation of s0 in the study name.
    s0_tag = f"{fixed_s0:.6f}".replace(".", "p")

    study_name = (
        "mot_opt_fixed_s0_"
        f"s0_{s0_tag}_"
        f"N{ZEEMAN_SURVIVORS_INITIAL_NUM_PARTICLES}_"
        f"zeeman_dt{ZEEMAN_SIM_CONFIG['dt_s'] * 1e6:.0f}us_"
        f"mot_dt{MOT_DT * 1e6:.0f}us_"
        f"angle{COLLIMATION_ANGLE_DEG}"
    )

    sampler = optuna.samplers.TPESampler(
        seed=DEFAULT_RANDOM_SEED,
    )

    OPTIMIZATION_DIR.mkdir(parents=True, exist_ok=True)
    study = optuna.create_study(
        study_name=study_name,
        storage=(
            f"sqlite:///{OPTIMIZATION_DIR}/"
            f"mot_optimization_fixed_s0_{s0_tag}.db"
        ),
        direction="maximize",
        sampler=sampler,
        load_if_exists=True,
    )

    study.optimize(
        objective,
        n_trials=n_trials,
    )

    print()
    print("========================================")
    print("FIXED-s0 MOT OPTIMIZATION FINISHED")
    print("========================================")

    print(f"Fixed s0 = {fixed_s0}")
    print(f"Best success count = {study.best_value}")

    print()
    print("Best parameters:")
    print(
        "detuning_gamma = "
        f"{study.best_params['detuning_gamma']}"
    )
    print(
        "magnet_radius  = "
        f"{study.best_params['magnet_radius']}"
    )

    return study


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    args = parse_args()

    # Search ranges
    BOUNDS_DETUNING = (
        -2.0,
        -0.6,
    )

    BOUNDS_MAGNET_RADIUS = (
        0.045,
        0.054,
    )

    # Sanity check before starting an expensive optimization.
    if not Path(ZEEMAN_SURVIVORS_FILE).exists():
        raise FileNotFoundError(
            f"Fixed Zeeman survivor file not found: "
            f"{ZEEMAN_SURVIVORS_FILE}"
        )

    survivors = np.load(
        ZEEMAN_SURVIVORS_FILE,
        mmap_mode="r",
    )

    print("========================================")
    print("2D MOT FIXED-s0 OPTIMIZATION")
    print("========================================")
    print(
        "Zeeman survivor file = "
        f"{ZEEMAN_SURVIVORS_FILE}"
    )
    print(
        "N_zeeman_survivors = "
        f"{len(survivors)}"
    )
    print(
        "fixed s0 = "
        f"{args.s0}"
    )
    print(
        "MOT dt = "
        f"{MOT_DT:.2e} s"
    )
    print(
        "n_trials = "
        f"{args.n_trials}"
    )
    print(
        "npools = "
        f"{args.npools}"
    )
    print("========================================")

    study = optimize_mot_fixed_s0(
        fixed_s0=args.s0,
        detuning_gamma_range=BOUNDS_DETUNING,
        magnet_radius_range=BOUNDS_MAGNET_RADIUS,
        n_trials=args.n_trials,
        npools=args.npools,
    )
