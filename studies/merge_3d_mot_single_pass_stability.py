"""Merge and plot the paired single-pass stability/factorial study."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def _load_point(reports, point_index):
    records = [report["records"][point_index] for report in reports]
    identity = (records[0]["variant"], records[0]["blue_s0"])
    if any((row["variant"], row["blue_s0"]) != identity for row in records):
        raise ValueError(f"Point {point_index} differs across shards.")
    arrays = []
    for record in records:
        with np.load(record["outcomes_path"]) as data:
            arrays.append({key: np.asarray(data[key]) for key in data.files})
    order = np.argsort(
        np.concatenate([row["global_particle_indices"] for row in arrays])
    )
    combined = {
        key: np.concatenate([row[key] for row in arrays])[order] for key in arrays[0]
    }
    total = sum(row["input_particle_count"] for row in records)
    merged = {
        **{key: value for key, value in records[0].items() if key != "outcomes_path"},
        "input_particle_count": total,
    }
    for field in (
        "usable_at_end_count",
        "usable_ever_count",
        "entered_capture_region_count",
        "slow_inside_count",
    ):
        merged[field] = int(sum(row[field] for row in records))
    merged["usable_at_end_fraction"] = merged["usable_at_end_count"] / total
    for field in (
        "minimum_distance_m",
        "speed_at_closest_approach_m_s",
        "final_distance_m",
        "final_speed_m_s",
        "final_z_m",
        "final_vz_m_s",
    ):
        finite = combined[field][np.isfinite(combined[field])]
        merged[f"{field}_median"] = float(np.median(finite)) if len(finite) else None
    return merged, combined


def _paired_transition(left, right):
    left = np.asarray(left, dtype=bool)
    right = np.asarray(right, dtype=bool)
    return {
        "captured_in_both": int(np.sum(left & right)),
        "lost_after_change": int(np.sum(left & ~right)),
        "gained_after_change": int(np.sum(~left & right)),
        "missed_in_both": int(np.sum(~left & ~right)),
        "net_change": int(right.sum() - left.sum()),
    }


def merge(input_root, output_dir, graph_path):
    input_root = Path(input_root)
    reports = [
        json.loads(path.read_text())
        for path in sorted(input_root.glob("shard_*/single_pass_stability.json"))
    ]
    if len(reports) != 3:
        raise ValueError(f"Expected three stability shards, found {len(reports)}.")
    point_count = len(reports[0]["records"])
    if any(len(report["records"]) != point_count for report in reports):
        raise ValueError("Stability shards contain different point counts.")

    records, outcomes = [], {}
    for point_index in range(point_count):
        record, arrays = _load_point(reports, point_index)
        records.append(record)
        outcomes[(record["variant"], record["blue_s0"])] = arrays

    factorial = [row for row in records if row["role"] == "factorial"]
    baseline_key = ("angle60_unclipped", factorial[0]["blue_s0"])
    baseline = outcomes[baseline_key]["usable_at_end"]
    factorial_effects = []
    for row in factorial:
        current = outcomes[(row["variant"], row["blue_s0"])]["usable_at_end"]
        factorial_effects.append(
            {
                "variant": row["variant"],
                "usable_at_end_count": row["usable_at_end_count"],
                "usable_at_end_fraction": row["usable_at_end_fraction"],
                "paired_transition_from_angle60_unclipped": _paired_transition(
                    baseline, current
                ),
            }
        )

    scan = sorted(
        [row for row in records if row["variant"] == "angle62_clipped"],
        key=lambda row: row["blue_s0"],
    )
    adjacent_transitions = []
    for left, right in zip(scan[:-1], scan[1:]):
        left_mask = outcomes[(left["variant"], left["blue_s0"])]["usable_at_end"]
        right_mask = outcomes[(right["variant"], right["blue_s0"])]["usable_at_end"]
        adjacent_transitions.append(
            {
                "from_blue_s0": left["blue_s0"],
                "to_blue_s0": right["blue_s0"],
                **_paired_transition(left_mask, right_mask),
            }
        )

    summary = {
        "kind": "merged_single_pass_stability_and_geometry_factorial",
        "input_particle_count": sum(
            report["input_particle_count"] for report in reports
        ),
        "num_shards": len(reports),
        "paired_design": (
            "Every point within a shard uses identical atoms and the same recoil seed."
        ),
        "factorial_effects": factorial_effects,
        "dense_s0_scan_angle62_clipped": scan,
        "adjacent_s0_paired_transitions": adjacent_transitions,
        "records": records,
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "single_pass_stability_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    fig, (scan_ax, factorial_ax) = plt.subplots(1, 2, figsize=(12, 4.8))
    scan_ax.plot(
        [row["blue_s0"] for row in scan],
        [100 * row["usable_at_end_fraction"] for row in scan],
        marker="o",
        linewidth=1.8,
    )
    scan_ax.set_xlabel("blue s0 per beam")
    scan_ax.set_ylabel("usable at 100 ms [%]")
    scan_ax.set_title("62° green geometry with hard apertures")
    scan_ax.grid(alpha=0.25)

    labels = [
        "60°\nno clip",
        "62°\nno clip",
        "60°\nclips",
        "62°\nclips",
    ]
    by_variant = {row["variant"]: row for row in factorial}
    variant_order = (
        "angle60_unclipped",
        "angle62_unclipped",
        "angle60_clipped",
        "angle62_clipped",
    )
    values = [
        100 * by_variant[name]["usable_at_end_fraction"] for name in variant_order
    ]
    factorial_ax.bar(labels, values, color=("#577590", "#43aa8b", "#f8961e", "#f94144"))
    factorial_ax.set_ylabel("usable at 100 ms [%]")
    factorial_ax.set_title("Paired angle/aperture factorial")
    factorial_ax.grid(axis="y", alpha=0.25)
    for index, value in enumerate(values):
        factorial_ax.text(index, value, f"{value:.1f}%", ha="center", va="bottom")
    fig.tight_layout()
    graph_path = Path(graph_path)
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(graph_path, dpi=200, bbox_inches="tight")
    plt.close(fig)

    print(
        json.dumps(
            {
                "summary": str(summary_path),
                "graph": str(graph_path),
                "factorial_effects": factorial_effects,
                "dense_scan": [
                    {"blue_s0": row["blue_s0"], "usable": row["usable_at_end_count"]}
                    for row in scan
                ],
            },
            indent=2,
        )
    )
    return summary_path, graph_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--graph-path", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    merge(args.input_root, args.output_dir, args.graph_path)
