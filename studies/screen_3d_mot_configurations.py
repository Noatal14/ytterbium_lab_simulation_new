"""Fast physics and trajectory screening for candidate 3D-MOT geometries."""

import argparse
import copy
import csv
import gc
import json
from pathlib import Path

import numpy as np
from atomsmltr.simulation.simulator.simbase import get_force_vec

from config import (
    DEFAULT_RANDOM_SEED,
    MOT_3D_CONFIGURATIONS,
    MOT_3D_SCREENING_CONFIG,
    MOT_3D_SIM_CONFIG,
)
from lab_setup.config_builder import build_base_config
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from simulations.mot_3d import mot_3d_simulation
from studies.compare_3d_mot_retention import analyze_results, load_shared_ensemble
from studies.scan_3d_mot_blue_slower import (
    _scan_record,
    blue_exposure_diagnostics,
    select_particle_shard,
)
from utils.data_paths import AFTER_2D_MOT_DIR


def apply_anchor(profile, anchor):
    profile["399"].update(
        s0=float(anchor["blue_s0"]),
        detuning_gamma=float(anchor["blue_detuning_gamma"]),
    )
    profile["556"].update(
        s0=float(anchor["green_s0"]),
        detuning_gamma=float(anchor["green_detuning_gamma"]),
    )
    return profile


def _single_colour_config(profile, colour, gradient, gravity_enabled=False):
    selected = copy.deepcopy(profile)
    selected["399" if colour == "556" else "556"]["enabled"] = False
    _, environment = build_base_config(
        include_2d_mot=False,
        include_zeeman=False,
        include_3dmot=True,
        _3d_mot_config=selected,
        _3d_mot_gradient_G_cm=gradient,
        gravity_enabled=gravity_enabled,
        zones=[],
    )
    return environment


def _green_equilibrium(config, center, search_half_width_m=5.0e-3):
    """Find a stable force zero along the project gravity axis (lab x)."""
    offsets = np.linspace(-search_half_width_m, search_half_width_m, 201)
    positions = np.zeros((len(offsets), 6), dtype=float)
    positions[:, :3] = center
    positions[:, 0] += offsets
    forces = np.asarray(get_force_vec(positions, config))[:, 0]
    candidates = np.flatnonzero((forces[:-1] > 0.0) & (forces[1:] < 0.0))
    if not len(candidates):
        return None
    index = int(candidates[np.argmin(np.abs(offsets[candidates]))])
    lower = positions[index].copy()
    upper = positions[index + 1].copy()
    for _ in range(40):
        midpoint = 0.5 * (lower + upper)
        force = float(get_force_vec(midpoint[None, :], config)[0, 0])
        if force > 0.0:
            lower = midpoint
        else:
            upper = midpoint
    return 0.5 * (lower[:3] + upper[:3])


def static_force_diagnostics(profile, sample_states, gradient, displacement_m):
    center = np.asarray(profile["center_position_m"], dtype=float)
    green_config = _single_colour_config(profile, "556", gradient, gravity_enabled=True)
    equilibrium = _green_equilibrium(green_config, center)
    evaluation_center = equilibrium if equilibrium is not None else center
    diagonal_gradients = []
    restoring = []
    for axis in range(3):
        displacement = np.zeros(3)
        displacement[axis] = displacement_m
        plus = np.array([[*(evaluation_center + displacement), 0.0, 0.0, 0.0]])
        minus = np.array([[*(evaluation_center - displacement), 0.0, 0.0, 0.0]])
        force_plus = float(get_force_vec(plus, green_config)[0, axis])
        force_minus = float(get_force_vec(minus, green_config)[0, axis])
        diagonal_gradients.append((force_plus - force_minus) / (2.0 * displacement_m))
        restoring.append(force_plus < 0.0 and force_minus > 0.0)

    blue_config = _single_colour_config(profile, "399", gradient)
    blue_forces = np.asarray(get_force_vec(np.asarray(sample_states), blue_config))
    longitudinal = blue_forces[:, 2]
    transverse = np.linalg.norm(blue_forces[:, :2], axis=1)
    mean_longitudinal = float(np.mean(longitudinal))
    mean_transverse = float(np.mean(transverse))

    blue_beams = [
        beam for beam in setup_3dmot_lasers(profile) if "3DMOT_399_" in beam.tag
    ]
    center_intensity = float(
        sum(beam.get_value(center[None, :])[0] for beam in blue_beams)
    )
    return {
        "green_force_gradient_x_N_m": float(diagonal_gradients[0]),
        "green_force_gradient_y_N_m": float(diagonal_gradients[1]),
        "green_force_gradient_z_N_m": float(diagonal_gradients[2]),
        "green_restoring_x": bool(restoring[0]),
        "green_restoring_y": bool(restoring[1]),
        "green_restoring_z": bool(restoring[2]),
        "green_restoring_all_axes": bool(all(restoring)),
        "green_equilibrium_found": equilibrium is not None,
        "green_equilibrium_x_offset_m": (
            float(evaluation_center[0] - center[0]) if equilibrium is not None else None
        ),
        "blue_center_intensity_W_m2": center_intensity,
        "initial_blue_mean_force_z_N": mean_longitudinal,
        "initial_blue_decelerating_fraction": float(np.mean(longitudinal < 0.0)),
        "initial_blue_mean_transverse_force_N": mean_transverse,
        "initial_blue_transverse_to_longitudinal_ratio": (
            mean_transverse / abs(mean_longitudinal)
            if mean_longitudinal != 0.0 else None
        ),
    }


