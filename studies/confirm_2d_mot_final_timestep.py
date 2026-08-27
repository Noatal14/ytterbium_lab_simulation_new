"""Confirm the selected 2D-MOT setting at the finer 5-us timestep."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import DEFAULT_NUM_POOLS
from studies.optimize_2d_mot_joint import evaluate_configuration
from studies.validate_2d_mot_production import (
    MOT_SEED_OFFSET,
    REPORTING_SURVIVORS,
    TARGET_HALF_WIDTH_FRACTION,
)
from studies.validate_2d_mot_robustness import SELECTED_PARAMETERS
from utils.data_paths import MOT_2D_VALIDATION_DIR
from utils.file_helpers import save_file_json
from utils.mot_2d_study import (
    load_production_ensembles,
    prediction_for_new_run,
    student_mean_interval,
    summarize_replicates,
)


FINE_DT_S = 5e-6
SCREENING_DT_S = 10e-6
TIMESTEP_EQUIVALENCE_MARGIN_FRACTION = 0.0005
DEFAULT_OUTPUT_DIR = MOT_2D_VALIDATION_DIR / "final_timestep_confirmation_v9"
BASELINE_SUMMARY_FILE = Path(
    "data/optimization/mot_2d/production_prediction_v8/summary.json"
)


def run_seeds(args):
    ensembles = load_production_ensembles(
        particles_per_ensemble=None,
        zeeman_seeds=args.zeeman_seeds,
    )
    mot_seeds = [seed + MOT_SEED_OFFSET for seed in args.zeeman_seeds]
    evaluation = evaluate_configuration(
        **SELECTED_PARAMETERS,
        ensembles=ensembles,
        mot_seed_start=mot_seeds[0],
        mot_seeds=mot_seeds,
        npools=args.npools,
        dt_s=FINE_DT_S,
    )
    output_dir = Path(args.output_dir) / "replicates"
    output_dir.mkdir(parents=True, exist_ok=True)
    for row in evaluation["replicates"]:
        payload = {
            "kind": "mot_2d_final_timestep_replicate",
            "parameters": SELECTED_PARAMETERS,
            "dt_s": FINE_DT_S,
            "npools": args.npools,
            "replicate": row,
        }
        save_file_json(output_dir / f"zeeman_seed{row['zeeman_seed']}.json", payload)
        print(
            "MOT_2D_FINE_DT_RESULT "
            f"zeeman_seed={row['zeeman_seed']} mot_seed={row['mot_seed']} "
            f"captured={row['captured']} n_input={row['n_input']} "
            f"conditional_percent={100 * row['conditional_efficiency']:.6f}"
        )


def summarize(output_dir, baseline_file=BASELINE_SUMMARY_FILE):
    baseline = json.loads(Path(baseline_file).read_text(encoding="utf-8"))
    baseline_rows = {int(row["zeeman_seed"]): row for row in baseline["replicates"]}
    fine_rows = []
    for path in sorted((Path(output_dir) / "replicates").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["dt_s"] != FINE_DT_S:
            raise ValueError(f"Unexpected timestep in {path}: {payload['dt_s']}")
        fine_rows.append(payload["replicate"])
    fine_rows.sort(key=lambda row: row["zeeman_seed"])
    if not fine_rows:
        raise FileNotFoundError("No fine-timestep replicate files were found.")

    differences = []
    for fine in fine_rows:
        seed = int(fine["zeeman_seed"])
        if seed not in baseline_rows:
            raise ValueError(f"No 10-us baseline exists for Zeeman seed {seed}.")
        coarse = baseline_rows[seed]
        identity = ("zeeman_seed", "mot_seed", "n_input", "subset_seed")
        if any(fine[key] != coarse[key] for key in identity):
            raise ValueError(f"Timestep replicates are not paired for seed {seed}.")
        differences.append(
            fine["conditional_efficiency"] - coarse["conditional_efficiency"]
        )

    mean, low, high, half_width = student_mean_interval(differences)
    equivalence_passes = bool(
        low is not None
        and low >= -TIMESTEP_EQUIVALENCE_MARGIN_FRACTION
        and high <= TIMESTEP_EQUIVALENCE_MARGIN_FRACTION
    )
    prediction = prediction_for_new_run(fine_rows, REPORTING_SURVIVORS)
    summary = {
        "kind": "mot_2d_final_timestep_confirmation",
        "parameters": SELECTED_PARAMETERS,
        "fine_dt_s": FINE_DT_S,
        "baseline_dt_s": SCREENING_DT_S,
        "paired_seed_count": len(fine_rows),
        "equivalence_margin_fraction": TIMESTEP_EQUIVALENCE_MARGIN_FRACTION,
        "paired_difference_fine_minus_baseline": {
            "mean_fraction": mean,
            "confidence_95_fraction": [low, high],
            "confidence_95_half_width_fraction": half_width,
        },
        "timestep_equivalence_passes": equivalence_passes,
        "fine_timestep_statistics": summarize_replicates(fine_rows),
        "fine_timestep_prediction_for_new_run": prediction,
        "prediction_precision_target_fraction": TARGET_HALF_WIDTH_FRACTION,
        "fine_timestep_prediction_precision_passes": bool(
            prediction is not None
            and prediction["predicted_95_half_width_fraction"]
            <= TARGET_HALF_WIDTH_FRACTION
        ),
        "replicates": fine_rows,
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
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--baseline-file", default=str(BASELINE_SUMMARY_FILE))
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
