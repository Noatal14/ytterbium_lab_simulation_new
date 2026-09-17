"""Run the two non-donut 3D-MOT finalists continuously for 400 ms.

The shared input is the complete saved 2D-MOT survivor ensemble.  The two
profiles are fixed at their best pre-optimization operating points: the
gravity-assisted five-beam MOT and the finite four-blue entrance/backstop
geometry.  The donut is intentionally not rerun; its existing 0--400 ms data
are incorporated by the merge/plot stage.
"""

import argparse
import copy
import gc
import json
from pathlib import Path

import numpy as np

from config import (
    DEFAULT_RANDOM_SEED,
    MOT_3D_CONFIGURATIONS,
    MOT_3D_FINALIST_STABILITY_CONFIG as STUDY_CONFIG,
    MOT_3D_SIM_CONFIG,
)
from simulations.mot_3d import mot_3d_simulation
from studies.compare_3d_mot_retention import (
    DEFAULT_INPUT,
    analyze_results,
    load_shared_ensemble,
    select_particle_shard,
)


PROFILE_NAMES = ("five_beam_best", "four_blue_gate_best")


def five_beam_profile(settings=None):
    """Return the best corrected five-beam pre-optimization profile."""
    settings = settings or STUDY_CONFIG
    point = settings["five_beam"]
    profile = copy.deepcopy(MOT_3D_CONFIGURATIONS["five_beam_gravity"])
    profile["magnetic_gradient_G_cm"] = point["magnetic_gradient_G_cm"]
    profile["556"].update(
        s0=point["paired_green_s0"],
        detuning_gamma=point["green_detuning_gamma"],
    )
    profile["556"]["s0_by_axis"] = {
        point["lower_green_axis_tag"]: point["lower_green_s0"]
    }
    return profile


def _blue_group(point, name, profile_kind, crossing, minimum=None, maximum=None):
    center_z = MOT_3D_CONFIGURATIONS["angled_donut"]["center_position_m"][2]
    group = {
        "name": name,
        "axis_tags": tuple(point["axis_tags"]),
        "profile": profile_kind,
        "center_offset_m": (0.0, 0.0, crossing),
        "s0": point["blue_s0"],
        "waist_m": point["blue_waist_m"],
        "inner_cutoff_radius_m": point["inner_cutoff_radius_m"],
    }
    if minimum is not None:
        group["minimum_lab_z_m"] = center_z + minimum
    if maximum is not None:
        group["maximum_lab_z_m"] = center_z + maximum
    return group


def four_blue_gate_profile(settings=None):
    """Return six green beams plus the best finite four-blue arrangement."""
    settings = settings or STUDY_CONFIG
    point = settings["four_blue_gate"]
    profile = copy.deepcopy(MOT_3D_CONFIGURATIONS["angled_donut"])
    profile["399"].update(
        s0=point["blue_s0"],
        detuning_gamma=point["blue_detuning_gamma"],
        waist_m=point["blue_waist_m"],
        inner_cutoff_radius_m=point["inner_cutoff_radius_m"],
    )
    z_min, z_max = point["backstop_window_m"]
    profile["399"]["beam_groups"] = [
        _blue_group(
            point,
            "entrance",
            "upstream_clipped_donut",
            point["entrance_crossing_offset_m"],
            maximum=point["entrance_cutoff_offset_m"],
        ),
        _blue_group(
            point,
            "downstream_backstop",
            "window_clipped_donut",
            point["backstop_crossing_offset_m"],
            minimum=z_min,
            maximum=z_max,
        ),
    ]
    return profile


def finalist_profiles(settings=None):
    return {
        "five_beam_best": five_beam_profile(settings),
        "four_blue_gate_best": four_blue_gate_profile(settings),
    }


def active_trajectory_counts(results, time_points):
    """Count trajectories that still have an exact state at each grid time."""
    counts = np.zeros(len(time_points), dtype=np.int64)
    for trajectory in results:
        times = np.asarray(trajectory.t, dtype=float)
        if not times.size:
            continue
        indices = np.searchsorted(time_points, times)
        valid = indices < len(time_points)
        indices = indices[valid]
        exact = np.isclose(time_points[indices], times[valid], rtol=0.0, atol=1e-12)
        np.add.at(counts, indices[exact], 1)
    return counts


def run_study(args):
    selected, input_files = load_shared_ensemble(args.input, args.max_atoms, args.seed)
    states, global_indices = select_particle_shard(
        selected, args.num_shards, args.shard_index
    )
    if not len(states):
        raise ValueError("The selected shard contains no atoms.")
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    simulation_seed = int(
        np.random.SeedSequence([args.seed, args.shard_index]).generate_state(1)[0]
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    records = {}

    for profile_index, (name, profile) in enumerate(finalist_profiles().items(), start=1):
        print(
            f"Starting finalist {profile_index}/{len(PROFILE_NAMES)}: {name} "
            f"with {len(states)} atoms through {args.t_max * 1e3:g} ms",
            flush=True,
        )
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
        active_counts = active_trajectory_counts(results, time_points)
        usable_counts = np.asarray(analysis["capture_eligible_counts"], dtype=np.int64)
        inside_counts = np.asarray(analysis["inside_counts"], dtype=np.int64)
        np.savez_compressed(
            output_dir / f"{name}_curves.npz",
            time_s=time_points,
            active_counts=active_counts,
            inside_counts=inside_counts,
            usable_counts=usable_counts,
        )
        records[name] = {
            "input_particle_count": int(len(states)),
            "usable_at_100ms_count": int(usable_counts[np.searchsorted(time_points, 0.1)]),
            "usable_at_400ms_count": int(usable_counts[-1]),
            "active_at_400ms_count": int(active_counts[-1]),
            "peak_usable_count": int(usable_counts.max()),
            "peak_usable_time_s": float(time_points[int(np.argmax(usable_counts))]),
            "diagnostics": analysis["diagnostics"],
        }
        print(
            f"Completed {name}: usable at 100 ms="
            f"{records[name]['usable_at_100ms_count']}/{len(states)}, "
            f"at 400 ms={records[name]['usable_at_400ms_count']}/{len(states)}",
            flush=True,
        )
        del results, analysis
        gc.collect()

    report = {
        "status": "provisional direct 0--400 ms finalist comparison",
        "input_files": [str(path) for path in input_files],
        "selected_particle_count_before_sharding": int(len(selected)),
        "input_particle_count": int(len(states)),
        "num_shards": int(args.num_shards),
        "shard_index": int(args.shard_index),
        "selected_particle_indices": global_indices.tolist(),
        "selection_seed": int(args.seed),
        "simulation_seed": simulation_seed,
        "dt_s": float(args.dt),
        "t_max_s": float(args.t_max),
        "profiles": list(PROFILE_NAMES),
        "operating_points": STUDY_CONFIG,
        "records": records,
    }
    (output_dir / "finalist_stability_shard.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-atoms", type=int, default=STUDY_CONFIG["max_atoms"])
    parser.add_argument("--num-shards", type=int, default=STUDY_CONFIG["num_shards"])
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--npools", type=int, default=STUDY_CONFIG["pbs_ncpus_per_shard"])
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=STUDY_CONFIG["t_max_s"])
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_study(parse_args())
