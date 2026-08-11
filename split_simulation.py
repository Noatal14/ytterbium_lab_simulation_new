import argparse

import numpy as np
from atomsmltr.simulation.simulator import ScipyIVP_3D
from dt_comparison.RK4StCustomDt import RK4StCustomDt
from lab_setup.config_builder import build_base_config, build_3dmot_config
from lab_setup.zones import get_entire_apparatus_zone, get_zeeman_only_zone, get_science_region_zone
from thermal_beam import generate_thermal_beam_state
from utils.simulation_helpers import run_multiple_atoms_simulation, generate_timepoints, zeeman_extract_survivors, _2d_mot_success_count, mot_extract_survivors, extract_trajectory_data
from config import zeeman_configs, zeeman_sim_config, _2d_mot_sim_config, _3d_mot_sim_config, mot_3d_laser_config, collimation_angle_deg
from pathlib import Path
from datetime import datetime
from utils.file_helpers import save_file_json
from dt_comparison.main import get_optimal_dt_2d_mot, get_optimal_dt_zeeman

# Note: If r0_arr is generated at distance=0.378 instead of 0.314, atoms would start *outside* the slower and enter it. This is physically fine.

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--n_atoms",
        type=int,
        default=1000,
        help="Number of atoms to simulate",
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

    return parser.parse_args()

def zeeman_simulation(
        N_particles=1000,
        _2d_mot_config={ "s0": 1.4, "detuning_gamma": -1.47 },
        zeeman_config={ "s0": 3.0, "detuning_gamma": -13.75 },
        zeeman_field_config={ "radii": None, "positions": None, "tilt_angles": None },
        magnet_radius=0.053,
        gravity_enabled=True,
        T_C=400.0,
        seed=42,
        npools=8,
        stochastic=True,
        dt=zeeman_sim_config["dt"],
        collimation_angle_deg=collimation_angle_deg,
    ):

    mot_config = dict(_2d_mot_config)
    mot_config.setdefault("swap_polarization", False)

    atom, config = build_base_config(
        atom_species="Yb171",
        gravity_enabled=gravity_enabled,
        include_zeeman_field=True,
        include_zeeman_laser=True,
        include_2d_mot_lasers=True,
        include_3dmot_lasers=False,
        magnet_radius=magnet_radius,
        _2d_mot_config=mot_config,
        zeeman_config= zeeman_config,
        zeeman_field_config=zeeman_field_config,
        include_2dmot_field=True,
        zones=get_zeeman_only_zone()
    )

    r0_arr, v0_arr, _ = generate_thermal_beam_state(
        N=N_particles,
        T_C=T_C,
        collimation_angle_deg=collimation_angle_deg,
        m=atom.mass,
        distance_m=zeeman_sim_config["start_distance"],
        seed=seed
    )

    dt_zeeman = get_optimal_dt_zeeman(
        s0=zeeman_config["s0"],
        detuning_gamma=zeeman_config["detuning_gamma"],
    )

    time_points, _ = generate_timepoints(zeeman_sim_config["t_max"], dt)

    u0_list = [np.concatenate((r0, v0)) for r0, v0 in zip(r0_arr, v0_arr)]

    sim_func = RK4StCustomDt if stochastic else ScipyIVP_3D

    res, sim =run_multiple_atoms_simulation(
        config=config,
        u0=u0_list,
        time_points=time_points,
        sim_function=sim_func,
        npools=npools,
        seed_idx=seed
    )

    survivor_states, survivor_indices = zeeman_extract_survivors(res, zeeman_sim_config["cutoff_distance"])

    return res, survivor_states, survivor_indices
        

def mot_simulation(
    survivor_states,
    _2d_mot_config={ "s0": 1.4, "detuning_gamma": -1.47 },
    zeeman_config={ "s0": 3.0, "detuning_gamma": -13.75 },
    zeeman_field_config={ "radii": None, "positions": None, "tilt_angles": None },
    magnet_radius=0.053,
    gravity_enabled=True,
    seed=42,
    npools=8,
    stochastic=True,
    dt=_2d_mot_sim_config["dt"],
):
    N = len(survivor_states)
    if N == 0:
        return [], np.array([])

    mot_config = dict(_2d_mot_config)
    mot_config.setdefault("swap_polarization", False)

    atom, config = build_base_config(
        atom_species="Yb171",
        gravity_enabled=gravity_enabled,
        include_zeeman_field=True,
        include_zeeman_laser=True,
        include_2d_mot_lasers=True,
        include_3dmot_lasers=False,
        magnet_radius=magnet_radius,
        _2d_mot_config=mot_config,
        zeeman_config= zeeman_config,
        zeeman_field_config=zeeman_field_config,
        include_2dmot_field=True,
        zones=get_entire_apparatus_zone()
    )

    # 2. Set initial conditions from survivor states
    u0_list = [state.copy() for state in survivor_states]

    # dt_2d_mot = get_optimal_dt_2d_mot(
    #     s0=_2d_mot_config["s0"],
    #     detuning_gamma=_2d_mot_config["detuning_gamma"],
    #     magnet_radius=magnet_radius,
    # )

    time_points, _ = generate_timepoints(_2d_mot_sim_config["t_max"], dt)

    sim_func = RK4StCustomDt if stochastic else ScipyIVP_3D

    res, sim =run_multiple_atoms_simulation(
        config=config,
        u0=u0_list,
        time_points=time_points,
        sim_function=sim_func,
        npools=npools,
        seed_idx=seed
    )

    mot_survivor_states, mot_survivor_indices = mot_extract_survivors(res)
    count = _2d_mot_success_count(res)

    return res, count, mot_survivor_states


