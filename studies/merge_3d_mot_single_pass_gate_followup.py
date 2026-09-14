"""Merge and plot the focused single-pass gate follow-up."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


COUNT_FIELDS = (
    "input_particle_count",
    "usable_ever_count",
    "usable_at_end_count",
    "peak_usable_count",
    "entered_capture_region_count",
)


def merge_screen(input_root, output_dir, graph_dir):
    paths = sorted(Path(input_root).glob("shard_*/single_pass_gate_followup.json"))
    if not paths:
        raise ValueError("No single-pass gate follow-up shard reports found.")
    reports = [json.loads(path.read_text()) for path in paths]
    records = []
    for index in range(len(reports[0]["records"])):
        rows = [report["records"][index] for report in reports]
        if len({row["label"] for row in rows}) != 1:
            raise ValueError(f"Shard candidates differ at point {index}.")
        record = dict(rows[0])
        for field in COUNT_FIELDS:
            record[field] = int(sum(row[field] for row in rows))
        record["usable_ever_fraction"] = record["usable_ever_count"] / record["input_particle_count"]
        record["usable_at_end_fraction"] = record["usable_at_end_count"] / record["input_particle_count"]
        records.append(record)

    output_dir = Path(output_dir)
    graph_dir = Path(graph_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    graph_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "status": reports[0]["status"],
        "input_particle_count": sum(report["input_particle_count"] for report in reports),
        "num_shards": len(reports),
        "records": records,
    }
    summary_path = output_dir / "single_pass_gate_followup_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    candidates = [
        row for row in records if row["kind"] == "entrance_plus_backstop"
    ]
    control = next(row for row in records if row["kind"] == "full_donut")
    entrance = next(row for row in records if row["kind"] == "entrance_only")
    crossings = sorted({row["backstop_crossing_offset_m"] for row in candidates})
    intensities = sorted({row["backstop_s0"] for row in candidates})
    grid = np.zeros((len(intensities), len(crossings)), dtype=float)
    for row in candidates:
        grid[intensities.index(row["backstop_s0"]), crossings.index(row["backstop_crossing_offset_m"])] = row["usable_at_end_count"]
    fig, (heatmap_axis, comparison_axis) = plt.subplots(1, 2, figsize=(13, 5.5))
    image = heatmap_axis.imshow(grid, origin="lower", aspect="auto", cmap="viridis")
    heatmap_axis.set_xticks(range(len(crossings)), [f"{value * 1e3:g}" for value in crossings])
    heatmap_axis.set_yticks(range(len(intensities)), [f"{value:g}" for value in intensities])
    heatmap_axis.set(xlabel="downstream backstop crossing [mm]", ylabel="backstop s0", title="Entrance slower + downstream backstop")
    for i in range(len(intensities)):
        for j in range(len(crossings)):
            heatmap_axis.text(j, i, str(int(grid[i, j])), ha="center", va="center", color="white")
    fig.colorbar(image, ax=heatmap_axis, label="usable atoms at 100 ms")
    best = max(candidates, key=lambda row: (row["usable_at_end_count"], row["usable_ever_count"]))
    labels = ["entrance only", "best entrance +\nbackstop", "full donut"]
    counts = [entrance["usable_at_end_count"], best["usable_at_end_count"], control["usable_at_end_count"]]
    comparison_axis.bar(labels, counts, color=["tab:blue", "tab:orange", "tab:green"])
    comparison_axis.set(ylabel="usable atoms at 100 ms", title="Best finite-gate candidate versus controls")
    comparison_axis.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    graph_path = graph_dir / "single_pass_gate_followup.png"
    fig.savefig(graph_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {summary_path}", flush=True)
    print(f"Saved: {graph_path}", flush=True)
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--graph-dir", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = parse_args()
    merge_screen(arguments.input_root, arguments.output_dir, arguments.graph_dir)
