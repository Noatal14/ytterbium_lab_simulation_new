"""Merge disjoint 3D-MOT retention shards at one global cohort peak."""

import argparse
import json
from pathlib import Path

import numpy as np

from studies.compare_3d_mot_retention import (
    DEFAULT_MIN_FIT_R_SQUARED,
    DEFAULT_MIN_LOSS_FRACTION,
    _json_ready_analysis,
    analyze_masks,
    plot_comparison,
)


DIAGNOSTIC_COUNT_FIELDS = (
    "particle_count",
    "entered_capture_region_count",
    "slow_inside_count",
    "minimum_residence_met_count",
    "capture_eligible_ever_count",
)


def _validate_reports(reports):
    if not reports:
        raise ValueError("No retention shard reports were found.")
    expected = reports[0]["num_shards"]
    indices = sorted(report["shard_index"] for report in reports)
    if len(reports) != expected or indices != list(range(expected)):
        raise ValueError(f"Expected shards 0..{expected - 1}, got {indices}.")
    shared = (
        reports[0]["profiles"],
        reports[0]["dt_s"],
        reports[0]["t_max_s"],
        reports[0]["time_points_s"],
    )
    if any(
        (report["profiles"], report["dt_s"], report["t_max_s"], report["time_points_s"])
        != shared
        for report in reports[1:]
    ):
        raise ValueError("Retention shard configurations do not match.")


def _merged_diagnostics(reports, profile):
    shard_diagnostics = [report["results"][profile]["diagnostics"] for report in reports]
    merged = {
        field: int(sum(item[field] for item in shard_diagnostics))
        for field in DIAGNOSTIC_COUNT_FIELDS
    }
    total = merged["particle_count"]
    merged["fractions"] = {
        "entered_capture_region": merged["entered_capture_region_count"] / total,
        "slow_inside": merged["slow_inside_count"] / total,
        "minimum_residence_met": merged["minimum_residence_met_count"] / total,
        "capture_eligible_ever": merged["capture_eligible_ever_count"] / total,
    }
    merged["distribution_note"] = (
        "Exact pooled distributions require trajectory data; per-shard summaries are retained below."
    )
    merged["shard_distribution_summaries"] = shard_diagnostics
    return merged


def retained_at_end_mask(analysis, final_state_available):
    """Select the global peak cohort that stayed inside through the final sample."""
    available = np.asarray(final_state_available, dtype=bool)
    retained = np.zeros(len(available), dtype=bool)
    retained[analysis["cohort_indices"]] = True
    retained &= np.all(
        analysis["inside_masks"][:, analysis["peak_index"] :], axis=1
    )
    return retained & available


def run_merge(
    input_root,
    output_dir,
    checkpoint_root=None,
    checkpoint_output_dir=None,
):
    input_root = Path(input_root)
    report_paths = sorted(input_root.glob("shard_*/retention_summary.json"))
    reports = [json.loads(path.read_text()) for path in report_paths]
    _validate_reports(reports)
    time_points = np.asarray(reports[0]["time_points_s"], dtype=float)
    analyses = {}
    for profile in reports[0]["profiles"]:
        inside_parts = []
        eligible_parts = []
        for report_path in report_paths:
            masks = np.load(report_path.parent / f"{profile}_retention_masks.npz")
            inside_parts.append(masks["inside_masks"])
            eligible_parts.append(masks["eligible_masks"])
        analyses[profile] = analyze_masks(
            np.concatenate(inside_parts, axis=0),
            np.concatenate(eligible_parts, axis=0),
            time_points,
            diagnostics=_merged_diagnostics(reports, profile),
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_path = output_dir / "retention_comparison.png"
    summary_path = output_dir / "retention_summary.json"
    checkpoint_summary = {}
    if (checkpoint_root is None) != (checkpoint_output_dir is None):
        raise ValueError(
            "checkpoint_root and checkpoint_output_dir must be supplied together."
        )
    if checkpoint_root is not None:
        checkpoint_root = Path(checkpoint_root)
        checkpoint_output_dir = Path(checkpoint_output_dir)
        checkpoint_output_dir.mkdir(parents=True, exist_ok=True)
        for profile, analysis in analyses.items():
            state_parts = []
            available_parts = []
            index_parts = []
            for report_path in report_paths:
                checkpoint = np.load(
                    checkpoint_root
                    / report_path.parent.name
                    / f"{profile}_final_states.npz"
                )
                state_parts.append(checkpoint["final_states"])
                available_parts.append(checkpoint["final_state_available"])
                index_parts.append(checkpoint["selected_particle_indices"])
            final_states = np.concatenate(state_parts, axis=0)
            final_available = np.concatenate(available_parts, axis=0)
            source_indices = np.concatenate(index_parts, axis=0)
            survivor_mask = retained_at_end_mask(analysis, final_available)
            survivor_states = final_states[survivor_mask]
            survivor_indices = source_indices[survivor_mask]
            states_path = checkpoint_output_dir / f"{profile}_survivors.npy"
            np.save(states_path, survivor_states)
            np.savez_compressed(
                checkpoint_output_dir / f"{profile}_survivor_metadata.npz",
                selected_particle_indices=survivor_indices,
                final_time_s=float(time_points[-1]),
            )
            checkpoint_summary[profile] = {
                "survivor_count": int(len(survivor_states)),
                "states_file": str(states_path),
            }
    plot_comparison(time_points, analyses, plot_path)
    summary = {
        "purpose": "globally merge disjoint retention shards before choosing each peak cohort",
        "source_files": [str(path) for path in report_paths],
        "input_particle_count": int(sum(r["input_particle_count"] for r in reports)),
        "num_shards": len(reports),
        "profiles": reports[0]["profiles"],
        "dt_s": reports[0]["dt_s"],
        "t_max_s": reports[0]["t_max_s"],
        "time_points_s": reports[0]["time_points_s"],
        "fit_model": "N_inf + (N0 - N_inf) * exp(-elapsed_time / tau)",
        "fit_acceptance": {
            "minimum_loss_fraction": DEFAULT_MIN_LOSS_FRACTION,
            "minimum_r_squared": DEFAULT_MIN_FIT_R_SQUARED,
        },
        "continuation_checkpoints": checkpoint_summary,
        "results": {
            profile: _json_ready_analysis(analysis)
            for profile, analysis in analyses.items()
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    for profile, analysis in analyses.items():
        fit = analysis["fit"]
        fit_text = (
            f"tau={fit['tau_s'] * 1e3:.3f} ms, R2={fit['r_squared']:.4f}"
            if fit.get("accepted")
            else f"tau rejected: {fit['reason']}"
        )
        print(f"{profile}: peak={analysis['peak_count']}; {fit_text}")
    print(f"Saved plot: {plot_path}")
    print(f"Saved summary: {summary_path}")
    return analyses, plot_path, summary_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--checkpoint-root")
    parser.add_argument("--checkpoint-output-dir")
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = parse_args()
    run_merge(
        arguments.input_root,
        arguments.output_dir,
        arguments.checkpoint_root,
        arguments.checkpoint_output_dir,
    )
