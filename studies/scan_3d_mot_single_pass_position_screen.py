"""Compare physical yz single-pass crossing positions with local detuning scans."""

import argparse
import copy
import json
from itertools import product
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


def run_screen(args):
    selected, input_files = load_shared_ensemble(args.input, args.max_atoms, args.seed)
    states, global_indices = select_particle_shard(
        selected, args.num_shards, args.shard_index
    )
    points = tuple(product(args.z_offset_m_values, args.detuning_gamma_values))
    simulation_seed = int(
        np.random.SeedSequence([args.seed, args.shard_index]).generate_state(1)[0]
    )
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []

    for point_index, (z_offset_m, detuning) in enumerate(points):
        profile = copy.deepcopy(MOT_3D_CONFIGURATIONS["single_pass"])
        profile["blue_crossing_z_offset_m"] = float(z_offset_m)
        profile["399"]["detuning_gamma"] = float(detuning)
        profile["399"]["s0"] = args.blue_s0
        profile["399"]["waist_m"] = args.blue_waist_m
        print(
            f"Starting point {point_index + 1}/{len(points)}: "
            f"z={1000 * z_offset_m:g} mm, detuning={detuning:g} Gamma, "
            f"s0={args.blue_s0:g}",
            flush=True,
        )
        trajectories, _ = mot_3d_simulation(
            states,
            _3d_mot_config=profile,
            gravity_enabled=True,
            npools=args.npools,
            dt=args.dt,
            t_max=args.t_max,
            seed=simulation_seed,
        )
        analysis = analyze_results(trajectories, time_points)
        usable_at_end = analysis["eligible_masks"][:, -1]
        usable_ever = np.any(analysis["eligible_masks"], axis=1)
        diagnostics = analysis["diagnostics"]
        np.savez_compressed(
            output_dir / f"point_{point_index:02d}_outcomes.npz",
            global_particle_indices=global_indices,
            usable_at_end=usable_at_end,
            usable_ever=usable_ever,
        )
        record = {
            "point_index": point_index,
            "blue_crossing_z_offset_m": float(z_offset_m),
            "blue_detuning_gamma": float(detuning),
            "blue_s0": float(args.blue_s0),
            "blue_waist_m": float(args.blue_waist_m),
            "input_particle_count": len(states),
            "usable_at_end_count": int(usable_at_end.sum()),
            "usable_ever_count": int(usable_ever.sum()),
            "peak_usable_count": int(analysis["peak_count"]),
            "entered_capture_region_count": int(
                diagnostics["entered_capture_region_count"]
            ),
            "slow_inside_count": int(diagnostics["slow_inside_count"]),
        }
        records.append(record)
        print(
            f"Completed point {point_index + 1}/{len(points)}: "
            f"end={record['usable_at_end_count']}/{len(states)}, "
            f"ever={record['usable_ever_count']}/{len(states)}, "
            f"entered={record['entered_capture_region_count']}/{len(states)}",
            flush=True,
        )

    report = {
        "status": "physical yz single-pass position and detuning screen",
        "input_files": [str(path) for path in input_files],
        "selected_particle_count_before_sharding": len(selected),
        "input_particle_count": len(states),
        "num_shards": args.num_shards,
        "shard_index": args.shard_index,
        "selection_seed": args.seed,
        "simulation_seed": simulation_seed,
        "dt_s": args.dt,
        "t_max_s": args.t_max,
        "records": records,
    }
    path = output_dir / "single_pass_position_screen.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    return report


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
    parser.add_argument(
        "--z-offset-m-values", nargs="+", type=float, default=(-0.050, -0.045, -0.040)
    )
    parser.add_argument("--detuning-gamma-values", nargs="+", type=float, required=True)
    parser.add_argument("--blue-s0", type=float, required=True)
    parser.add_argument("--blue-waist-m", type=float, default=0.0075)
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_screen(parse_args())
