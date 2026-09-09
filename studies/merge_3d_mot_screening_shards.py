"""Merge disjoint fast-screening shards and create a compact comparison."""

import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from config import MOT_3D_SCREENING_CONFIG
from studies.merge_3d_mot_blue_scan_shards import merge_reports
from studies.screen_3d_mot_configurations import screening_rank_key


STATIC_MEAN_FIELDS = (
    "green_force_gradient_x_N_m",
    "green_force_gradient_y_N_m",
    "green_force_gradient_z_N_m",
    "initial_blue_mean_force_z_N",
    "initial_blue_decelerating_fraction",
    "initial_blue_mean_transverse_force_N",
    "initial_blue_transverse_to_longitudinal_ratio",
)


def _key(row):
    return (
        row["profile"], row["s0"], row["detuning_gamma"],
        row["gradient_G_cm"], row["green_s0"], row["green_detuning_gamma"],
    )


def merge_screening_reports(reports):
    merged = merge_reports(reports)
    source_maps = [{_key(row): row for row in report["records"]} for report in reports]
    weights = np.asarray([report["input_particle_count"] for report in reports], dtype=float)
    for row in merged:
        rows = [mapping[_key(row)] for mapping in source_maps]
        row["screening_anchor"] = int(rows[0]["screening_anchor"])
        for axis in "xyz":
            row[f"green_restoring_{axis}"] = bool(all(item[f"green_restoring_{axis}"] for item in rows))
        row["green_restoring_all_axes"] = bool(all(item["green_restoring_all_axes"] for item in rows))
        row["green_equilibrium_found"] = bool(all(item["green_equilibrium_found"] for item in rows))
        equilibrium_offsets = {item["green_equilibrium_x_offset_m"] for item in rows}
        if len(equilibrium_offsets) != 1:
            raise ValueError("Green equilibrium differs between shards.")
        row["green_equilibrium_x_offset_m"] = equilibrium_offsets.pop()
        center_values = {float(item["blue_center_intensity_W_m2"]) for item in rows}
        if len(center_values) != 1:
            raise ValueError("Blue center intensity differs between shards.")
        row["blue_center_intensity_W_m2"] = center_values.pop()
        for field in STATIC_MEAN_FIELDS:
            available = [(item[field], weight) for item, weight in zip(rows, weights) if item[field] is not None]
            row[field] = (
                float(np.average([value for value, _ in available], weights=[weight for _, weight in available]))
                if available else None
            )
    return merged


def screening_verdict(rows):
    """Return a transparent rejection verdict for one candidate geometry."""
    physics_valid = all(row["green_restoring_all_axes"] for row in rows)
    center_dark = all(row["blue_center_intensity_W_m2"] == 0.0 for row in rows)
    total = max(row["input_particle_count"] for row in rows)
    maximum_exposed_fraction = max(row["blue_exposed_particle_count"] / total for row in rows)
    delta_values = [
        row["weighted_mean_of_shard_medians_delta_vz_during_blue_exposure_m_s"]
        for row in rows
        if row["weighted_mean_of_shard_medians_delta_vz_during_blue_exposure_m_s"] is not None
    ]
    best_median_delta_vz = min(delta_values) if delta_values else None
    overlap_valid = maximum_exposed_fraction >= MOT_3D_SCREENING_CONFIG["minimum_exposed_fraction"]
    slowing_valid = best_median_delta_vz is not None and best_median_delta_vz <= -MOT_3D_SCREENING_CONFIG["minimum_median_slowing_m_s"]
    if not physics_valid:
        verdict = "reject_nonrestoring_force"
    elif not center_dark:
        verdict = "reject_blue_leakage_at_center"
    elif not overlap_valid:
        verdict = "reject_insufficient_blue_overlap"
    elif not slowing_valid:
        verdict = "reject_insufficient_longitudinal_slowing"
    else:
        verdict = "promising_for_confirmation"
    return {
        "verdict": verdict,
        "physics_valid": physics_valid,
        "blue_center_dark": center_dark,
        "maximum_blue_exposed_fraction": maximum_exposed_fraction,
        "best_median_delta_vz_during_blue_exposure_m_s": best_median_delta_vz,
        "capture_signal_count": max(row["capture_eligible_ever_count"] for row in rows),
    }


def _plot(records, output_path):
    profiles = sorted({row["profile"] for row in records})
    fig, axes = plt.subplots(len(profiles), 1, figsize=(10, 3.6 * len(profiles)), squeeze=False)
    for axis, profile in zip(axes[:, 0], profiles):
        rows = sorted((row for row in records if row["profile"] == profile), key=lambda row: row["screening_anchor"])
        labels = [str(row["screening_anchor"]) for row in rows]
        axis.bar(labels, [row["capture_eligible_ever_count"] for row in rows], label="capture eligible")
        axis.plot(labels, [row["slow_inside_count"] for row in rows], "o-", color="tab:orange", label="slow inside")
        axis.set_title(profile)
        axis.set_xlabel("screening anchor")
        axis.set_ylabel("atom count")
        axis.grid(axis="y", alpha=0.25)
        axis.legend()
    fig.suptitle("Fast 3D-MOT geometry screening (not an optimization)")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def run_merge(input_root, output_dir):
    paths = sorted(Path(input_root).glob("shard_*/screening_scan.json"))
    reports = [json.loads(path.read_text()) for path in paths]
    records = merge_screening_reports(reports)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "merged_screening_scan.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    best = {
        profile: max((row for row in records if row["profile"] == profile), key=screening_rank_key)
        for profile in reports[0]["profiles"]
    }
    verdicts = {
        profile: screening_verdict([row for row in records if row["profile"] == profile])
        for profile in reports[0]["profiles"]
    }
    summary = {
        "purpose": "fast geometry rejection screening; not optimization",
        "status": "provisional comparison probes",
        "source_files": [str(path) for path in paths],
        "input_particle_count": int(sum(report["input_particle_count"] for report in reports)),
        "num_shards": len(reports),
        "anchors": reports[0]["anchors"],
        "best_by_profile": best,
        "verdicts": verdicts,
        "records": records,
    }
    json_path = output_dir / "merged_screening_scan.json"
    json_path.write_text(json.dumps(summary, indent=2) + "\n")
    _plot(records, output_dir / "screening_comparison.png")
    print(json.dumps({"best_by_profile": best, "verdicts": verdicts}, indent=2))
    print(f"Saved merged screening: {json_path}")
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    run_merge(args.input_root, args.output_dir)
