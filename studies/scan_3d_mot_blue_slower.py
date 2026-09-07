"""Scan 399-nm slowing parameters before optimizing 3D-MOT retention.

Every point uses the same saved 2D-MOT survivor ensemble and random seed. Only
the selected profile's 399-nm saturation parameter and detuning are changed;
the green light, magnetic field, geometry, capture criterion, and simulation
settings remain fixed. The scan is therefore a diagnostic of blue-light
slowing, not a complete optimization of the 3D MOT.
"""

import argparse
import copy
import csv
import gc
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from config import (
    DEFAULT_NUM_POOLS,
    DEFAULT_RANDOM_SEED,
    MOT_3D_CONFIGURATIONS,
    MOT_3D_SIM_CONFIG,
)
from simulations.mot_3d import mot_3d_simulation
from studies.compare_3d_mot_retention import analyze_results, load_shared_ensemble
from utils.data_paths import AFTER_2D_MOT_DIR


DEFAULT_OUTPUT_DIR = Path("data/validation/mot_3d/blue_slower_scan")
DEFAULT_DETUNINGS_GAMMA = (-1.0, -2.0, -3.0, -4.0, -5.0)
DEFAULT_SATURATION_PARAMETERS = (0.3, 1.0, 3.0)


def _finite_or_none(value):
    return float(value) if value is not None and np.isfinite(value) else None


def _scan_record(profile_name, detuning_gamma, s0, analysis):
    diagnostics = analysis["diagnostics"]
    return {
        "profile": profile_name,
        "detuning_gamma": float(detuning_gamma),
        "s0": float(s0),
        "entered_capture_region_count": diagnostics[
            "entered_capture_region_count"
        ],
        "slow_inside_count": diagnostics["slow_inside_count"],
        "minimum_residence_met_count": diagnostics[
            "minimum_residence_met_count"
        ],
        "capture_eligible_ever_count": diagnostics[
            "capture_eligible_ever_count"
        ],
        "peak_capture_eligible_count": analysis["peak_count"],
        "median_minimum_speed_inside_m_s": _finite_or_none(
            diagnostics["minimum_speed_inside_m_s"]["median"]
        ),
        "p10_minimum_speed_inside_m_s": _finite_or_none(
            diagnostics["minimum_speed_inside_m_s"]["p10"]
        ),
        "p90_maximum_residence_time_s": _finite_or_none(
            diagnostics["maximum_continuous_residence_time_s"]["p90"]
        ),
    }


def slowing_rank_key(record):
    """Rank capture first, then slowing/residence, then lower speed."""
    median_speed = record["median_minimum_speed_inside_m_s"]
    return (
        record["capture_eligible_ever_count"],
        record["slow_inside_count"],
        record["minimum_residence_met_count"],
        -(median_speed if median_speed is not None else float("inf")),
        record["entered_capture_region_count"],
    )


def _matrix(records, profile, detunings, saturation_parameters, field):
    lookup = {
        (record["profile"], record["detuning_gamma"], record["s0"]): record
        for record in records
    }
    return np.asarray(
        [
            [lookup[(profile, float(detuning), float(s0))][field] for detuning in detunings]
            for s0 in saturation_parameters
        ],
        dtype=float,
    )


