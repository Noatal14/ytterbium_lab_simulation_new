"""Run and summarize multi-seed Zeeman timestep-convergence jobs."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import t as student_t

from config import COLLIMATION_ANGLE_DEG, ZEEMAN_SIM_CONFIG
from simulations.zeeman import zeeman_simulation
from utils.data_paths import ZEEMAN_CONVERGENCE_DIR
from utils.file_helpers import save_file_json


def _base_git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _working_tree_is_dirty():
    try:
        return bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def wilson_interval(successes, total, confidence=0.95):
    """Wilson score interval for a single binomial survivor fraction."""
    if total <= 0 or not 0 <= successes <= total:
        raise ValueError("Require 0 <= successes <= total and total > 0.")
    from statistics import NormalDist

    z = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    p = successes / total
    denominator = 1.0 + z**2 / total
    center = (p + z**2 / (2.0 * total)) / denominator
    half_width = (
        z
        * np.sqrt(p * (1.0 - p) / total + z**2 / (4.0 * total**2))
        / denominator
    )
    return float(center - half_width), float(center + half_width)


def run_one_configuration(n_atoms, dt_s, seed, npools, output_file):
    """Run one independent stochastic ensemble and save a standalone JSON result."""
    started = time.time()
    _, survivors, _ = zeeman_simulation(
        N_particles=n_atoms,
        npools=npools,
        stochastic=True,
        dt=dt_s,
        collimation_angle_deg=COLLIMATION_ANGLE_DEG,
        seed=seed,
    )
    elapsed = time.time() - started
    n_survivors = len(survivors)
    efficiency = n_survivors / n_atoms
    ci_low, ci_high = wilson_interval(n_survivors, n_atoms)
    result = {
        "kind": "zeeman_stochastic_convergence_single_run",
        "base_git_commit": _base_git_commit(),
        "working_tree_was_dirty": _working_tree_is_dirty(),
        "host": platform.node(),
        "configuration": {
            "n_atoms": int(n_atoms),
            "dt_s": float(dt_s),
            "dt_us": float(dt_s * 1e6),
            "seed": int(seed),
            "npools": int(npools),
            "collimation_angle_deg": float(COLLIMATION_ANGLE_DEG),
            "stochastic": True,
        },
        "result": {
            "n_survivors": int(n_survivors),
            "survival_fraction": float(efficiency),
            "survival_percent": float(100.0 * efficiency),
            "binomial_wilson_95_ci_fraction": [ci_low, ci_high],
            "elapsed_seconds": float(elapsed),
        },
    }
    save_file_json(output_file, result)
    print(
        "ZEEMAN_CONVERGENCE_RESULT "
        f"n_atoms={n_atoms} dt_us={dt_s * 1e6:g} seed={seed} "
        f"survivors={n_survivors} survival_percent={100 * efficiency:.6f} "
        f"elapsed_seconds={elapsed:.1f}"
    )
    return result


def summarize_records(records, confidence=0.95):
    """Group runs by timestep and calculate across-seed uncertainty."""
    groups = {}
    for record in records:
        config = record["configuration"]
        key = (int(config["n_atoms"]), float(config["dt_s"]))
        groups.setdefault(key, []).append(record)

    summaries = []
    for (n_atoms, dt_s), group in sorted(groups.items(), key=lambda item: item[0][1]):
        group = sorted(group, key=lambda row: row["configuration"]["seed"])
        fractions = np.array([row["result"]["survival_fraction"] for row in group])
        n_seeds = len(group)
        mean = float(np.mean(fractions))
        if n_seeds > 1:
            std = float(np.std(fractions, ddof=1))
            sem = std / np.sqrt(n_seeds)
            critical = float(student_t.ppf(0.5 + confidence / 2.0, n_seeds - 1))
            ci = [mean - critical * sem, mean + critical * sem]
        else:
            std = sem = None
            ci = [None, None]
        summaries.append(
            {
                "n_atoms": n_atoms,
                "dt_s": dt_s,
                "dt_us": dt_s * 1e6,
                "seeds": [int(row["configuration"]["seed"]) for row in group],
                "n_seeds": n_seeds,
                "mean_survival_fraction": mean,
                "mean_survival_percent": 100.0 * mean,
                "sample_std_fraction": std,
                "sem_fraction": sem,
                "student_t_95_ci_fraction": ci,
            }
        )
    return summaries


def paired_differences(records, reference_dt_s=None):
    """Compare each timestep with the finest timestep using matching seeds."""
    if not records:
        return []
    particle_counts = {int(row["configuration"]["n_atoms"]) for row in records}
    if len(particle_counts) != 1:
        return []
    if reference_dt_s is None:
        reference_dt_s = min(row["configuration"]["dt_s"] for row in records)
    by_dt_seed = {
        (float(row["configuration"]["dt_s"]), int(row["configuration"]["seed"])): row
        for row in records
    }
    timesteps = sorted({key[0] for key in by_dt_seed})
    comparisons = []
    for dt_s in timesteps:
        if np.isclose(dt_s, reference_dt_s):
            continue
        shared_seeds = sorted(
            seed
            for candidate_dt, seed in by_dt_seed
            if np.isclose(candidate_dt, dt_s)
            and (reference_dt_s, seed) in by_dt_seed
        )
        differences = [
            by_dt_seed[(dt_s, seed)]["result"]["survival_fraction"]
            - by_dt_seed[(reference_dt_s, seed)]["result"]["survival_fraction"]
            for seed in shared_seeds
        ]
        comparisons.append(
            {
                "dt_s": dt_s,
                "reference_dt_s": float(reference_dt_s),
                "shared_seeds": shared_seeds,
                "paired_differences_fraction": differences,
                "mean_paired_difference_fraction": (
                    float(np.mean(differences)) if differences else None
                ),
            }
        )
    return comparisons


def load_records(input_dir):
    records = []
    for path in sorted(Path(input_dir).glob("run_*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("kind") == "zeeman_stochastic_convergence_single_run":
            records.append(record)
    return records


def infer_scan_axis(summaries):
    """Identify whether a result collection scans timestep or particle count."""
    timesteps = {row["dt_s"] for row in summaries}
    particle_counts = {row["n_atoms"] for row in summaries}
    if len(timesteps) > 1 and len(particle_counts) == 1:
        return "dt"
    if len(particle_counts) > 1 and len(timesteps) == 1:
        return "n_atoms"
    raise ValueError(
        "A summary must vary exactly one of dt or n_atoms; use separate input directories."
    )


def reproducibility_comparison(first, second):
    """Compare the scientific outputs of two nominally identical runs."""
    keys = ("n_atoms", "dt_s", "seed")
    same_configuration = all(
        first["configuration"][key] == second["configuration"][key] for key in keys
    )
    first_result = first["result"]
    second_result = second["result"]
    same_survivors = first_result["n_survivors"] == second_result["n_survivors"]
    same_fraction = first_result["survival_fraction"] == second_result["survival_fraction"]
    return {
        "same_configuration": same_configuration,
        "same_survivor_count": same_survivors,
        "same_survival_fraction": same_fraction,
        "reproducible": bool(same_configuration and same_survivors and same_fraction),
        "first_n_survivors": int(first_result["n_survivors"]),
        "second_n_survivors": int(second_result["n_survivors"]),
    }


def plot_summary(summaries, output_file, scan_axis="auto"):
    if scan_axis == "auto":
        scan_axis = infer_scan_axis(summaries)
    if scan_axis == "dt":
        x_values = np.array([row["dt_us"] for row in summaries])
        x_label = "RK4 timestep [us]"
        title = "Stochastic Zeeman timestep convergence (95% t interval)"
    elif scan_axis == "n_atoms":
        x_values = np.array([row["n_atoms"] for row in summaries])
        x_label = "initial atom count per seed"
        title = "Zeeman particle-count convergence (95% t interval)"
    else:
        raise ValueError("scan_axis must be 'auto', 'dt', or 'n_atoms'.")
    means = np.array([row["mean_survival_percent"] for row in summaries])
    low = np.array(
        [
            100.0 * row["student_t_95_ci_fraction"][0]
            if row["student_t_95_ci_fraction"][0] is not None
            else np.nan
            for row in summaries
        ]
    )
    high = np.array(
        [
            100.0 * row["student_t_95_ci_fraction"][1]
            if row["student_t_95_ci_fraction"][1] is not None
            else np.nan
            for row in summaries
        ]
    )
    errors = np.vstack((means - low, high - means))
    fig, axis = plt.subplots(figsize=(8, 5.5))
    order = np.argsort(x_values)
    axis.errorbar(x_values[order], means[order], yerr=errors[:, order], marker="o", capsize=5)
    axis.set_xlabel(x_label)
    axis.set_ylabel("mean Zeeman survival [%]")
    axis.set_title(title)
    axis.grid(alpha=0.25)
    fig.tight_layout()
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return output_path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--n-atoms", type=int, required=True)
    run_parser.add_argument("--dt-us", type=float, required=True)
    run_parser.add_argument("--seed", type=int, required=True)
    run_parser.add_argument("--npools", type=int, required=True)
    run_parser.add_argument("--output", type=Path)
    summarize_parser = subparsers.add_parser("summarize")
    summarize_parser.add_argument("--input-dir", type=Path, default=ZEEMAN_CONVERGENCE_DIR)
    summarize_parser.add_argument(
        "--output", type=Path, default=ZEEMAN_CONVERGENCE_DIR / "summary.json"
    )
    summarize_parser.add_argument(
        "--plot", type=Path, default=ZEEMAN_CONVERGENCE_DIR / "summary.png"
    )
    summarize_parser.add_argument(
        "--scan-axis", choices=("auto", "dt", "n_atoms"), default="auto"
    )
    compare_parser = subparsers.add_parser("compare-repeats")
    compare_parser.add_argument("first", type=Path)
    compare_parser.add_argument("second", type=Path)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.command == "run":
        output = args.output or (
            ZEEMAN_CONVERGENCE_DIR
            / f"run_n{args.n_atoms}_dt{args.dt_us:g}us_seed{args.seed}.json"
        )
        run_one_configuration(
            args.n_atoms, args.dt_us * 1e-6, args.seed, args.npools, output
        )
        return
    if args.command == "compare-repeats":
        first = json.loads(args.first.read_text(encoding="utf-8"))
        second = json.loads(args.second.read_text(encoding="utf-8"))
        comparison = reproducibility_comparison(first, second)
        print(json.dumps(comparison, indent=2))
        if not comparison["reproducible"]:
            raise SystemExit(1)
        return
    records = load_records(args.input_dir)
    if not records:
        raise FileNotFoundError(f"No run_*.json files found in {args.input_dir}")
    summaries = summarize_records(records)
    report = {
        "kind": "zeeman_stochastic_convergence_summary",
        "n_run_files": len(records),
        "scan_axis": infer_scan_axis(summaries),
        "groups": summaries,
        "paired_comparisons_to_finest_dt": paired_differences(records),
    }
    save_file_json(args.output, report)
    plot_summary(summaries, args.plot, args.scan_axis)
    print(f"Summary: {args.output}")
    print(f"Plot:    {args.plot}")


if __name__ == "__main__":
    main()
