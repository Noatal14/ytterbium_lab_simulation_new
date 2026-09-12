"""Merge donut-ablation shards and create population and trajectory figures."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from config import Geometry
from studies.analyze_3d_mot_donut_ablation import VARIANT_ORDER
from studies.compare_3d_mot_retention import _json_ready_analysis, analyze_masks


LABELS = {
    "full_donut": "full donut",
    "without_positive_z_blue": "without +z blue beams",
    "without_transverse_y_blue": "without transverse y blue beams",
    "counterpropagating_pair_shell": "counterpropagating pair, full shell",
    "single_pass_counterpropagating_pair": "counterpropagating pair, single pass",
}


def _load_reports(input_root):
    paths = sorted(Path(input_root).glob("shard_*/ablation_summary.json"))
    if not paths:
        raise ValueError("No donut-ablation shard reports found.")
    return paths, [json.loads(path.read_text()) for path in paths]


def _merge_masks(paths, reports):
    time_points = np.asarray(reports[0]["time_points_s"], dtype=float)
    analyses = {}
    for name in VARIANT_ORDER:
        inside_parts = []
        eligible_parts = []
        for report_path, report in zip(paths, reports):
            if not np.array_equal(time_points, np.asarray(report["time_points_s"], dtype=float)):
                raise ValueError("Shard time grids differ.")
            data = np.load(report_path.parent / f"{name}_masks.npz")
            inside_parts.append(data["inside_masks"])
            eligible_parts.append(data["eligible_masks"])
        analyses[name] = analyze_masks(
            np.concatenate(inside_parts, axis=0),
            np.concatenate(eligible_parts, axis=0),
            time_points,
        )
    return time_points, analyses


def _plot_population(time_points, analyses, output_path):
    fig, (curve_ax, bar_ax) = plt.subplots(1, 2, figsize=(14, 5.8))
    for name in VARIANT_ORDER:
        curve_ax.plot(
            time_points * 1e3,
            analyses[name]["capture_eligible_counts"],
            linewidth=2.0,
            label=LABELS[name],
        )
    curve_ax.set_xlabel("simulation time [ms]")
    curve_ax.set_ylabel("capture-eligible atom count")
    curve_ax.set_title("Time-resolved captured population")
    curve_ax.grid(alpha=0.25)
    curve_ax.legend(fontsize=8)

    counts = [int(np.any(analyses[name]["eligible_masks"], axis=1).sum()) for name in VARIANT_ORDER]
    bars = bar_ax.barh([LABELS[name] for name in VARIANT_ORDER], counts)
    bar_ax.bar_label(bars, padding=3)
    bar_ax.set_xlabel("atoms capture-eligible at least once")
    bar_ax.set_title("Paired ablation outcome")
    bar_ax.grid(axis="x", alpha=0.25)
    fig.suptitle("Which 399-nm beam functions make the donut effective?")
    fig.tight_layout()
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return counts


def _choose_representative(paths, reports):
    candidates = []
    for path, report in zip(paths, reports):
        metadata = report.get("representative")
        if metadata:
            candidates.append((metadata, path.parent / "representative_trajectory.npz"))
    if not candidates:
        return None, None
    metadata, path = max(
        candidates,
        key=lambda item: (
            item[0]["qualifies_full_captured_single_pass_failed"],
            item[0]["full_donut_blue_exposure_episode_count"],
        ),
    )
    return metadata, np.load(path)


def _plot_representative(metadata, data, output_path):
    center = np.asarray(Geometry.MOT_3D_CENTER_M, dtype=float)
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    for name in VARIANT_ORDER:
        times = data[f"{name}__time_s"] * 1e3
        state = data[f"{name}__state"]
        axes[0, 0].plot(times, (state[2] - center[2]) * 1e3, label=LABELS[name])
        axes[0, 1].plot(times, state[5], label=LABELS[name])
        distance = np.linalg.norm(state[:3].T - center, axis=1) * 1e3
        axes[1, 0].plot(times, distance, label=LABELS[name])
    axes[0, 0].set_ylabel("z relative to MOT center [mm]")
    axes[0, 1].set_ylabel("longitudinal velocity vz [m/s]")
    axes[1, 0].set_ylabel("distance from MOT center [mm]")
    for axis in (axes[0, 0], axes[0, 1], axes[1, 0]):
        axis.set_xlabel("time [ms]")
        axis.grid(alpha=0.25)
    axes[0, 0].legend(fontsize=7)

    full_time = data["full_donut__time_s"] * 1e3
    intensities = data["full_donut__blue_intensity_W_m2"]
    for tag, values in zip(metadata["full_donut_blue_beam_tags"], intensities):
        axes[1, 1].plot(full_time, values, linewidth=1.4, label=tag)
    axes[1, 1].set_xlabel("time [ms]")
    axes[1, 1].set_ylabel("399-nm intensity along full-donut trajectory [W/m²]")
    axes[1, 1].set_yscale("symlog", linthresh=1e-12)
    axes[1, 1].grid(alpha=0.25)
    axes[1, 1].legend(fontsize=7, ncol=2)
    fig.suptitle(
        f"Representative atom {metadata['global_particle_index']}: "
        f"{metadata['full_donut_blue_exposure_episode_count']} blue exposure episodes"
    )
    fig.tight_layout()
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def run_merge(input_root, output_dir, graph_dir):
    paths, reports = _load_reports(input_root)
    time_points, analyses = _merge_masks(paths, reports)
    output_dir = Path(output_dir)
    graph_dir = Path(graph_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    graph_dir.mkdir(parents=True, exist_ok=True)
    counts = _plot_population(time_points, analyses, graph_dir / "donut_ablation_population.png")
    representative, data = _choose_representative(paths, reports)
    if representative is not None:
        _plot_representative(representative, data, graph_dir / "donut_ablation_trajectory.png")
    summary = {
        "purpose": "causal evidence for the blue-shell functions of angled_donut",
        "input_particle_count": int(sum(report["input_particle_count"] for report in reports)),
        "num_shards": len(reports),
        "time_points_s": time_points.tolist(),
        "variants": list(VARIANT_ORDER),
        "capture_eligible_ever_counts": dict(zip(VARIANT_ORDER, counts)),
        "representative": representative,
        "results": {name: _json_ready_analysis(value) for name, value in analyses.items()},
    }
    path = output_dir / "donut_ablation_summary.json"
    path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary["capture_eligible_ever_counts"], indent=2), flush=True)
    print(f"Saved summary: {path}", flush=True)
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--graph-dir", default="graphs/mot_3d_donut_ablation")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    run_merge(args.input_root, args.output_dir, args.graph_dir)
