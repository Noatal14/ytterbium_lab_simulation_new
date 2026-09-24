"""Merge and plot the narrow-waist donut core/shell split sanity screen."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


def merge_screen(input_root, output_dir, graph_dir):
    paths = sorted(Path(input_root).glob("shard_*/donut_aperture_screen.json"))
    reports = [json.loads(path.read_text()) for path in paths]
    if len(reports) != 3:
        raise ValueError(f"Expected three donut-screen shards, found {len(reports)}.")
    if any(report.get("run_label") != "donut_core_shell_split_screen_v2_600" for report in reports):
        raise ValueError("Refusing to merge results from a different run label.")
    point_count = len(reports[0]["records"])
    if any(len(report["records"]) != point_count for report in reports):
        raise ValueError("Donut-screen shards contain different point counts.")

    merged = []
    for index in range(point_count):
        parts = [report["records"][index] for report in reports]
        split = parts[0]["core_shell_split_radius_m"]
        if any(
            part["core_shell_split_radius_m"] != split
            for part in parts
        ):
            raise ValueError(f"Point {index} differs across shards.")
        total = sum(part["input_particle_count"] for part in parts)
        row = {
            "point_index": index,
            "core_shell_split_radius_m": split,
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
        "status": "merged narrow-waist donut core/shell split sanity screen",
        "run_label": "donut_core_shell_split_screen_v2_600",
        "input_particle_count": sum(
            report["input_particle_count"] for report in reports
        ),
        "num_shards": len(reports),
        "best": ranked[0],
        "records": ranked,
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "donut_aperture_screen_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    ordered = sorted(merged, key=lambda row: row["core_shell_split_radius_m"])
    x = [1000 * row["core_shell_split_radius_m"] for row in ordered]
    y_end = [100 * row["usable_at_end_fraction"] for row in ordered]
    y_ever = [100 * row["usable_ever_fraction"] for row in ordered]
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    ax.plot(x, y_ever, "o--", color="#7f8c8d", label="usable at least once")
    ax.plot(x, y_end, "o-", color="#2471a3", label="usable at 100 ms")
    for split_mm, fraction, row in zip(x, y_end, ordered):
        ax.annotate(
            f"{row['usable_at_end_count']}/600\n({fraction:.1f}%)",
            (split_mm, fraction),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
        )
    ax.set_xlabel("shared green-core / blue-shell split radius [mm]")
    ax.set_ylabel("usable atoms [% of 2D-MOT survivors]")
    ax.set_title("Narrow-waist donut: shared core/shell split")
    ax.set_xticks(x)
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    graph_dir = Path(graph_dir)
    graph_dir.mkdir(parents=True, exist_ok=True)
    graph_path = graph_dir / "donut_core_shell_split_screen_v2.png"
    fig.savefig(graph_path, dpi=200, bbox_inches="tight")
    plt.close(fig)

    for rank, row in enumerate(ranked, start=1):
        print(
            f"{rank}. split={1000 * row['core_shell_split_radius_m']:g} mm: "
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
