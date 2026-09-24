"""Merge and plot the physical yz single-pass operating-point screen."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def _weighted_summary(records, field):
    total = sum(record["input_particle_count"] for record in records)
    keys = ("min", "p10", "median", "p90", "max")
    return {
        key: float(
            sum(record[field][key] * record["input_particle_count"] for record in records)
            / total
        )
        for key in keys
    }


def merge_screen(input_root, output_dir, graph_dir):
    input_root = Path(input_root)
    paths = sorted(input_root.glob("shard_*/single_pass_operating_screen.json"))
    reports = [json.loads(path.read_text()) for path in paths]
    if len(reports) != 3:
        raise ValueError(f"Expected three screen shards, found {len(reports)}.")
    point_count = len(reports[0]["records"])
    if any(len(report["records"]) != point_count for report in reports):
        raise ValueError("Screen shards contain different point counts.")

    merged = []
    for index in range(point_count):
        parts = [report["records"][index] for report in reports]
        identity = (parts[0]["blue_detuning_gamma"], parts[0]["blue_s0"])
        if any((part["blue_detuning_gamma"], part["blue_s0"]) != identity for part in parts):
            raise ValueError(f"Point {index} differs across shards.")
        total = sum(part["input_particle_count"] for part in parts)
        row = {
            "point_index": index,
            "blue_detuning_gamma": identity[0],
            "blue_s0": identity[1],
            "input_particle_count": total,
        }
        for field in (
            "usable_at_end_count", "usable_ever_count", "peak_usable_count",
            "entered_capture_region_count", "slow_inside_count",
        ):
            row[field] = int(sum(part[field] for part in parts))
        row["usable_at_end_fraction"] = row["usable_at_end_count"] / total
        row["usable_ever_fraction"] = row["usable_ever_count"] / total
        row["minimum_distance_to_center_m"] = _weighted_summary(
            parts, "minimum_distance_to_center_m"
        )
        row["speed_at_closest_approach_m_s"] = _weighted_summary(
            parts, "speed_at_closest_approach_m_s"
        )
        merged.append(row)

    merged.sort(
        key=lambda row: (
            row["usable_at_end_count"], row["usable_ever_count"],
            row["entered_capture_region_count"], -row["minimum_distance_to_center_m"]["median"],
        ),
        reverse=True,
    )
    summary = {
        "status": "merged physical yz single-pass operating-point screen",
        "input_particle_count": sum(r["input_particle_count"] for r in reports),
        "num_shards": len(reports),
        "fixed_geometry": reports[0]["fixed_geometry"],
        "best": merged[0],
        "records": merged,
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "single_pass_operating_screen_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    detunings = sorted({row["blue_detuning_gamma"] for row in merged})
    intensities = sorted({row["blue_s0"] for row in merged})
    grid = np.zeros((len(detunings), len(intensities)))
    for row in merged:
        grid[detunings.index(row["blue_detuning_gamma"]), intensities.index(row["blue_s0"])] = row["usable_at_end_fraction"] * 100
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    image = ax.imshow(grid, origin="lower", aspect="auto", cmap="viridis")
    for i in range(len(detunings)):
        for j in range(len(intensities)):
            ax.text(j, i, f"{grid[i, j]:.1f}%", ha="center", va="center", color="white" if grid[i, j] < 45 else "black")
    ax.set_xticks(range(len(intensities)), intensities)
    ax.set_yticks(range(len(detunings)), detunings)
    ax.set_xlabel("blue s0 per beam")
    ax.set_ylabel("blue detuning [Gamma]")
    ax.set_title("Physical yz single pass: usable atoms at 100 ms")
    fig.colorbar(image, ax=ax, label="usable fraction [%]")
    fig.tight_layout()
    graph_dir = Path(graph_dir)
    graph_dir.mkdir(parents=True, exist_ok=True)
    graph_path = graph_dir / "single_pass_yz_operating_screen.png"
    fig.savefig(graph_path, dpi=200, bbox_inches="tight")
    plt.close(fig)

    for rank, row in enumerate(merged, start=1):
        print(
            f"{rank:2d}. detuning={row['blue_detuning_gamma']:g} Gamma, "
            f"s0={row['blue_s0']:g}: end={row['usable_at_end_count']}/600 "
            f"({100 * row['usable_at_end_fraction']:.1f}%), "
            f"ever={row['usable_ever_count']}, entered={row['entered_capture_region_count']}"
        )
    print(f"Saved summary: {summary_path}")
    print(f"Saved graph: {graph_path}")
    return summary_path, graph_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--graph-dir", default="graphs/mot_3d_configuration_decision")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    merge_screen(args.input_root, args.output_dir, args.graph_dir)