def mot_3d_simulation(
    survivor_states,
    _3d_mot_config=mot_3d_laser_config,
    gravity_enabled=True,
    seed=42,
    npools=8,
    dt=_3d_mot_sim_config["dt"],
):
    """
    Deterministic 3D MOT stage for atoms that made it past the 2D MOT + DPS.

    The proposal specifies a 3D MOT with three orthogonal counter-propagating
    beam pairs and a 3D quadrupole field in the science region. This stage
    therefore uses the deterministic ScipyIVP_3D integrator only.
    """
    N = len(survivor_states)
    if N == 0:
        return [], np.empty((0, 6))

    _, config = build_base_config(
        atom_species="Yb171",
        include_2d_mot_lasers=False,
        include_zeeman_field=False,
        include_zeeman_laser=False,
        include_3dmot_lasers=True,
        _3d_mot_config=_3d_mot_config,
        include_2dmot_field=True,
        use_3d_mot_field=True,
        gravity_enabled=gravity_enabled,
        zones=get_entire_apparatus_zone(),
    )

    u0_list = [state.copy() for state in survivor_states]
    time_points, _ = generate_timepoints(_3d_mot_sim_config["t_max"], dt)

    res, sim = run_multiple_atoms_simulation(
        config=config,
        u0=u0_list,
        time_points=time_points,
        sim_function=ScipyIVP_3D,
        npools=npools,
        seed_idx=seed,
    )

    final_states = np.array([traj.y[:, -1].copy() for traj in res]) if len(res) > 0 else np.empty((0, 6))
    return res, final_states

def run_both(save_file = None, N=500, seed=42, collimation_angle_deg=collimation_angle_deg, npools=8):
    radii, positions, tilt_angles = zeeman_configs["80_2"]

    print("Running Zeeman phase simulation...")

    zeeman_traj, survivors, surv_idx = zeeman_simulation(
        N_particles=N,
        _2d_mot_config={ "s0": 1.5, "detuning_gamma": -1.2 },
        zeeman_config={ "s0": 3.0, "detuning_gamma": -13.75 },
        zeeman_field_config={ "radii": radii, "positions": positions, "tilt_angles": tilt_angles },
        magnet_radius=0.053,
        T_C=400.0,
        seed=seed,
        stochastic=False,
        collimation_angle_deg=collimation_angle_deg,
        npools=npools,
    )

    print(f"Zeeman phase simulation ended")

    print("zeeman survivors: ", len(survivors))
    
    if len(survivors) == 0:
        print("No survivors — nothing to do in Phase 2.")
    else:
        mot_traj, success_count, mot_survivors = mot_simulation(
            survivor_states=survivors,
            _2d_mot_config={ "s0": 1.4, "detuning_gamma": -1.47 },
            magnet_radius=0.053,
            seed=seed,
            stochastic=False,
            npools=npools,
        )

        print(f"Success count: {success_count}")

        n_survivors = len(survivors)
        efficiency = success_count / n_survivors if n_survivors > 0 else np.nan

        print(
            f"RESULT "
            f"cutoff_angle_deg={collimation_angle_deg} "
            f"N_initial={N} "
            f"N_zeeman_survivors={n_survivors} "
            f"N_mot_success={success_count} "
            f"mot_given_zeeman_efficiency={efficiency:.8f}"
        )

        # mot3d_traj = []
        # if success_count == 0:
        #     print("No 2D MOT survivors reached the science region — nothing to do in Phase 3.")
        # else:
        #     mot3d_traj, final_3d_states = mot_3d_simulation(
        #         survivor_states=mot_survivors,
        #         _3d_mot_config=mot_3d_laser_config,
        #         seed=seed,
        #     )
        #     print(f"3D MOT deterministic trajectories: {len(mot3d_traj)}")

        # if (save_file):
        #     save_path = Path(save_file)
        #     zeeman_traj_ex = extract_trajectory_data(zeeman_traj)
        #     mot_traj_ex = extract_trajectory_data(mot_traj)

        #     save_file_json(save_path / f"zeeman_traj_N={N}_{datetime.utcnow().isoformat()}.json", zeeman_traj_ex)
        #     save_file_json(save_path / f"mot_traj_N={N}_{datetime.utcnow().isoformat()}.json", mot_traj_ex)
        #     if mot3d_traj:
        #         mot3d_traj_ex = extract_trajectory_data(mot3d_traj)
        #         save_file_json(save_path / f"mot3d_traj_N={N}_{datetime.utcnow().isoformat()}.json", mot3d_traj_ex)

if __name__ == "__main__":
    args = parse_args()

    n_atoms = args.n_atoms
    cutoff_angle_deg = args.cutoff_angle_deg
    npools = args.npools
    
    run_both(save_file=None, N=n_atoms, collimation_angle_deg=cutoff_angle_deg, npools=npools)
