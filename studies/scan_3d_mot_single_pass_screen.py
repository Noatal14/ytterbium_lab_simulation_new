"""Run a focused intensity/detuning screen of the single-pass blue pair."""

import argparse
import copy
import json
from itertools import product
from pathlib import Path

import numpy as np

from config import (
    DEFAULT_RANDOM_SEED,
    MOT_3D_SIM_CONFIG,
    MOT_3D_SINGLE_PASS_SCREEN_CONFIG,
)
from simulations.mot_3d import mot_3d_simulation
from studies.analyze_3d_mot_donut_ablation import DEFAULT_INPUT, build_ablation_profiles
from studies.compare_3d_mot_retention import (
    analyze_results,
    load_shared_ensemble,
    select_particle_shard,
)


def screen_points(detunings, intensities):
    """Return deterministic detuning-major scan points."""
    points = tuple((float(detuning), float(s0)) for detuning, s0 in product(detunings, intensities))
    if not points or any(detuning >= 0.0 or s0 <= 0.0 for detuning, s0 in points):
        raise ValueError("Single-pass candidates require negative detuning and positive s0.")
    return points


def run_screen(args):
    settings = MOT_3D_SINGLE_PASS_SCREEN_CONFIG
    selected, input_files = load_shared_ensemble(args.input, args.max_atoms, args.seed)
    states, global_indices = select_particle_shard(
        selected, args.num_shards, args.shard_index
    )
    if not len(states):
        raise ValueError("The selected shard contains no atoms.")
    points = screen_points(args.detuning_gamma_values, args.s0_values)
    simulation_seed = int(
        np.random.SeedSequence([args.seed, args.shard_index]).generate_state(1)[0]
    )
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []

    base = build_ablation_profiles()["single_pass_counterpropagating_pair"]
    for point_index, (detuning, s0) in enumerate(points):
        print(
            f"Starting single-pass point {point_index + 1}/{len(points)}: "
            f"detuning={detuning:g} Gamma, s0={s0:g}",
            flush=True,
        )
        profile = copy.deepcopy(base)
        profile["399"].update(
            detuning_gamma=detuning,
            s0=s0,
            waist_m=settings["fixed_blue_waist_m"],
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
        captured = np.any(analysis["eligible_masks"], axis=1)
        np.savez_compressed(
            output_dir / f"point_{point_index:02d}_outcomes.npz",
            global_particle_indices=global_indices,
            capture_eligible_ever=captured,
        )
        record = {
            "point_index": point_index,
            "blue_detuning_gamma": detuning,
            "blue_s0": s0,
            "blue_waist_mm": settings["fixed_blue_waist_m"] * 1e3,
            "input_particle_count": len(states),
            "capture_eligible_ever_count": int(captured.sum()),
            "peak_capture_eligible_count": int(analysis["peak_count"]),
            "entered_capture_region_count": int(
                analysis["diagnostics"]["entered_capture_region_count"]
            ),
            "slow_inside_count": int(analysis["diagnostics"]["slow_inside_count"]),
        }
        records.append(record)
        print(
            f"Completed point {point_index + 1}/{len(points)}: "
            f"captured={record['capture_eligible_ever_count']}/{len(states)}",
            flush=True,
        )

    report = {
        "status": "provisional single-pass screen; not laboratory-set values",
        "purpose": "isolate detuning/intensity acceptance before scanning waist",
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
    path = output_dir / "single_pass_screen.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def parse_args(argv=None):
    settings = MOT_3D_SINGLE_PASS_SCREEN_CONFIG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-atoms", type=int, default=settings["max_atoms"])
    parser.add_argument("--num-shards", type=int, default=settings["num_shards"])
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--npools", type=int, default=1)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=settings["t_max_s"])
    parser.add_argument(
        "--detuning-gamma-values",
        nargs="+",
        type=float,
        default=list(settings["blue_detuning_gamma_values"]),
    )
    parser.add_argument(
        "--s0-values",
        nargs="+",
        type=float,
        default=list(settings["blue_s0_values"]),
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_screen(parse_args())
