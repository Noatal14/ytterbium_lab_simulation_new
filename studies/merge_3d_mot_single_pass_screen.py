"""Merge focused single-pass screen shards and visualize velocity acceptance."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from studies.analyze_3d_mot_donut_ablation import DEFAULT_INPUT
from studies.compare_3d_mot_retention import load_shared_ensemble


def _load_reports(input_root):
    paths = sorted(Path(input_root).glob("shard_*/single_pass_screen.json"))
    if not paths:
        raise ValueError("No single-pass screen shard reports found.")
    return paths, [json.loads(path.read_text()) for path in paths]


def merge_screen(input_root, output_dir, graph_dir):
    paths, reports = _load_reports(input_root)
    reference = reports[0]
    n_points = len(reference["records"])
    if any(len(report["records"]) != n_points for report in reports):
        raise ValueError("Single-pass shard point counts differ.")
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
        parameter_pair = {
            (row["blue_detuning_gamma"], row["blue_s0"]) for row in shard_records
        }
        if len(parameter_pair) != 1:
            raise ValueError(f"Shard parameters differ at point {point_index}.")
        outcome_parts = []
        index_parts = []
        for report_path in paths:
            with np.load(report_path.parent / f"point_{point_index:02d}_outcomes.npz") as data:
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
    summary_path = output_dir / "single_pass_screen_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    detunings = sorted({row["blue_detuning_gamma"] for row in merged_records})
    intensities = sorted({row["blue_s0"] for row in merged_records})
    count_grid = np.full((len(intensities), len(detunings)), np.nan)
    for row in merged_records:
        i = intensities.index(row["blue_s0"])
        j = detunings.index(row["blue_detuning_gamma"])
        count_grid[i, j] = row["capture_eligible_ever_count"]
    fig, axis = plt.subplots(figsize=(8, 5.5))
    image = axis.imshow(count_grid, origin="lower", aspect="auto", cmap="viridis")
    axis.set_xticks(range(len(detunings)), [f"{value:g}" for value in detunings])
    axis.set_yticks(range(len(intensities)), [f"{value:g}" for value in intensities])
    axis.set_xlabel("399-nm detuning [Gamma]")
    axis.set_ylabel("399-nm s0")
    axis.set_title("Single-pass capture: focused spectral/intensity screen")
    for i in range(len(intensities)):
        for j in range(len(detunings)):
            axis.text(j, i, f"{int(count_grid[i, j])}", ha="center", va="center", color="white")
    fig.colorbar(image, ax=axis, label="capture-eligible atoms out of 600")
    fig.tight_layout()
    fig.savefig(graph_dir / "single_pass_screen_heatmap.png", dpi=220, bbox_inches="tight")
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(9, 6))
    edges = np.linspace(float(initial_vz.min()), float(initial_vz.max()), 10)
    centers = 0.5 * (edges[:-1] + edges[1:])
    for row in ranked[:3]:
        outcomes = outcomes_by_point[row["point_index"]]
        bin_index = np.digitize(initial_vz, edges[1:-1])
        total = np.bincount(bin_index, minlength=len(centers))
        captured = np.bincount(
            bin_index, weights=outcomes.astype(float), minlength=len(centers)
        )
        fraction = np.divide(captured, total, out=np.zeros_like(captured), where=total > 0)
        axis.plot(
            centers,
            fraction,
            marker="o",
            label=f"{row['blue_detuning_gamma']:g} Gamma, s0={row['blue_s0']:g}",
        )
    axis.set_xlabel("initial longitudinal velocity vz,0 [m/s]")
    axis.set_ylabel("capture fraction")
    axis.set_ylim(-0.04, 1.04)
    axis.set_title("Velocity acceptance of the three best single-pass points")
    axis.grid(alpha=0.25)
    axis.legend()
    fig.tight_layout()
    fig.savefig(
        graph_dir / "single_pass_screen_velocity_acceptance.png",
        dpi=220,
        bbox_inches="tight",
    )
    plt.close(fig)
    print(f"Best single-pass point: {ranked[0]}", flush=True)
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
