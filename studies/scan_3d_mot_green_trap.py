"""Scan provisional 556-nm MOT parameters at fixed blue and field settings."""

import argparse
import copy
import csv
import gc
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from config import (
    DEFAULT_NUM_POOLS,
    DEFAULT_RANDOM_SEED,
    MOT_3D_CONFIGURATIONS,
    MOT_3D_SIM_CONFIG,
)
from simulations.mot_3d import mot_3d_simulation
from studies.compare_3d_mot_retention import analyze_results, load_shared_ensemble
from studies.scan_3d_mot_blue_slower import (
    _scan_record,
    blue_exposure_diagnostics,
    select_particle_shard,
)
from utils.data_paths import AFTER_2D_MOT_DIR


FIXED_BLUE_S0 = 0.6
FIXED_BLUE_DETUNING_GAMMA = -1.65
FIXED_GRADIENT_G_CM = 10.0
DEFAULT_GREEN_S0_VALUES = (1.0, 3.0, 5.0, 10.0, 20.0)
DEFAULT_GREEN_DETUNINGS_GAMMA = (-20.0, -15.0, -10.0, -5.0, -2.0)


def green_rank_key(record):
    """Rank trapping points without claiming an exponential lifetime."""
    return (
        record["capture_eligible_ever_count"],
        record["peak_capture_eligible_count"],
        record["minimum_residence_met_count"],
        record["slow_inside_count"],
        record["entered_capture_region_count"],
    )


def _grid(records, s0_values, detunings, field):
    lookup = {
        (row["green_s0"], row["green_detuning_gamma"]): row[field]
        for row in records
    }
    return np.asarray(
        [[lookup[(s0, detuning)] for detuning in detunings] for s0 in s0_values]
    )


