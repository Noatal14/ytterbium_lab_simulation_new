import numpy as np
from atomsmltr.simulation.simulator import ScipyIVP_3D
from dt_comparison.RK4StCustomDt import RK4StCustomDt
from lab_setup.config_builder import build_base_config
from lab_setup.zones import get_entire_apparatus_zone
from thermal_beam import generate_thermal_beam_state
from utils.file_helpers import save_file_json
from utils.simulation_helpers import run_simulation, generate_timepoints
from config import zeeman_configs, full_sim_config

# Note: If r0_arr is generated at distance=0.378 instead of 0.314, atoms would start *outside* the slower and enter it. This is physically fine.

def simulation(
        N_particles=1000,
        _2d_mot_config={ "s0": 1.5, "detuning_gamma": -1.2, "swap_polarization": False },
        zeeman_config={ "s0": 3.0, "detuning_gamma": -13.75 },
        zeeman_field_config={ "radii": None, "positions": None, "tilt_angles": None },
        magnet_radius=0.053,
        T_C=400.0,
        npools=8,
    ):

    atom, config = build_base_config(
        atom_species="Yb171",
        gravity_enabled=True,
        include_zeeman_field=True,
        include_zeeman_laser=True,
        include_2d_mot_lasers=True,
        include_3dmot_lasers=False,
        magnet_radius=magnet_radius,
        _2d_mot_config=_2d_mot_config,
        zeeman_config= zeeman_config,
        zeeman_field_config=zeeman_field_config,
        include_magnetic_field=True,
        zones=get_entire_apparatus_zone()
    )

    r0_arr, v0_arr, beam_info = generate_thermal_beam_state(
        config_name="thermal beam",
        N=N_particles,
        T_C=T_C,
        m=atom.mass,
        distance_m=full_sim_config.start_distance,
    )

    time_points, _ = generate_timepoints(full_sim_config.t_max, full_sim_config.dt)

    u0_list = [np.concatenate((r0, v0)) for r0, v0 in zip(r0_arr, v0_arr)]

    _, y, sim =run_simulation(
        config=config,
        u0=u0_list,
        time_points=time_points,
        sim_function=RK4StCustomDt,
        npools=npools
    )
        



if __name__ == "__main__":
    radii, positions, tilt_angles = zeeman_configs["80_2"]

    percent_completed = simulation(
        N_particles=1000,
        _2d_mot_config={ "s0": 1.5, "detuning_gamma": -1.2, "swap_polarization": False },
        zeeman_config={ "s0": 3.0, "detuning_gamma": -13.75 },
        zeeman_field_config={ "radii": radii, "positions": positions, "tilt_angles": tilt_angles },
        magnet_radius=0.053,
        gravity_enabled=True,
        T_C=400.0,
        seed=42, 
        npools=8,
    )

    print(f"Percent Completed: {percent_completed}")
    print("\\nTesting complete. Data saved.")


