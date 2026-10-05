"""Merge independent fixed-s0 corrected-Zeeman 2D-MOT discovery workers."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def merge(input_root, output_dir):
    input_root = Path(input_root)
    paths = sorted(input_root.glob("worker_*/summary.json"))
    if len(paths) != 3:
        raise ValueError(f"Expected three worker summaries, found {len(paths)}.")
    summaries = [json.loads(path.read_text()) for path in paths]
    if any(summary["fixed_s0"] != 1.3 for summary in summaries):
        raise ValueError("Every corrected-Zeeman worker must hold s0 fixed at 1.3.")

    ranked = []
    for worker_index, (path, summary) in enumerate(zip(paths, summaries)):
        for row in summary["ranked_trials"]:
            ranked.append(
                {
                    "worker_index": worker_index,
                    "worker_summary": str(path),
                    **row,
                }
            )
    ranked.sort(
        key=lambda row: (
            -row["mean_conditional_efficiency"],
            row["worker_index"],
            row["trial_number"],
        )
    )
    best = ranked[0]
    bounds = summaries[0]["design"]["bounds"]
    detuning_low, detuning_high = bounds["detuning_gamma"]
    radius_low, radius_high = bounds["magnet_radius_m"]
    parameters = best["parameters"]
    detuning_tolerance = 0.02 * (detuning_high - detuning_low)
    radius_tolerance = 0.02 * (radius_high - radius_low)
    boundary_flags = {
        "detuning_at_lower_bound": abs(parameters["detuning_gamma"] - detuning_low)
        <= detuning_tolerance,
        "detuning_at_upper_bound": abs(parameters["detuning_gamma"] - detuning_high)
        <= detuning_tolerance,
        "magnet_radius_at_lower_bound": abs(parameters["magnet_radius"] - radius_low)
        <= radius_tolerance,
        "magnet_radius_at_upper_bound": abs(parameters["magnet_radius"] - radius_high)
        <= radius_tolerance,
    }
    payload = {
        "kind": "merged_corrected_zeeman_fixed_s0_2d_mot_discovery",
        "fixed_s0": 1.3,
        "worker_count": len(summaries),
        "completed_trial_count": len(ranked),
        "best": best,
        "best_boundary_flags": boundary_flags,
        "design": summaries[0]["design"],
        "ranked_trials": ranked,
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "merged_summary.json"
    summary_path.write_text(json.dumps(payload, indent=2) + "\n")
    csv_path = output_dir / "ranked_trials.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "rank",
                "worker_index",
                "trial_number",
                "mean_conditional_efficiency",
                "s0",
                "detuning_gamma",
                "magnet_radius_m",
            ),
        )
        writer.writeheader()
        for rank, row in enumerate(ranked, start=1):
            writer.writerow(
                {
                    "rank": rank,
                    "worker_index": row["worker_index"],
                    "trial_number": row["trial_number"],
                    "mean_conditional_efficiency": row["mean_conditional_efficiency"],
                    "s0": row["parameters"]["s0"],
                    "detuning_gamma": row["parameters"]["detuning_gamma"],
                    "magnet_radius_m": row["parameters"]["magnet_radius"],
                }
            )
    print(json.dumps({"best": best, "boundary_flags": boundary_flags}, indent=2))
    print(f"Saved summary: {summary_path}")
    print(f"Saved ranking: {csv_path}")
    return payload


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    merge(args.input_root, args.output_dir)
