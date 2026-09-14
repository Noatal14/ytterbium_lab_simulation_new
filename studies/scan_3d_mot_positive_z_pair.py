"""Compare shell and tuned single-pass versions of the blue +z pair."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from config import (
    DEFAULT_RANDOM_SEED,
    MOT_3D_CONFIGURATIONS,
    MOT_3D_POSITIVE_Z_PAIR_SCREEN_CONFIG,
    MOT_3D_SIM_CONFIG,
)
from simulations.mot_3d import mot_3d_simulation
from studies.analyze_3d_mot_donut_ablation import DEFAULT_INPUT
from studies.compare_3d_mot_retention import (
    analyze_results,
    load_shared_ensemble,
    select_particle_shard,
)
from studies.scan_3d_mot_single_pass_screen import screen_points


POSITIVE_Z_BLUE_TAGS = {"+XZ_1", "+XZ_2"}
ALL_ANGLED_TAGS = ("+XZ_1", "-XZ_1", "+XZ_2", "-XZ_2", "+Y", "-Y")


def positive_z_pair_profiles():
    """Build study-only profiles; do not register new MOT configurations."""
    shell = copy.deepcopy(MOT_3D_CONFIGURATIONS["angled_donut"])
    shell["beam_components"] = {
        tag: {
            "399_enabled": tag in POSITIVE_Z_BLUE_TAGS,
            "556_enabled": True,
        }
        for tag in ALL_ANGLED_TAGS
    }
    single_pass = copy.deepcopy(shell)
    single_pass["399"]["profile"] = "upstream_clipped_donut"
    single_pass["399"]["green_exclusion_radius_m"] = (
        MOT_3D_POSITIVE_Z_PAIR_SCREEN_CONFIG["single_pass_cutoff_upstream_m"]
    )
    return {"positive_z_pair_shell": shell, "positive_z_pair_single_pass": single_pass}


def candidate_points(settings=None):
    settings = settings or MOT_3D_POSITIVE_Z_PAIR_SCREEN_CONFIG
    shell = positive_z_pair_profiles()["positive_z_pair_shell"]
    points = [
        {
            "kind": "shell_control",
            "label": "positive_z_pair_shell",
            "detuning_gamma": float(shell["399"]["detuning_gamma"]),
            "s0": float(shell["399"]["s0"]),
        }
    ]
    points.extend(
        {
            "kind": "single_pass",
            "label": f"single_pass_det{detuning:g}_s0_{s0:g}",
            "detuning_gamma": detuning,
            "s0": s0,
        }
        for detuning, s0 in screen_points(
            settings["blue_detuning_gamma_values"], settings["blue_s0_values"]
        )
    )
    return tuple(points)


def run_screen(args):
    settings = MOT_3D_POSITIVE_Z_PAIR_SCREEN_CONFIG
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
    profiles = positive_z_pair_profiles()
    points = candidate_points()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []

    for point_index, point in enumerate(points):
        print(
            f"Starting +z-pair point {point_index + 1}/{len(points)}: "
            f"{point['kind']}, detuning={point['detuning_gamma']:g} Gamma, "
            f"s0={point['s0']:g}",
            flush=True,
        )
        profile_key = (
            "positive_z_pair_shell"
            if point["kind"] == "shell_control"
            else "positive_z_pair_single_pass"
        )
        profile = copy.deepcopy(profiles[profile_key])
        profile["399"].update(
            detuning_gamma=point["detuning_gamma"],
            s0=point["s0"],
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
            "kind": point["kind"],
            "label": point["label"],
            "blue_detuning_gamma": point["detuning_gamma"],
            "blue_s0": point["s0"],
            "blue_waist_mm": settings["fixed_blue_waist_m"] * 1e3,
            "input_particle_count": len(states),
            "capture_eligible_ever_count": int(captured.sum()),
            "peak_capture_eligible_count": int(analysis["peak_count"]),
            "entered_capture_region_count": int(
                analysis["diagnostics"]["entered_capture_region_count"]
            ),
            "slow_inside_count": int(analysis["diagnostics"]["slow_inside_count"]),
            "minimum_residence_met_count": int(
                analysis["diagnostics"]["minimum_residence_met_count"]
            ),
        }
        records.append(record)
        print(
            f"Completed point {point_index + 1}/{len(points)}: "
            f"captured={record['capture_eligible_ever_count']}/{len(states)}",
            flush=True,
        )

    report = {
        "status": "provisional +z blue-pair study; not laboratory-set values",
        "purpose": "test the removed +z-propagating pair alone as shell and single pass",
        "blue_propagation_vectors": [
            [0.5, 0.0, np.sqrt(3.0) / 2.0],
            [-0.5, 0.0, np.sqrt(3.0) / 2.0],
        ],
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
    (output_dir / "positive_z_pair_screen.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def parse_args(argv=None):
    settings = MOT_3D_POSITIVE_Z_PAIR_SCREEN_CONFIG
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
