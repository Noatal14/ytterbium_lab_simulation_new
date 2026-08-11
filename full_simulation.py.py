import numpy as np
from atomsmltr.simulation.simulator import ScipyIVP_3D
from dt_comparison.RK4StCustomDt import RK4StCustomDt
from lab_setup.config_builder import build_base_config
from lab_setup.zones import get_entire_apparatus_zone
from thermal_beam import generate_thermal_beam_state
from utils.file_helpers import save_file_json
from utils.simulation_helpers import run_simulation, generate_timepoints
from config import full_sim_config, zeeman_laser_config, _2d_mot_laser_config, _2d_mot_magnet_radius, zeeman_field_config

# Note: If r0_arr is generated at distance=0.378 instead of 0.314, atoms would start *outside* the slower and enter it. This is physically fine.

def simulation(
        N_particles=1000,
        _2d_mot_config=_2d_mot_laser_config,
        zeeman_config=zeeman_laser_config,
        zeeman_field_config=zeeman_field_config,
        magnet_radius=_2d_mot_magnet_radius,
        npools=8,
    ):

    atom, config = build_base_config(
        atom_species="Yb171",
        gravity_enabled=True,

        include_2d_mot=True,
        include_zeeman=True,
        include_3dmot=False,

        magnet_radius=magnet_radius,
        zeeman_field_config=zeeman_field_config,

        _2d_mot_config=_2d_mot_config,
        zeeman_config= zeeman_config,

        zones=get_entire_apparatus_zone()
    )

    r0_arr, v0_arr, beam_info = generate_thermal_beam_state(
        N=N_particles,
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
    percent_completed = simulation(
        N_particles=1000,
        _2d_mot_config=_2d_mot_laser_config,
        zeeman_config=zeeman_laser_config,
        zeeman_field_config=zeeman_field_config,
        magnet_radius=_2d_mot_magnet_radius,
        gravity_enabled=True,
        npools=8,
    )

    print(f"Percent Completed: {percent_completed}")
    print("\\nTesting complete. Data saved.")


