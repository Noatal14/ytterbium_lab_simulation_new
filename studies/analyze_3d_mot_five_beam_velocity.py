"""Save compact per-atom longitudinal trajectories for the corrected five-beam MOT."""

import argparse
import json
from pathlib import Path

import numpy as np

from config import (
    DEFAULT_RANDOM_SEED,
    MOT_3D_FINALIST_STABILITY_CONFIG as STUDY_CONFIG,
    MOT_3D_SIM_CONFIG,
)
from simulations.mot_3d import mot_3d_simulation
from studies.compare_3d_mot_finalist_stability import five_beam_profile
from studies.compare_3d_mot_retention import (
    DEFAULT_INPUT,
    analyze_results,
    load_shared_ensemble,
    select_particle_shard,
)


def sampled_longitudinal_velocities(results, time_points, sample_interval_s):
    """Sample every atom's vz on a compact common time grid."""
    time_points = np.asarray(time_points, dtype=float)
    if sample_interval_s <= 0:
        raise ValueError("sample_interval_s must be positive.")
    if len(time_points) < 2:
        sample_indices = np.array([0], dtype=int)
    else:
        dt = float(time_points[1] - time_points[0])
        stride = max(1, int(round(sample_interval_s / dt)))
        sample_indices = np.arange(0, len(time_points), stride, dtype=int)
        if sample_indices[-1] != len(time_points) - 1:
            sample_indices = np.append(sample_indices, len(time_points) - 1)
    sample_times = time_points[sample_indices]
    velocities = np.full((len(results), len(sample_times)), np.nan, dtype=np.float32)
    for particle_index, trajectory in enumerate(results):
        trajectory_times = np.asarray(trajectory.t, dtype=float)
        states = np.asarray(trajectory.y, dtype=float)
        if not trajectory_times.size or states.ndim != 2 or states.shape[0] < 6:
            continue
        trajectory_indices = np.searchsorted(trajectory_times, sample_times)
        valid = trajectory_indices < len(trajectory_times)
        exact = np.zeros_like(valid)
        exact[valid] = np.isclose(
            trajectory_times[trajectory_indices[valid]],
            sample_times[valid],
            rtol=0.0,
            atol=1e-12,
        )
        velocities[particle_index, exact] = states[5, trajectory_indices[exact]]
    return sample_times, velocities


def run_study(args):
    selected, input_files = load_shared_ensemble(args.input, args.max_atoms, args.seed)
    states, global_indices = select_particle_shard(
        selected, args.num_shards, args.shard_index
    )
    if not len(states):
        raise ValueError("The selected shard contains no atoms.")
    simulation_seed = int(
        np.random.SeedSequence([args.seed, args.shard_index]).generate_state(1)[0]
    )
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    print(
        f"Starting corrected five-beam velocity diagnostic with {len(states)} atoms",
        flush=True,
    )
    results, _ = mot_3d_simulation(
        states,
        _3d_mot_config=five_beam_profile(),
        gravity_enabled=True,
        npools=args.npools,
        dt=args.dt,
        t_max=args.t_max,
        seed=simulation_seed,
    )
    analysis = analyze_results(results, time_points)
    sample_times, velocities = sampled_longitudinal_velocities(
        results, time_points, args.sample_interval
    )
    usable_ever = np.any(analysis["eligible_masks"], axis=1)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_dir / "five_beam_velocity.npz",
        time_s=sample_times,
        vz_m_s=velocities,
        initial_vz_m_s=states[:, 5],
        usable_ever=usable_ever,
        global_particle_indices=global_indices,
    )
    report = {
        "status": "corrected five-beam 600-atom longitudinal-velocity diagnostic",
        "input_files": [str(path) for path in input_files],
        "selected_particle_count_before_sharding": int(len(selected)),
        "input_particle_count": int(len(states)),
        "num_shards": int(args.num_shards),
        "shard_index": int(args.shard_index),
        "selection_seed": int(args.seed),
        "simulation_seed": simulation_seed,
        "dt_s": float(args.dt),
        "t_max_s": float(args.t_max),
        "sample_interval_s": float(args.sample_interval),
        "usable_ever_count": int(usable_ever.sum()),
    }
    (output_dir / "five_beam_velocity_shard.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(
        f"Completed corrected five-beam diagnostic: usable ever="
        f"{usable_ever.sum()}/{len(states)}",
        flush=True,
    )
    return report


def parse_args(argv=None):
    diagnostic = STUDY_CONFIG["velocity_diagnostic"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-atoms", type=int, default=diagnostic["max_atoms"])
    parser.add_argument("--num-shards", type=int, default=STUDY_CONFIG["num_shards"])
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--npools", type=int, default=STUDY_CONFIG["pbs_ncpus_per_shard"])
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=diagnostic["t_max_s"])
    parser.add_argument(
        "--sample-interval", type=float, default=diagnostic["sample_interval_s"]
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_study(parse_args())
