"""Merge five-beam gravity-balance shards and plot capture versus lower-beam s0."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


COUNT_FIELDS = (
    "input_particle_count",
    "capture_eligible_ever_count",
    "peak_capture_eligible_count",
    "entered_capture_region_count",
    "slow_inside_count",
    "minimum_residence_met_count",
)


def merge_screen(input_root, output_dir, graph_dir):
    paths = sorted(Path(input_root).glob("shard_*/five_beam_balance_screen.json"))
    if not paths:
        raise ValueError("No five-beam balance shard reports found.")
    reports = [json.loads(path.read_text()) for path in paths]
    reference = reports[0]
    n_points = len(reference["records"])
    if any(len(report["records"]) != n_points for report in reports):
        raise ValueError("Five-beam balance shard point counts differ.")
    merged_records = []
    for point_index in range(n_points):
        rows = [report["records"][point_index] for report in reports]
        if len({row["lower_green_s0"] for row in rows}) != 1:
            raise ValueError(f"Shard parameters differ at point {point_index}.")
        record = dict(rows[0])
        for field in COUNT_FIELDS:
            record[field] = int(sum(row[field] for row in rows))
        record["capture_fraction"] = (
            record["capture_eligible_ever_count"] / record["input_particle_count"]
        )
        merged_records.append(record)
    ranked = sorted(
        merged_records,
        key=lambda row: (
            row["capture_eligible_ever_count"],
            row["peak_capture_eligible_count"],
            row["minimum_residence_met_count"],
        ),
        reverse=True,
    )
    output_dir = Path(output_dir)
    graph_dir = Path(graph_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    graph_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "status": reference["status"],
        "purpose": reference["purpose"],
        "input_particle_count": sum(
            report["input_particle_count"] for report in reports
        ),
        "num_shards": len(reports),
        "best": ranked[0],
        "records": merged_records,
    }
    (output_dir / "five_beam_balance_screen_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )

    s0 = np.asarray([row["lower_green_s0"] for row in merged_records])
    counts = np.asarray(
        [row["capture_eligible_ever_count"] for row in merged_records]
    )
    equilibrium = np.asarray(
        [row["equilibrium_displacement_x_mm"] for row in merged_records]
    )
    order = np.argsort(s0)
    fig, (capture_axis, equilibrium_axis) = plt.subplots(
        2, 1, figsize=(8.5, 8), sharex=True, constrained_layout=True
    )
    capture_axis.plot(s0[order], counts[order], marker="o", linewidth=2.2)
    capture_axis.set_ylabel(f"capture-eligible atoms out of {summary['input_particle_count']}")
    capture_axis.set_title("Five-beam MOT: tuning only the lower +x green beam")
    capture_axis.grid(alpha=0.25)
    equilibrium_axis.plot(
        s0[order], equilibrium[order], marker="o", linewidth=2.2, color="tab:orange"
    )
    equilibrium_axis.axhline(0.0, color="black", linewidth=1, linestyle="--")
    equilibrium_axis.set_xlabel("lower +x 556-nm beam s0")
    equilibrium_axis.set_ylabel("equilibrium displacement x [mm]")
    equilibrium_axis.grid(alpha=0.25)
    fig.savefig(
        graph_dir / "five_beam_lower_green_balance.png",
        dpi=220,
        bbox_inches="tight",
    )
    plt.close(fig)
    print(f"Best five-beam balance point: {ranked[0]}", flush=True)
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
