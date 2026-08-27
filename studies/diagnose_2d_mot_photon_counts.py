"""Measure per-laser expected photon counts along representative 2D-MOT runs."""

from __future__ import annotations

import argparse
from pathlib import Path

from config import DEFAULT_NUM_POOLS
from lab_setup.config_builder import build_base_config
from lab_setup.zones import get_entire_apparatus_zone
from simulations.mot_2d import mot_simulation_paired_ensembles
from studies.validate_2d_mot_robustness import SELECTED_PARAMETERS
from utils.RK4StPhotonDiagnosticCustom import (
    PHOTON_COUNT_THRESHOLDS,
    RK4StPhotonDiagnosticCustom,
    _empty_laser_statistics,
)
from utils.data_paths import MOT_2D_VALIDATION_DIR
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles
from utils.simulation_helpers import mot_extract_survivors


DEFAULT_OUTPUT = MOT_2D_VALIDATION_DIR / "photon_count_diagnostics_v10.json"


def merge_statistics(target, source):
    target["evaluations"] += source["evaluations"]
    target["sum_expected_photons"] += source["sum_expected_photons"]
    for key in ("minimum_expected_photons", "maximum_expected_photons"):
        value = source[key]
        if value is None:
            continue
        if target[key] is None:
            target[key] = value
        elif key.startswith("minimum"):
            target[key] = min(target[key], value)
        else:
            target[key] = max(target[key], value)
    for threshold in PHOTON_COUNT_THRESHOLDS:
        label = f"below_{threshold:g}"
        target[f"{label}_evaluations"] += source[f"{label}_evaluations"]
        target[f"{label}_expected_photons"] += source[f"{label}_expected_photons"]


def finalize_statistics(statistics):
    evaluations = statistics["evaluations"]
    photons = statistics["sum_expected_photons"]
    result = dict(statistics)
    result["mean_expected_photons"] = photons / evaluations if evaluations else None
    for threshold in PHOTON_COUNT_THRESHOLDS:
        label = f"below_{threshold:g}"
        result[f"{label}_evaluation_fraction"] = (
            statistics[f"{label}_evaluations"] / evaluations if evaluations else None
        )
        result[f"{label}_expected_photon_fraction"] = (
            statistics[f"{label}_expected_photons"] / photons if photons else None
        )
    return result


def laser_tags_for_selected_configuration():
    _, configuration = build_base_config(
        atom_species="Yb171",
        gravity_enabled=True,
        include_zeeman=True,
        include_2d_mot=True,
        include_3dmot=False,
        magnet_radius=SELECTED_PARAMETERS["magnet_radius"],
        _2d_mot_config={
            "s0": SELECTED_PARAMETERS["s0"],
            "detuning_gamma": SELECTED_PARAMETERS["detuning_gamma"],
            "swap_polarization": False,
        },
        zones=get_entire_apparatus_zone(),
    )
    return list(configuration.objects["laser"])


def run_diagnostics(args):
    ensembles = load_production_ensembles(
        particles_per_ensemble=args.particles_per_ensemble,
        zeeman_seeds=args.zeeman_seeds,
    )
    mot_seeds = [seed + 5000 for seed in args.zeeman_seeds]
    grouped = mot_simulation_paired_ensembles(
        survivor_state_ensembles=[row["states"] for row in ensembles],
        seeds=mot_seeds,
        _2d_mot_config={
            "s0": SELECTED_PARAMETERS["s0"],
            "detuning_gamma": SELECTED_PARAMETERS["detuning_gamma"],
            "swap_polarization": False,
        },
        magnet_radius=SELECTED_PARAMETERS["magnet_radius"],
        npools=args.npools,
        stochastic=True,
        dt=args.dt,
        stochastic_sim_function=RK4StPhotonDiagnosticCustom,
    )
    laser_tags = laser_tags_for_selected_configuration()
    categories = {
        "all": {},
        "captured": {},
        "not_captured": {},
    }
    replicate_results = []
    for ensemble, mot_seed, (results, captured_count, _) in zip(
        ensembles, mot_seeds, grouped
    ):
        _, _, captured_indices = mot_extract_survivors(results)
        captured_indices = set(captured_indices)
        for trajectory_index, result in enumerate(results):
            category = (
                "captured" if trajectory_index in captured_indices else "not_captured"
            )
            for laser_index, statistics in result.photon_statistics.items():
                for target_category in ("all", category):
                    target = categories[target_category].setdefault(
                        laser_index, _empty_laser_statistics()
                    )
                    merge_statistics(target, statistics)
        replicate_results.append(
            {
                "zeeman_seed": ensemble["zeeman_seed"],
                "mot_seed": mot_seed,
                "n_input": len(ensemble["states"]),
                "captured": captured_count,
            }
        )

    finalized = {}
    combined = {}
    for category, by_laser in categories.items():
        finalized[category] = {
            (
                laser_tags[int(index)] if int(index) < len(laser_tags) else index
            ): finalize_statistics(statistics)
            for index, statistics in by_laser.items()
        }
        aggregate = _empty_laser_statistics()
        for statistics in by_laser.values():
            merge_statistics(aggregate, statistics)
        combined[category] = finalize_statistics(aggregate)

        total_photons = aggregate["sum_expected_photons"]
        for statistics in finalized[category].values():
            statistics["fraction_of_category_expected_photons"] = (
                statistics["sum_expected_photons"] / total_photons
                if total_photons
                else None
            )
    payload = {
        "kind": "mot_2d_photon_count_diagnostics",
        "parameters": SELECTED_PARAMETERS,
        "dt_s": args.dt,
        "gaussian_approximation_minimum_expected_photons": 15,
        "design": {
            "zeeman_seeds": args.zeeman_seeds,
            "mot_seeds": mot_seeds,
            "particles_per_ensemble": args.particles_per_ensemble,
            "npools": args.npools,
        },
        "replicates": replicate_results,
        "statistics_by_capture_and_laser": finalized,
        "combined_laser_statistics_by_capture": combined,
    }
    save_file_json(Path(args.output), payload)
    print(f"Photon-count diagnostics saved to: {args.output}")
    overall = combined["all"]
    print(
        "All lasers combined: "
        f"evaluations_N_lt_15="
        f"{100 * overall['below_15_evaluation_fraction']:.3f}% "
        f"expected_photons_from_N_lt_15="
        f"{100 * overall['below_15_expected_photon_fraction']:.3f}%"
    )
    for laser, statistics in finalized["all"].items():
        print(
            f"{laser}: "
            f"evaluations_N_lt_15="
            f"{100 * statistics['below_15_evaluation_fraction']:.3f}% "
            f"expected_photons_from_N_lt_15="
            f"{100 * statistics['below_15_expected_photon_fraction']:.3f}% "
            f"share_of_expected_photons="
            f"{100 * statistics['fraction_of_category_expected_photons']:.3f}%"
        )
    return payload


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--zeeman-seeds", type=int, nargs="+", default=[3000, 3001, 3002]
    )
    parser.add_argument("--particles-per-ensemble", type=int, default=2000)
    parser.add_argument("--dt", type=float, default=5e-6)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_diagnostics(parse_args())
