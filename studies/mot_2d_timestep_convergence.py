"""Run and summarize paired stochastic 2D-MOT timestep convergence checks."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from config import MOT_2D_LASER_CONFIG, MOT_2D_MAGNET_RADIUS_M
from simulations.mot_2d import mot_simulation
from utils.data_paths import MOT_2D_VALIDATION_DIR
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles, summarize_replicates


def run_one(dt_s, ensemble_index, particles, mot_seed, npools, output_dir):
    ensembles = load_production_ensembles(
        max_ensembles=ensemble_index + 1,
        particles_per_ensemble=particles,
    )
    ensemble = ensembles[ensemble_index]
    started = time.time()
    _, captured, _ = mot_simulation(
        survivor_states=ensemble["states"],
        _2d_mot_config=MOT_2D_LASER_CONFIG,
        magnet_radius=MOT_2D_MAGNET_RADIUS_M,
        stochastic=True,
        npools=npools,
        dt=dt_s,
        seed=mot_seed,
    )
    elapsed = time.time() - started
    n_input = len(ensemble["states"])
    conditional = captured / n_input
    record = {
        "kind": "mot_2d_timestep_convergence_single_run",
        "configuration": {
            "dt_s": float(dt_s),
            "dt_us": float(dt_s * 1e6),
            "ensemble_index": int(ensemble_index),
            "zeeman_seed": ensemble["zeeman_seed"],
            "mot_seed": int(mot_seed),
            "n_input": int(n_input),
            "npools": int(npools),
            "s0": float(MOT_2D_LASER_CONFIG["s0"]),
            "detuning_gamma": float(MOT_2D_LASER_CONFIG["detuning_gamma"]),
            "magnet_radius_m": float(MOT_2D_MAGNET_RADIUS_M),
        },
        "result": {
            "captured": int(captured),
            "conditional_efficiency": float(conditional),
            "estimated_total_efficiency": float(
                conditional * ensemble["zeeman_survival_fraction"]
            ),
            "elapsed_seconds": float(elapsed),
        },
    }
    output_dir = Path(output_dir)
    output = output_dir / (
        f"run_dt{dt_s * 1e6:g}us_zeeman{ensemble['zeeman_seed']}_mot{mot_seed}.json"
    )
    save_file_json(output, record)
    print(
        "MOT_2D_DT_RESULT "
        f"dt_us={dt_s * 1e6:g} zeeman_seed={ensemble['zeeman_seed']} "
        f"mot_seed={mot_seed} captured={captured}/{n_input} "
        f"conditional_percent={100 * conditional:.6f} elapsed_seconds={elapsed:.1f}"
    )
    return record


def summarize(input_dir, output_file):
    records = []
    for path in sorted(Path(input_dir).glob("run_*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("kind") == "mot_2d_timestep_convergence_single_run":
            records.append(record)
    groups = {}
    for record in records:
        groups.setdefault(record["configuration"]["dt_s"], []).append(record)
    summaries = []
    for dt_s, group in sorted(groups.items()):
        replicates = [
            {
                **row["result"],
                "zeeman_seed": row["configuration"]["zeeman_seed"],
                "mot_seed": row["configuration"]["mot_seed"],
            }
            for row in group
        ]
        summaries.append({"dt_s": dt_s, "dt_us": dt_s * 1e6, **summarize_replicates(replicates)})
    reference = min(groups) if groups else None
    paired = []
    if reference is not None:
        by_key = {
            (row["configuration"]["dt_s"], row["configuration"]["zeeman_seed"], row["configuration"]["mot_seed"]): row
            for row in records
        }
        for dt_s in sorted(groups):
            if dt_s == reference:
                continue
            differences = []
            for key, row in by_key.items():
                candidate_dt, zeeman_seed, mot_seed = key
                reference_key = (reference, zeeman_seed, mot_seed)
                if candidate_dt == dt_s and reference_key in by_key:
                    differences.append(
                        row["result"]["conditional_efficiency"]
                        - by_key[reference_key]["result"]["conditional_efficiency"]
                    )
            paired.append(
                {
                    "dt_s": dt_s,
                    "reference_dt_s": reference,
                    "paired_differences_fraction": differences,
                    "mean_paired_difference_fraction": (
                        sum(differences) / len(differences) if differences else None
                    ),
                }
            )
    payload = {"groups": summaries, "paired_comparisons_to_finest_dt": paired}
    save_file_json(output_file, payload)
    print(f"Summary saved to: {output_file}")
    return payload


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--dt", type=float, required=True)
    run.add_argument("--ensemble-index", type=int, required=True)
    run.add_argument("--particles", type=int, default=2000)
    run.add_argument("--mot-seed", type=int, required=True)
    run.add_argument("--npools", type=int, default=80)
    run.add_argument("--output-dir", default=str(MOT_2D_VALIDATION_DIR / "timestep_convergence"))
    summary = subparsers.add_parser("summarize")
    summary.add_argument("--input-dir", default=str(MOT_2D_VALIDATION_DIR / "timestep_convergence"))
    summary.add_argument("--output", default=str(MOT_2D_VALIDATION_DIR / "timestep_convergence" / "summary.json"))
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.command == "run":
        run_one(args.dt, args.ensemble_index, args.particles, args.mot_seed, args.npools, args.output_dir)
    else:
        summarize(args.input_dir, args.output)
