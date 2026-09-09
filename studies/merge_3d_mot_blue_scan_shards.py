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
        reports[0].get("parameter_pairs"),
        reports[0].get("gradient_G_cm_values"),
        reports[0].get("green_s0_values"),
        reports[0].get("green_detuning_gamma_values"),
        reports[0].get("blue_waists_mm"),
        reports[0].get("green_exclusion_radii_mm"),
        reports[0].get("crossing_distances_mm"),
    )
    if any(
        (
            report["profiles"],
            report["detuning_gamma_values"],
            report["s0_values"],
            report.get("parameter_pairs"),
            report.get("gradient_G_cm_values"),
            report.get("green_s0_values"),
            report.get("green_detuning_gamma_values"),
            report.get("blue_waists_mm"),
            report.get("green_exclusion_radii_mm"),
            report.get("crossing_distances_mm"),
        )
        != reference_grid
        for report in reports[1:]
    ):
        raise ValueError("Shard scan grids do not match.")

    by_report = []
    for report in reports:
        by_report.append(
            {
                (
                    row["profile"],
                    row["detuning_gamma"],
                    row["s0"],
                    row.get("gradient_G_cm"),
                    row.get("green_s0"),
                    row.get("green_detuning_gamma"),
                    row.get("blue_waist_mm"),
                    row.get("green_exclusion_radius_mm"),
                    row.get("crossing_distance_mm"),
                ): row
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
        if key[3] is not None:
            row["gradient_G_cm"] = float(key[3])
        if key[4] is not None:
            row["green_s0"] = float(key[4])
        if key[5] is not None:
            row["green_detuning_gamma"] = float(key[5])
        if key[6] is not None:
            row["blue_waist_mm"] = float(key[6])
        if key[7] is not None:
            row["green_exclusion_radius_mm"] = float(key[7])
        if key[8] is not None:
            row["crossing_distance_mm"] = float(key[8])
        geometry_intensity_fields = (
            "summed_blue_intensity_at_mot_center_W_m2",
            "summed_blue_intensity_at_crossing_W_m2",
        )
        has_geometry_intensity_checks = [
            all(field in item for field in geometry_intensity_fields)
            for item in rows
        ]
        if any(has_geometry_intensity_checks) and not all(has_geometry_intensity_checks):
            raise ValueError("Geometry intensity checks are missing from some shards.")
        if all(has_geometry_intensity_checks):
            center_values = {
                float(item["summed_blue_intensity_at_mot_center_W_m2"])
                for item in rows
            }
            crossing_values = {
                float(item["summed_blue_intensity_at_crossing_W_m2"])
                for item in rows
            }
            if len(center_values) != 1 or len(crossing_values) != 1:
                raise ValueError("Shard geometry intensity checks do not match.")
            row["summed_blue_intensity_at_mot_center_W_m2"] = center_values.pop()
            row["summed_blue_intensity_at_crossing_W_m2"] = crossing_values.pop()
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
    if not paths:
        paths = sorted(input_root.glob("shard_*/green_trap_scan.json"))
    if not paths:
        paths = sorted(input_root.glob("shard_*/sequential_geometry_scan.json"))
    reports = [json.loads(path.read_text()) for path in paths]
    merged = merge_reports(reports)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if reports[0].get("blue_waists_mm") is not None:
        output_stem = "merged_sequential_geometry_scan"
    elif reports[0].get("green_s0_values") is not None:
        output_stem = "merged_green_trap_scan"
    else:
        output_stem = "merged_blue_slower_scan"
    csv_path = output_dir / f"{output_stem}.csv"
    json_path = output_dir / f"{output_stem}.json"
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
