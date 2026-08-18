"""Simpler full-pipeline simulation entry point for the apparatus.

This script is a convenience wrapper for a broader end-to-end run. The
production workflow remains in split_simulation.py, which is the clearer and
more explicit starting point for new users.
"""

import numpy as np

from utils.ScipyIVP_3DCustom import ScipyIVP_3DCustom
from utils.RK4StCustom import RK4StCustom
from lab_setup.config_builder import build_base_config
from lab_setup.zones import get_entire_apparatus_zone
from thermal_beam import generate_thermal_beam_state
from utils.simulation_helpers import (
    mot_extract_survivors,
    run_multiple_atoms_simulation,
    generate_timepoints,
)
from config import (
    FULL_SIM_CONFIG,
    DEFAULT_NUM_POOLS,
    ZEEMAN_LASER_CONFIG,
    MOT_2D_LASER_CONFIG,
    MOT_2D_MAGNET_RADIUS_M,
    ZEEMAN_FIELD_CONFIG,
    DEFAULT_RANDOM_SEED,
)

# Note: If r0_arr is generated at distance=0.378 instead of 0.314, atoms would start *outside* the slower and enter it. This is physically fine.

def simulation(
        N_particles=1000,
        _2d_mot_config=MOT_2D_LASER_CONFIG,
        zeeman_config=ZEEMAN_LASER_CONFIG,
        zeeman_field_config=ZEEMAN_FIELD_CONFIG,
        magnet_radius=MOT_2D_MAGNET_RADIUS_M,
        npools=DEFAULT_NUM_POOLS,
        stochastic=True
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
        distance_m=FULL_SIM_CONFIG["start_distance_m"],
        collimation_angle_deg=1.3,
        seed=DEFAULT_RANDOM_SEED
    )

    time_points, _ = generate_timepoints(FULL_SIM_CONFIG["t_max_s"], FULL_SIM_CONFIG["dt_s"])

    u0_list = [np.concatenate((r0, v0)) for r0, v0 in zip(r0_arr, v0_arr)]

    sim_func = RK4StCustom if stochastic else ScipyIVP_3DCustom

    res, sim =run_multiple_atoms_simulation(
        config=config,
        u0=u0_list,
        time_points=time_points,
        sim_function=sim_func,
        npools=npools
    )

    _, count, _ = mot_extract_survivors(res)

    return count

if __name__ == "__main__":
    success_count = simulation(
        N_particles=1000,
        _2d_mot_config=MOT_2D_LASER_CONFIG,
        zeeman_config=ZEEMAN_LASER_CONFIG,
        zeeman_field_config=ZEEMAN_FIELD_CONFIG,
        magnet_radius=MOT_2D_MAGNET_RADIUS_M,
        stochastic=False,
        npools=DEFAULT_NUM_POOLS,
    )

    print(f"Success Count: {success_count}")
    print("\\nTesting complete. Data saved.")


