"""Run and summarize Zeeman survival from the full thermal angular distribution."""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import beta

from config import (
    ACTIVE_ZEEMAN_MAGNET_PROFILE,
    ZEEMAN_MAGNET_PROFILES,
    ZEEMAN_SIM_CONFIG,
)
from simulations.zeeman import run_and_save_zeeman
from studies.beam_source.estimate_oven_flux import estimate_oven_flux
from utils.data_paths import VALIDATION_DIR
from utils.file_helpers import save_file_json


DEFAULT_OUTPUT_DIR = VALIDATION_DIR / "zeeman" / "full_thermal_flux_v1"
CORRECTED_PROFILE = "corrected_projectant_19ring_20261005"


def field_config(profile):
    if profile not in ZEEMAN_MAGNET_PROFILES:
        raise ValueError(f"Unknown Zeeman magnet profile: {profile}")
    radii, positions, tilts = ZEEMAN_MAGNET_PROFILES[profile]
    return {
        "radii_m": list(radii),
        "positions_m": list(positions),
        "tilt_angles_deg": list(tilts),
    }


def output_dir_for_profile(output_dir, profile):
    """Keep non-active profiles out of the historical active-profile directory."""
    output_dir = Path(output_dir)
    if (
        profile != ACTIVE_ZEEMAN_MAGNET_PROFILE
        and output_dir.resolve() == DEFAULT_OUTPUT_DIR.resolve()
    ):
        return VALIDATION_DIR / "zeeman" / f"full_thermal_flux_{profile}_v1"
    return output_dir


def resolve_magnet_profile(parameters):
    """Return the named profile matching metadata's resolved field arrays."""
    recorded = parameters.get("resolved_zeeman_magnet_profile")
    field = parameters.get("zeeman_field_config")
    if not field:
        raise ValueError("Zeeman metadata does not contain field arrays")
    matched = None
    for name, values in ZEEMAN_MAGNET_PROFILES.items():
        if all(
            np.array_equal(np.asarray(field[key]), np.asarray(expected))
            for key, expected in zip(
                ("radii_m", "positions_m", "tilt_angles_deg"), values
            )
        ):
            matched = name
            break
    if matched is None:
        raise ValueError("Zeeman field arrays do not match a registered profile")
    if recorded is not None and recorded != matched:
        raise ValueError(
            "Recorded Zeeman profile does not match embedded field arrays: "
            f"{recorded!r} != {matched!r}"
        )
    return matched


def run(args):
    profile = getattr(args, "magnet_profile", ACTIVE_ZEEMAN_MAGNET_PROFILE)
    output_dir = output_dir_for_profile(args.output_dir, profile)
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
        zeeman_field_config=field_config(profile),
    )


def clopper_pearson_interval(successes, trials, confidence=0.95):
    alpha = 1.0 - confidence
    low = 0.0 if successes == 0 else beta.ppf(alpha / 2, successes, trials - successes + 1)
    high = 1.0 if successes == trials else beta.ppf(1 - alpha / 2, successes + 1, trials - successes)
    return float(low), float(high)


def summarize(args):
    requested_profile = getattr(
        args, "magnet_profile", ACTIVE_ZEEMAN_MAGNET_PROFILE
    )
    output_dir = output_dir_for_profile(args.output_dir, requested_profile)
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
                "zeeman_magnet_profile": resolve_magnet_profile(parameters),
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
    magnet_profiles = {row["zeeman_magnet_profile"] for row in runs}
    if len(magnet_profiles) != 1:
        raise ValueError("Full-thermal results contain mixed magnet profiles")
    magnet_profile = magnet_profiles.pop()
    if magnet_profile != requested_profile:
        raise ValueError(
            "Requested profile does not match the verified result metadata: "
            f"{requested_profile!r} != {magnet_profile!r}"
        )

    summary = {
        "kind": "full_thermal_zeeman_flux_summary",
        "angular_distribution": "complete broadened microtube forward hemisphere",
        "angular_broadening_factor": broadening_factor,
        "zeeman_magnet_profile": magnet_profile,
        "canonical_for_corrected_19ring_campaign": magnet_profile == CORRECTED_PROFILE,
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
            "Uncertainty in the physical oven model and apparatus is separate. "
            "Only a summary whose zeeman_magnet_profile matches the corrected "
            "19-ring campaign may be combined with that campaign's downstream results."
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
    run_parser.add_argument(
        "--magnet-profile",
        choices=sorted(ZEEMAN_MAGNET_PROFILES),
        default=ACTIVE_ZEEMAN_MAGNET_PROFILE,
        help="Explicit Zeeman magnet profile to simulate.",
    )
    run_parser.set_defaults(func=run)

    summary_parser = subparsers.add_parser("summarize")
    summary_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    summary_parser.add_argument(
        "--magnet-profile",
        choices=sorted(ZEEMAN_MAGNET_PROFILES),
        default=ACTIVE_ZEEMAN_MAGNET_PROFILE,
        help="Profile used to choose the default versioned result directory.",
    )
    summary_parser.add_argument("--temperature-c", type=float, default=400.0)
    summary_parser.set_defaults(func=summarize)

    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    arguments.func(arguments)
