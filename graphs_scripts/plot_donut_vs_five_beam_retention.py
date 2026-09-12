"""Plot historical 3D-MOT population data for donut and five-beam geometries."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


DEFAULT_INITIAL = Path(
    "data/validation/mot_3d/retention/optimized_full_100ms/merged/retention_summary.json"
)
DEFAULT_DONUT_CONTINUATION = Path(
    "data/validation/mot_3d/retention/donut_continuation_100_to_400ms/merged/retention_summary.json"
)
DEFAULT_OUTPUT = Path(
    "graphs/mot_3d_retention_comparison/donut_vs_five_beam_0_to_400ms.png"
)


def _load(path):
    report = json.loads(Path(path).read_text())
    if "time_points_s" not in report or "results" not in report:
        raise ValueError(f"Invalid retention summary: {path}")
    return report


def _population(report, profile):
    if profile not in report["results"]:
        raise ValueError(f"Profile {profile!r} is missing from retention summary.")
    time_s = np.asarray(report["time_points_s"], dtype=float)
    counts = np.asarray(report["results"][profile]["capture_eligible_counts"], dtype=float)
    if time_s.ndim != 1 or counts.shape != time_s.shape:
        raise ValueError(f"Invalid population curve for {profile}.")
    return time_s, counts


def _continuous_donut_curve(initial, continuation):
    initial_time, initial_counts = _population(initial, "angled_donut")
    continuation_time, continuation_counts = _population(continuation, "angled_donut")
    offset = float(initial_time[-1])
    checkpoint_drop = initial_counts[-1] - continuation_counts[0]
    maximum_allowed_drop = max(1.0, 1e-3 * initial_counts[-1])
    if checkpoint_drop < 0.0 or checkpoint_drop > maximum_allowed_drop:
        raise ValueError(
            "Donut continuation is inconsistent with the final 100-ms population "
            f"({initial_counts[-1]} != {continuation_counts[0]})."
        )
    return (
        np.concatenate((initial_time, offset + continuation_time)),
        np.concatenate((initial_counts, continuation_counts)),
    )


def _five_beam_fit(initial):
    result = initial["results"]["five_beam_gravity"]
    fit = result.get("fit", {})
    if not fit.get("accepted"):
        raise ValueError(f"The stored five-beam fit was not accepted: {fit.get('reason')}")
    peak_time = float(result["peak_time_s"])
    peak_count = float(result["peak_count"])
    tau_s = float(fit["tau_s"])
    plateau = float(fit["plateau_count"])
    elapsed_s = np.asarray(result["elapsed_post_peak_s"], dtype=float)
    retained = np.asarray(result["retained_counts"], dtype=float)
    if elapsed_s.shape != retained.shape:
        raise ValueError("Invalid five-beam retained-cohort curve.")
    observed_time = peak_time + elapsed_s
    fit_time = np.linspace(peak_time, float(observed_time[-1]), 500)
    fit_counts = plateau + (peak_count - plateau) * np.exp(-(fit_time - peak_time) / tau_s)
    return observed_time, retained, fit_time, fit_counts, tau_s, plateau


def create_comparison_plot(initial_path, continuation_path, output_path):
    initial = _load(initial_path)
    continuation = _load(continuation_path)
    donut_time, donut_counts = _continuous_donut_curve(initial, continuation)
    five_time, five_counts = _population(initial, "five_beam_gravity")
    cohort_time, cohort_counts, fit_time, fit_counts, tau_s, plateau = _five_beam_fit(initial)

    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    ax.plot(donut_time * 1e3, donut_counts, linewidth=2.5, label="angled donut")
    ax.plot(five_time * 1e3, five_counts, linewidth=2.5, label="five-beam MOT")
    ax.step(
        cohort_time * 1e3,
        cohort_counts,
        where="post",
        linewidth=1.7,
        color="tab:red",
        alpha=0.9,
        label="five-beam retained peak cohort",
    )
    ax.plot(
        fit_time * 1e3,
        fit_counts,
        "--",
        linewidth=2.0,
        color="tab:green",
        label=rf"five-beam decay fit: $\tau={tau_s * 1e3:.2f}$ ms",
    )
    ax.axvline(100.0, color="0.45", linestyle=":", linewidth=1.3)
    ax.text(
        102.0,
        0.97,
        "five-beam simulation ends at 100 ms",
        transform=ax.get_xaxis_transform(),
        va="top",
        fontsize=9,
        color="0.35",
    )
    ax.set_xlim(0.0, 400.0)
    ax.set_ylim(bottom=0.0)
    ax.set_xlabel("simulation time [ms]")
    ax.set_ylabel("atoms satisfying the 3D-MOT capture criterion")
    ax.set_title("3D-MOT captured population: donut versus five-beam geometry")
    ax.grid(alpha=0.25)
    ax.legend()
    ax.text(
        0.99,
        0.02,
        f"five-beam fitted plateau: {plateau:.1f} atoms\n"
        "Historical simulation data; geometries are pre-laboratory designs",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8.5,
        color="0.35",
    )
    fig.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {output_path}")
    return output_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial", type=Path, default=DEFAULT_INITIAL)
    parser.add_argument("--donut-continuation", type=Path, default=DEFAULT_DONUT_CONTINUATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    create_comparison_plot(args.initial, args.donut_continuation, args.output)
