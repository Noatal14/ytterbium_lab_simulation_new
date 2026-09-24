"""Run the five donut-ablation variants solely for all-atom vz(t) figures."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from config import DEFAULT_RANDOM_SEED, MOT_3D_CONFIGURATIONS, MOT_3D_SIM_CONFIG
from simulations.mot_3d import mot_3d_simulation
from studies.compare_3d_mot_retention import (
    DEFAULT_INPUT,
    analyze_results,
    load_shared_ensemble,
    select_particle_shard,
)


VARIANT_ORDER = (
    "full_donut",
    "without_positive_z_blue",
    "without_transverse_y_blue",
    "counterpropagating_pair_shell",
    "single_pass_counterpropagating_pair",
)
AXIS_TAGS = ("+XZ_1", "-XZ_1", "+XZ_2", "-XZ_2", "+Y", "-Y")


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
    velocities = np.full(
        (len(results), len(sample_times)), np.nan, dtype=np.float32
    )
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


def build_profiles():
    base = copy.deepcopy(MOT_3D_CONFIGURATIONS["angled_donut"])

    def variant(enabled_blue):
        profile = copy.deepcopy(base)
        profile["beam_components"] = {
            tag: {"399_enabled": tag in enabled_blue, "556_enabled": True}
            for tag in AXIS_TAGS
        }
        return profile

    profiles = {
        "full_donut": copy.deepcopy(base),
        "without_positive_z_blue": variant({"-XZ_1", "-XZ_2", "+Y", "-Y"}),
        "without_transverse_y_blue": variant(
            {"+XZ_1", "-XZ_1", "+XZ_2", "-XZ_2"}
        ),
        "counterpropagating_pair_shell": variant({"-XZ_1", "-XZ_2"}),
        "single_pass_counterpropagating_pair": variant({"-XZ_1", "-XZ_2"}),
    }
    single_pass = profiles["single_pass_counterpropagating_pair"]
    single_pass["399"]["profile"] = "upstream_clipped_donut"
    single_pass["399"]["green_exclusion_radius_m"] = 10e-3
    return profiles


def run(args):
    selected, input_files = load_shared_ensemble(args.input, args.max_atoms, args.seed)
    states, global_indices = select_particle_shard(
        selected, args.num_shards, args.shard_index
    )
    simulation_seed = int(
        np.random.SeedSequence([args.seed, args.shard_index]).generate_state(1)[0]
    )
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for index, (name, profile) in enumerate(build_profiles().items(), start=1):
        print(f"Starting velocity variant {index}/{len(VARIANT_ORDER)}: {name}", flush=True)
        results, _ = mot_3d_simulation(
            states,
            _3d_mot_config=profile,
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
        captured = np.any(analysis["eligible_masks"], axis=1)
        np.savez_compressed(
            output_dir / f"{name}_longitudinal_velocities.npz",
            time_s=sample_times,
            vz_m_s=velocities,
            capture_eligible_ever=captured,
            global_particle_indices=global_indices,
        )
        records.append({"variant": name, "captured": int(captured.sum())})
        print(f"Completed {name}: {captured.sum()}/{len(captured)}", flush=True)
    report = {
        "input_files": [str(path) for path in input_files],
        "input_particle_count": len(states),
        "num_shards": args.num_shards,
        "shard_index": args.shard_index,
        "records": records,
    }
    (output_dir / "donut_velocity_shard.json").write_text(json.dumps(report, indent=2) + "\n")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-atoms", type=int, default=600)
    parser.add_argument("--num-shards", type=int, default=3)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--npools", type=int, default=200)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=0.1)
    parser.add_argument("--sample-interval", type=float, default=50e-6)
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
