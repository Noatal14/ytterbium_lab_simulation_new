"""Run the 2D-MOT Optuna optimization workflow for fixed Zeeman-survivor inputs.

This script is the main parameter-search workflow for the 2D MOT stage using a
precomputed Zeeman-survivor ensemble. It is intentionally a thin production
wrapper around the simulation helpers and keeps the underlying physics and
numerical algorithms unchanged.
"""

import argparse
from pathlib import Path

import numpy as np
import optuna

from config import (
    DEFAULT_NUM_POOLS,
    COLLIMATION_ANGLE_DEG,
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


def build_study_name(s0_range, detuning_gamma_range, magnet_radius_range):
    """Build a study name from actual runtime values instead of fragile literals."""
    return (
        "mot_opt_"
        f"N{ZEEMAN_SURVIVORS_INITIAL_NUM_PARTICLES}_"
        f"zeeman_dt{ZEEMAN_SIM_CONFIG['dt_s'] * 1e6:.0f}us_"
        f"mot_dt{MOT_DT * 1e6:.0f}us_"
        f"s0max{max(s0_range):.3f}_"
        f"angle{COLLIMATION_ANGLE_DEG}"
    )


# ============================================================
# Command-line arguments
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser()

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
    Zeeman-survivor ensemble.

    Parameters
    ----------
    s0 : float
        MOT saturation parameter.

    detuning_gamma : float
        MOT detuning in units of Gamma.

    magnet_radius : float
        Effective magnet radius in meters.

    npools : int
        Number of multiprocessing workers.

    Returns
    -------
    success_count : int
        Number of Zeeman-surviving atoms successfully captured by the MOT.
    """

    survivors = np.load(ZEEMAN_SURVIVORS_FILE)

    n_survivors = len(survivors)

    print()
    print("========================================")
    print("2D MOT OPTIMIZATION TRIAL")
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
        f"MOT given Zeeman efficiency = "
        f"{mot_given_zeeman_efficiency:.8f}"
    )
    print(
        f"Total efficiency = "
        f"{total_efficiency:.8f}"
    )

    # Save a human-readable record in addition to the Optuna database.
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
        save_path / "mot_optimization_summary.json",
        key,
        data_to_push,
    )

    return success_count


# ============================================================
# Optuna optimization
# ============================================================

def optimize_mot(
    s0_range,
    detuning_gamma_range,
    magnet_radius_range,
    n_trials=50,
    npools=DEFAULT_NUM_POOLS,
):
    """
    Optimize the 2D-MOT parameters using Optuna.
    """

    def objective(trial):
        s0 = trial.suggest_float(
            "s0",
            s0_range[0],
            s0_range[1],
        )

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
            s0=s0,
            detuning_gamma=detuning_gamma,
            magnet_radius=magnet_radius,
            npools=npools,
        )

        print(
            f"OPTUNA_RESULT "
            f"trial={trial.number} "
            f"s0={s0:.8f} "
            f"detuning_gamma={detuning_gamma:.8f} "
            f"magnet_radius={magnet_radius:.8f} "
            f"success_count={success_count}"
        )

        return success_count

    study_name = build_study_name(
        s0_range=s0_range,
        detuning_gamma_range=detuning_gamma_range,
        magnet_radius_range=magnet_radius_range,
    )

    sampler = optuna.samplers.TPESampler(
        seed=DEFAULT_RANDOM_SEED,
    )

    OPTIMIZATION_DIR.mkdir(parents=True, exist_ok=True)
    study = optuna.create_study(
        study_name=study_name,
        storage=f"sqlite:///{OPTIMIZATION_DIR}/mot_optimization_s0max1p5.db",
        direction="maximize",
        sampler=sampler,
        load_if_exists=True,
    )

    study.optimize(
        objective,
        n_trials=n_trials,
    )

    print()
    print("==============================")
    print("MOT optimization finished")
    print("==============================")

    print(
        f"Best success count: "
        f"{study.best_value}"
    )

    print()
    print("Best parameters:")
    print(
        f"s0             = "
        f"{study.best_params['s0']}"
    )
    print(
        f"detuning_gamma = "
        f"{study.best_params['detuning_gamma']}"
    )
    print(
        f"magnet_radius  = "
        f"{study.best_params['magnet_radius']}"
    )

    return study


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    args = parse_args()

    # Search ranges
    BOUNDS_S0 = (
        0.8,
        1.5,
    )

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
    print("2D MOT OPTIMIZATION")
    print("========================================")
    print(
        f"Zeeman survivor file = "
        f"{ZEEMAN_SURVIVORS_FILE}"
    )
    print(
        f"N_zeeman_survivors = "
        f"{len(survivors)}"
    )
    print(
        f"MOT dt = "
        f"{MOT_DT:.2e} s"
    )
    print(
        f"n_trials = "
        f"{args.n_trials}"
    )
    print(
        f"npools = "
        f"{args.npools}"
    )
    print("========================================")

    study = optimize_mot(
        s0_range=BOUNDS_S0,
        detuning_gamma_range=BOUNDS_DETUNING,
        magnet_radius_range=BOUNDS_MAGNET_RADIUS,
        n_trials=args.n_trials,
        npools=args.npools,
    )
