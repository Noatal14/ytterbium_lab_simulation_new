"""Create separate population and retention plots for every 3D-MOT profile.

The script reads an existing ``retention_summary.json`` and never reruns or
refits the simulation. An exponential curve is drawn only when the stored fit
was accepted by the retention study.
"""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


DEFAULT_INPUT = Path(
    "data/validation/mot_3d/retention/optimized_full_100ms/merged/retention_summary.json"
)
DEFAULT_OUTPUT_DIR = Path("graphs/mot_3d_tau")


def load_summary(path):
    path = Path(path)
    report = json.loads(path.read_text())
    if "time_points_s" not in report or not isinstance(report.get("results"), dict):
        raise ValueError("Retention summary must contain time_points_s and results.")
    time_points = np.asarray(report["time_points_s"], dtype=float)
    if time_points.ndim != 1 or time_points.size == 0:
        raise ValueError("time_points_s must be a non-empty one-dimensional array.")
    return report, time_points


def _subtitle(data_label):
    return f"\n{data_label}" if data_label else ""


def _save_population_plot(profile, result, time_points, output_path, data_label):
    counts = np.asarray(result["capture_eligible_counts"], dtype=float)
    if counts.shape != time_points.shape:
        raise ValueError(f"{profile}: capture_eligible_counts length does not match time_points_s.")

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.plot(time_points * 1e3, counts, linewidth=2.2, color="tab:blue")
    peak_time = result.get("peak_time_s")
    if peak_time is not None:
        ax.axvline(
            float(peak_time) * 1e3,
            color="tab:blue",
            linestyle="--",
            alpha=0.65,
            label=f"peak: {result['peak_count']} atoms at {float(peak_time)*1e3:.2f} ms",
        )
        ax.legend()
    ax.set_title(f"3D-MOT captured population — {profile}{_subtitle(data_label)}")
    ax.set_xlabel("simulation time [ms]")
    ax.set_ylabel("atom count satisfying capture criterion")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _save_retention_plot(profile, result, output_path, data_label):
    retained = np.asarray(result["retained_counts"], dtype=float)
    elapsed_s = np.asarray(result["elapsed_post_peak_s"], dtype=float)
    if retained.shape != elapsed_s.shape:
        raise ValueError(f"{profile}: retained_counts length does not match elapsed_post_peak_s.")
    normalized = retained / retained[0] if retained.size and retained[0] else retained

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.step(
        elapsed_s * 1e3,
        normalized,
        where="post",
        linewidth=2.2,
        color="tab:orange",
        label="simulated retention",
    )
    fit = result.get("fit", {})
    if fit.get("accepted") and retained.size and retained[0] > 0:
        tau_s = float(fit["tau_s"])
        plateau = float(fit["plateau_count"])
        fitted = plateau + (retained[0] - plateau) * np.exp(-elapsed_s / tau_s)
        ax.plot(
            elapsed_s * 1e3,
            fitted / retained[0],
            linestyle="--",
            linewidth=2.0,
            color="black",
            label=f"accepted fit: tau = {tau_s*1e3:.2f} ms",
        )
    else:
        reason = fit.get("reason", "fit not available")
        ax.text(
            0.98,
            0.95,
            f"tau not reported\n{reason}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=9,
        )
    ax.set_title(f"Continuous peak-cohort retention — {profile}{_subtitle(data_label)}")
    ax.set_xlabel("time since profile-specific population peak [ms]")
    ax.set_ylabel("retained fraction of peak cohort")
    ax.set_ylim(-0.03, 1.03)
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def generate_profile_plots(input_path, output_dir, profiles=None, data_label=None):
    report, time_points = load_summary(input_path)
    available = report["results"]
    selected = list(available) if profiles is None else list(profiles)
    unknown = sorted(set(selected) - set(available))
    if unknown:
        raise ValueError(f"Profiles not present in retention summary: {unknown}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for profile in selected:
        population_path = output_dir / f"{profile}_population.png"
        retention_path = output_dir / f"{profile}_retention.png"
        _save_population_plot(profile, available[profile], time_points, population_path, data_label)
        _save_retention_plot(profile, available[profile], retention_path, data_label)
        paths.extend((population_path, retention_path))
        print(f"Saved: {population_path}")
        print(f"Saved: {retention_path}")
    return paths


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--profiles", nargs="+")
    parser.add_argument(
        "--data-label",
        help="Optional subtitle, for example 'historical pre-geometry-change run'.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    generate_profile_plots(args.input, args.output_dir, args.profiles, args.data_label)
