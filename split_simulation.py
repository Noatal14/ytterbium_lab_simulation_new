import argparse
from pathlib import Path

import numpy as np

from utils.ScipyIVP_3DCustom import ScipyIVP_3DCustom
from utils.RK4StCustom import RK4StCustom

from lab_setup.config_builder import build_base_config
from lab_setup.zones import (
    get_entire_apparatus_zone,
    get_zeeman_only_zone,
)

from thermal_beam import generate_thermal_beam_state

from utils.simulation_helpers import (
    run_multiple_atoms_simulation,
    generate_timepoints,
    zeeman_extract_survivors,
    mot_extract_survivors,
)

from config import (
    Geometry,
    ZEEMAN_BEAM_DIR,
    N_particles,
    zeeman_sim_config,
    _2d_mot_sim_config,
    _3d_mot_sim_config,
    mot_3d_laser_config,
    collimation_angle_deg,
    zeeman_laser_config,
    _2d_mot_laser_config,
    _2d_mot_magnet_radius,
    zeeman_field_config,
)


# ============================================================
# Command-line arguments
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=[
            "both",
            "generate_zeeman_survivors",
            "mot_from_survivors",
        ],
        default="both",
        help=(
            "Simulation mode: "
            "'both' runs Zeeman + MOT, "
            "'generate_zeeman_survivors' runs Zeeman and saves survivors, "
            "'mot_from_survivors' loads saved survivors and runs the MOT."
        ),
    )

    parser.add_argument(
        "--n_atoms",
        type=int,
        default=N_particles,
        help="Number of initial atoms to simulate",
    )

    parser.add_argument(
        "--cutoff_angle_deg",
        type=float,
        default=collimation_angle_deg,
        help="Cutoff angle for the thermal beam in degrees",
    )

    parser.add_argument(
        "--npools",
        type=int,
        default=8,
        help="Number of worker processes",
    )

    parser.add_argument(
        "--stochastic",
        type=int,
        choices=[0, 1],
        default=1,
        help="1 for stochastic simulation, 0 for deterministic simulation",
    )

    parser.add_argument(
        "--chunksize",
        type=int,
        default=1,
        help="Chunk size used by multiprocessing Pool",
    )

    parser.add_argument(
        "--dt",
        type=float,
        default=zeeman_sim_config["dt"],
        help="Zeeman timestep in seconds",
    )

    parser.add_argument(
        "--mot_dt_us",
        type=float,
        default=8.0,
        help="2D MOT timestep in microseconds",
    )

    parser.add_argument(
        "--survivors_file",
        type=str,
        default="data/mot_dt_scan_zeeman_survivors.npy",
        help="File used to save/load fixed Zeeman survivor states",
    )

    parser.add_argument(
        "--max_survivors",
        type=int,
        default=None,
        help=(
            "Maximum number of saved Zeeman survivors to use in the MOT. "
            "Useful for benchmarks. If omitted, all survivors are used."
        ),
    )

    return parser.parse_args()


# ============================================================
# Zeeman slower simulation
# ============================================================

def zeeman_simulation(
    N_particles=1000,
    _2d_mot_config=_2d_mot_laser_config,
    zeeman_config=zeeman_laser_config,
    zeeman_field_config=zeeman_field_config,
    magnet_radius=_2d_mot_magnet_radius,
    gravity_enabled=True,
    npools=8,
    stochastic=True,
    dt=zeeman_sim_config["dt"],
    collimation_angle_deg=collimation_angle_deg,
    chunksize=1,
):
    atom, config = build_base_config(
        atom_species="Yb171",
        gravity_enabled=gravity_enabled,

        include_2d_mot=True,
        include_3dmot=False,
        include_zeeman=True,

        magnet_radius=magnet_radius,
        zeeman_field_config=zeeman_field_config,

        _2d_mot_config=_2d_mot_config,
        zeeman_config=zeeman_config,

        zones=get_zeeman_only_zone(
            cutoff_distance=zeeman_sim_config["cutoff_distance"]
        ),
    )

    r0_arr, v0_arr, _ = generate_thermal_beam_state(
        N=N_particles,
        collimation_angle_deg=collimation_angle_deg,
        m=atom.mass,
        distance_m=zeeman_sim_config["start_distance"],
        seed=42,
    )

    time_points, _ = generate_timepoints(
        zeeman_sim_config["t_max"],
        dt,
    )

    u0_list = [
        np.concatenate((r0, v0))
        for r0, v0 in zip(r0_arr, v0_arr)
    ]

    sim_func = RK4StCustom if stochastic else ScipyIVP_3DCustom

    res, _ = run_multiple_atoms_simulation(
        config=config,
        u0=u0_list,
        time_points=time_points,
        sim_function=sim_func,
        npools=npools,
        seed_idx=42,
        chunksize=chunksize,
    )

    survivor_states, survivor_indices = zeeman_extract_survivors(
        res,
        zeeman_sim_config["cutoff_distance"],
    )

    return res, survivor_states, survivor_indices


