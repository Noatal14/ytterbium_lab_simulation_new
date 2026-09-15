"""Run a compact, paired decision screen for the corrected five-beam MOT."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from config import (
    DEFAULT_RANDOM_SEED,
    MOT_3D_CONFIGURATIONS,
    MOT_3D_FIVE_BEAM_DECISION_SCREEN_CONFIG as STUDY_CONFIG,
    MOT_3D_FIVE_BEAM_LOCAL_GRID_CONFIG as LOCAL_GRID_CONFIG,
    MOT_3D_FIVE_BEAM_REFINED_SCREEN_CONFIG as REFINED_CONFIG,
    MOT_3D_SIM_CONFIG,
)
from simulations.mot_3d import mot_3d_simulation
from studies.analyze_3d_mot_donut_ablation import DEFAULT_INPUT
from studies.compare_3d_mot_retention import (
    analyze_results,
    load_shared_ensemble,
    select_particle_shard,
)


FIELDS = (
    "label",
    "blue_s0",
    "blue_detuning_gamma",
    "gradient_G_cm",
    "paired_green_s0",
    "lower_green_s0",
    "green_detuning_gamma",
)


def candidate_points(settings=None):
    settings = settings or STUDY_CONFIG
    points = [{"kind": "full_donut", "label": "full_donut_control"}]
    for values in settings["points"]:
        point = dict(zip(FIELDS, values))
        point["kind"] = "five_beam_gravity"
        points.append(point)
    return tuple(points)


def profile_for_point(point):
    if point["kind"] == "full_donut":
        return copy.deepcopy(MOT_3D_CONFIGURATIONS["angled_donut"])
    profile = copy.deepcopy(MOT_3D_CONFIGURATIONS["five_beam_gravity"])
    profile["399"]["s0"] = float(point["blue_s0"])
    profile["399"]["detuning_gamma"] = float(point["blue_detuning_gamma"])
    profile["556"]["s0"] = float(point["paired_green_s0"])
    profile["556"]["s0_by_axis"] = {"+X": float(point["lower_green_s0"])}
    profile["556"]["detuning_gamma"] = float(point["green_detuning_gamma"])
    profile["magnetic_gradient_G_cm"] = float(point["gradient_G_cm"])
    return profile


def run_screen(args):
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
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.local_grid:
        settings = LOCAL_GRID_CONFIG
        screen_stage = "local_grid"
    elif args.refined:
        settings = REFINED_CONFIG
        screen_stage = "refined"
    else:
        settings = STUDY_CONFIG
        screen_stage = "initial"
    points = candidate_points(settings)
    records = []
    for index, point in enumerate(points):
        print(
            f"Starting five-beam decision point {index + 1}/{len(points)}: "
            f"{point['label']}",
            flush=True,
        )
        profile = profile_for_point(point)
        trajectories, _ = mot_3d_simulation(
            states,
            _3d_mot_config=profile,
            gravity_enabled=True,
            npools=args.npools,
            dt=args.dt,
            t_max=args.t_max,
            seed=simulation_seed,
            magnetic_gradient_G_cm=profile["magnetic_gradient_G_cm"],
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
            slow_inside_count=int(analysis["diagnostics"]["slow_inside_count"]),
        )
        records.append(record)
        print(
            f"Completed {point['label']}: usable ever={usable_ever.sum()}/{len(states)}, "
            f"at end={usable_at_end.sum()}/{len(states)}",
            flush=True,
        )
    report = {
        "status": "provisional corrected-five-beam decision screen",
        "screen_stage": screen_stage,
        "purpose": "paired 100-ms screen against the full-donut control",
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
    (output_dir / "five_beam_decision_screen.json").write_text(
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
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument("--refined", action="store_true")
    stage.add_argument("--local-grid", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_screen(parse_args())