def plot_scan(records, profiles, detunings, saturation_parameters, output_path):
    """Plot slowing count and median in-region speed for every profile."""
    fig, axes = plt.subplots(
        2,
        len(profiles),
        figsize=(5 * len(profiles), 8),
        squeeze=False,
        constrained_layout=True,
    )
    for column, profile in enumerate(profiles):
        slow = _matrix(
            records, profile, detunings, saturation_parameters, "slow_inside_count"
        )
        speed = _matrix(
            records,
            profile,
            detunings,
            saturation_parameters,
            "median_minimum_speed_inside_m_s",
        )
        slow_image = axes[0, column].imshow(
            slow, origin="lower", aspect="auto", interpolation="nearest"
        )
        speed_image = axes[1, column].imshow(
            speed, origin="lower", aspect="auto", interpolation="nearest"
        )
        axes[0, column].set_title(f"{profile}: atoms reaching <=1 m/s")
        axes[1, column].set_title(f"{profile}: median minimum speed")
        fig.colorbar(slow_image, ax=axes[0, column], label="atom count")
        fig.colorbar(speed_image, ax=axes[1, column], label="m/s")
        for row in range(2):
            axes[row, column].set_xticks(
                np.arange(len(detunings)), labels=[f"{value:g}" for value in detunings]
            )
            axes[row, column].set_yticks(
                np.arange(len(saturation_parameters)),
                labels=[f"{value:g}" for value in saturation_parameters],
            )
            axes[row, column].set_xlabel("399-nm detuning [Gamma]")
            axes[row, column].set_ylabel("399-nm s0")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def run_scan(args):
    detunings = tuple(sorted(set(args.detuning_gamma_values)))
    saturation_parameters = tuple(sorted(set(args.s0_values)))
    unknown = sorted(set(args.profiles) - set(MOT_3D_CONFIGURATIONS))
    if unknown:
        raise ValueError(f"Unknown 3D-MOT profiles: {unknown}")
    if not args.profiles or not detunings or not saturation_parameters:
        raise ValueError("Profiles, detunings, and s0 values must not be empty.")
    if any(s0 <= 0 for s0 in saturation_parameters):
        raise ValueError("Every s0 value must be positive.")
    if any(detuning >= 0 for detuning in detunings):
        raise ValueError("This slowing scan requires red detunings below zero.")

    states, input_files = load_shared_ensemble(
        args.input, max_atoms=args.max_atoms, seed=args.seed
    )
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    records = []
    total_points = len(args.profiles) * len(detunings) * len(saturation_parameters)
    point = 0

    for profile_name in args.profiles:
        for s0 in saturation_parameters:
            for detuning in detunings:
                point += 1
                print(
                    f"[{point}/{total_points}] {profile_name}: "
                    f"399 s0={s0:g}, detuning={detuning:g} Gamma"
                )
                profile = copy.deepcopy(MOT_3D_CONFIGURATIONS[profile_name])
                profile["399"]["s0"] = float(s0)
                profile["399"]["detuning_gamma"] = float(detuning)
                results, _ = mot_3d_simulation(
                    states,
                    _3d_mot_config=profile,
                    gravity_enabled=not args.no_gravity,
                    npools=args.npools,
                    dt=args.dt,
                    t_max=args.t_max,
                    seed=args.seed,
                )
                analysis = analyze_results(results, time_points)
                record = _scan_record(profile_name, detuning, s0, analysis)
                records.append(record)
                print(
                    "  entered={entered_capture_region_count}, "
                    "slow={slow_inside_count}, residence={minimum_residence_met_count}, "
                    "eligible={capture_eligible_ever_count}, median v_min={speed}".format(
                        **record,
                        speed=(
                            f"{record['median_minimum_speed_inside_m_s']:.3f} m/s"
                            if record["median_minimum_speed_inside_m_s"] is not None
                            else "n/a"
                        ),
                    )
                )
                del results
                gc.collect()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "blue_slower_scan.csv"
    json_path = output_dir / "blue_slower_scan.json"
    plot_path = output_dir / "blue_slower_scan.png"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

    best_by_profile = {
        profile: max(
            (record for record in records if record["profile"] == profile),
            key=slowing_rank_key,
        )
        for profile in args.profiles
    }
    report = {
        "purpose": "screen 399-nm slowing parameters with all other 3D-MOT settings fixed",
        "input_files": [str(path) for path in input_files],
        "input_particle_count": int(len(states)),
        "shared_seed": int(args.seed),
        "profiles": list(args.profiles),
        "detuning_gamma_values": [float(value) for value in detunings],
        "s0_values": [float(value) for value in saturation_parameters],
        "fixed_magnetic_field": True,
        "fixed_green_light": True,
        "dt_s": float(args.dt),
        "t_max_s": float(args.t_max),
        "ranking_priority": [
            "capture_eligible_ever_count (higher)",
            "slow_inside_count (higher)",
            "minimum_residence_met_count (higher)",
            "median_minimum_speed_inside_m_s (lower)",
            "entered_capture_region_count (higher)",
        ],
        "best_by_profile": best_by_profile,
        "records": records,
    }
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    plot_scan(
        records,
        args.profiles,
        detunings,
        saturation_parameters,
        plot_path,
    )
    print("Best exploratory point per profile:")
    for profile, record in best_by_profile.items():
        print(
            f"  {profile}: s0={record['s0']:g}, "
            f"detuning={record['detuning_gamma']:g} Gamma, "
            f"slow={record['slow_inside_count']}, "
            f"eligible={record['capture_eligible_ever_count']}"
        )
    print(f"Saved CSV: {csv_path}")
    print(f"Saved JSON: {json_path}")
    print(f"Saved plot: {plot_path}")
    return records, best_by_profile


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default=str(AFTER_2D_MOT_DIR / "final_ensemble_s0_1.47"),
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--profiles", nargs="+", default=list(MOT_3D_CONFIGURATIONS))
    parser.add_argument(
        "--detuning-gamma-values",
        nargs="+",
        type=float,
        default=list(DEFAULT_DETUNINGS_GAMMA),
    )
    parser.add_argument(
        "--s0-values",
        nargs="+",
        type=float,
        default=list(DEFAULT_SATURATION_PARAMETERS),
    )
    parser.add_argument("--max-atoms", type=int)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=MOT_3D_SIM_CONFIG["t_max_s"])
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument("--no-gravity", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_scan(parse_args())
