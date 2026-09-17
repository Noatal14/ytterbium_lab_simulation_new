"""Merge corrected five-beam velocity shards and create the diagnostic graph."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np

from config import MOT_3D_CAPTURE_CONFIG


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
    time_ms = data["time_s"] * 1e3
    velocities = data["vz_m_s"]
    initial = data["initial_vz_m_s"]
    usable = data["usable_ever"]
    normalization = Normalize(vmin=float(np.nanmin(initial)), vmax=float(np.nanmax(initial)))
    colormap = plt.get_cmap("coolwarm")
    fig, axis = plt.subplots(figsize=(11, 7))

    for row, initial_vz in zip(velocities[usable], initial[usable]):
        axis.plot(
            time_ms,
            row,
            color=colormap(normalization(initial_vz)),
            linewidth=0.75,
            alpha=0.55,
            rasterized=True,
        )
    # Draw failures last and dark so their escape paths remain visible.
    for row in velocities[~usable]:
        axis.plot(
            time_ms,
            row,
            color="black",
            linewidth=0.75,
            alpha=0.52,
            rasterized=True,
        )

    speed_bound = MOT_3D_CAPTURE_CONFIG["maximum_final_speed_m_s"]
    axis.axhline(speed_bound, color="black", linestyle=":", linewidth=0.9)
    axis.axhline(-speed_bound, color="black", linestyle=":", linewidth=0.9)
    axis.plot([], [], color="0.35", label=f"usable at least once ({usable.sum()})")
    axis.plot(
        [], [], color="black", linewidth=1.2,
        label=f"not usable ({len(usable) - usable.sum()})"
    )
    axis.set_xlabel("simulation time [ms]")
    axis.set_ylabel("longitudinal velocity vz [m/s]")
    axis.set_title("All incoming atoms: corrected five-beam MOT")
    axis.grid(alpha=0.2)
    axis.legend()
    scalar = plt.cm.ScalarMappable(norm=normalization, cmap=colormap)
    scalar.set_array([])
    colorbar = fig.colorbar(scalar, ax=axis, pad=0.025)
    colorbar.set_label("initial longitudinal velocity vz,0 [m/s]\nblue = slower, red = faster")
    fig.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


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
