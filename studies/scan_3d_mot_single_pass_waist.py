"""Run the focused single-pass blue-waist screen."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from config import (
    DEFAULT_RANDOM_SEED,
    MOT_3D_SIM_CONFIG,
    MOT_3D_SINGLE_PASS_WAIST_SCREEN_CONFIG,
)
from simulations.mot_3d import mot_3d_simulation
from studies.analyze_3d_mot_donut_ablation import DEFAULT_INPUT, build_ablation_profiles
from studies.compare_3d_mot_retention import (
    analyze_results,
    load_shared_ensemble,
    select_particle_shard,
)


def gaussian_relative_intensity(radius_m, waist_m):
    """Return I(r)/I(0) for the project's 1/e^2 Gaussian waist convention."""
    return float(np.exp(-2.0 * (radius_m / waist_m) ** 2))


def matched_cutoff_s0(waist_m, settings=None):
    """Choose s0 to preserve baseline intensity at the clipping radius."""
    settings = settings or MOT_3D_SINGLE_PASS_WAIST_SCREEN_CONFIG
    radius = settings["cutoff_radius_m"]
    baseline_edge = settings["baseline_blue_s0"] * gaussian_relative_intensity(
        radius, settings["baseline_blue_waist_m"]
    )
    return baseline_edge / gaussian_relative_intensity(radius, waist_m)


def waist_screen_points(settings=None):
    """Return the five predefined candidates in deterministic order."""
    settings = settings or MOT_3D_SINGLE_PASS_WAIST_SCREEN_CONFIG
    baseline_waist, *wider_waists = settings["blue_waist_values_m"]
    if baseline_waist != settings["baseline_blue_waist_m"] or len(wider_waists) != 2:
        raise ValueError("Waist screen requires one 15-mm baseline and two wider waists.")
    points = [
        {
            "label": "baseline_15mm",
            "waist_m": baseline_waist,
            "s0": settings["baseline_blue_s0"],
            "intensity_control": "baseline",
        }
    ]
    for waist in wider_waists:
        points.append(
            {
                "label": f"fixed_s0_{waist * 1e3:g}mm",
                "waist_m": waist,
                "s0": settings["baseline_blue_s0"],
                "intensity_control": "fixed_peak_s0",
            }
        )
    for waist in wider_waists:
        points.append(
            {
                "label": f"matched_cutoff_{waist * 1e3:g}mm",
                "waist_m": waist,
                "s0": matched_cutoff_s0(waist, settings),
                "intensity_control": "matched_intensity_at_cutoff",
            }
        )
    return tuple(points)


def run_screen(args):
    settings = MOT_3D_SINGLE_PASS_WAIST_SCREEN_CONFIG
    selected, input_files = load_shared_ensemble(args.input, args.max_atoms, args.seed)
    states, global_indices = select_particle_shard(
        selected, args.num_shards, args.shard_index
    )
    if not len(states):
        raise ValueError("The selected shard contains no atoms.")
    points = waist_screen_points()
    simulation_seed = int(
        np.random.SeedSequence([args.seed, args.shard_index]).generate_state(1)[0]
    )
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    base = build_ablation_profiles()["single_pass_counterpropagating_pair"]

    for point_index, point in enumerate(points):
        print(
            f"Starting waist point {point_index + 1}/{len(points)}: "
            f"{point['label']}, waist={point['waist_m'] * 1e3:g} mm, "
            f"s0={point['s0']:.6g}",
            flush=True,
        )
        profile = copy.deepcopy(base)
        profile["399"].update(
            detuning_gamma=settings["blue_detuning_gamma"],
            s0=point["s0"],
            waist_m=point["waist_m"],
            green_exclusion_radius_m=settings["cutoff_radius_m"],
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
        cutoff_intensity = point["s0"] * gaussian_relative_intensity(
            settings["cutoff_radius_m"], point["waist_m"]
        )
        record = {
            "point_index": point_index,
            "label": point["label"],
            "intensity_control": point["intensity_control"],
            "blue_detuning_gamma": settings["blue_detuning_gamma"],
            "blue_s0": point["s0"],
            "blue_waist_mm": point["waist_m"] * 1e3,
            "cutoff_radius_mm": settings["cutoff_radius_m"] * 1e3,
            "nominal_s0_at_cutoff": cutoff_intensity,
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
            f"Completed waist point {point_index + 1}/{len(points)}: "
            f"captured={record['capture_eligible_ever_count']}/{len(states)}",
            flush=True,
        )

    report = {
        "status": "provisional single-pass waist screen; not laboratory-set values",
        "purpose": "separate wider-beam coverage from intensity at the clipping radius",
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
    (output_dir / "single_pass_waist_screen.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def parse_args(argv=None):
    settings = MOT_3D_SINGLE_PASS_WAIST_SCREEN_CONFIG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-atoms", type=int, default=settings["max_atoms"])
    parser.add_argument("--num-shards", type=int, default=settings["num_shards"])
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--npools", type=int, default=1)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=settings["t_max_s"])
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_screen(parse_args())
