"""Merge corrected five-beam velocity shards and create the diagnostic graph."""

import argparse
import json
from pathlib import Path

import numpy as np

from config import MOT_3D_FINALIST_STABILITY_CONFIG
from graphs_scripts.mot_3d_velocity_style import plot_longitudinal_velocity


DEFAULT_GRAPH = Path(
    "graphs/mot_3d_configuration_decision/19_five_beam_longitudinal_velocity.png"
)


def load_and_merge(input_root):
    report_paths = sorted(Path(input_root).glob("shard_*/five_beam_velocity_shard.json"))
    if not report_paths:
        raise ValueError("No corrected five-beam velocity shard reports found.")
    reports = [json.loads(path.read_text()) for path in report_paths]
    expected = int(reports[0]["num_shards"])
    indices = sorted(int(report["shard_index"]) for report in reports)
    if len(reports) != expected or indices != list(range(expected)):
        raise ValueError(f"Expected shards 0..{expected - 1}, got {indices}.")
    parts = [np.load(path.parent / "five_beam_velocity.npz") for path in report_paths]
    time_s = np.asarray(parts[0]["time_s"], dtype=float)
    if any(not np.array_equal(time_s, part["time_s"]) for part in parts[1:]):
        raise ValueError("Five-beam velocity time grids differ between shards.")
    merged = {
        "time_s": time_s,
        "vz_m_s": np.concatenate([part["vz_m_s"] for part in parts]),
        "initial_vz_m_s": np.concatenate([part["initial_vz_m_s"] for part in parts]),
        "usable_ever": np.concatenate([part["usable_ever"] for part in parts]).astype(bool),
        "global_particle_indices": np.concatenate(
            [part["global_particle_indices"] for part in parts]
        ),
    }
    order = np.argsort(merged["global_particle_indices"])
    for key in ("vz_m_s", "initial_vz_m_s", "usable_ever", "global_particle_indices"):
        merged[key] = merged[key][order]
    return reports, merged


def plot_velocity(data, output_path):
    velocities = data["vz_m_s"]
    initial = data["initial_vz_m_s"]
    usable = data["usable_ever"]
    diagnostic = MOT_3D_FINALIST_STABILITY_CONFIG["velocity_diagnostic"]
    usable_at_end = diagnostic["usable_at_100ms_reference_count"]
    transient = int(usable.sum()) - usable_at_end
    return plot_longitudinal_velocity(
        time_s=data["time_s"],
        velocities_m_s=velocities,
        initial_vz_m_s=initial,
        usable=usable,
        title="All incoming atoms: corrected five-beam MOT",
        output_path=output_path,
        usable_label="usable at least once",
        unusable_label="not usable",
        statistics_lines=(
            "usable at least once: "
            f"{usable.sum()}/{len(usable)} ({100 * usable.mean():.1f}%)",
            "usable at 100 ms:     "
            f"{usable_at_end}/{len(usable)} "
            f"({100 * usable_at_end / len(usable):.1f}%)",
            "transiently usable:    "
            f"{transient}/{len(usable)} ({100 * transient / len(usable):.1f}%)",
        ),
    )


def run_merge(input_root, output_dir, graph):
    reports, merged = load_and_merge(input_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output_dir / "five_beam_velocity.npz", **merged)
    plot_velocity(merged, graph)
    total = len(merged["usable_ever"])
    usable = int(merged["usable_ever"].sum())
    summary = {
        "status": "corrected five-beam longitudinal-velocity diagnostic",
        "input_particle_count": total,
        "num_shards": len(reports),
        "usable_ever_count": usable,
        "usable_ever_fraction": usable / total,
        "usable_at_100ms_reference_count": MOT_3D_FINALIST_STABILITY_CONFIG[
            "velocity_diagnostic"
        ]["usable_at_100ms_reference_count"],
        "usable_at_100ms_reference_source": MOT_3D_FINALIST_STABILITY_CONFIG[
            "velocity_diagnostic"
        ]["usable_at_100ms_reference_source"],
        "graph": str(graph),
    }
    summary_path = output_dir / "five_beam_velocity_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Corrected five-beam usable at least once: {usable}/{total}")
    print(f"Saved graph: {graph}")
    print(f"Saved summary: {summary_path}")
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    run_merge(args.input_root, args.output_dir, args.graph)