# ============================================================
# 2D MOT simulation
# ============================================================

def mot_simulation(
    survivor_states,
    _2d_mot_config=_2d_mot_laser_config,
    zeeman_config=zeeman_laser_config,
    zeeman_field_config=zeeman_field_config,
    magnet_radius=_2d_mot_magnet_radius,
    gravity_enabled=True,
    npools=8,
    stochastic=True,
    dt=_2d_mot_sim_config["dt"],
    chunksize=1,
):
    N = len(survivor_states)

    if N == 0:
        return [], 0, np.empty((0, 6))

    _, config = build_base_config(
        atom_species="Yb171",
        gravity_enabled=gravity_enabled,

        include_zeeman=True,
        include_2d_mot=True,
        include_3dmot=False,

        magnet_radius=magnet_radius,
        zeeman_field_config=zeeman_field_config,

        _2d_mot_config=_2d_mot_config,
        zeeman_config=zeeman_config,

        zones=get_entire_apparatus_zone(),
    )

    # Initial conditions are the fixed states that survived
    # the Zeeman slower.
    u0_list = [
        np.asarray(state).copy()
        for state in survivor_states
    ]

    time_points, _ = generate_timepoints(
        _2d_mot_sim_config["t_max"],
        dt,
    )

    sim_func = RK4StCustom if stochastic else ScipyIVP_3DCustom

    res, _ = run_multiple_atoms_simulation(
        config=config,
        u0=u0_list,
        time_points=time_points,
        sim_function=sim_func,
        npools=npools,
        seed_idx=42,
        chunksize=chunksize,
    )

    mot_survivor_states, count, _ = mot_extract_survivors(res)

    return res, count, mot_survivor_states


# ============================================================
# 3D MOT simulation
# ============================================================

def mot_3d_simulation(
    survivor_states,
    _3d_mot_config=mot_3d_laser_config,
    gravity_enabled=True,
    npools=8,
    dt=_3d_mot_sim_config["dt"],
    chunksize=1,
):
    N = len(survivor_states)

    if N == 0:
        return [], np.empty((0, 6))

    _, config = build_base_config(
        atom_species="Yb171",

        include_zeeman=True,
        include_2d_mot=True,
        include_3dmot=False,

        gravity_enabled=gravity_enabled,
        magnet_radius=_2d_mot_magnet_radius,

        _2d_mot_config=_2d_mot_laser_config,
        zeeman_config=zeeman_laser_config,

        zones=get_entire_apparatus_zone(),
        _3d_mot_config=_3d_mot_config,
    )

    u0_list = [
        np.asarray(state).copy()
        for state in survivor_states
    ]

    time_points, _ = generate_timepoints(
        _3d_mot_sim_config["t_max"],
        dt,
    )

    res, _ = run_multiple_atoms_simulation(
        config=config,
        u0=u0_list,
        time_points=time_points,
        sim_function=ScipyIVP_3DCustom,
        npools=npools,
        seed_idx=42,
        chunksize=chunksize,
    )

    final_states = (
        np.array([traj.y[:, -1].copy() for traj in res])
        if len(res) > 0
        else np.empty((0, 6))
    )

    return res, final_states


# ============================================================
# Standard full Zeeman + 2D MOT run
# ============================================================

def run_both(
    N=500,
    collimation_angle_deg=collimation_angle_deg,
    npools=8,
    stochastic=True,
    dt=zeeman_sim_config["dt"],
    chunksize=1,
):
    print("Running Zeeman phase simulation...")
    print(f"npools = {npools}")
    print(f"chunksize = {chunksize}")

    _, survivors, _ = zeeman_simulation(
        N_particles=N,
        _2d_mot_config=_2d_mot_laser_config,
        zeeman_config=zeeman_laser_config,
        zeeman_field_config=zeeman_field_config,
        magnet_radius=_2d_mot_magnet_radius,
        stochastic=stochastic,
        collimation_angle_deg=collimation_angle_deg,
        npools=npools,
        dt=dt,
        chunksize=chunksize,
    )

    print("Zeeman phase simulation ended")
    print("Zeeman survivors:", len(survivors))

    if len(survivors) == 0:
        print("No survivors — nothing to do in Phase 2.")
        return

    _, success_count, _ = mot_simulation(
        survivor_states=survivors,
        _2d_mot_config=_2d_mot_laser_config,
        magnet_radius=_2d_mot_magnet_radius,
        stochastic=stochastic,
        npools=npools,
        chunksize=chunksize,
    )

    print(f"Success count: {success_count}")

    n_survivors = len(survivors)

    efficiency = (
        success_count / n_survivors
        if n_survivors > 0
        else np.nan
    )

    print(
        f"RESULT "
        f"cutoff_angle_deg={collimation_angle_deg} "
        f"N_initial={N} "
        f"N_zeeman_survivors={n_survivors} "
        f"N_mot_success={success_count} "
        f"mot_given_zeeman_efficiency={efficiency:.8f} "
        f"chunksize={chunksize}"
    )


