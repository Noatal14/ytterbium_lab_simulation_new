"""Screen finite blue-gate sequences against the complete donut shell."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from config import (
    DEFAULT_RANDOM_SEED,
    MOT_3D_BLUE_GATE_SEQUENCE_CONFIG,
    MOT_3D_CONFIGURATIONS,
    MOT_3D_SIM_CONFIG,
)
from simulations.mot_3d import mot_3d_simulation
from studies.analyze_3d_mot_donut_ablation import DEFAULT_INPUT
from studies.compare_3d_mot_retention import (
    analyze_results,
    load_shared_ensemble,
    select_particle_shard,
)


MINUS_Z_TAGS = ("-XZ_1", "-XZ_2")
PLUS_Z_TAGS = ("+XZ_1", "+XZ_2")
VARIANT_ORDER = (
    "full_donut_control",
    "single_minus_z_gate",
    "two_stage_minus_z_gates",
    "minus_z_plus_return_gate",
    "two_stage_plus_return_gate",
)


def _group(name, axis_tags, crossing_offset_m, cutoff_offset_m, settings):
    return {
        "name": name,
        "axis_tags": axis_tags,
        "profile": "upstream_clipped_donut",
        "center_offset_m": (0.0, 0.0, crossing_offset_m),
        "maximum_lab_z_m": (
            MOT_3D_CONFIGURATIONS["angled_donut"]["center_position_m"][2]
            + cutoff_offset_m
        ),
        "s0": settings["blue_s0"],
        "waist_m": settings["blue_waist_m"],
        "inner_cutoff_radius_m": settings["inner_cutoff_radius_m"],
    }


def build_gate_profiles(settings=None):
    """Return study-only profiles with explicitly separated blue gates."""
    settings = settings or MOT_3D_BLUE_GATE_SEQUENCE_CONFIG
    base = copy.deepcopy(MOT_3D_CONFIGURATIONS["angled_donut"])
    base["399"]["s0"] = settings["blue_s0"]
    base["399"]["detuning_gamma"] = settings["blue_detuning_gamma"]
    base["399"]["waist_m"] = settings["blue_waist_m"]

    first = _group(
        "slow_1",
        MINUS_Z_TAGS,
        settings["first_slowing_crossing_offset_m"],
        settings["first_cutoff_offset_m"],
        settings,
    )
    second = _group(
        "slow_2",
        MINUS_Z_TAGS,
        settings["second_slowing_crossing_offset_m"],
        settings["second_cutoff_offset_m"],
        settings,
    )
    returning = _group(
        "return",
        PLUS_Z_TAGS,
        settings["return_crossing_offset_m"],
        settings["return_cutoff_offset_m"],
        settings,
    )

    def gates(*groups):
        profile = copy.deepcopy(base)
        profile["399"]["beam_groups"] = [copy.deepcopy(group) for group in groups]
        return profile

    return {
        "full_donut_control": copy.deepcopy(MOT_3D_CONFIGURATIONS["angled_donut"]),
        "single_minus_z_gate": gates(first),
        "two_stage_minus_z_gates": gates(first, second),
        "minus_z_plus_return_gate": gates(first, returning),
        "two_stage_plus_return_gate": gates(first, second, returning),
    }


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
    records = []
    profiles = build_gate_profiles()

    for index, name in enumerate(VARIANT_ORDER):
        print(f"Starting gate geometry {index + 1}/{len(VARIANT_ORDER)}: {name}", flush=True)
        trajectories, _ = mot_3d_simulation(
            states,
            _3d_mot_config=profiles[name],
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
            output_dir / f"{name}_outcomes.npz",
            global_particle_indices=global_indices,
            usable_ever=usable_ever,
            usable_at_end=usable_at_end,
        )
        diagnostics = analysis["diagnostics"]
        records.append(
            {
                "variant": name,
                "input_particle_count": len(states),
                "usable_ever_count": int(usable_ever.sum()),
                "usable_at_end_count": int(usable_at_end.sum()),
                "peak_usable_count": int(analysis["peak_count"]),
                "entered_capture_region_count": int(
                    diagnostics["entered_capture_region_count"]
                ),
                "minimum_residence_met_count": int(
                    diagnostics["minimum_residence_met_count"]
                ),
            }
        )
        print(
            f"Completed {name}: usable ever={usable_ever.sum()}/{len(states)}, "
            f"at end={usable_at_end.sum()}/{len(states)}",
            flush=True,
        )

    report = {
        "status": "provisional finite-blue-gate geometry study",
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
    (output_dir / "blue_gate_sequence_screen.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def parse_args(argv=None):
    settings = MOT_3D_BLUE_GATE_SEQUENCE_CONFIG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-atoms", type=int, default=settings["max_atoms"])
    parser.add_argument("--num-shards", type=int, default=settings["num_shards"])
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--npools", type=int, default=settings["pbs_ncpus_per_shard"])
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=settings["t_max_s"])
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_screen(parse_args())
