"""Run the 2D-MOT stage from a saved particle-state ensemble."""

import argparse

import numpy as np

from config import (
    DEFAULT_NUM_POOLS,
    DEFAULT_RANDOM_SEED,
    MOT_2D_LASER_CONFIG,
    MOT_2D_MAGNET_RADIUS_M,
    MOT_2D_SIM_CONFIG,
    ZEEMAN_FIELD_CONFIG,
    ZEEMAN_LASER_CONFIG,
)
from lab_setup.config_builder import build_base_config
from lab_setup.zones import get_entire_apparatus_zone
from utils.RK4StCustom import RK4StCustom
from utils.ScipyIVP_3DCustom import ScipyIVP_3DCustom
from utils.data_paths import (
    DEFAULT_2D_MOT_STATES_FILE,
    DEFAULT_ZEEMAN_STATES_FILE,
    load_particle_states,
    save_particle_states,
)
from utils.simulation_helpers import (
    generate_timepoints,
    mot_extract_survivors,
    run_multiple_atoms_simulation,
)


def mot_simulation(
    survivor_states,
    _2d_mot_config=MOT_2D_LASER_CONFIG,
    zeeman_config=ZEEMAN_LASER_CONFIG,
    zeeman_field_config=ZEEMAN_FIELD_CONFIG,
    magnet_radius=MOT_2D_MAGNET_RADIUS_M,
    gravity_enabled=True,
    npools=DEFAULT_NUM_POOLS,
    stochastic=True,
    dt=MOT_2D_SIM_CONFIG["dt_s"],
    seed=DEFAULT_RANDOM_SEED,
):
    """Propagate saved states through the 2D MOT and return its survivors."""
    if len(survivor_states) == 0:
        return [], 0, np.empty((0, 6))
    _, simulation_config = build_base_config(
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
    time_points, _ = generate_timepoints(MOT_2D_SIM_CONFIG["t_max_s"], dt)
    simulation_function = RK4StCustom if stochastic else ScipyIVP_3DCustom
    results, _ = run_multiple_atoms_simulation(
        config=simulation_config,
        u0=[np.asarray(state).copy() for state in survivor_states],
        time_points=time_points,
        sim_function=simulation_function,
        npools=npools,
        seed_idx=seed,
    )
    mot_survivor_states, count, _ = mot_extract_survivors(results)
    return results, count, mot_survivor_states


def mot_simulation_paired_ensembles(
    survivor_state_ensembles,
    seeds,
    _2d_mot_config=MOT_2D_LASER_CONFIG,
    zeeman_config=ZEEMAN_LASER_CONFIG,
    zeeman_field_config=ZEEMAN_FIELD_CONFIG,
    magnet_radius=MOT_2D_MAGNET_RADIUS_M,
    gravity_enabled=True,
    npools=DEFAULT_NUM_POOLS,
    stochastic=True,
    dt=MOT_2D_SIM_CONFIG["dt_s"],
):
    """Run paired ensembles through one shared config and worker pool.

    Each ensemble retains the exact RNG streams it would receive from a
    separate call with its own seed. Combining the trajectories only avoids
    rebuilding the physical configuration and multiprocessing pool.
    """
    if len(survivor_state_ensembles) != len(seeds):
        raise ValueError("Provide exactly one MOT seed per survivor ensemble.")
    if not survivor_state_ensembles:
        return []

    arrays = [np.asarray(states) for states in survivor_state_ensembles]
    for states in arrays:
        if states.ndim != 2 or states.shape[1] != 6:
            raise ValueError(f"Expected particle states with shape (N, 6), got {states.shape}")

    _, simulation_config = build_base_config(
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
    time_points, _ = generate_timepoints(MOT_2D_SIM_CONFIG["t_max_s"], dt)
    simulation_function = RK4StCustom if stochastic else ScipyIVP_3DCustom

    initial_states = []
    trajectory_seed_sequences = []
    boundaries = [0]
    for states, seed in zip(arrays, seeds):
        initial_states.extend(np.asarray(state).copy() for state in states)
        if stochastic:
            trajectory_seed_sequences.extend(
                np.random.SeedSequence(seed).spawn(len(states))
            )
        boundaries.append(boundaries[-1] + len(states))

    results, _ = run_multiple_atoms_simulation(
        config=simulation_config,
        u0=initial_states,
        time_points=time_points,
        sim_function=simulation_function,
        npools=npools,
        seed_idx=seeds[0] if seeds else DEFAULT_RANDOM_SEED,
        trajectory_seed_sequences=(
            trajectory_seed_sequences if stochastic else None
        ),
    )

    ensemble_results = []
    for start, stop in zip(boundaries[:-1], boundaries[1:]):
        grouped_results = results[start:stop]
        survivor_states, count, _ = mot_extract_survivors(grouped_results)
        ensemble_results.append((grouped_results, count, survivor_states))
    return ensemble_results


def run_2d_mot_from_file(input_file, output_file, max_particles=None, **kwargs):
    states = load_particle_states(input_file)
    if max_particles is not None:
        states = states[:max_particles]
    _, count, survivors = mot_simulation(states, **kwargs)
    output_path = save_particle_states(output_file, survivors)
    percentage = 100.0 * count / len(states) if len(states) else 0.0
    print(f"2D-MOT survivors: {count}/{len(states)} ({percentage:.4f}%)")
    print(f"Saved states to: {output_path}")
    return survivors


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_ZEEMAN_STATES_FILE))
    parser.add_argument("--output", default=str(DEFAULT_2D_MOT_STATES_FILE))
    parser.add_argument("--max_particles", type=int, default=None)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--stochastic", type=int, choices=[0, 1], default=1)
    parser.add_argument("--dt", type=float, default=MOT_2D_SIM_CONFIG["dt_s"])
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_2d_mot_from_file(
        args.input,
        args.output,
        max_particles=args.max_particles,
        npools=args.npools,
        stochastic=bool(args.stochastic),
        dt=args.dt,
        seed=args.seed,
    )
