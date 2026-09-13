"""Plot input phase space and capture acceptance for the donut ablation study."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize

from config import DEFAULT_RANDOM_SEED, Geometry, MOT_3D_CAPTURE_CONFIG
from studies.analyze_3d_mot_donut_ablation import DEFAULT_INPUT, VARIANT_ORDER
from studies.compare_3d_mot_retention import load_shared_ensemble


DEFAULT_VELOCITY_DIR = Path(
    "data/validation/mot_3d/donut_ablation/full_600_100ms/merged/"
    "longitudinal_velocities"
)
DEFAULT_GRAPH_DIR = Path("graphs/mot_3d_donut_ablation")
LABELS = {
    "full_donut": "full donut",
    "without_positive_z_blue": "without +z blue beams",
    "without_transverse_y_blue": "without transverse y blue beams",
    "counterpropagating_pair_shell": "counterpropagating pair, full shell",
    "single_pass_counterpropagating_pair": "counterpropagating pair, single pass",
}
COLORS = {
    "full_donut": "tab:blue",
    "without_positive_z_blue": "tab:orange",
    "without_transverse_y_blue": "tab:green",
    "counterpropagating_pair_shell": "tab:red",
    "single_pass_counterpropagating_pair": "tab:purple",
}


def derived_input_features(states):
    """Return physically useful entrance features from six-component states."""
    states = np.asarray(states, dtype=float)
    if states.ndim != 2 or states.shape[1] != 6:
        raise ValueError("Input states must have shape (N, 6).")
    center = np.asarray(Geometry.MOT_3D_CENTER_M, dtype=float)
    transverse_position = states[:, :2] - center[:2]
    transverse_velocity = states[:, 3:5]
    radial_position = np.linalg.norm(transverse_position, axis=1)
    radial_velocity = np.linalg.norm(transverse_velocity, axis=1)
    angle = np.degrees(np.arctan2(radial_velocity, np.abs(states[:, 5])))
    return {
        "x_mm": transverse_position[:, 0] * 1e3,
        "y_mm": transverse_position[:, 1] * 1e3,
        "z_from_center_mm": (states[:, 2] - center[2]) * 1e3,
        "z_from_entry_um": (states[:, 2] - np.median(states[:, 2])) * 1e6,
        "vx_m_s": states[:, 3],
        "vy_m_s": states[:, 4],
        "vz_m_s": states[:, 5],
        "r_perp_mm": radial_position * 1e3,
        "v_perp_m_s": radial_velocity,
        "speed_m_s": np.linalg.norm(states[:, 3:6], axis=1),
        "angle_deg": angle,
    }


def binned_capture_fraction(values, captured, bin_edges):
    """Return bin centers, fractions, counts, and binomial standard errors."""
    values = np.asarray(values, dtype=float)
    captured = np.asarray(captured, dtype=bool)
    bin_edges = np.asarray(bin_edges, dtype=float)
    bin_index = np.digitize(values, bin_edges[1:-1], right=False)
    total = np.bincount(bin_index, minlength=len(bin_edges) - 1)
    success = np.bincount(
        bin_index, weights=captured.astype(float), minlength=len(bin_edges) - 1
    )
    fraction = np.divide(
        success,
        total,
        out=np.full(len(total), np.nan, dtype=float),
        where=total > 0,
    )
    standard_error = np.sqrt(
        np.divide(
            fraction * (1.0 - fraction),
            total,
            out=np.full(len(total), np.nan, dtype=float),
            where=total > 0,
        )
    )
    return 0.5 * (bin_edges[:-1] + bin_edges[1:]), fraction, total, standard_error


def _load_velocity_results(velocity_dir, states):
    results = {}
    expected_indices = np.arange(len(states))
    for name in VARIANT_ORDER:
        path = Path(velocity_dir) / f"{name}.npz"
        with np.load(path) as data:
            result = {key: np.asarray(data[key]) for key in data.files}
        order = np.argsort(result["global_particle_indices"])
        for key in ("vz_m_s", "capture_eligible_ever", "global_particle_indices"):
            result[key] = result[key][order]
        if not np.array_equal(result["global_particle_indices"], expected_indices):
            raise ValueError(f"Particle indices in {path} do not match the input ensemble.")
        if not np.allclose(result["vz_m_s"][:, 0], states[:, 5], atol=3e-6):
            raise ValueError(f"Initial longitudinal velocities in {path} do not match.")
        results[name] = result
    return results


def _plot_velocity_trajectories(results, initial_vz, graph_dir):
    normalization = Normalize(vmin=float(initial_vz.min()), vmax=float(initial_vz.max()))
    colormap = plt.get_cmap("coolwarm")
    for name, result in results.items():
        fig, axis = plt.subplots(figsize=(11, 7))
        time_ms = result["time_s"] * 1e3
        captured = result["capture_eligible_ever"].astype(bool)
        for is_captured, alpha, linewidth in (
            (False, 0.09, 0.55),
            (True, 0.58, 0.8),
        ):
            for atom_index in np.flatnonzero(captured == is_captured):
                axis.plot(
                    time_ms,
                    result["vz_m_s"][atom_index],
                    color=colormap(normalization(initial_vz[atom_index])),
                    alpha=alpha,
                    linewidth=linewidth,
                    rasterized=True,
                )
        speed_bound = MOT_3D_CAPTURE_CONFIG["maximum_final_speed_m_s"]
        axis.axhspan(-speed_bound, speed_bound, color="black", alpha=0.035)
        axis.axhline(speed_bound, color="black", linestyle=":", linewidth=0.8)
        axis.axhline(-speed_bound, color="black", linestyle=":", linewidth=0.8)
        axis.plot(
            [],
            [],
            color="black",
            alpha=0.58,
            label=f"captured at least once ({captured.sum()})",
        )
        axis.plot(
            [],
            [],
            color="black",
            alpha=0.18,
            label=f"not captured ({(~captured).sum()})",
        )
        axis.set_xlabel("simulation time [ms]")
        axis.set_ylabel("longitudinal velocity vz [m/s]")
        axis.set_title(f"All incoming atoms: {LABELS[name]}")
        axis.grid(alpha=0.2)
        axis.legend(loc="upper right")
        colorbar = fig.colorbar(
            plt.cm.ScalarMappable(norm=normalization, cmap=colormap),
            ax=axis,
            pad=0.02,
        )
        colorbar.set_label(
            "initial longitudinal velocity vz,0 [m/s]\n"
            "(blue = slower, red = faster)"
        )
        fig.tight_layout()
        fig.savefig(
            graph_dir / f"{name}_all_atoms_longitudinal_velocity.png",
            dpi=220,
            bbox_inches="tight",
        )
        plt.close(fig)


def _plot_input_distribution(features, graph_dir):
    panels = (
        ("x_mm", "x0 relative to MOT center [mm]"),
        ("y_mm", "y0 relative to MOT center [mm]"),
        ("z_from_entry_um", "z0 relative to median entrance plane [um]"),
        ("vx_m_s", "vx,0 [m/s]"),
        ("vy_m_s", "vy,0 [m/s]"),
        ("vz_m_s", "vz,0 [m/s]"),
        ("r_perp_mm", "transverse radius r_perp,0 [mm]"),
        ("v_perp_m_s", "transverse speed v_perp,0 [m/s]"),
        ("angle_deg", "entrance angle from +z [deg]"),
    )
    fig, axes = plt.subplots(3, 3, figsize=(14, 10.5))
    for axis, (key, label) in zip(axes.flat, panels):
        axis.hist(features[key], bins=24, color="0.25", alpha=0.82)
        axis.set_xlabel(label)
        axis.set_ylabel("atom count")
        axis.grid(alpha=0.2)
    entrance_z = float(np.median(features["z_from_center_mm"]))
    fig.suptitle(
        "Shared 600-atom phase-space distribution entering the 3D MOT\n"
        f"median entrance plane: z = {entrance_z:.3f} mm relative to MOT center"
    )
    fig.tight_layout()
    fig.savefig(
        graph_dir / "shared_input_phase_space.png", dpi=220, bbox_inches="tight"
    )
    plt.close(fig)


def _scatter_outcome(axis, x, y, captured, xlabel, ylabel, initial_vz, norm, cmap):
    axis.scatter(
        x[~captured],
        y[~captured],
        s=12,
        color="0.72",
        alpha=0.32,
        linewidths=0,
    )
    axis.scatter(
        x[captured],
        y[captured],
        s=19,
        c=initial_vz[captured],
        norm=norm,
        cmap=cmap,
        alpha=0.82,
        linewidths=0,
    )
    axis.set_xlabel(xlabel)
    axis.set_ylabel(ylabel)
    axis.grid(alpha=0.2)


def _plot_acceptance_maps(results, features, graph_dir):
    initial_vz = features["vz_m_s"]
    norm = Normalize(vmin=float(initial_vz.min()), vmax=float(initial_vz.max()))
    cmap = plt.get_cmap("coolwarm")
    for name, result in results.items():
        captured = result["capture_eligible_ever"].astype(bool)
        fig, axes = plt.subplots(2, 2, figsize=(12.5, 10))
        panels = (
            ("vz_m_s", "v_perp_m_s", "vz,0 [m/s]", "v_perp,0 [m/s]"),
            ("r_perp_mm", "v_perp_m_s", "r_perp,0 [mm]", "v_perp,0 [m/s]"),
            (
                "x_mm",
                "y_mm",
                "x0 relative to center [mm]",
                "y0 relative to center [mm]",
            ),
            ("vx_m_s", "vy_m_s", "vx,0 [m/s]", "vy,0 [m/s]"),
        )
        for axis, (x_key, y_key, x_label, y_label) in zip(axes.flat, panels):
            _scatter_outcome(
                axis,
                features[x_key],
                features[y_key],
                captured,
                x_label,
                y_label,
                initial_vz,
                norm,
                cmap,
            )
        fig.subplots_adjust(
            left=0.08,
            right=0.86,
            bottom=0.08,
            top=0.88,
            hspace=0.28,
            wspace=0.25,
        )
        colorbar_axis = fig.add_axes((0.89, 0.16, 0.018, 0.66))
        colorbar = fig.colorbar(
            plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=colorbar_axis
        )
        colorbar.set_label("initial longitudinal velocity vz,0 [m/s]")
        fig.suptitle(
            f"Entrance acceptance: {LABELS[name]} — {captured.sum()}/{len(captured)} captured\n"
            "colored = captured; gray = not captured"
        )
        fig.savefig(
            graph_dir / f"{name}_entrance_acceptance_map.png",
            dpi=220,
            bbox_inches="tight",
        )
        plt.close(fig)


def _plot_capture_probability(results, features, graph_dir):
    feature_specs = (
        ("vz_m_s", "initial longitudinal velocity vz,0 [m/s]"),
        ("v_perp_m_s", "initial transverse speed v_perp,0 [m/s]"),
        ("r_perp_mm", "initial transverse radius r_perp,0 [mm]"),
        ("angle_deg", "initial angle from +z [deg]"),
    )
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    for axis, (key, label) in zip(axes.flat, feature_specs):
        values = features[key]
        edges = np.linspace(float(values.min()), float(values.max()), 9)
        for name in VARIANT_ORDER:
            captured = results[name]["capture_eligible_ever"].astype(bool)
            centers, fraction, counts, error = binned_capture_fraction(values, captured, edges)
            valid = counts >= 10
            axis.errorbar(
                centers[valid],
                fraction[valid],
                yerr=error[valid],
                marker="o",
                markersize=4,
                linewidth=1.6,
                capsize=2,
                color=COLORS[name],
                label=LABELS[name],
            )
        axis.set_xlabel(label)
        axis.set_ylabel("capture fraction")
        axis.set_ylim(-0.04, 1.04)
        axis.grid(alpha=0.22)
    axes[0, 0].legend(fontsize=8)
    fig.suptitle(
        "Which entrance conditions determine 3D-MOT capture?\n"
        "(error bars: binomial standard error)"
    )
    fig.tight_layout()
    fig.savefig(
        graph_dir / "capture_probability_by_entrance_condition.png",
        dpi=220,
        bbox_inches="tight",
    )
    plt.close(fig)


def _write_summary(results, features, graph_dir):
    feature_keys = ("vz_m_s", "v_perp_m_s", "r_perp_mm", "angle_deg")
    summary = {
        "purpose": "entrance phase-space acceptance of donut ablation variants",
        "input_particle_count": int(len(features["vz_m_s"])),
        "input_ranges": {
            key: {
                "minimum": float(np.min(features[key])),
                "maximum": float(np.max(features[key])),
                "median": float(np.median(features[key])),
            }
            for key in feature_keys
        },
        "variants": {},
    }
    for name in VARIANT_ORDER:
        captured = results[name]["capture_eligible_ever"].astype(bool)
        captured_features = {}
        for key in feature_keys:
            values = features[key][captured]
            captured_features[key] = {
                "minimum": float(np.min(values)) if len(values) else None,
                "maximum": float(np.max(values)) if len(values) else None,
                "median": float(np.median(values)) if len(values) else None,
            }
        summary["variants"][name] = {
            "capture_eligible_ever_count": int(captured.sum()),
            "capture_fraction": float(captured.mean()),
            "captured_input_features": captured_features,
        }
    output_path = graph_dir / "capture_phase_space_summary.json"
    output_path.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def run_analysis(
    input_path,
    velocity_dir,
    graph_dir,
    max_atoms=600,
    seed=DEFAULT_RANDOM_SEED,
):
    """Generate every first-stage phase-space diagnostic without rerunning dynamics."""
    states, _ = load_shared_ensemble(input_path, max_atoms=max_atoms, seed=seed)
    results = _load_velocity_results(velocity_dir, states)
    features = derived_input_features(states)
    graph_dir = Path(graph_dir)
    graph_dir.mkdir(parents=True, exist_ok=True)
    _plot_velocity_trajectories(results, features["vz_m_s"], graph_dir)
    _plot_input_distribution(features, graph_dir)
    _plot_acceptance_maps(results, features, graph_dir)
    _plot_capture_probability(results, features, graph_dir)
    _write_summary(results, features, graph_dir)
    print(f"Saved phase-space diagnostics under {graph_dir}", flush=True)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--velocity-dir", default=str(DEFAULT_VELOCITY_DIR))
    parser.add_argument("--graph-dir", default=str(DEFAULT_GRAPH_DIR))
    parser.add_argument("--max-atoms", type=int, default=600)
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = parse_args()
    run_analysis(
        arguments.input,
        arguments.velocity_dir,
        arguments.graph_dir,
        max_atoms=arguments.max_atoms,
        seed=arguments.seed,
    )
