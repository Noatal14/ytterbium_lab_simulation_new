"""Scan a single entrance slower plus a downstream blue backstop gate."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from config import DEFAULT_RANDOM_SEED, MOT_3D_CONFIGURATIONS, MOT_3D_SIM_CONFIG
from config import MOT_3D_SINGLE_PASS_GATE_FOLLOWUP_CONFIG as STUDY_CONFIG
from simulations.mot_3d import mot_3d_simulation
from studies.analyze_3d_mot_donut_ablation import DEFAULT_INPUT
from studies.compare_3d_mot_retention import (
    analyze_results,
    load_shared_ensemble,
    select_particle_shard,
)


MINUS_Z_TAGS = ("-XZ_1", "-XZ_2")


def candidate_points(settings=None):
    settings = settings or STUDY_CONFIG
    points = [
        {"kind": "full_donut", "label": "full_donut_control"},
        {"kind": "entrance_only", "label": "entrance_gate_only"},
    ]
    points.extend(
        {
            "kind": "entrance_plus_backstop",
            "label": f"backstop_crossing_{crossing * 1e3:g}mm_s0_{s0:g}",
            "backstop_crossing_offset_m": crossing,
            "backstop_s0": s0,
        }
        for crossing in settings["backstop_crossing_offsets_m"]
        for s0 in settings["backstop_s0_values"]
    )
    return tuple(points)


def _base_profile(settings):
    profile = copy.deepcopy(MOT_3D_CONFIGURATIONS["angled_donut"])
    profile["399"].update(
        s0=settings["entrance_blue_s0"],
        detuning_gamma=settings["blue_detuning_gamma"],
        waist_m=settings["blue_waist_m"],
    )
    return profile


def _group(settings, name, profile_kind, crossing, s0, minimum=None, maximum=None):
    center_z = MOT_3D_CONFIGURATIONS["angled_donut"]["center_position_m"][2]
    group = {
        "name": name,
        "axis_tags": MINUS_Z_TAGS,
        "profile": profile_kind,
        "center_offset_m": (0.0, 0.0, crossing),
        "s0": s0,
        "waist_m": settings["blue_waist_m"],
        "inner_cutoff_radius_m": settings["inner_cutoff_radius_m"],
    }
    if minimum is not None:
        group["minimum_lab_z_m"] = center_z + minimum
    if maximum is not None:
        group["maximum_lab_z_m"] = center_z + maximum
    return group


def profile_for_point(point, settings=None):
    """Build one study-only profile; all six green beams remain unchanged."""
    settings = settings or STUDY_CONFIG
    if point["kind"] == "full_donut":
        return copy.deepcopy(MOT_3D_CONFIGURATIONS["angled_donut"])

    profile = _base_profile(settings)
    entrance = _group(
        settings,
        "entrance",
        "upstream_clipped_donut",
        settings["entrance_crossing_offset_m"],
        settings["entrance_blue_s0"],
        maximum=settings["entrance_cutoff_offset_m"],
    )
    groups = [entrance]
    if point["kind"] == "entrance_plus_backstop":
        z_min, z_max = settings["backstop_window_m"]
        groups.append(
            _group(
                settings,
                "downstream_backstop",
                "window_clipped_donut",
                point["backstop_crossing_offset_m"],
                point["backstop_s0"],
                minimum=z_min,
                maximum=z_max,
            )
        )
    profile["399"]["beam_groups"] = groups
    return profile


def run_screen(args):
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
    points = candidate_points()
    records = []
    for index, point in enumerate(points):
        print(
            f"Starting entrance/backstop point {index + 1}/{len(points)}: "
            f"{point['label']}",
            flush=True,
        )
        trajectories, _ = mot_3d_simulation(
            states,
            _3d_mot_config=profile_for_point(point),
            gravity_enabled=True,
            npools=args.npools,
            dt=args.dt,
            t_max=args.t_max,
            seed=simulation_seed,
        )
        analysis = analyze_results(trajectories, time_points)
        usable_ever = np.any(analysis["eligible_masks"], axis=1)
        usable_at_end = analysis["eligible_masks"][:, -1]
        np.savez_compressed(
            output_dir / f"point_{index:02d}_outcomes.npz",
            global_particle_indices=global_indices,
            usable_ever=usable_ever,
            usable_at_end=usable_at_end,
        )
        record = dict(point)
        record.update(
            point_index=index,
            input_particle_count=len(states),
            usable_ever_count=int(usable_ever.sum()),
            usable_at_end_count=int(usable_at_end.sum()),
            peak_usable_count=int(analysis["peak_count"]),
            entered_capture_region_count=int(
                analysis["diagnostics"]["entered_capture_region_count"]
            ),
        )
        records.append(record)
        print(
            f"Completed {point['label']}: usable ever={usable_ever.sum()}/{len(states)}, "
            f"at end={usable_at_end.sum()}/{len(states)}",
            flush=True,
        )
    report = {
        "status": "provisional entrance-slower/downstream-backstop study",
        "input_files": [str(path) for path in input_files],
        "selected_particle_count_before_sharding": len(selected),
        "input_particle_count": len(states),
        "num_shards": args.num_shards,
        "shard_index": args.shard_index,
        "selection_seed": args.seed,
        "dt_s": args.dt,
        "t_max_s": args.t_max,
        "records": records,
    }
    (output_dir / "single_pass_gate_followup.json").write_text(
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
    run_screen(parse_args())
