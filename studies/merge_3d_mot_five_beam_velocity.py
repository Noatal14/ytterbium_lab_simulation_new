"""Merge corrected five-beam velocity shards and create the diagnostic graph."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np

from config import MOT_3D_CAPTURE_CONFIG, MOT_3D_FINALIST_STABILITY_CONFIG


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
    # All failures establish the background distribution without turning it
    # into an opaque black mass.
    for row in velocities[~usable]:
        axis.plot(
            time_ms,
            row,
            color="#555b61",
            linewidth=0.5,
            alpha=0.20,
            rasterized=True,
        )
    # Emphasize a deterministic, velocity-stratified subset so representative
    # escape paths remain individually traceable.
    failed_indices = np.flatnonzero(~usable)
    if failed_indices.size:
        ordered = failed_indices[np.argsort(initial[failed_indices])]
        selected_positions = np.linspace(
            0, len(ordered) - 1, min(30, len(ordered)), dtype=int
        )
        for row in velocities[ordered[selected_positions]]:
            axis.plot(
                time_ms,
                row,
                color="#30343b",
                linewidth=0.8,
                alpha=0.65,
                rasterized=True,
            )
    # Successful trajectories carry the initial-velocity encoding and remain
    # visually above the neutral failure distribution.
    for row, initial_vz in zip(velocities[usable], initial[usable]):
        axis.plot(
            time_ms,
            row,
            color=colormap(normalization(initial_vz)),
            linewidth=0.8,
            alpha=0.62,
            rasterized=True,
        )

    speed_bound = MOT_3D_CAPTURE_CONFIG["maximum_final_speed_m_s"]
    axis.axhline(speed_bound, color="black", linestyle=":", linewidth=0.9)
    axis.axhline(-speed_bound, color="black", linestyle=":", linewidth=0.9)
    axis.plot(
        [], [], color="tab:blue", linewidth=1.2,
        label=f"usable at least once ({usable.sum()})"
    )
    axis.plot(
        [], [], color="#555b61", linewidth=1.2,
        label=f"not usable ({len(usable) - usable.sum()}; 30 emphasized)"
    )
    axis.set_xlabel("simulation time [ms]")
    axis.set_ylabel("longitudinal velocity vz [m/s]")
    axis.set_title("All incoming atoms: corrected five-beam MOT")
    axis.grid(alpha=0.2)
    axis.legend()
    diagnostic = MOT_3D_FINALIST_STABILITY_CONFIG["velocity_diagnostic"]
    usable_at_end = diagnostic["usable_at_100ms_reference_count"]
    transient = int(usable.sum()) - usable_at_end
    axis.text(
        0.985,
        0.77,
        "usable at least once: "
        f"{usable.sum()}/{len(usable)} ({100 * usable.mean():.1f}%)\n"
        "usable at 100 ms:     "
        f"{usable_at_end}/{len(usable)} ({100 * usable_at_end / len(usable):.1f}%)\n"
        "transiently usable:    "
        f"{transient}/{len(usable)} ({100 * transient / len(usable):.1f}%)",
        transform=axis.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        color="0.20",
        bbox={"facecolor": "white", "edgecolor": "0.75", "alpha": 0.88},
    )
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
