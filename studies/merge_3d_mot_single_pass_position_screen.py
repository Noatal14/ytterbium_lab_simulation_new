"""Merge and plot the yz single-pass position and detuning screen."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def merge_screen(input_root, output_dir, graph_dir):
    paths = sorted(Path(input_root).glob("shard_*/single_pass_position_screen.json"))
    reports = [json.loads(path.read_text()) for path in paths]
    if len(reports) != 3:
        raise ValueError(f"Expected three screen shards, found {len(reports)}.")
    point_count = len(reports[0]["records"])
    if any(len(report["records"]) != point_count for report in reports):
        raise ValueError("Screen shards contain different point counts.")

    merged = []
    for index in range(point_count):
        parts = [report["records"][index] for report in reports]
        identity = (
            parts[0]["blue_crossing_z_offset_m"],
            parts[0]["blue_detuning_gamma"],
        )
        if any(
            (part["blue_crossing_z_offset_m"], part["blue_detuning_gamma"])
            != identity
            for part in parts
        ):
            raise ValueError(f"Point {index} differs across shards.")
        total = sum(part["input_particle_count"] for part in parts)
        row = {
            "point_index": index,
            "blue_crossing_z_offset_m": identity[0],
            "blue_detuning_gamma": identity[1],
            "blue_s0": parts[0]["blue_s0"],
            "blue_waist_m": parts[0]["blue_waist_m"],
            "input_particle_count": total,
        }
        for field in (
            "usable_at_end_count",
            "usable_ever_count",
            "peak_usable_count",
            "entered_capture_region_count",
            "slow_inside_count",
        ):
            row[field] = int(sum(part[field] for part in parts))
        row["usable_at_end_fraction"] = row["usable_at_end_count"] / total
        row["usable_ever_fraction"] = row["usable_ever_count"] / total
        merged.append(row)

    ranked = sorted(
        merged,
        key=lambda row: (
            row["usable_at_end_count"],
            row["usable_ever_count"],
            row["entered_capture_region_count"],
        ),
        reverse=True,
    )
    summary = {
        "status": "merged physical yz single-pass position and detuning screen",
        "input_particle_count": sum(report["input_particle_count"] for report in reports),
        "num_shards": len(reports),
        "best": ranked[0],
        "records": ranked,
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "single_pass_position_screen_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    positions = sorted({row["blue_crossing_z_offset_m"] for row in merged})
    detunings = sorted({row["blue_detuning_gamma"] for row in merged})
    grid = np.zeros((len(positions), len(detunings)))
    for row in merged:
        i = positions.index(row["blue_crossing_z_offset_m"])
        j = detunings.index(row["blue_detuning_gamma"])
        grid[i, j] = 100.0 * row["usable_at_end_fraction"]
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    image = ax.imshow(grid, origin="lower", aspect="auto", cmap="viridis")
    for i in range(len(positions)):
        for j in range(len(detunings)):
            ax.text(j, i, f"{grid[i, j]:.1f}%", ha="center", va="center")
    ax.set_xticks(range(len(detunings)), detunings)
    ax.set_yticks(range(len(positions)), [f"{1000 * value:g}" for value in positions])
    ax.set_xlabel("blue detuning [Gamma]")
    ax.set_ylabel("blue crossing z [mm]")
    ax.set_title("Physical yz single pass: crossing position and detuning")
    fig.colorbar(image, ax=ax, label="usable at 100 ms [%]")
    fig.tight_layout()
    graph_dir = Path(graph_dir)
    graph_dir.mkdir(parents=True, exist_ok=True)
    graph_path = graph_dir / "single_pass_yz_position_screen.png"
    fig.savefig(graph_path, dpi=200, bbox_inches="tight")
    plt.close(fig)

    for rank, row in enumerate(ranked, start=1):
        print(
            f"{rank:2d}. z={1000 * row['blue_crossing_z_offset_m']:g} mm, "
            f"detuning={row['blue_detuning_gamma']:g} Gamma: "
            f"end={row['usable_at_end_count']}/600 "
            f"({100 * row['usable_at_end_fraction']:.1f}%), "
            f"ever={row['usable_ever_count']}, "
            f"entered={row['entered_capture_region_count']}"
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
