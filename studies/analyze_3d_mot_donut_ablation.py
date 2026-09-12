"""Run causal blue-beam ablations of the 3D-MOT donut geometry."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from config import (
    DEFAULT_RANDOM_SEED,
    Geometry,
    MOT_3D_CONFIGURATIONS,
    MOT_3D_DONUT_ABLATION_CONFIG,
    MOT_3D_SIM_CONFIG,
)
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from simulations.mot_3d import mot_3d_simulation
from studies.compare_3d_mot_retention import (
    _json_ready_analysis,
    analyze_results,
    load_shared_ensemble,
    select_particle_shard,
)
from utils.data_paths import AFTER_2D_MOT_DIR


DEFAULT_INPUT = AFTER_2D_MOT_DIR / "final_ensemble_s0_1.47"
VARIANT_ORDER = (
    "full_donut",
    "without_positive_z_blue",
    "without_transverse_y_blue",
    "counterpropagating_pair_shell",
    "single_pass_counterpropagating_pair",
)
AXIS_TAGS = ("+XZ_1", "-XZ_1", "+XZ_2", "-XZ_2", "+Y", "-Y")


def build_ablation_profiles():
    """Derive study-only profiles without registering new configurations."""
    base = copy.deepcopy(MOT_3D_CONFIGURATIONS["angled_donut"])

    def variant(enabled_blue):
        profile = copy.deepcopy(base)
        profile["beam_components"] = {
            tag: {"399_enabled": tag in enabled_blue, "556_enabled": True}
            for tag in AXIS_TAGS
        }
        return profile

    profiles = {
        "full_donut": copy.deepcopy(base),
        "without_positive_z_blue": variant({"-XZ_1", "-XZ_2", "+Y", "-Y"}),
        "without_transverse_y_blue": variant({"+XZ_1", "-XZ_1", "+XZ_2", "-XZ_2"}),
        "counterpropagating_pair_shell": variant({"-XZ_1", "-XZ_2"}),
        "single_pass_counterpropagating_pair": variant({"-XZ_1", "-XZ_2"}),
    }
    single_pass = profiles["single_pass_counterpropagating_pair"]
    single_pass["399"]["profile"] = "upstream_clipped_donut"
    single_pass["399"]["green_exclusion_radius_m"] = MOT_3D_DONUT_ABLATION_CONFIG[
        "single_pass_cutoff_upstream_m"
    ]
    return profiles


def _blue_intensities(profile, trajectory):
    states = np.asarray(trajectory.y, dtype=float)
    positions = states[:3].T
    beams = [beam for beam in setup_3dmot_lasers(profile) if "3DMOT_399_" in beam.tag]
    values = np.vstack([np.asarray(beam.get_value(positions), dtype=float) for beam in beams])
    return [beam.tag.removeprefix("3DMOT_399_") for beam in beams], values


def _exposure_episode_count(intensities):
    total = np.asarray(intensities, dtype=float).sum(axis=0)
    if not total.size or total.max() <= 0.0:
        return 0
    exposed = total >= MOT_3D_DONUT_ABLATION_CONFIG[
        "blue_exposure_threshold_fraction"
    ] * total.max()
    return int(exposed[0]) + int(np.count_nonzero((~exposed[:-1]) & exposed[1:]))


def _save_representative(output_dir, profiles, results, analyses, global_indices):
    full_ever = np.any(analyses["full_donut"]["eligible_masks"], axis=1)
    single_ever = np.any(
        analyses["single_pass_counterpropagating_pair"]["eligible_masks"], axis=1
    )
    candidates = np.flatnonzero(full_ever & ~single_ever)
    qualifies = bool(candidates.size)
    if not candidates.size:
        candidates = np.flatnonzero(full_ever)
    if not candidates.size:
        return None

    scored = []
    for local_index in candidates:
        _, intensities = _blue_intensities(
            profiles["full_donut"], results["full_donut"][local_index]
        )
        scored.append((_exposure_episode_count(intensities), int(local_index)))
    episode_count, local_index = max(scored)

    arrays = {}
    for name in VARIANT_ORDER:
        trajectory = results[name][local_index]
        arrays[f"{name}__time_s"] = np.asarray(trajectory.t, dtype=float)
        arrays[f"{name}__state"] = np.asarray(trajectory.y, dtype=float)
    tags, intensities = _blue_intensities(
        profiles["full_donut"], results["full_donut"][local_index]
    )
    arrays["full_donut__blue_intensity_W_m2"] = intensities
    path = output_dir / "representative_trajectory.npz"
    np.savez_compressed(path, **arrays)
    return {
        "global_particle_index": int(global_indices[local_index]),
        "qualifies_full_captured_single_pass_failed": qualifies,
        "full_donut_blue_exposure_episode_count": episode_count,
        "full_donut_blue_beam_tags": tags,
        "data_file": str(path),
    }


def run_study(args):
    selected, input_files = load_shared_ensemble(args.input, args.max_atoms, args.seed)
    states, global_indices = select_particle_shard(selected, args.num_shards, args.shard_index)
    if not len(states):
        raise ValueError("The selected shard contains no atoms.")
    profiles = build_ablation_profiles()
    simulation_seed = int(
        np.random.SeedSequence([args.seed, args.shard_index]).generate_state(1)[0]
    )
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    results = {}
    analyses = {}
    for index, name in enumerate(VARIANT_ORDER, start=1):
        print(f"Starting donut ablation {index}/{len(VARIANT_ORDER)}: {name}", flush=True)
        result, _ = mot_3d_simulation(
            states,
            _3d_mot_config=profiles[name],
            gravity_enabled=True,
            npools=args.npools,
            dt=args.dt,
            t_max=args.t_max,
            seed=simulation_seed,
        )
        results[name] = result
        analyses[name] = analyze_results(result, time_points)
        print(
            f"Completed {name}: peak={analyses[name]['peak_count']}, "
            f"eligible ever={np.any(analyses[name]['eligible_masks'], axis=1).sum()}",
            flush=True,
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, analysis in analyses.items():
        np.savez_compressed(
            output_dir / f"{name}_masks.npz",
            inside_masks=analysis["inside_masks"],
            eligible_masks=analysis["eligible_masks"],
        )
    representative = _save_representative(
        output_dir, profiles, results, analyses, global_indices
    )
    report = {
        "purpose": "causal ablation of blue-beam functions in angled_donut",
        "input_files": [str(path) for path in input_files],
        "input_particle_count": len(states),
        "selected_particle_count_before_sharding": len(selected),
        "num_shards": args.num_shards,
        "shard_index": args.shard_index,
        "selected_particle_indices": global_indices.tolist(),
        "selection_seed": args.seed,
        "simulation_seed": simulation_seed,
        "dt_s": args.dt,
        "t_max_s": args.t_max,
        "time_points_s": time_points.tolist(),
        "variants": list(VARIANT_ORDER),
        "results": {name: _json_ready_analysis(value) for name, value in analyses.items()},
        "representative": representative,
    }
    (output_dir / "ablation_summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-atoms", type=int, default=MOT_3D_DONUT_ABLATION_CONFIG["max_atoms"])
    parser.add_argument("--num-shards", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--npools", type=int, default=1)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=MOT_3D_SIM_CONFIG["t_max_s"])
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_study(parse_args())