def plot_green_scan(records, output_path):
    s0_values = sorted({row["green_s0"] for row in records})
    detunings = sorted({row["green_detuning_gamma"] for row in records})
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    fields = (
        ("capture_eligible_ever_count", "Atoms satisfying full capture criterion"),
        ("minimum_residence_met_count", "Atoms meeting residence criterion"),
    )
    def bounds(values):
        if len(values) == 1:
            padding = max(abs(values[0]) * 0.05, 0.5)
            return values[0] - padding, values[0] + padding
        return min(values), max(values)

    detuning_bounds = bounds(detunings)
    s0_bounds = bounds(s0_values)
    extent = [*detuning_bounds, *s0_bounds]
    for axis, (field, title) in zip(axes, fields):
        image = axis.imshow(
            _grid(records, s0_values, detunings, field),
            origin="lower",
            aspect="auto",
            interpolation="nearest",
            extent=extent,
        )
        axis.set_title(title)
        axis.set_xlabel("556-nm detuning [Gamma]")
        axis.set_ylabel("556-nm s0")
        axis.set_xticks(detunings)
        axis.set_yticks(s0_values)
        fig.colorbar(image, ax=axis, label="atom count")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def run_scan(args):
    if args.profile not in MOT_3D_CONFIGURATIONS:
        raise ValueError(f"Unknown 3D-MOT profile: {args.profile}")
    green_s0_values = tuple(sorted(set(args.green_s0_values)))
    green_detunings = tuple(sorted(set(args.green_detuning_gamma_values)))
    if not green_s0_values or not green_detunings:
        raise ValueError("Green s0 and detuning grids must not be empty.")
    if any(value <= 0 for value in green_s0_values):
        raise ValueError("Every green s0 value must be positive.")
    if any(value >= 0 for value in green_detunings):
        raise ValueError("This MOT scan requires red green-light detunings.")

    selected_states, input_files = load_shared_ensemble(
        args.input, max_atoms=args.max_atoms, seed=args.seed
    )
    states, shard_indices = select_particle_shard(
        selected_states, args.num_shards, args.shard_index
    )
    if not len(states):
        raise ValueError("The selected shard contains no atoms.")
    simulation_seed = int(
        np.random.SeedSequence([args.seed, args.shard_index]).generate_state(1)[0]
    )
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    records = []
    total_points = len(green_s0_values) * len(green_detunings)
    point_index = 0
    for green_s0 in green_s0_values:
        for green_detuning in green_detunings:
            point_index += 1
            print(
                f"[{point_index}/{total_points}] {args.profile}: 556 s0={green_s0:g}, "
                f"detuning={green_detuning:g} Gamma"
            )
            profile = copy.deepcopy(MOT_3D_CONFIGURATIONS[args.profile])
            profile["399"]["s0"] = FIXED_BLUE_S0
            profile["399"]["detuning_gamma"] = FIXED_BLUE_DETUNING_GAMMA
            profile["556"]["s0"] = float(green_s0)
            profile["556"]["detuning_gamma"] = float(green_detuning)
            results, _ = mot_3d_simulation(
                states,
                _3d_mot_config=profile,
                gravity_enabled=not args.no_gravity,
                npools=args.npools,
                dt=args.dt,
                t_max=args.t_max,
                seed=simulation_seed,
                magnetic_gradient_G_cm=FIXED_GRADIENT_G_CM,
            )
            analysis = analyze_results(results, time_points)
            exposure = blue_exposure_diagnostics(
                results, profile, args.exposure_threshold_fraction
            )
            record = _scan_record(
                args.profile,
                FIXED_BLUE_DETUNING_GAMMA,
                FIXED_BLUE_S0,
                analysis,
                exposure,
            )
            record.update(
                gradient_G_cm=FIXED_GRADIENT_G_CM,
                green_s0=float(green_s0),
                green_detuning_gamma=float(green_detuning),
            )
            records.append(record)
            print(
                f"  entered={record['entered_capture_region_count']}, "
                f"slow={record['slow_inside_count']}, "
                f"residence={record['minimum_residence_met_count']}, "
                f"eligible={record['capture_eligible_ever_count']}"
            )
            del results
            gc.collect()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "green_trap_scan.csv"
    json_path = output_dir / "green_trap_scan.json"
    plot_path = output_dir / "green_trap_scan.png"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    best = max(records, key=green_rank_key)
    report = {
        "purpose": "scan provisional 556-nm MOT parameters at fixed blue and field settings",
        "input_files": [str(path) for path in input_files],
        "input_particle_count": int(len(states)),
        "selected_particle_count_before_sharding": int(len(selected_states)),
        "num_shards": int(args.num_shards),
        "shard_index": int(args.shard_index),
        "selected_particle_indices": shard_indices.tolist(),
        "selection_seed": int(args.seed),
        "simulation_seed": simulation_seed,
        "profiles": [args.profile],
        "detuning_gamma_values": [FIXED_BLUE_DETUNING_GAMMA],
        "s0_values": [FIXED_BLUE_S0],
        "parameter_pairs": [
            {
                "s0": FIXED_BLUE_S0,
                "detuning_gamma": FIXED_BLUE_DETUNING_GAMMA,
            }
        ],
        "gradient_G_cm_values": [FIXED_GRADIENT_G_CM],
        "green_s0_values": [float(value) for value in green_s0_values],
        "green_detuning_gamma_values": [float(value) for value in green_detunings],
        "fixed_blue_light": True,
        "fixed_magnetic_field": True,
        "dt_s": float(args.dt),
        "t_max_s": float(args.t_max),
        "ranking_priority": [
            "capture_eligible_ever_count (higher)",
            "peak_capture_eligible_count (higher)",
            "minimum_residence_met_count (higher)",
            "slow_inside_count (higher)",
            "entered_capture_region_count (higher)",
        ],
        "best_point": best,
        "records": records,
    }
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    plot_green_scan(records, plot_path)
    print(f"Best point: {best}")
    print(f"Saved CSV: {csv_path}")
    print(f"Saved JSON: {json_path}")
    print(f"Saved plot: {plot_path}")
    return records, best


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", default=str(AFTER_2D_MOT_DIR / "final_ensemble_s0_1.47")
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--profile", default="angled_sequential")
    parser.add_argument(
        "--green-s0-values",
        nargs="+",
        type=float,
        default=list(DEFAULT_GREEN_S0_VALUES),
    )
    parser.add_argument(
        "--green-detuning-gamma-values",
        nargs="+",
        type=float,
        default=list(DEFAULT_GREEN_DETUNINGS_GAMMA),
    )
    parser.add_argument("--max-atoms", type=int)
    parser.add_argument("--num-shards", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=MOT_3D_SIM_CONFIG["t_max_s"])
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument("--exposure-threshold-fraction", type=float, default=0.01)
    parser.add_argument("--no-gravity", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_scan(parse_args())
