"""Merge finalist shards and plot loading plus 0--400 ms stability."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from studies.compare_3d_mot_finalist_stability import PROFILE_NAMES
from studies.compare_3d_mot_retention import fit_retention_lifetime


DEFAULT_INITIAL_DONUT = Path(
    "data/validation/mot_3d/retention/optimized_full_100ms/merged/retention_summary.json"
)
DEFAULT_DONUT_CONTINUATION = Path(
    "data/validation/mot_3d/retention/donut_continuation_100_to_400ms/merged/retention_summary.json"
)
DEFAULT_GRAPH = Path(
    "graphs/mot_3d_configuration_decision/18_finalist_loading_and_stability.png"
)


def _load_json(path):
    return json.loads(Path(path).read_text())


def _validate_reports(reports):
    if not reports:
        raise ValueError("No finalist-stability shard reports were found.")
    expected = int(reports[0]["num_shards"])
    indices = sorted(int(report["shard_index"]) for report in reports)
    if len(reports) != expected or indices != list(range(expected)):
        raise ValueError(f"Expected shards 0..{expected - 1}, got {indices}.")
    shared = (
        reports[0]["profiles"],
        reports[0]["dt_s"],
        reports[0]["t_max_s"],
        reports[0]["selected_particle_count_before_sharding"],
    )
    if any(
        (
            report["profiles"],
            report["dt_s"],
            report["t_max_s"],
            report["selected_particle_count_before_sharding"],
        )
        != shared
        for report in reports[1:]
    ):
        raise ValueError("Finalist-stability shard configurations do not match.")


def _population(report, profile):
    time_s = np.asarray(report["time_points_s"], dtype=float)
    counts = np.asarray(report["results"][profile]["capture_eligible_counts"], dtype=float)
    if time_s.ndim != 1 or counts.shape != time_s.shape:
        raise ValueError(f"Invalid historical population curve for {profile}.")
    return time_s, counts


def historical_donut_curve(initial_path, continuation_path):
    """Join the existing donut loading and continuation without rerunning it."""
    initial = _load_json(initial_path)
    continuation = _load_json(continuation_path)
    loading_time, loading_counts = _population(initial, "angled_donut")
    hold_time, hold_counts = _population(continuation, "angled_donut")
    drop = loading_counts[-1] - hold_counts[0]
    if drop < 0 or drop > max(1.0, 1e-3 * loading_counts[-1]):
        raise ValueError(
            "Historical donut checkpoint does not match its continuation: "
            f"{loading_counts[-1]} versus {hold_counts[0]}."
        )
    return (
        np.concatenate((loading_time, loading_time[-1] + hold_time[1:])),
        np.concatenate((loading_counts, hold_counts[1:])),
    )


def merge_direct_curves(report_paths, profile):
    parts = []
    for report_path in report_paths:
        with np.load(report_path.parent / f"{profile}_curves.npz") as data:
            parts.append({key: np.asarray(data[key]) for key in data.files})
    time_s = parts[0]["time_s"]
    if any(not np.array_equal(part["time_s"], time_s) for part in parts[1:]):
        raise ValueError(f"Time grids differ between shards for {profile}.")
    return {
        "time_s": time_s,
        "active_counts": np.sum([part["active_counts"] for part in parts], axis=0),
        "inside_counts": np.sum([part["inside_counts"] for part in parts], axis=0),
        "usable_counts": np.sum([part["usable_counts"] for part in parts], axis=0),
    }


def population_fit(time_s, counts):
    counts = np.asarray(counts, dtype=float)
    peak_index = int(np.argmax(counts))
    elapsed = np.asarray(time_s[peak_index:], dtype=float) - time_s[peak_index]
    return peak_index, fit_retention_lifetime(elapsed, counts[peak_index:])


def _json_fit(fit):
    result = dict(fit)
    if "fitted_counts" in result:
        result["fitted_counts"] = np.asarray(result["fitted_counts"]).tolist()
    return result


def plot_finalists(curves, output_path):
    labels = {
        "angled_donut": "angled donut (existing run)",
        "five_beam_best": "corrected five-beam MOT",
        "four_blue_gate_best": "four-blue entrance + backstop",
    }
    colors = {
        "angled_donut": "tab:blue",
        "five_beam_best": "tab:orange",
        "four_blue_gate_best": "tab:purple",
    }
    fig, (population_ax, stability_ax) = plt.subplots(
        2, 1, figsize=(11.0, 9.0), gridspec_kw={"height_ratios": (1.25, 1.0)}
    )
    fits = {}
    for name, curve in curves.items():
        time_s = np.asarray(curve["time_s"], dtype=float)
        counts = np.asarray(curve["usable_counts"], dtype=float)
        population_ax.plot(
            time_s * 1e3,
            counts,
            linewidth=2.4,
            color=colors[name],
            label=labels[name],
        )
        peak_index, fit = population_fit(time_s, counts)
        fits[name] = fit
        post_counts = counts[peak_index:]
        elapsed_ms = (time_s[peak_index:] - time_s[peak_index]) * 1e3
        normalized = post_counts / post_counts[0] if post_counts[0] else post_counts
        stability_ax.plot(
            elapsed_ms,
            normalized,
            linewidth=2.2,
            color=colors[name],
            label=labels[name],
        )
        if fit.get("accepted"):
            fitted = np.asarray(fit["fitted_counts"], dtype=float) / post_counts[0]
            stability_ax.plot(
                elapsed_ms,
                fitted,
                "--",
                linewidth=1.8,
                color=colors[name],
                label=rf"{labels[name]} fit: $\tau={fit['tau_s'] * 1e3:.2f}$ ms",
            )

    population_ax.set_xlim(0, 400)
    population_ax.set_ylim(bottom=0)
    population_ax.set_title("3D-MOT finalists: loading and long-time stability")
    population_ax.set_xlabel("simulation time [ms]")
    population_ax.set_ylabel("usable atoms (r <= 5 mm, speed <= 1 m/s)")
    population_ax.grid(alpha=0.25)
    population_ax.legend()

    stability_ax.set_xlim(left=0)
    stability_ax.set_ylim(-0.03, 1.03)
    stability_ax.set_xlabel("time since each configuration's usable-population peak [ms]")
    stability_ax.set_ylabel("fraction of peak usable population")
    stability_ax.grid(alpha=0.25)
    stability_ax.legend()
    stability_ax.text(
        0.99,
        0.03,
        "Same 2D-MOT survivor ensemble; donut curve reused from the existing run",
        transform=stability_ax.transAxes,
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
    return fits


def run_merge(input_root, output_dir, initial_donut, donut_continuation, graph):
    input_root = Path(input_root)
    report_paths = sorted(input_root.glob("shard_*/finalist_stability_shard.json"))
    reports = [_load_json(path) for path in report_paths]
    _validate_reports(reports)
    direct = {name: merge_direct_curves(report_paths, name) for name in PROFILE_NAMES}
    donut_time, donut_counts = historical_donut_curve(initial_donut, donut_continuation)
    curves = {
        "angled_donut": {"time_s": donut_time, "usable_counts": donut_counts},
        **direct,
    }
    fits = plot_finalists(curves, graph)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, curve in direct.items():
        np.savez_compressed(output_dir / f"{name}_merged_curves.npz", **curve)
    total = int(sum(report["input_particle_count"] for report in reports))
    summary = {
        "status": "provisional direct 0--400 ms finalist comparison",
        "input_particle_count": total,
        "num_shards": len(reports),
        "profiles": list(PROFILE_NAMES),
        "historical_donut_sources": [str(initial_donut), str(donut_continuation)],
        "graph": str(graph),
        "criterion": "instantaneous radius <= 5 mm and speed <= 1 m/s",
        "results": {},
    }
    for name, curve in curves.items():
        counts = np.asarray(curve["usable_counts"])
        time_s = np.asarray(curve["time_s"])
        peak = int(np.argmax(counts))
        at_100 = int(counts[np.argmin(np.abs(time_s - 0.1))])
        summary["results"][name] = {
            "peak_usable_count": int(counts[peak]),
            "peak_time_s": float(time_s[peak]),
            "usable_at_100ms_count": at_100,
            "usable_at_400ms_count": int(counts[-1]),
            "fit": _json_fit(fits[name]),
        }
    summary_path = output_dir / "finalist_stability_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Saved graph: {graph}")
    print(f"Saved summary: {summary_path}")
    for name, result in summary["results"].items():
        fit = result["fit"]
        fit_text = (
            f"tau={fit['tau_s'] * 1e3:.2f} ms" if fit.get("accepted")
            else f"tau rejected ({fit['reason']})"
        )
        print(
            f"{name}: peak={result['peak_usable_count']}, "
            f"100 ms={result['usable_at_100ms_count']}, "
            f"400 ms={result['usable_at_400ms_count']}; {fit_text}"
        )
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--initial-donut", type=Path, default=DEFAULT_INITIAL_DONUT)
    parser.add_argument(
        "--donut-continuation", type=Path, default=DEFAULT_DONUT_CONTINUATION
    )
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    run_merge(
        args.input_root,
        args.output_dir,
        args.initial_donut,
        args.donut_continuation,
        args.graph,
    )
