"""Merge finite blue-gate geometry shards and plot their usable populations."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from studies.scan_3d_mot_blue_gate_sequence import VARIANT_ORDER


COUNT_FIELDS = (
    "input_particle_count",
    "usable_ever_count",
    "usable_at_end_count",
    "peak_usable_count",
    "entered_capture_region_count",
    "minimum_residence_met_count",
)


def merge_screen(input_root, output_dir, graph_dir):
    paths = sorted(Path(input_root).glob("shard_*/blue_gate_sequence_screen.json"))
    if not paths:
        raise ValueError("No blue-gate sequence shard reports found.")
    reports = [json.loads(path.read_text()) for path in paths]
    if sorted(report["shard_index"] for report in reports) != list(range(len(reports))):
        raise ValueError("Blue-gate shard indices are incomplete.")
    records = []
    for index, variant in enumerate(VARIANT_ORDER):
        rows = [report["records"][index] for report in reports]
        if any(row["variant"] != variant for row in rows):
            raise ValueError(f"Shard variants differ at index {index}.")
        record = {"variant": variant}
        for field in COUNT_FIELDS:
            record[field] = int(sum(row[field] for row in rows))
        record["usable_ever_fraction"] = (
            record["usable_ever_count"] / record["input_particle_count"]
        )
        record["usable_at_end_fraction"] = (
            record["usable_at_end_count"] / record["input_particle_count"]
        )
        records.append(record)

    output_dir = Path(output_dir)
    graph_dir = Path(graph_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    graph_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "status": reports[0]["status"],
        "input_particle_count": sum(
            report["input_particle_count"] for report in reports
        ),
        "num_shards": len(reports),
        "records": records,
    }
    summary_path = output_dir / "blue_gate_sequence_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    x = np.arange(len(records))
    width = 0.36
    fig, axis = plt.subplots(figsize=(11, 6))
    ever = [row["usable_ever_count"] for row in records]
    final = [row["usable_at_end_count"] for row in records]
    axis.bar(x - width / 2, ever, width, label="usable at least once")
    axis.bar(x + width / 2, final, width, label="usable at 100 ms")
    axis.set_xticks(x, [row["variant"].replace("_", "\n") for row in records])
    axis.set_ylabel(f"atom count out of {summary['input_particle_count']}")
    axis.set_title("Finite blue-gate sequences versus the full donut")
    axis.grid(axis="y", alpha=0.25)
    axis.legend()
    fig.tight_layout()
    graph_path = graph_dir / "blue_gate_sequence_comparison.png"
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
