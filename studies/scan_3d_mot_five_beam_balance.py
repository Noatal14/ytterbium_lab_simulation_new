"""Scan only the unpaired lower green beam intensity in five_beam_gravity."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np
from atomsmltr.simulation.simulator.simbase import get_force_vec

from config import (
    DEFAULT_RANDOM_SEED,
    MOT_3D_CONFIGURATIONS,
    MOT_3D_FIVE_BEAM_BALANCE_SCREEN_CONFIG,
    MOT_3D_SIM_CONFIG,
)
from lab_setup.config_builder import build_base_config
from simulations.mot_3d import mot_3d_simulation
from studies.analyze_3d_mot_donut_ablation import DEFAULT_INPUT
from studies.compare_3d_mot_retention import (
    analyze_results,
    load_shared_ensemble,
    select_particle_shard,
)


def profile_with_lower_green_s0(lower_s0):
    """Return five-beam profile varying only the lower-source (+x) green beam."""
    lower_s0 = float(lower_s0)
    if not np.isfinite(lower_s0) or lower_s0 <= 0.0:
        raise ValueError("The lower green-beam s0 must be finite and positive.")
    profile = copy.deepcopy(MOT_3D_CONFIGURATIONS["five_beam_gravity"])
    profile["556"]["s0_by_axis"] = {"+X": lower_s0}
    return profile


def _green_gravity_force_x(profile, displacement_x_m):
    green_only = copy.deepcopy(profile)
    green_only["399"]["enabled"] = False
    _, simulation_config = build_base_config(
        include_2d_mot=False,
        include_zeeman=False,
        include_3dmot=True,
        _3d_mot_config=green_only,
        gravity_enabled=True,
        zones=[],
    )
    center = np.asarray(green_only["center_position_m"], dtype=float)
    position = center + np.array([displacement_x_m, 0.0, 0.0])
    state = np.array([[*position, 0.0, 0.0, 0.0]], dtype=float)
    return float(get_force_vec(state, simulation_config)[0, 0])


def equilibrium_displacement_m(profile, bounds_m=None):
    """Locate the nearest stable x-force zero including gravity."""
    bounds_m = bounds_m or MOT_3D_FIVE_BEAM_BALANCE_SCREEN_CONFIG[
        "equilibrium_search_bounds_m"
    ]
    samples = np.linspace(float(bounds_m[0]), float(bounds_m[1]), 201)
    forces = np.asarray([_green_gravity_force_x(profile, x) for x in samples])
    candidates = []
    for index in range(len(samples) - 1):
        if forces[index] >= 0.0 and forces[index + 1] <= 0.0:
            lower, upper = samples[index], samples[index + 1]
            for _ in range(45):
                middle = 0.5 * (lower + upper)
                if _green_gravity_force_x(profile, middle) > 0.0:
                    lower = middle
                else:
                    upper = middle
            candidates.append(0.5 * (lower + upper))
    if not candidates:
        return None
    return float(min(candidates, key=abs))


def usable_masks(analysis):
    """Return historical-ever and primary final instantaneous masks."""
    eligible = np.asarray(analysis["eligible_masks"], dtype=bool)
    return np.any(eligible, axis=1), eligible[:, -1]


def run_screen(args):
    settings = MOT_3D_FIVE_BEAM_BALANCE_SCREEN_CONFIG
    values = tuple(float(value) for value in args.lower_green_s0_values)
    if not values or any(not np.isfinite(value) or value <= 0.0 for value in values):
        raise ValueError("All lower green-beam s0 candidates must be finite and positive.")
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
    records = []

    for point_index, lower_s0 in enumerate(values):
        print(
            f"Starting five-beam balance point {point_index + 1}/{len(values)}: "
            f"lower +X green s0={lower_s0:g}",
            flush=True,
        )
        profile = profile_with_lower_green_s0(lower_s0)
        equilibrium = equilibrium_displacement_m(profile)
        force_at_center = _green_gravity_force_x(profile, 0.0)
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
        usable_ever, usable_at_end = usable_masks(analysis)
        np.savez_compressed(
            output_dir / f"point_{point_index:02d}_outcomes.npz",
            global_particle_indices=global_indices,
            usable_ever=usable_ever,
            usable_at_end=usable_at_end,
        )
        record = {
            "point_index": point_index,
            "lower_green_s0": lower_s0,
            "paired_yz_green_s0": float(profile["556"]["s0"]),
            "green_detuning_gamma": float(profile["556"]["detuning_gamma"]),
            "net_force_x_at_center_N": force_at_center,
            "equilibrium_displacement_x_mm": (
                None if equilibrium is None else equilibrium * 1e3
            ),
            "input_particle_count": len(states),
            "usable_ever_count": int(usable_ever.sum()),
            "usable_at_end_count": int(usable_at_end.sum()),
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
            f"Completed point {point_index + 1}/{len(values)}: "
            f"usable ever={record['usable_ever_count']}/{len(states)}, "
            f"at end={record['usable_at_end_count']}/{len(states)}, "
            f"equilibrium x={record['equilibrium_displacement_x_mm']:.4g} mm",
            flush=True,
        )

    report = {
        "status": "provisional five-beam balance screen; not laboratory-set values",
        "purpose": "vary only the unpaired lower green beam to control gravity balance",
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
    (output_dir / "five_beam_balance_screen.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def parse_args(argv=None):
    settings = MOT_3D_FIVE_BEAM_BALANCE_SCREEN_CONFIG
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
        "--lower-green-s0-values",
        nargs="+",
        type=float,
        default=list(settings["lower_green_s0_values"]),
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_screen(parse_args())
