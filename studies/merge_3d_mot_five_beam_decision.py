"""Merge the paired corrected-five-beam decision screen and plot its ranking."""

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
    "slow_inside_count",
)


def _outcome(path):
    with np.load(path) as data:
        return {name: data[name] for name in data.files}


def merge_screen(input_root, output_dir, graph_dir):
    paths = sorted(Path(input_root).glob("shard_*/five_beam_decision_screen.json"))
    if not paths:
        raise ValueError("No five-beam decision shard reports found.")
    reports = [json.loads(path.read_text()) for path in paths]
    n_points = len(reports[0]["records"])
    if any(len(report["records"]) != n_points for report in reports):
        raise ValueError("Five-beam decision shard point counts differ.")
    control_index = next(
        index
        for index, row in enumerate(reports[0]["records"])
        if row["kind"] == "full_donut"
    )
    control_outcomes = [
        _outcome(path.parent / f"point_{control_index:02d}_outcomes.npz")
        for path in paths
    ]
    records = []
    for index in range(n_points):
        rows = [report["records"][index] for report in reports]
        if len({row["label"] for row in rows}) != 1:
            raise ValueError(f"Shard candidates differ at point {index}.")
        record = dict(rows[0])
        for field in COUNT_FIELDS:
            record[field] = int(sum(row[field] for row in rows))
        record["usable_ever_fraction"] = (
            record["usable_ever_count"] / record["input_particle_count"]
        )
        record["usable_at_end_fraction"] = (
            record["usable_at_end_count"] / record["input_particle_count"]
        )
        if record["kind"] == "five_beam_gravity":
            rescued = lost = shared = 0
            for path, control in zip(paths, control_outcomes):
                candidate = _outcome(path.parent / f"point_{index:02d}_outcomes.npz")
                if not np.array_equal(
                    candidate["global_particle_indices"],
                    control["global_particle_indices"],
                ):
                    raise ValueError("Five-beam and donut outcomes use different atoms.")
                candidate_mask = candidate["usable_at_end"]
                control_mask = control["usable_at_end"]
                rescued += int(np.count_nonzero(candidate_mask & ~control_mask))
                lost += int(np.count_nonzero(~candidate_mask & control_mask))
                shared += int(np.count_nonzero(candidate_mask & control_mask))
            record.update(
                usable_only_in_five_beam_count=rescued,
                usable_only_in_donut_count=lost,
                usable_in_both_count=shared,
            )
        records.append(record)

    ranked = sorted(
        (row for row in records if row["kind"] == "five_beam_gravity"),
        key=lambda row: (
            row["usable_at_end_count"],
            row["usable_ever_count"],
            row["peak_usable_count"],
        ),
        reverse=True,
    )
    control = next(row for row in records if row["kind"] == "full_donut")
    summary = {
        "status": reports[0]["status"],
        "screen_stage": reports[0].get("screen_stage", "initial"),
        "purpose": reports[0]["purpose"],
        "input_particle_count": sum(
            report["input_particle_count"] for report in reports
        ),
        "num_shards": len(reports),
        "best_five_beam": ranked[0],
        "full_donut_control": control,
        "records": records,
    }
    output_dir = Path(output_dir)
    graph_dir = Path(graph_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    graph_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "five_beam_decision_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    display = ranked[::-1]
    fig, axis = plt.subplots(figsize=(11, 7), constrained_layout=True)
    bars = axis.barh(
        [row["label"] for row in display],
        [row["usable_at_end_count"] for row in display],
        color="tab:orange",
    )
    axis.axvline(
        control["usable_at_end_count"],
        color="tab:green",
        linewidth=2.5,
        label=f"full donut: {control['usable_at_end_count']}",
    )
    axis.bar_label(bars, padding=3)
    axis.set(
        xlabel=f"usable atoms at 100 ms out of {summary['input_particle_count']}",
        title="Corrected five-beam MOT: compact paired decision screen",
    )
    axis.grid(axis="x", alpha=0.25)
    axis.legend()
    graph_path = graph_dir / "five_beam_decision_screen.png"
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
    merge_screen(args.input_root, args.output_dir, args.graph_dir)
