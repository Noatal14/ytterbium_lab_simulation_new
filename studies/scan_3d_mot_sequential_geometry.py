"""Scan the buildable circular, planar-clipped angled-sequential geometry."""

import argparse
import copy
import csv
import gc
import json
from itertools import product
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from config import DEFAULT_NUM_POOLS, DEFAULT_RANDOM_SEED, MOT_3D_CONFIGURATIONS, MOT_3D_SIM_CONFIG
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from simulations.mot_3d import mot_3d_simulation
from studies.compare_3d_mot_retention import analyze_results, load_shared_ensemble
from studies.scan_3d_mot_blue_slower import (
    _scan_record,
    blue_exposure_diagnostics,
    select_particle_shard,
    slowing_rank_key,
)
from utils.data_paths import AFTER_2D_MOT_DIR


DEFAULT_WAISTS_MM = (3.0, 5.0, 10.0)
DEFAULT_EXCLUSIONS_MM = (5.0, 10.0)
DEFAULT_CROSSINGS_MM = (10.0, 20.0)


def geometry_points(waists_mm, exclusions_mm, crossings_mm):
    """Return validated waist/exclusion/crossing combinations in metres."""
    points = []
    for waist_mm, exclusion_mm, crossing_mm in product(
        waists_mm, exclusions_mm, crossings_mm
    ):
        if min(waist_mm, exclusion_mm, crossing_mm) <= 0.0:
            raise ValueError("All geometry lengths must be positive.")
        if crossing_mm < exclusion_mm:
            raise ValueError("crossing distance must be >= exclusion radius.")
        points.append(tuple(value * 1e-3 for value in (waist_mm, exclusion_mm, crossing_mm)))
    return tuple(points)


def _geometry_record(point, analysis, exposure, center_intensity, crossing_intensity):
    waist_m, exclusion_m, crossing_m = point
    record = _scan_record(
        "angled_sequential",
        MOT_3D_CONFIGURATIONS["angled_sequential"]["399"]["detuning_gamma"],
        MOT_3D_CONFIGURATIONS["angled_sequential"]["399"]["s0"],
        analysis,
        exposure,
    )
    record.update(
        blue_waist_mm=waist_m * 1e3,
        green_exclusion_radius_mm=exclusion_m * 1e3,
        crossing_distance_mm=crossing_m * 1e3,
        summed_blue_intensity_at_mot_center_W_m2=center_intensity,
        summed_blue_intensity_at_crossing_W_m2=crossing_intensity,
    )
    return record