# ============================================================
# Generate fixed Zeeman ensemble for MOT timestep scan
# ============================================================

def generate_and_save_zeeman_survivors(
    save_file,
    N,
    collimation_angle_deg,
    npools,
    stochastic=True,
    zeeman_dt=4e-5,
    chunksize=1,
):
    print("========================================")
    print("GENERATING FIXED ZEEMAN SURVIVOR ENSEMBLE")
    print("========================================")

    print(f"N_initial = {N}")
    print(f"Zeeman dt = {zeeman_dt:.2e} s")
    print(f"cutoff angle = {collimation_angle_deg} deg")
    print(f"stochastic = {int(stochastic)}")
    print(f"npools = {npools}")
    print(f"chunksize = {chunksize}")

    _, survivors, _ = zeeman_simulation(
        N_particles=N,
        _2d_mot_config=_2d_mot_laser_config,
        zeeman_config=zeeman_laser_config,
        zeeman_field_config=zeeman_field_config,
        magnet_radius=_2d_mot_magnet_radius,
        stochastic=stochastic,
        collimation_angle_deg=collimation_angle_deg,
        npools=npools,
        dt=zeeman_dt,
        chunksize=chunksize,
    )

    survivors = np.asarray(survivors)

    save_path = Path(save_file)
    save_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    np.save(save_path, survivors)

    print()
    print("Zeeman phase simulation ended")
    print(f"Zeeman survivors = {len(survivors)}")
    print(f"Saved survivor states to: {save_path}")

    print(
        f"ZEEMAN_SURVIVORS_RESULT "
        f"N_initial={N} "
        f"N_zeeman_survivors={len(survivors)} "
        f"zeeman_dt={zeeman_dt:.8e} "
        f"cutoff_angle_deg={collimation_angle_deg} "
        f"chunksize={chunksize}"
    )

    return survivors


# ============================================================
# Run one MOT timestep using saved Zeeman survivors
# ============================================================

def run_mot_from_saved_survivors(
    survivors_file,
    mot_dt,
    npools=8,
    stochastic=True,
    chunksize=1,
    max_survivors=None,
):
    survivor_states = np.load(survivors_file)

    # For benchmarking we want to run exactly the same subset of
    # Zeeman survivors for every chunksize.
    if max_survivors is not None:
        survivor_states = survivor_states[:max_survivors]

    n_survivors = len(survivor_states)

    print("========================================")
    print("2D MOT TIMESTEP TEST")
    print("========================================")

    print(f"Survivors file = {survivors_file}")
    print(f"N_zeeman_survivors = {n_survivors}")
    print(f"MOT dt = {mot_dt:.8e} s")
    print(f"stochastic = {int(stochastic)}")
    print(f"npools = {npools}")
    print(f"chunksize = {chunksize}")
    print(f"max_survivors = {max_survivors}")

    if n_survivors == 0:
        print("No Zeeman survivors — MOT simulation skipped.")
        return

    _, success_count, _ = mot_simulation(
        survivor_states=survivor_states,
        _2d_mot_config=_2d_mot_laser_config,
        zeeman_config=zeeman_laser_config,
        zeeman_field_config=zeeman_field_config,
        magnet_radius=_2d_mot_magnet_radius,
        stochastic=stochastic,
        npools=npools,
        dt=mot_dt,
        chunksize=chunksize,
    )

    efficiency = success_count / n_survivors

    print()
    print(f"Success count = {success_count}")

    print(
        f"MOT_DT_RESULT "
        f"dt={mot_dt:.8e} "
        f"N_zeeman_survivors={n_survivors} "
        f"N_mot_success={success_count} "
        f"mot_given_zeeman_efficiency={efficiency:.8f} "
        f"chunksize={chunksize}"
    )


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    args = parse_args()

    n_atoms = args.n_atoms
    cutoff_angle = args.cutoff_angle_deg
    npools = args.npools
    stochastic = bool(args.stochastic)
    zeeman_dt = args.dt
    chunksize = args.chunksize
    mot_dt = args.mot_dt_us * 1e-6
    max_survivors = args.max_survivors

    if args.mode == "both":
        run_both(
            N=n_atoms,
            collimation_angle_deg=cutoff_angle,
            npools=npools,
            stochastic=stochastic,
            dt=zeeman_dt,
            chunksize=chunksize,
        )

    elif args.mode == "generate_zeeman_survivors":
        generate_and_save_zeeman_survivors(
            save_file=args.survivors_file,
            N=n_atoms,
            collimation_angle_deg=cutoff_angle,
            npools=npools,
            stochastic=stochastic,
            zeeman_dt=zeeman_dt,
            chunksize=chunksize,
        )

    elif args.mode == "mot_from_survivors":
        run_mot_from_saved_survivors(
            survivors_file=args.survivors_file,
            mot_dt=mot_dt,
            npools=npools,
            stochastic=stochastic,
            chunksize=chunksize,
            max_survivors=max_survivors,
        )