"""Merge count metrics from disjoint 3D-MOT blue-scan shards."""

import argparse
import csv
import json
from pathlib import Path

import numpy as np


COUNT_FIELDS = (
    "entered_capture_region_count",
    "slow_inside_count",
    "minimum_residence_met_count",
    "capture_eligible_ever_count",
    "peak_capture_eligible_count",
    "blue_exposed_particle_count",
)
MEDIAN_FIELDS = (
    "median_minimum_speed_inside_m_s",
    "median_maximum_blue_relative_intensity",
    "median_blue_exposure_time_s",
    "median_delta_vz_during_blue_exposure_m_s",
)


def merge_reports(reports):
    """Combine disjoint shards, summing counts exactly."""
    if not reports:
        raise ValueError("At least one shard report is required.")
    expected_num_shards = reports[0]["num_shards"]
    shard_indices = sorted(report["shard_index"] for report in reports)
    if len(reports) != expected_num_shards or shard_indices != list(
        range(expected_num_shards)
    ):
        raise ValueError(
            f"Expected shards 0..{expected_num_shards - 1}, got {shard_indices}."
        )
    reference_grid = (
        reports[0]["profiles"],
        reports[0]["detuning_gamma_values"],
        reports[0]["s0_values"],
    )
    if any(
        (report["profiles"], report["detuning_gamma_values"], report["s0_values"])
        != reference_grid
        for report in reports[1:]
    ):
        raise ValueError("Shard scan grids do not match.")

    by_report = []
    for report in reports:
        by_report.append(
            {
                (row["profile"], row["detuning_gamma"], row["s0"]): row
                for row in report["records"]
            }
        )
    merged = []
    for key in by_report[0]:
        rows = [mapping[key] for mapping in by_report]
        weights = np.asarray(
            [report["input_particle_count"] for report in reports], dtype=float
        )
        row = {
            "profile": key[0],
            "detuning_gamma": float(key[1]),
            "s0": float(key[2]),
            "input_particle_count": int(weights.sum()),
        }
        for field in COUNT_FIELDS:
            row[field] = int(sum(item[field] for item in rows))
        for field in MEDIAN_FIELDS:
            values_and_weights = [
                (float(item[field]), weight)
                for item, weight in zip(rows, weights)
                if item[field] is not None
            ]
            values = [value for value, _ in values_and_weights]
            value_weights = [weight for _, weight in values_and_weights]
            prefix = field.removeprefix("median_")
            row[f"weighted_mean_of_shard_medians_{prefix}"] = (
                float(np.average(values, weights=value_weights)) if values else None
            )
            row[f"minimum_shard_median_{prefix}"] = min(values) if values else None
            row[f"maximum_shard_median_{prefix}"] = max(values) if values else None
        merged.append(row)
    return merged


def run_merge(input_root, output_dir):
    input_root = Path(input_root)
    paths = sorted(input_root.glob("shard_*/blue_slower_scan.json"))
    reports = [json.loads(path.read_text()) for path in paths]
    merged = merge_reports(reports)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "merged_blue_slower_scan.csv"
    json_path = output_dir / "merged_blue_slower_scan.json"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(merged[0]))
        writer.writeheader()
        writer.writerows(merged)
    summary = {
        "source_files": [str(path) for path in paths],
        "num_shards": len(reports),
        "input_particle_count": sum(
            report["input_particle_count"] for report in reports
        ),
        "distribution_note": (
            "Counts are exact sums. Distribution columns are explicitly labeled "
            "statistics of shard medians, not exact pooled-particle quantiles."
        ),
        "records": merged,
    }
    json_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Saved merged CSV: {csv_path}")
    print(f"Saved merged JSON: {json_path}")
    return merged


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = parse_args()
    run_merge(arguments.input_root, arguments.output_dir)
