"""Merge and plot the focused single-pass gate follow-up."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


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

    single = [row for row in records if row["kind"] == "single_gate"]
    two_stage = [row for row in records if row["kind"] == "two_stage"]
    control = next(row for row in records if row["kind"] == "full_donut")
    fig, (location_axis, allocation_axis) = plt.subplots(1, 2, figsize=(13, 5.5))
    location_axis.plot(
        [abs(row["crossing_offset_m"]) * 1e3 for row in single],
        [row["usable_at_end_count"] for row in single],
        marker="o",
    )
    location_axis.axhline(control["usable_at_end_count"], linestyle="--", color="tab:green", label="full donut")
    location_axis.set(xlabel="single-gate crossing upstream [mm]", ylabel="usable atoms at 100 ms", title="Single-gate location")
    location_axis.grid(alpha=0.25)
    location_axis.legend()
    allocation_axis.bar(
        [f"{row['front_s0']:g} + {row['rear_s0']:g}" for row in two_stage],
        [row["usable_at_end_count"] for row in two_stage],
    )
    allocation_axis.axhline(control["usable_at_end_count"], linestyle="--", color="tab:green", label="full donut")
    allocation_axis.set(xlabel="front + rear nominal s0", ylabel="usable atoms at 100 ms", title="Two non-overlapping gates; total s0 = 0.75")
    allocation_axis.grid(axis="y", alpha=0.25)
    allocation_axis.legend()
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
