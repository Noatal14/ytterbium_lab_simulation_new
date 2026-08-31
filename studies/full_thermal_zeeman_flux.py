"""Run and summarize Zeeman survival from the full thermal angular distribution."""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import beta

from config import ZEEMAN_SIM_CONFIG
from simulations.zeeman import run_and_save_zeeman
from studies.estimate_oven_flux import estimate_oven_flux
from utils.data_paths import VALIDATION_DIR
from utils.file_helpers import save_file_json


DEFAULT_OUTPUT_DIR = VALIDATION_DIR / "zeeman" / "full_thermal_flux_v1"


def run(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / (
        f"full_thermal_zeeman_n{args.n_atoms}_seed{args.seed}.npy"
    )
    run_and_save_zeeman(
        output_file,
        N_particles=args.n_atoms,
        collimation_angle_deg=None,
        angular_broadening_factor=args.angular_broadening_factor,
        npools=args.npools,
        stochastic=True,
        dt=args.dt_us * 1e-6,
        seed=args.seed,
    )


def clopper_pearson_interval(successes, trials, confidence=0.95):
    alpha = 1.0 - confidence
    low = 0.0 if successes == 0 else beta.ppf(alpha / 2, successes, trials - successes + 1)
    high = 1.0 if successes == trials else beta.ppf(1 - alpha / 2, successes + 1, trials - successes)
    return float(low), float(high)


def summarize(args):
    output_dir = Path(args.output_dir)
    metadata_paths = sorted(output_dir.glob("full_thermal_zeeman_n*_seed*.json"))
    if not metadata_paths:
        raise FileNotFoundError(f"No full-thermal metadata found in {output_dir}")

    runs = []
    for path in metadata_paths:
        with path.open() as stream:
            row = json.load(stream)
        parameters = row["parameters"]
        if not parameters.get("full_angular_distribution", False):
            raise ValueError(f"Not a full-angular run: {path}")
        runs.append(
            {
                "metadata_file": path.name,
                "seed": parameters["seed"],
                "n_initial_atoms": parameters["n_initial_atoms"],
                "n_survivors": row["n_survivors"],
                "survival_fraction": row["survival_fraction"],
                "elapsed_seconds": row["elapsed_seconds"],
                "output_sha256": row["output_sha256"],
                "git_commit": row["software"]["git_commit"],
            }
        )

    seeds = [row["seed"] for row in runs]
    if len(seeds) != len(set(seeds)):
        raise ValueError("Duplicate seeds found in full-thermal results")

    total_initial = sum(row["n_initial_atoms"] for row in runs)
    total_survivors = sum(row["n_survivors"] for row in runs)
    survival_fraction = total_survivors / total_initial
    interval = clopper_pearson_interval(total_survivors, total_initial)
    oven = estimate_oven_flux(args.temperature_c)
    input_flux = oven["yb171_total_flux_s"]

    broadening_factors = {
        row.get("angular_broadening_factor", 1.0)
        for row in (json.loads(path.read_text())["parameters"] for path in metadata_paths)
    }
    if len(broadening_factors) != 1:
        raise ValueError("Full-thermal results contain mixed broadening factors")
    broadening_factor = broadening_factors.pop()

    summary = {
        "kind": "full_thermal_zeeman_flux_summary",
        "angular_distribution": "complete broadened microtube forward hemisphere",
        "angular_broadening_factor": broadening_factor,
        "n_runs": len(runs),
        "total_initial_atoms": total_initial,
        "total_zeeman_survivors": total_survivors,
        "pooled_zeeman_survival_fraction": survival_fraction,
        "exact_binomial_95_ci_fraction": list(interval),
        "estimated_yb171_oven_flux_s": input_flux,
        "estimated_zeeman_survivor_flux_s": input_flux * survival_fraction,
        "estimated_zeeman_survivor_flux_95_ci_s": [
            input_flux * interval[0],
            input_flux * interval[1],
        ],
        "oven_flux_calculation": oven,
        "runs": runs,
        "interpretation_note": (
            "The interval includes Monte Carlo counting uncertainty only. "
            "Uncertainty in the physical oven model and apparatus is separate."
        ),
    }
    output_path = output_dir / "summary.json"
    save_file_json(output_path, summary)
    print(json.dumps(summary, indent=2))
    print(f"Summary saved to: {output_path}")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--n-atoms", type=int, default=50_000)
    run_parser.add_argument("--seed", type=int, required=True)
    run_parser.add_argument("--npools", type=int, default=150)
    run_parser.add_argument(
        "--angular-broadening-factor",
        type=float,
        default=3.0,
        help="Divergence broadening relative to transparent flow (default: 3).",
    )
    run_parser.add_argument(
        "--dt-us", type=float, default=ZEEMAN_SIM_CONFIG["dt_s"] * 1e6
    )
    run_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    run_parser.set_defaults(func=run)

    summary_parser = subparsers.add_parser("summarize")
    summary_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    summary_parser.add_argument("--temperature-c", type=float, default=400.0)
    summary_parser.set_defaults(func=summarize)

    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    arguments.func(arguments)