def _plot_scan(records, output_path):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    exclusion_values = sorted({row["green_exclusion_radius_mm"] for row in records})
    crossing_values = sorted({row["crossing_distance_mm"] for row in records})
    if len(exclusion_values) != 2:
        raise ValueError("The summary plot expects exactly two exclusion radii.")
    for ax, exclusion in zip(axes, exclusion_values):
        rows = [row for row in records if row["green_exclusion_radius_mm"] == exclusion]
        for crossing in crossing_values:
            selected = sorted(
                (row for row in rows if row["crossing_distance_mm"] == crossing),
                key=lambda row: row["blue_waist_mm"],
            )
            ax.plot(
                [row["blue_waist_mm"] for row in selected],
                [row["capture_eligible_ever_count"] for row in selected],
                marker="o",
                label=f"crossing {crossing:g} mm",
            )
        ax.set_title(f"protected-core radius {exclusion:g} mm")
        ax.set_xlabel("399-nm circular waist [mm]")
        ax.grid(alpha=0.25)
        ax.legend()
    axes[0].set_ylabel("capture-eligible atoms")
    fig.suptitle("angled_sequential planar-cut geometry scan")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def run_scan(args):
    points = geometry_points(args.waists_mm, args.exclusions_mm, args.crossings_mm)
    selected_states, input_files = load_shared_ensemble(
        args.input, max_atoms=args.max_atoms, seed=args.seed
    )
    states, shard_indices = select_particle_shard(
        selected_states, args.num_shards, args.shard_index
    )
    if not len(states):
        raise ValueError("The selected shard contains no atoms.")
    simulation_seed = int(np.random.SeedSequence([args.seed, args.shard_index]).generate_state(1)[0])
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    records = []

    for index, point in enumerate(points, start=1):
        waist_m, exclusion_m, crossing_m = point
        print(
            f"[{index}/{len(points)}] waist={waist_m*1e3:g} mm, "
            f"exclusion={exclusion_m*1e3:g} mm, crossing={crossing_m*1e3:g} mm"
        )
        profile = copy.deepcopy(MOT_3D_CONFIGURATIONS["angled_sequential"])
        profile["399"].update(
            waist_m=waist_m,
            green_exclusion_radius_m=exclusion_m,
            center_offset_m=(0.0, 0.0, -crossing_m),
        )
        blue_beams = [
            beam for beam in setup_3dmot_lasers(profile) if "3DMOT_399_" in beam.tag
        ]
        center = np.asarray(profile["center_position_m"], dtype=float)
        crossing = center + np.array([0.0, 0.0, -crossing_m])
        center_intensity = float(sum(beam.get_value(center[None, :])[0] for beam in blue_beams))
        crossing_intensity = float(sum(beam.get_value(crossing[None, :])[0] for beam in blue_beams))
        if center_intensity != 0.0 or crossing_intensity <= 0.0:
            raise RuntimeError("Invalid planar cutoff: expected dark center and lit crossing.")
        results, _ = mot_3d_simulation(
            states, _3d_mot_config=profile, gravity_enabled=not args.no_gravity,
            npools=args.npools, dt=args.dt, t_max=args.t_max, seed=simulation_seed,
        )
        analysis = analyze_results(results, time_points)
        exposure = blue_exposure_diagnostics(results, profile, 0.01)
        records.append(_geometry_record(point, analysis, exposure, center_intensity, crossing_intensity))
        del results
        gc.collect()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "sequential_geometry_scan.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    best = max(records, key=slowing_rank_key)
    report = {
        "status": "provisional geometry scan; not laboratory-set values",
        "input_files": [str(path) for path in input_files],
        "selected_particle_count_before_sharding": len(selected_states),
        "input_particle_count": len(states),
        "num_shards": args.num_shards,
        "shard_index": args.shard_index,
        "selected_particle_indices": shard_indices.tolist(),
        "selection_seed": args.seed,
        "simulation_seed": simulation_seed,
        "profiles": ["angled_sequential"],
        "detuning_gamma_values": [float(MOT_3D_CONFIGURATIONS["angled_sequential"]["399"]["detuning_gamma"])],
        "s0_values": [float(MOT_3D_CONFIGURATIONS["angled_sequential"]["399"]["s0"])],
        "blue_waists_mm": [float(value) for value in args.waists_mm],
        "green_exclusion_radii_mm": [float(value) for value in args.exclusions_mm],
        "crossing_distances_mm": [float(value) for value in args.crossings_mm],
        "fixed_blue_operating_point": True,
        "fixed_green_light_and_magnetic_field": True,
        "blue_center_leakage_required_W_m2": 0.0,
        "best": best,
        "records": records,
    }
    (output_dir / "sequential_geometry_scan.json").write_text(json.dumps(report, indent=2) + "\n")
    _plot_scan(records, output_dir / "sequential_geometry_scan.png")
    print(f"Best provisional geometry: {best}")
    return records, best


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(AFTER_2D_MOT_DIR / "final_ensemble_s0_1.47"))
    parser.add_argument("--output-dir", default="data/validation/mot_3d/sequential_geometry_scan")
    parser.add_argument("--waists-mm", nargs="+", type=float, default=list(DEFAULT_WAISTS_MM))
    parser.add_argument("--exclusions-mm", nargs="+", type=float, default=list(DEFAULT_EXCLUSIONS_MM))
    parser.add_argument("--crossings-mm", nargs="+", type=float, default=list(DEFAULT_CROSSINGS_MM))
    parser.add_argument("--max-atoms", type=int)
    parser.add_argument("--num-shards", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=MOT_3D_SIM_CONFIG["t_max_s"])
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument("--no-gravity", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_scan(parse_args())
