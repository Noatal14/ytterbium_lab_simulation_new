"""Scan the 3D-MOT magnetic gradient at selected 399-nm operating points."""

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
    MOT_3D_MAGNETIC_FIELD_GRADIENT_G_CM,
    MOT_3D_SIM_CONFIG,
)
from simulations.mot_3d import mot_3d_simulation
from studies.compare_3d_mot_retention import analyze_results, load_shared_ensemble
from studies.scan_3d_mot_blue_slower import (
    _scan_record,
    blue_exposure_diagnostics,
    parse_parameter_pairs,
    select_particle_shard,
    slowing_rank_key,
)
from utils.data_paths import AFTER_2D_MOT_DIR


DEFAULT_GRADIENTS_G_CM = (5.0, 7.5, 10.0, 12.5, 15.0)
DEFAULT_PARAMETER_PAIRS = (
    "0.6:-1.65",
    "0.8:-1.85",
    "1.5:-2.5",
    "1.6:-2.6",
    "2.0:-2.7",
)


def plot_gradient_scan(records, output_path):
    fig, (capture_ax, slow_ax) = plt.subplots(2, 1, figsize=(10, 9))
    pairs = sorted({(row["s0"], row["detuning_gamma"]) for row in records})
    for s0, detuning in pairs:
        rows = sorted(
            (
                row
                for row in records
                if row["s0"] == s0 and row["detuning_gamma"] == detuning
            ),
            key=lambda row: row["gradient_G_cm"],
        )
        gradients = [row["gradient_G_cm"] for row in rows]
        label = f"s0={s0:g}, detuning={detuning:g} Gamma"
        capture_ax.plot(
            gradients,
            [row["capture_eligible_ever_count"] for row in rows],
            marker="o",
            label=label,
        )
        slow_ax.plot(
            gradients,
            [row["slow_inside_count"] for row in rows],
            marker="o",
            label=label,
        )
    capture_ax.set_ylabel("capture-eligible atom count")
    capture_ax.set_title("Full 3D-MOT capture criterion")
    slow_ax.set_ylabel("atoms reaching <=1 m/s")
    slow_ax.set_title("Slowing inside the capture region")
    for axis in (capture_ax, slow_ax):
        axis.set_xlabel("magnetic gradient [G/cm]")
        axis.grid(alpha=0.25)
        axis.legend(fontsize=8)
    fig.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def run_scan(args):
    if args.profile not in MOT_3D_CONFIGURATIONS:
        raise ValueError(f"Unknown 3D-MOT profile: {args.profile}")
    pairs = parse_parameter_pairs(args.parameter_pairs)
    if args.parameter_points_file:
        selection = json.loads(Path(args.parameter_points_file).read_text())
        pairs = tuple(
            (float(point["s0"]), float(point["detuning_gamma"]))
            for point in selection["selected_points"]
        )
    gradients = tuple(sorted(set(args.gradient_G_cm_values)))
    if not pairs or not gradients:
        raise ValueError("Parameter pairs and gradient values must not be empty.")
    if any(gradient <= 0.0 for gradient in gradients):
        raise ValueError("Magnetic gradients must be positive.")

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
    total_points = len(pairs) * len(gradients)
    point_index = 0
    for s0, detuning in pairs:
        for gradient in gradients:
            point_index += 1
            print(
                f"[{point_index}/{total_points}] {args.profile}: s0={s0:g}, "
                f"detuning={detuning:g} Gamma, gradient={gradient:g} G/cm"
            )
            profile = copy.deepcopy(MOT_3D_CONFIGURATIONS[args.profile])
            profile["399"]["s0"] = float(s0)
            profile["399"]["detuning_gamma"] = float(detuning)
            results, _ = mot_3d_simulation(
                states,
                _3d_mot_config=profile,
                gravity_enabled=not args.no_gravity,
                npools=args.npools,
                dt=args.dt,
                t_max=args.t_max,
                seed=simulation_seed,
                magnetic_gradient_G_cm=gradient,
            )
            analysis = analyze_results(results, time_points)
            exposure = blue_exposure_diagnostics(
                results, profile, args.exposure_threshold_fraction
            )
            record = _scan_record(
                args.profile, detuning, s0, analysis, exposure
            )
            record["gradient_G_cm"] = float(gradient)
            records.append(record)
            print(
                f"  entered={record['entered_capture_region_count']}, "
                f"slow={record['slow_inside_count']}, "
                f"eligible={record['capture_eligible_ever_count']}"
            )
            del results
            gc.collect()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "gradient_scan.csv"
    json_path = output_dir / "blue_slower_scan.json"
    plot_path = output_dir / "gradient_scan.png"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    best = max(records, key=slowing_rank_key)
    report = {
        "purpose": "scan 3D-MOT gradient at selected 399-nm operating points",
        "input_files": [str(path) for path in input_files],
        "input_particle_count": int(len(states)),
        "selected_particle_count_before_sharding": int(len(selected_states)),
        "num_shards": int(args.num_shards),
        "shard_index": int(args.shard_index),
        "selected_particle_indices": shard_indices.tolist(),
        "selection_seed": int(args.seed),
        "simulation_seed": simulation_seed,
        "profiles": [args.profile],
        "detuning_gamma_values": sorted({float(pair[1]) for pair in pairs}),
        "s0_values": sorted({float(pair[0]) for pair in pairs}),
        "parameter_pairs": [
            {"s0": float(s0), "detuning_gamma": float(detuning)}
            for s0, detuning in pairs
        ],
        "gradient_G_cm_values": [float(value) for value in gradients],
        "config_default_gradient_G_cm": MOT_3D_MAGNETIC_FIELD_GRADIENT_G_CM,
        "dt_s": float(args.dt),
        "t_max_s": float(args.t_max),
        "best_point": best,
        "records": records,
    }
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    plot_gradient_scan(records, plot_path)
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
        "--parameter-pairs", nargs="+", default=list(DEFAULT_PARAMETER_PAIRS)
    )
    parser.add_argument("--parameter-points-file")
    parser.add_argument(
        "--gradient-G-cm-values",
        nargs="+",
        type=float,
        default=list(DEFAULT_GRADIENTS_G_CM),
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
