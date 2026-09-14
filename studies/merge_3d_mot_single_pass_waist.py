"""Merge the focused single-pass waist-screen shards and plot the result."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from studies.analyze_3d_mot_donut_ablation import DEFAULT_INPUT
from studies.compare_3d_mot_retention import load_shared_ensemble


def merge_screen(input_root, output_dir, graph_dir):
    report_paths = sorted(
        Path(input_root).glob("shard_*/single_pass_waist_screen.json")
    )
    if not report_paths:
        raise ValueError("No single-pass waist-screen shard reports found.")
    reports = [json.loads(path.read_text()) for path in report_paths]
    reference = reports[0]
    n_points = len(reference["records"])
    if any(len(report["records"]) != n_points for report in reports):
        raise ValueError("Waist-screen shard point counts differ.")
    states, _ = load_shared_ensemble(
        DEFAULT_INPUT,
        max_atoms=reference["selected_particle_count_before_sharding"],
        seed=reference["selection_seed"],
    )
    initial_vz = states[:, 5]
    merged_records = []
    outcomes_by_point = {}
    for point_index in range(n_points):
        shard_records = [report["records"][point_index] for report in reports]
        signatures = {
            (row["label"], row["blue_waist_mm"], row["blue_s0"])
            for row in shard_records
        }
        if len(signatures) != 1:
            raise ValueError(f"Shard parameters differ at point {point_index}.")
        outcome_parts = []
        index_parts = []
        for report_path in report_paths:
            with np.load(
                report_path.parent / f"point_{point_index:02d}_outcomes.npz"
            ) as data:
                outcome_parts.append(data["capture_eligible_ever"].astype(bool))
                index_parts.append(data["global_particle_indices"].astype(int))
        outcomes = np.concatenate(outcome_parts)
        indices = np.concatenate(index_parts)
        order = np.argsort(indices)
        if not np.array_equal(indices[order], np.arange(len(states))):
            raise ValueError(f"Particle indices are incomplete at point {point_index}.")
        outcomes = outcomes[order]
        outcomes_by_point[point_index] = outcomes
        record = dict(shard_records[0])
        for field in (
            "input_particle_count",
            "capture_eligible_ever_count",
            "peak_capture_eligible_count",
            "entered_capture_region_count",
            "slow_inside_count",
        ):
            record[field] = int(sum(row[field] for row in shard_records))
        record["capture_fraction"] = (
            record["capture_eligible_ever_count"] / record["input_particle_count"]
        )
        captured_vz = initial_vz[outcomes]
        record["captured_initial_vz_min_m_s"] = (
            float(captured_vz.min()) if len(captured_vz) else None
        )
        record["captured_initial_vz_max_m_s"] = (
            float(captured_vz.max()) if len(captured_vz) else None
        )
        merged_records.append(record)

    ranked = sorted(
        merged_records,
        key=lambda row: (
            row["capture_eligible_ever_count"],
            row["peak_capture_eligible_count"],
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
        "input_particle_count": len(states),
        "num_shards": len(reports),
        "best": ranked[0],
        "records": merged_records,
    }
    (output_dir / "single_pass_waist_screen_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )

    labels = [row["label"].replace("_", "\n") for row in merged_records]
    counts = [row["capture_eligible_ever_count"] for row in merged_records]
    colors = [
        "#4c78a8" if row["intensity_control"] != "matched_intensity_at_cutoff"
        else "#f58518"
        for row in merged_records
    ]
    fig, axis = plt.subplots(figsize=(10, 6))
    bars = axis.bar(range(len(labels)), counts, color=colors)
    axis.set_xticks(range(len(labels)), labels)
    axis.set_ylabel(f"capture-eligible atoms out of {len(states)}")
    axis.set_title("Single-pass waist screen at -2 Gamma")
    axis.grid(axis="y", alpha=0.25)
    for bar, count in zip(bars, counts):
        axis.text(bar.get_x() + bar.get_width() / 2, count, str(count), ha="center", va="bottom")
    axis.legend(
        handles=[
            plt.Line2D([0], [0], color="#4c78a8", lw=8, label="fixed peak s0"),
            plt.Line2D([0], [0], color="#f58518", lw=8, label="matched cutoff intensity"),
        ]
    )
    fig.tight_layout()
    fig.savefig(graph_dir / "single_pass_waist_capture.png", dpi=220, bbox_inches="tight")
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(9, 6))
    edges = np.linspace(float(initial_vz.min()), float(initial_vz.max()), 10)
    centers = 0.5 * (edges[:-1] + edges[1:])
    bin_index = np.digitize(initial_vz, edges[1:-1])
    total = np.bincount(bin_index, minlength=len(centers))
    for row in merged_records:
        captured = np.bincount(
            bin_index,
            weights=outcomes_by_point[row["point_index"]].astype(float),
            minlength=len(centers),
        )
        fraction = np.divide(captured, total, out=np.zeros_like(captured), where=total > 0)
        axis.plot(centers, fraction, marker="o", label=row["label"])
    axis.set_xlabel("initial longitudinal velocity vz,0 [m/s]")
    axis.set_ylabel("capture fraction")
    axis.set_ylim(-0.04, 1.04)
    axis.set_title("Velocity acceptance versus single-pass blue waist")
    axis.grid(alpha=0.25)
    axis.legend()
    fig.tight_layout()
    fig.savefig(
        graph_dir / "single_pass_waist_velocity_acceptance.png",
        dpi=220,
        bbox_inches="tight",
    )
    plt.close(fig)
    print(f"Best single-pass waist point: {ranked[0]}", flush=True)
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
