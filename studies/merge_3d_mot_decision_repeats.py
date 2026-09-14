"""Merge stochastic 3D-MOT repeats and plot seed-to-seed uncertainty."""

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
)


def merge_repeats(input_root, output_dir, graph_dir):
    paths = sorted(Path(input_root).glob("shard_*/decision_repeats.json"))
    if not paths:
        raise ValueError("No decision-repeat shard reports found.")
    reports = [json.loads(path.read_text()) for path in paths]
    keys = [
        (row["configuration"], row["repeat_seed"])
        for row in reports[0]["records"]
    ]
    if any(
        [(row["configuration"], row["repeat_seed"]) for row in report["records"]]
        != keys
        for report in reports
    ):
        raise ValueError("Decision-repeat shard candidates differ.")
    records = []
    for index, (configuration, seed) in enumerate(keys):
        rows = [report["records"][index] for report in reports]
        record = dict(rows[0])
        for field in COUNT_FIELDS:
            record[field] = int(sum(row[field] for row in rows))
        record["usable_at_end_fraction"] = (
            record["usable_at_end_count"] / record["input_particle_count"]
        )
        records.append(record)
    configurations = sorted({row["configuration"] for row in records})
    aggregate = {}
    for name in configurations:
        values = np.asarray(
            [
                row["usable_at_end_fraction"]
                for row in records
                if row["configuration"] == name
            ]
        )
        aggregate[name] = {
            "mean_usable_at_end_fraction": float(values.mean()),
            "sample_std_usable_at_end_fraction": float(values.std(ddof=1)),
            "minimum_usable_at_end_fraction": float(values.min()),
            "maximum_usable_at_end_fraction": float(values.max()),
            "repeat_count": len(values),
        }
    summary = {
        "status": reports[0]["status"],
        "purpose": reports[0]["purpose"],
        "input_particle_count": sum(
            report["input_particle_count"] for report in reports
        ),
        "num_shards": len(reports),
        "repeat_seeds": reports[0]["repeat_seeds"],
        "aggregate": aggregate,
        "records": records,
    }
    output_dir = Path(output_dir)
    graph_dir = Path(graph_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    graph_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "decision_repeats_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    labels = configurations
    means = [aggregate[name]["mean_usable_at_end_fraction"] for name in labels]
    errors = [aggregate[name]["sample_std_usable_at_end_fraction"] for name in labels]
    fig, axis = plt.subplots(figsize=(9, 6), constrained_layout=True)
    bars = axis.bar(labels, means, yerr=errors, capsize=6, color=["tab:orange", "tab:green", "tab:blue"])
    axis.bar_label(bars, labels=[f"{100 * value:.1f}%" for value in means], padding=4)
    axis.set(
        ylabel="usable fraction at 100 ms",
        title="3D-MOT decision representatives: stochastic-seed repeatability",
        ylim=(0.0, max(means) * 1.18 if max(means) else 1.0),
    )
    axis.grid(axis="y", alpha=0.25)
    graph_path = graph_dir / "decision_repeatability.png"
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
    args = parse_args()
    merge_repeats(args.input_root, args.output_dir, args.graph_dir)
