"""Extend the final 2D-MOT prediction across independent Zeeman ensembles.

Workers receive explicit Zeeman seeds and process them together through one
shared multiprocessing pool.  Each seed is saved separately so interrupted
runs can resume without discarding completed results.  Summarization combines
the accepted original center run with every new saved replicate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import DEFAULT_NUM_POOLS, MOT_2D_SIM_CONFIG
from studies.optimize_2d_mot_joint import evaluate_configuration
from studies.validate_2d_mot_robustness import SELECTED_PARAMETERS
from utils.data_paths import MOT_2D_OPTIMIZATION_DIR
from utils.file_helpers import save_file_json
from utils.mot_2d_study import (
    load_production_ensembles,
    prediction_for_new_run,
    summarize_replicates,
)


DEFAULT_OUTPUT_DIR = MOT_2D_OPTIMIZATION_DIR / "production_prediction_v8"
BASELINE_CENTER_FILE = (
    MOT_2D_OPTIMIZATION_DIR / "robustness_followup_v7_all_survivors" / "point_13.json"
)
TARGET_HALF_WIDTH_FRACTION = 0.0005  # 0.05 percentage points
REPORTING_SURVIVORS = 10_000_000
MOT_SEED_OFFSET = 5000


def run_seeds(args):
    ensembles = load_production_ensembles(
        particles_per_ensemble=None,
        zeeman_seeds=args.zeeman_seeds,
    )
    evaluation = evaluate_configuration(
        **SELECTED_PARAMETERS,
        ensembles=ensembles,
        mot_seed_start=args.zeeman_seeds[0] + MOT_SEED_OFFSET,
        mot_seeds=[seed + MOT_SEED_OFFSET for seed in args.zeeman_seeds],
        npools=args.npools,
        dt_s=args.dt,
    )
    output_dir = Path(args.output_dir) / "replicates"
    output_dir.mkdir(parents=True, exist_ok=True)
    for row in evaluation["replicates"]:
        expected_mot_seed = row["zeeman_seed"] + MOT_SEED_OFFSET
        payload = {
            "kind": "mot_2d_production_prediction_replicate",
            "parameters": SELECTED_PARAMETERS,
            "dt_s": args.dt,
            "npools": args.npools,
            "replicate": row,
        }
        save_file_json(output_dir / f"zeeman_seed{row['zeeman_seed']}.json", payload)
        print(
            "MOT_2D_PRODUCTION_RESULT "
            f"zeeman_seed={row['zeeman_seed']} mot_seed={expected_mot_seed} "
            f"captured={row['captured']} n_input={row['n_input']} "
            f"conditional_percent={100 * row['conditional_efficiency']:.6f}"
        )


def summarize(output_dir, baseline_file=BASELINE_CENTER_FILE):
    baseline = json.loads(Path(baseline_file).read_text(encoding="utf-8"))
    replicates = list(baseline["evaluation"]["replicates"])
    seen_seeds = {int(row["zeeman_seed"]) for row in replicates}
    for path in sorted((Path(output_dir) / "replicates").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        row = payload["replicate"]
        seed = int(row["zeeman_seed"])
        if seed in seen_seeds:
            raise ValueError(f"Duplicate Zeeman seed in production data: {seed}")
        seen_seeds.add(seed)
        replicates.append(row)
    replicates.sort(key=lambda row: row["zeeman_seed"])
    statistics = summarize_replicates(replicates)
    prediction = prediction_for_new_run(replicates, REPORTING_SURVIVORS)
    summary = {
        "kind": "mot_2d_production_prediction_summary",
        "parameters": SELECTED_PARAMETERS,
        "baseline_file": str(baseline_file),
        "target_95_ci_half_width_fraction": TARGET_HALF_WIDTH_FRACTION,
        "target_95_ci_half_width_percentage_points": 100 * TARGET_HALF_WIDTH_FRACTION,
        "stopping_rule_passes": bool(
            prediction is not None
            and prediction["predicted_95_half_width_fraction"]
            <= TARGET_HALF_WIDTH_FRACTION
        ),
        "zeeman_seeds": [row["zeeman_seed"] for row in replicates],
        "replicates": replicates,
        "statistics": statistics,
        "prediction_for_new_run": prediction,
    }
    output_path = Path(output_dir) / "summary.json"
    save_file_json(output_path, summary)
    print(json.dumps(summary, indent=2))
    print(f"Summary saved to: {output_path}")
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zeeman-seeds", type=int, nargs="+")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--dt", type=float, default=MOT_2D_SIM_CONFIG["dt_s"])
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--baseline-file", default=str(BASELINE_CENTER_FILE))
    args = parser.parse_args(argv)
    if not args.summarize_only and not args.zeeman_seeds:
        parser.error("--zeeman-seeds is required unless --summarize-only is used")
    return args


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.summarize_only:
        summarize(arguments.output_dir, arguments.baseline_file)
    else:
        run_seeds(arguments)