def screening_rank_key(record):
    speed = record.get(
        "median_minimum_speed_inside_m_s",
        record.get("weighted_mean_of_shard_medians_minimum_speed_inside_m_s"),
    )
    delta_vz = record.get(
        "median_delta_vz_during_blue_exposure_m_s",
        record.get("weighted_mean_of_shard_medians_delta_vz_during_blue_exposure_m_s"),
    )
    return (
        record["green_restoring_all_axes"],
        record["capture_eligible_ever_count"],
        record["slow_inside_count"],
        record["minimum_residence_met_count"],
        -(speed if speed is not None else float("inf")),
        -(delta_vz if delta_vz is not None else float("inf")),
        record["blue_exposed_particle_count"],
    )


def run_screen(args):
    unknown = sorted(set(args.profiles) - set(MOT_3D_CONFIGURATIONS))
    if unknown:
        raise ValueError(f"Unknown 3D-MOT profiles: {unknown}")
    anchors = tuple(MOT_3D_SCREENING_CONFIG["anchors"])
    selected, input_files = load_shared_ensemble(args.input, args.max_atoms, args.seed)
    states, shard_indices = select_particle_shard(selected, args.num_shards, args.shard_index)
    if not len(states):
        raise ValueError("The selected screening shard contains no atoms.")
    simulation_seed = int(np.random.SeedSequence([args.seed, args.shard_index]).generate_state(1)[0])
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    records = []
    total = len(args.profiles) * len(anchors)
    for point_index, (profile_name, anchor_index) in enumerate(
        ((profile, index) for profile in args.profiles for index in range(len(anchors))), start=1
    ):
        anchor = anchors[anchor_index]
        profile = apply_anchor(copy.deepcopy(MOT_3D_CONFIGURATIONS[profile_name]), anchor)
        gradient = float(anchor["gradient_G_cm"])
        print(f"[{point_index}/{total}] screening {profile_name}, anchor {anchor_index + 1}", flush=True)
        static = static_force_diagnostics(profile, states, gradient, args.force_displacement)
        results, _ = mot_3d_simulation(
            states, _3d_mot_config=profile, gravity_enabled=not args.no_gravity,
            npools=args.npools, dt=args.dt, t_max=args.t_max,
            seed=simulation_seed, magnetic_gradient_G_cm=gradient,
        )
        analysis = analyze_results(results, time_points)
        exposure = blue_exposure_diagnostics(results, profile, args.exposure_threshold_fraction)
        record = _scan_record(
            profile_name, anchor["blue_detuning_gamma"], anchor["blue_s0"], analysis, exposure
        )
        record.update(
            screening_anchor=anchor_index + 1,
            gradient_G_cm=gradient,
            green_s0=float(anchor["green_s0"]),
            green_detuning_gamma=float(anchor["green_detuning_gamma"]),
            **static,
        )
        records.append(record)
        print(
            f"  restoring={static['green_restoring_all_axes']}, "
            f"exposed={record['blue_exposed_particle_count']}, "
            f"slow={record['slow_inside_count']}, eligible={record['capture_eligible_ever_count']}",
            flush=True,
        )
        del results
        gc.collect()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "screening_scan.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    report = {
        "purpose": "fast rejection screening; not parameter optimization",
        "status": "all anchors are provisional comparison probes",
        "input_files": [str(path) for path in input_files],
        "selected_particle_count_before_sharding": len(selected),
        "input_particle_count": len(states),
        "num_shards": args.num_shards,
        "shard_index": args.shard_index,
        "selected_particle_indices": shard_indices.tolist(),
        "selection_seed": args.seed,
        "simulation_seed": simulation_seed,
        "profiles": list(args.profiles),
        "detuning_gamma_values": sorted({float(point["blue_detuning_gamma"]) for point in anchors}),
        "s0_values": sorted({float(point["blue_s0"]) for point in anchors}),
        "parameter_pairs": [
            {"s0": float(point["blue_s0"]), "detuning_gamma": float(point["blue_detuning_gamma"])}
            for point in anchors
        ],
        "gradient_G_cm_values": sorted({float(point["gradient_G_cm"]) for point in anchors}),
        "green_s0_values": sorted({float(point["green_s0"]) for point in anchors}),
        "green_detuning_gamma_values": sorted({float(point["green_detuning_gamma"]) for point in anchors}),
        "anchors": anchors,
        "dt_s": args.dt,
        "t_max_s": args.t_max,
        "force_displacement_m": args.force_displacement,
        "records": records,
        "best_by_profile": {
            name: max((row for row in records if row["profile"] == name), key=screening_rank_key)
            for name in args.profiles
        },
    }
    (output_dir / "screening_scan.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Saved screening report: {output_dir / 'screening_scan.json'}", flush=True)
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(AFTER_2D_MOT_DIR / "final_ensemble_s0_1.47"))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--profiles", nargs="+", default=list(MOT_3D_CONFIGURATIONS))
    parser.add_argument("--max-atoms", type=int, default=MOT_3D_SCREENING_CONFIG["max_atoms"])
    parser.add_argument("--num-shards", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--npools", type=int, default=1)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=MOT_3D_SIM_CONFIG["t_max_s"])
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument("--force-displacement", type=float, default=MOT_3D_SCREENING_CONFIG["force_displacement_m"])
    parser.add_argument("--exposure-threshold-fraction", type=float, default=MOT_3D_SCREENING_CONFIG["blue_exposure_threshold_fraction"])
    parser.add_argument("--no-gravity", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_screen(parse_args())
