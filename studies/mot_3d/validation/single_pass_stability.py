"""Paired single-pass stability and 62-degree/aperture-factorial study."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path

import numpy as np

from config import Geometry, MOT_3D_SIM_CONFIG
from simulations.mot_3d import mot_3d_simulation
from studies.mot_3d.analysis.retention import (
    analyze_results,
    load_shared_ensemble,
    select_particle_shard,
)


ROOT = Path("data/validation/mot_3d/single_pass_stability_v1")
REFERENCE_S0 = 0.20308958176149428
DENSE_S0_VALUES = tuple(np.round(np.arange(0.16, 0.281, 0.01), 8)) + (REFERENCE_S0,)
GREEN_APERTURE_RADIUS_M = 5e-3
BLUE_APERTURE_RADIUS_M = 7.5e-3
VARIANTS = {
    "angle60_unclipped": {"green_full_angle_deg": 60.0, "clipped": False},
    "angle62_unclipped": {"green_full_angle_deg": 62.0, "clipped": False},
    "angle60_clipped": {"green_full_angle_deg": 60.0, "clipped": True},
    "angle62_clipped": {"green_full_angle_deg": 62.0, "clipped": True},
}


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(temporary, path)


def finalist_profile(selection):
    payload = json.loads(Path(selection).read_text())
    if payload["family"] != "single_pass":
        raise ValueError("Expected a single-pass finalist selection.")
    return copy.deepcopy(payload["candidates"][0]["resolved_profile"])


def stability_profile(variant, blue_s0, selection):
    if variant not in VARIANTS:
        raise ValueError(f"Unknown stability variant: {variant}")
    specification = VARIANTS[variant]
    profile = finalist_profile(selection)
    # xz_angle_from_z_deg is half the full included angle between the two
    # positive-z green beams (and likewise between the negative-z pair).
    profile["xz_angle_from_z_deg"] = 0.5 * specification["green_full_angle_deg"]
    profile["399"]["s0"] = float(blue_s0)
    if specification["clipped"]:
        profile["399"]["profile"] = "outer_clipped_gaussian"
        profile["399"]["outer_cutoff_radius_m"] = BLUE_APERTURE_RADIUS_M
        profile["556"]["profile"] = "outer_clipped_gaussian"
        profile["556"]["outer_cutoff_radius_m"] = GREEN_APERTURE_RADIUS_M
    else:
        profile["399"]["profile"] = "gaussian"
        profile["399"].pop("outer_cutoff_radius_m", None)
        profile["556"]["profile"] = "gaussian"
        profile["556"].pop("outer_cutoff_radius_m", None)
    return profile


def study_points():
    points = [
        {"variant": variant, "blue_s0": REFERENCE_S0, "role": "factorial"}
        for variant in VARIANTS
    ]
    points.extend(
        {
            "variant": "angle62_clipped",
            "blue_s0": float(s0),
            "role": "dense_s0_scan",
        }
        for s0 in sorted(set(DENSE_S0_VALUES))
        if not np.isclose(s0, REFERENCE_S0, rtol=0.0, atol=1e-12)
    )
    return points


def _trajectory_features(trajectories):
    center = np.asarray(Geometry.MOT_3D_CENTER_M, dtype=float)
    features = {
        key: np.full(len(trajectories), np.nan)
        for key in (
            "minimum_distance_m",
            "speed_at_closest_approach_m_s",
            "final_distance_m",
            "final_speed_m_s",
            "final_z_m",
            "final_vz_m_s",
        )
    }
    for index, trajectory in enumerate(trajectories):
        states = np.asarray(trajectory.y, dtype=float)
        if states.ndim != 2 or states.shape[0] < 6 or states.shape[1] == 0:
            continue
        distances = np.linalg.norm(states[:3].T - center, axis=1)
        closest = int(np.argmin(distances))
        features["minimum_distance_m"][index] = distances[closest]
        features["speed_at_closest_approach_m_s"][index] = np.linalg.norm(
            states[3:6, closest]
        )
        features["final_distance_m"][index] = distances[-1]
        features["final_speed_m_s"][index] = np.linalg.norm(states[3:6, -1])
        features["final_z_m"][index] = states[2, -1]
        features["final_vz_m_s"][index] = states[5, -1]
    return features


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

    for point_index, point in enumerate(study_points()):
        profile = stability_profile(point["variant"], point["blue_s0"], args.selection)
        stem = f"point_{point_index:02d}"
        npz_path = output_dir / f"{stem}_outcomes.npz"
        print(
            f"STABILITY_START {point_index + 1}/{len(study_points())} "
            f"variant={point['variant']} blue_s0={point['blue_s0']:.8g}",
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
        usable_at_end = np.asarray(analysis["eligible_masks"][:, -1], dtype=bool)
        features = _trajectory_features(trajectories)
        np.savez_compressed(
            npz_path,
            global_particle_indices=global_indices,
            usable_at_end=usable_at_end,
            **features,
        )
        diagnostics = analysis["diagnostics"]
        record = {
            **point,
            "point_index": point_index,
            "green_full_angle_deg": VARIANTS[point["variant"]]["green_full_angle_deg"],
            "hard_apertures_enabled": VARIANTS[point["variant"]]["clipped"],
            "green_aperture_radius_m": (
                GREEN_APERTURE_RADIUS_M
                if VARIANTS[point["variant"]]["clipped"]
                else None
            ),
            "blue_aperture_radius_m": (
                BLUE_APERTURE_RADIUS_M
                if VARIANTS[point["variant"]]["clipped"]
                else None
            ),
            "input_particle_count": len(states),
            "usable_at_end_count": int(usable_at_end.sum()),
            "usable_ever_count": int(np.any(analysis["eligible_masks"], axis=1).sum()),
            "entered_capture_region_count": int(
                diagnostics["entered_capture_region_count"]
            ),
            "slow_inside_count": int(diagnostics["slow_inside_count"]),
            "outcomes_path": str(npz_path),
        }
        records.append(record)
        print(
            f"STABILITY_RESULT variant={point['variant']} "
            f"blue_s0={point['blue_s0']:.8g} "
            f"usable={record['usable_at_end_count']}/{len(states)}",
            flush=True,
        )

    _atomic_json(
        output_dir / "single_pass_stability.json",
        {
            "kind": "single_pass_stability_shard",
            "input_files": [str(path) for path in input_files],
            "selection": str(args.selection),
            "selected_particle_count_before_sharding": len(selected),
            "input_particle_count": len(states),
            "num_shards": args.num_shards,
            "shard_index": args.shard_index,
            "selection_seed": args.seed,
            "simulation_seed": simulation_seed,
            "dt_s": args.dt,
            "t_max_s": args.t_max,
            "records": records,
        },
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        help="2D-MOT survivor-state file or directory used as the shared input ensemble.",
    )
    parser.add_argument(
        "--selection",
        required=True,
        help="Single-pass finalist-selection JSON produced by the active 3D campaign.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-atoms", type=int, default=600)
    parser.add_argument("--num-shards", type=int, default=3)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--npools", type=int, default=200)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=20261005)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
