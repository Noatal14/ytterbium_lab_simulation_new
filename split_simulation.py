import numpy as np
from atomsmltr.simulation.simulator import ScipyIVP_3D
from dt_comparison.RK4StCustomDt import RK4StCustomDt
from lab_setup.config_builder import build_base_config
from lab_setup.zones import get_entire_apparatus_zone, get_zeeman_only_zone
from thermal_beam import generate_thermal_beam_state
from utils.simulation_helpers import run_multiple_atoms_simulation, generate_timepoints, zeeman_extract_survivors, _2d_mot_success_count, mot_extract_survivors, extract_trajectory_data
from config import zeeman_configs, zeeman_sim_config, _2d_mot_sim_config
from pathlib import Path
from datetime import datetime
from utils.file_helpers import save_file_json
from dt_comparison.main import get_optimal_dt_2d_mot, get_optimal_dt_zeeman

# Note: If r0_arr is generated at distance=0.378 instead of 0.314, atoms would start *outside* the slower and enter it. This is physically fine.

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
        include_magnetic_field=True,
        zones=get_zeeman_only_zone()
    )

    r0_arr, v0_arr, _ = generate_thermal_beam_state(
        config_name="thermal beam",
        N=N_particles,
        T_C=T_C,
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
        include_magnetic_field=True,
        zones=get_entire_apparatus_zone()
    )

    # 2. Set initial conditions from survivor states
    u0_list = [state.copy() for state in survivor_states]

    dt_2d_mot = get_optimal_dt_2d_mot(
        s0=_2d_mot_config["s0"],
        detuning_gamma=_2d_mot_config["detuning_gamma"],
        magnet_radius=magnet_radius,
    )

    time_points, _ = generate_timepoints(_2d_mot_sim_config["t_max"], _2d_mot_sim_config["dt"])

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

def run_both(save_file = None, N=500, seed=42):
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
    )

    print(f"Zeeman phase simulation ended")

    print("zeeman survivors: ", len(survivors))
    
    if len(survivors) == 0:
        print("No survivors — nothing to do in Phase 2.")
    else:
        mot_traj, success_count, _ = mot_simulation(
            survivor_states=survivors,
            _2d_mot_config={ "s0": 1.4, "detuning_gamma": -1.47 },
            magnet_radius=0.053,
            seed=seed,
        )

        print(f"Success count: {success_count}")

        if (save_file):
            save_path = Path(save_file)
            zeeman_traj_ex = extract_trajectory_data(zeeman_traj)
            mot_traj_ex = extract_trajectory_data(mot_traj)

            save_file_json(save_path / f"zeeman_traj_N={N}_{datetime.utcnow().isoformat()}.json", zeeman_traj_ex)
            save_file_json(save_path / f"mot_traj_N={N}_{datetime.utcnow().isoformat()}.json", mot_traj_ex)

if __name__ == "__main__":
    save_file = "junk/simulation_results"
    run_both(save_file=save_file, N=1000)

