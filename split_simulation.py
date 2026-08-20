"""Compatibility entry point for the stage-based simulation workflow.

New runs should normally use ``zeeman_simulation.py``,
``mot_2d_simulation.py``, and ``mot_3d_simulation.py`` directly. This module
keeps the former combined commands and imports working for existing Zeus jobs.
"""

import argparse

from config import (
    COLLIMATION_ANGLE_DEG,
    DEFAULT_NUM_PARTICLES,
    DEFAULT_NUM_POOLS,
    MOT_2D_SIM_CONFIG,
    ZEEMAN_SIM_CONFIG,
)
from mot_2d_simulation import mot_simulation
from mot_3d_simulation import mot_3d_simulation
from utils.data_paths import DEFAULT_ZEEMAN_STATES_FILE, load_particle_states
from zeeman_simulation import run_and_save_zeeman, zeeman_simulation


def run_both(
    N=500,
    collimation_angle_deg=COLLIMATION_ANGLE_DEG,
    npools=DEFAULT_NUM_POOLS,
    stochastic=True,
    zeeman_dt=ZEEMAN_SIM_CONFIG["dt_s"],
    mot_dt=MOT_2D_SIM_CONFIG["dt_s"],
):
    """Run Zeeman followed immediately by 2D MOT (legacy convenience mode)."""
    _, survivors, _ = zeeman_simulation(
        N_particles=N,
        collimation_angle_deg=collimation_angle_deg,
        npools=npools,
        stochastic=stochastic,
        dt=zeeman_dt,
    )
    if len(survivors) == 0:
        print("No Zeeman survivors; 2D-MOT stage skipped.")
        return
    _, success_count, _ = mot_simulation(
        survivors,
        npools=npools,
        stochastic=stochastic,
        dt=mot_dt,
    )
    efficiency = success_count / len(survivors)
    print(
        "RESULT "
        f"cutoff_angle_deg={collimation_angle_deg} "
        f"N_initial={N} "
        f"N_zeeman_survivors={len(survivors)} "
        f"N_mot_success={success_count} "
        f"mot_given_zeeman_efficiency={efficiency:.8f}"
    )


def generate_and_save_zeeman_survivors(
    save_file,
    N,
    collimation_angle_deg,
    npools,
    stochastic=True,
    zeeman_dt=ZEEMAN_SIM_CONFIG["dt_s"],
):
    """Legacy wrapper around the standalone Zeeman stage."""
    return run_and_save_zeeman(
        save_file,
        N_particles=N,
        collimation_angle_deg=collimation_angle_deg,
        npools=npools,
        stochastic=stochastic,
        dt=zeeman_dt,
    )


def run_mot_from_saved_survivors(
    survivors_file,
    mot_dt,
    npools=DEFAULT_NUM_POOLS,
    stochastic=True,
    max_survivors=None,
):
    """Legacy wrapper for running 2D MOT from a saved state ensemble."""
    survivor_states = load_particle_states(survivors_file)
    if max_survivors is not None:
        survivor_states = survivor_states[:max_survivors]
    if len(survivor_states) == 0:
        print("No Zeeman survivors; 2D-MOT stage skipped.")
        return
    _, success_count, _ = mot_simulation(
        survivor_states,
        npools=npools,
        stochastic=stochastic,
        dt=mot_dt,
    )
    efficiency = success_count / len(survivor_states)
    print(
        "MOT_DT_RESULT "
        f"dt={mot_dt:.8e} "
        f"N_zeeman_survivors={len(survivor_states)} "
        f"N_mot_success={success_count} "
        f"mot_given_zeeman_efficiency={efficiency:.8f}"
    )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["both", "generate_zeeman_survivors", "mot_from_survivors"],
        default="both",
    )
    parser.add_argument("--n_atoms", type=int, default=DEFAULT_NUM_PARTICLES)
    parser.add_argument("--cutoff_angle_deg", type=float, default=COLLIMATION_ANGLE_DEG)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--stochastic", type=int, choices=[0, 1], default=1)
    parser.add_argument("--dt", type=float, default=ZEEMAN_SIM_CONFIG["dt_s"])
    parser.add_argument(
        "--mot_dt_us", type=float, default=MOT_2D_SIM_CONFIG["dt_s"] * 1e6
    )
    parser.add_argument("--survivors_file", default=str(DEFAULT_ZEEMAN_STATES_FILE))
    parser.add_argument("--max_survivors", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    common = {
        "npools": args.npools,
        "stochastic": bool(args.stochastic),
    }
    if args.mode == "both":
        run_both(
            N=args.n_atoms,
            collimation_angle_deg=args.cutoff_angle_deg,
            zeeman_dt=args.dt,
            mot_dt=args.mot_dt_us * 1e-6,
            **common,
        )
    elif args.mode == "generate_zeeman_survivors":
        generate_and_save_zeeman_survivors(
            save_file=args.survivors_file,
            N=args.n_atoms,
            collimation_angle_deg=args.cutoff_angle_deg,
            zeeman_dt=args.dt,
            **common,
        )
    else:
        run_mot_from_saved_survivors(
            survivors_file=args.survivors_file,
            mot_dt=args.mot_dt_us * 1e-6,
            max_survivors=args.max_survivors,
            **common,
        )
