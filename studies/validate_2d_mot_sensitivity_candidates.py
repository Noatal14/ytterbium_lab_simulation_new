"""Confirm the two actionable candidates selected by the v20 sensitivity screen."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import DEFAULT_NUM_POOLS
from studies.optimize_2d_mot_joint import evaluate_configuration
from studies.validate_2d_mot_hybrid_finalists import paired_comparison
from utils.RK4StHybridCustom import RK4StHybridCustom
from utils.data_paths import MOT_2D_OPTIMIZATION_DIR
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles


FINAL_DT_S = 0.625e-6
REFERENCE_PATH = (
    MOT_2D_OPTIMIZATION_DIR
    / "hybrid_finalist_confirmation_v19_dt0p625us"
    / "overnight_lower_power.json"
)
DEFAULT_OUTPUT_DIR = (
    MOT_2D_OPTIMIZATION_DIR
    / "sensitivity_candidate_confirmation_v21_n10000x10_dt0p625us"
)
CANDIDATES = (
    {
        "name": "shifted_tuning_selected_s0",
        "origin": "final_sensitivity_v20 point02",
        "s0": 1.4744970,
        "detuning_gamma": -1.2040645,
        "magnet_radius": 0.049317614,
    },
    {
        "name": "shifted_tuning_s0_1p5",
        "origin": "final_sensitivity_v20 point02 with maximum expected s0",
        "s0": 1.5,
        "detuning_gamma": -1.2040645,
        "magnet_radius": 0.049317614,
    },
)


def run_candidate(args):
    candidate = CANDIDATES[args.candidate_index]
    ensembles = load_production_ensembles(
        max_ensembles=args.n_ensembles,
        particles_per_ensemble=args.particles_per_ensemble,
    )
    parameters = {
        key: candidate[key] for key in ("s0", "detuning_gamma", "magnet_radius")
    }
    evaluation = evaluate_configuration(
        **parameters,
        ensembles=ensembles,
        mot_seed_start=args.mot_seed_start,
        npools=args.npools,
        dt_s=FINAL_DT_S,
        stochastic_sim_function=RK4StHybridCustom,
    )
    result = {
        "kind": "mot_2d_sensitivity_candidate_confirmation_result",
        "name": candidate["name"],
        "origin": candidate["origin"],
        "parameters": parameters,
        "design": {
            "n_ensembles": len(ensembles),
            "particles_per_ensemble": args.particles_per_ensemble,
            "mot_seed_start": args.mot_seed_start,
            "dt_s": FINAL_DT_S,
            "npools": args.npools,
            "paired_design": True,
            "stochastic_solver": RK4StHybridCustom.__name__,
        },
        "evaluation": evaluation,
    }
    output_dir = Path(args.output_dir)
    save_file_json(output_dir / f"{candidate['name']}.json", result)
    print(
        "MOT_2D_SENSITIVITY_CANDIDATE_RESULT "
        f"name={candidate['name']} "
        "mean_conditional_percent="
        f"{100 * evaluation['statistics']['mean_conditional_efficiency']:.6f}"
    )
    return result


def summarize_saved_results(output_dir, reference_path=REFERENCE_PATH):
    reference = json.loads(Path(reference_path).read_text(encoding="utf-8"))
    results = [
        json.loads((Path(output_dir) / f"{candidate['name']}.json").read_text())
        for candidate in CANDIDATES
    ]
    expected_design = reference["design"]
    if any(result["design"] != expected_design for result in results):
        raise ValueError(
            "Candidate runs must use the exact paired design of the v19 reference."
        )
    all_results = [reference, *results]
    comparisons = []
    for reference_index, reference_result in enumerate(all_results):
        for candidate_result in all_results[reference_index + 1 :]:
            comparisons.append(
                paired_comparison(candidate_result, reference_result)
            )
    summary = {
        "kind": "mot_2d_sensitivity_candidate_confirmation_summary",
        "reference": {
            "name": reference["name"],
            "parameters": reference["parameters"],
            "statistics": reference["evaluation"]["statistics"],
        },
        "candidates": [
            {
                "name": result["name"],
                "parameters": result["parameters"],
                "statistics": result["evaluation"]["statistics"],
            }
            for result in results
        ],
        "paired_comparisons": comparisons,
        "design": expected_design,
    }
    save_file_json(Path(output_dir) / "summary.json", summary)
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-index", type=int, choices=range(len(CANDIDATES)))
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--n-ensembles", type=int, default=10)
    parser.add_argument("--particles-per-ensemble", type=int, default=10_000)
    parser.add_argument("--mot-seed-start", type=int, default=12_000)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    if not args.summarize_only and args.candidate_index is None:
        parser.error("--candidate-index is required unless --summarize-only is used")
    return args


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.summarize_only:
        print(json.dumps(summarize_saved_results(arguments.output_dir), indent=2))
    else:
        run_candidate(arguments)
