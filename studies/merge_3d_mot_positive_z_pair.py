"""Merge +z blue-pair screen shards and visualize the shell comparison."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from studies.analyze_3d_mot_donut_ablation import DEFAULT_INPUT
from studies.compare_3d_mot_retention import load_shared_ensemble


COUNT_FIELDS = (
    "input_particle_count",
    "capture_eligible_ever_count",
    "peak_capture_eligible_count",
    "entered_capture_region_count",
    "slow_inside_count",
    "minimum_residence_met_count",
)


def merge_screen(input_root, output_dir, graph_dir):
    paths = sorted(Path(input_root).glob("shard_*/positive_z_pair_screen.json"))
    if not paths:
        raise ValueError("No +z-pair screen shard reports found.")
    reports = [json.loads(path.read_text()) for path in paths]
    reference = reports[0]
    n_points = len(reference["records"])
    if any(len(report["records"]) != n_points for report in reports):
        raise ValueError("+z-pair shard point counts differ.")
    states, _ = load_shared_ensemble(
        DEFAULT_INPUT,
        max_atoms=reference["selected_particle_count_before_sharding"],
        seed=reference["selection_seed"],
    )
    initial_vz = states[:, 5]
    merged_records = []
    outcomes_by_point = {}
    for point_index in range(n_points):
        rows = [report["records"][point_index] for report in reports]
        signatures = {
            (row["kind"], row["blue_detuning_gamma"], row["blue_s0"])
            for row in rows
        }
        if len(signatures) != 1:
            raise ValueError(f"Shard parameters differ at point {point_index}.")
        outcome_parts = []
        index_parts = []
        for path in paths:
            with np.load(path.parent / f"point_{point_index:02d}_outcomes.npz") as data:
                outcome_parts.append(data["capture_eligible_ever"].astype(bool))
                index_parts.append(data["global_particle_indices"].astype(int))
        outcomes = np.concatenate(outcome_parts)
        indices = np.concatenate(index_parts)
        order = np.argsort(indices)
        if not np.array_equal(indices[order], np.arange(len(states))):
            raise ValueError(f"Particle indices are incomplete at point {point_index}.")
        outcomes = outcomes[order]
        outcomes_by_point[point_index] = outcomes
        record = dict(rows[0])
        for field in COUNT_FIELDS:
            record[field] = int(sum(row[field] for row in rows))
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

    shell = next(row for row in merged_records if row["kind"] == "shell_control")
    single_pass = [row for row in merged_records if row["kind"] == "single_pass"]
    ranked_single_pass = sorted(
        single_pass,
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
        "shell_control": shell,
        "best_single_pass": ranked_single_pass[0],
        "records": merged_records,
    }
    (output_dir / "positive_z_pair_screen_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )

    detunings = sorted({row["blue_detuning_gamma"] for row in single_pass})
    intensities = sorted({row["blue_s0"] for row in single_pass})
    grid = np.full((len(intensities), len(detunings)), np.nan)
    for row in single_pass:
        grid[intensities.index(row["blue_s0"]), detunings.index(row["blue_detuning_gamma"])] = row[
            "capture_eligible_ever_count"
        ]
    fig, axis = plt.subplots(figsize=(8, 5.5))
    image = axis.imshow(grid, origin="lower", aspect="auto", cmap="viridis")
    axis.set_xticks(range(len(detunings)), [f"{value:g}" for value in detunings])
    axis.set_yticks(range(len(intensities)), [f"{value:g}" for value in intensities])
    axis.set_xlabel("399-nm detuning [Gamma]")
    axis.set_ylabel("399-nm s0")
    axis.set_title(
        "+z-propagating blue pair: single-pass capture\n"
        f"shell control = {shell['capture_eligible_ever_count']}/{len(states)}"
    )
    for i in range(len(intensities)):
        for j in range(len(detunings)):
            axis.text(j, i, f"{int(grid[i, j])}", ha="center", va="center", color="white")
    fig.colorbar(image, ax=axis, label=f"capture-eligible atoms out of {len(states)}")
    fig.tight_layout()
    fig.savefig(graph_dir / "positive_z_pair_single_pass_heatmap.png", dpi=220, bbox_inches="tight")
    plt.close(fig)

    comparison = [shell, *ranked_single_pass[:3]]
    fig, axis = plt.subplots(figsize=(9, 5.5))
    labels = [
        "shell control"
        if row["kind"] == "shell_control"
        else f"single pass\n{row['blue_detuning_gamma']:g} Gamma, s0={row['blue_s0']:g}"
        for row in comparison
    ]
    counts = [row["capture_eligible_ever_count"] for row in comparison]
    bars = axis.bar(labels, counts, color=["tab:blue", "tab:orange", "tab:orange", "tab:orange"])
    axis.set_ylabel(f"capture-eligible atoms out of {len(states)}")
    axis.set_title("+z blue pair: shell versus best single-pass candidates")
    axis.grid(axis="y", alpha=0.25)
    for bar, count in zip(bars, counts):
        axis.text(bar.get_x() + bar.get_width() / 2, count, str(count), ha="center", va="bottom")
    fig.tight_layout()
    fig.savefig(graph_dir / "positive_z_pair_shell_comparison.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    print(f"Shell control: {shell}", flush=True)
    print(f"Best +z-pair single pass: {ranked_single_pass[0]}", flush=True)
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
