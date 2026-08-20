"""Run the Zeeman-slower stage from a generated thermal beam."""

import argparse

import numpy as np

from config import (
    COLLIMATION_ANGLE_DEG,
    DEFAULT_NUM_PARTICLES,
    DEFAULT_NUM_POOLS,
    DEFAULT_RANDOM_SEED,
    MOT_2D_LASER_CONFIG,
    MOT_2D_MAGNET_RADIUS_M,
    ZEEMAN_FIELD_CONFIG,
    ZEEMAN_LASER_CONFIG,
    ZEEMAN_SIM_CONFIG,
)
from lab_setup.config_builder import build_base_config
from lab_setup.zones import get_zeeman_only_zone
from thermal_beam import generate_thermal_beam_state
from utils.RK4StCustom import RK4StCustom
from utils.ScipyIVP_3DCustom import ScipyIVP_3DCustom
from utils.data_paths import DEFAULT_ZEEMAN_STATES_FILE, save_particle_states
from utils.simulation_helpers import (
    generate_timepoints,
    run_multiple_atoms_simulation,
    zeeman_extract_survivors,
)


def zeeman_simulation(
    N_particles=DEFAULT_NUM_PARTICLES,
    _2d_mot_config=MOT_2D_LASER_CONFIG,
    zeeman_config=ZEEMAN_LASER_CONFIG,
    zeeman_field_config=ZEEMAN_FIELD_CONFIG,
    magnet_radius=MOT_2D_MAGNET_RADIUS_M,
    gravity_enabled=True,
    npools=DEFAULT_NUM_POOLS,
    stochastic=True,
    dt=ZEEMAN_SIM_CONFIG["dt_s"],
    collimation_angle_deg=COLLIMATION_ANGLE_DEG,
    seed=DEFAULT_RANDOM_SEED,
):
    """Generate a thermal beam and return the states that survive Zeeman."""
    atom, simulation_config = build_base_config(
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
            cutoff_distance=ZEEMAN_SIM_CONFIG["cutoff_distance_m"]
        ),
    )
    r0_arr, v0_arr, _ = generate_thermal_beam_state(
        N=N_particles,
        collimation_angle_deg=collimation_angle_deg,
        m=atom.mass,
        distance_m=ZEEMAN_SIM_CONFIG["start_distance_m"],
        seed=seed,
    )
    time_points, _ = generate_timepoints(ZEEMAN_SIM_CONFIG["t_max_s"], dt)
    initial_states = [
        np.concatenate((position, velocity))
        for position, velocity in zip(r0_arr, v0_arr)
    ]
    simulation_function = RK4StCustom if stochastic else ScipyIVP_3DCustom
    results, _ = run_multiple_atoms_simulation(
        config=simulation_config,
        u0=initial_states,
        time_points=time_points,
        sim_function=simulation_function,
        npools=npools,
        seed_idx=seed,
    )
    survivor_states, survivor_indices = zeeman_extract_survivors(
        results, ZEEMAN_SIM_CONFIG["cutoff_distance_m"]
    )
    return results, survivor_states, survivor_indices


def run_and_save_zeeman(output_file, **simulation_kwargs):
    """Run Zeeman and save only the reusable survivor states."""
    _, survivors, _ = zeeman_simulation(**simulation_kwargs)
    output_path = save_particle_states(output_file, survivors)
    print(f"Zeeman survivors: {len(survivors)}")
    print(f"Saved states to: {output_path}")
    return np.asarray(survivors)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n_atoms", type=int, default=DEFAULT_NUM_PARTICLES)
    parser.add_argument("--output", default=str(DEFAULT_ZEEMAN_STATES_FILE))
    parser.add_argument("--cutoff_angle_deg", type=float, default=COLLIMATION_ANGLE_DEG)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--stochastic", type=int, choices=[0, 1], default=1)
    parser.add_argument("--dt", type=float, default=ZEEMAN_SIM_CONFIG["dt_s"])
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_and_save_zeeman(
        args.output,
        N_particles=args.n_atoms,
        collimation_angle_deg=args.cutoff_angle_deg,
        npools=args.npools,
        stochastic=bool(args.stochastic),
        dt=args.dt,
        seed=args.seed,
    )
