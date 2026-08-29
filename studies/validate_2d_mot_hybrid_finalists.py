"""Run the final paired comparison of hybrid 2D-MOT parameter candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import DEFAULT_NUM_POOLS
from studies.optimize_2d_mot_joint import evaluate_configuration
from utils.RK4StHybridCustom import RK4StHybridCustom
from utils.data_paths import MOT_2D_OPTIMIZATION_DIR
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles, student_mean_interval


FINAL_DT_S = 0.625e-6
DECISION_MARGIN_FRACTION = 0.0005
SOURCE_STUDY = "hybrid_refinement_v18"
DEFAULT_OUTPUT_DIR = (
    MOT_2D_OPTIMIZATION_DIR / "hybrid_finalist_confirmation_v19_dt0p625us"
)

FINALISTS = (
    {
        "name": "validated_anchor",
        "origin": "candidate_recheck_hybrid_v17 maximum_capture",
        "s0": 1.4932290341911787,
        "detuning_gamma": -1.2326140031998183,
        "magnet_radius": 0.049418961579403425,
    },
    {
        "name": "overnight_maximum",
        "origin": "hybrid_refinement_v18 worker0 trial16",
        "s0": 1.4918021,
        "detuning_gamma": -1.1733592,
        "magnet_radius": 0.049719911,
    },
    {
        "name": "overnight_lower_power",
        "origin": "hybrid_refinement_v18 worker1 trial15",
        "s0": 1.4744970,
        "detuning_gamma": -1.1840645,
        "magnet_radius": 0.049217614,
    },
)


def paired_comparison(candidate, reference):
    candidate_rows = candidate["evaluation"]["replicates"]
    reference_rows = reference["evaluation"]["replicates"]
    differences = []
    for candidate_row, reference_row in zip(candidate_rows, reference_rows):
        identity = ("zeeman_seed", "mot_seed", "n_input", "subset_seed")
        if any(candidate_row[key] != reference_row[key] for key in identity):
            raise ValueError("Finalist replicates are not aligned for pairing.")
        differences.append(
            candidate_row["conditional_efficiency"]
            - reference_row["conditional_efficiency"]
        )
    mean, low, high, half_width = student_mean_interval(differences)
    return {
        "candidate": candidate["name"],
        "reference": reference["name"],
        "paired_differences_fraction": differences,
        "mean_paired_difference_fraction": mean,
        "paired_95_ci_fraction": [low, high],
        "paired_95_ci_half_width_fraction": half_width,
        "decision_margin_fraction": DECISION_MARGIN_FRACTION,
    }


def build_summary(results, design):
    comparisons = []
    for reference_index, reference in enumerate(results):
        for candidate in results[reference_index + 1 :]:
            comparisons.append(paired_comparison(candidate, reference))
    return {
        "kind": "mot_2d_hybrid_finalist_confirmation_summary",
        "source_study": SOURCE_STUDY,
        "design": design,
        "completed_finalists": [
            {
                "name": row["name"],
                "origin": row["origin"],
                "parameters": row["parameters"],
                "statistics": row["evaluation"]["statistics"],
                "batch_elapsed_seconds": row["evaluation"]["batch_elapsed_seconds"],
            }
            for row in results
        ],
        "all_pairwise_comparisons": comparisons,
    }


def run_finalist(args):
    finalist = FINALISTS[args.finalist_index]
    ensembles = load_production_ensembles(
        max_ensembles=args.n_ensembles,
        particles_per_ensemble=args.particles_per_ensemble,
    )
    parameters = {
        key: finalist[key] for key in ("s0", "detuning_gamma", "magnet_radius")
    }
    evaluation = evaluate_configuration(
        **parameters,
        ensembles=ensembles,
        mot_seed_start=args.mot_seed_start,
        npools=args.npools,
        dt_s=FINAL_DT_S,
        stochastic_sim_function=RK4StHybridCustom,
    )
    design = {
        "n_ensembles": len(ensembles),
        "particles_per_ensemble": args.particles_per_ensemble,
        "mot_seed_start": args.mot_seed_start,
        "dt_s": FINAL_DT_S,
        "npools": args.npools,
        "paired_design": True,
        "stochastic_solver": RK4StHybridCustom.__name__,
    }
    result = {
        "kind": "mot_2d_hybrid_finalist_confirmation_result",
        "name": finalist["name"],
        "origin": finalist["origin"],
        "parameters": parameters,
        "design": design,
        "evaluation": evaluation,
    }
    output_dir = Path(args.output_dir)
    save_file_json(output_dir / f"{finalist['name']}.json", result)
    print(
        "MOT_2D_HYBRID_FINALIST_RESULT "
        f"name={finalist['name']} "
        f"mean_conditional_percent="
        f"{100 * evaluation['statistics']['mean_conditional_efficiency']:.6f}"
    )
    return result


def summarize_saved_results(output_dir):
    output_dir = Path(output_dir)
    results = []
    for finalist in FINALISTS:
        path = output_dir / f"{finalist['name']}.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing finalist result: {path}")
        results.append(json.loads(path.read_text(encoding="utf-8")))
    design = results[0]["design"]
    if any(row["design"] != design for row in results[1:]):
        raise ValueError("Finalist results do not share one paired design.")
    summary = build_summary(results, design)
    save_file_json(output_dir / "summary.json", summary)
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--finalist-index", type=int, choices=range(len(FINALISTS)))
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--n-ensembles", type=int, default=10)
    parser.add_argument("--particles-per-ensemble", type=int, default=10_000)
    parser.add_argument("--mot-seed-start", type=int, default=12_000)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    if not args.summarize_only and args.finalist_index is None:
        parser.error("--finalist-index is required unless --summarize-only is used")
    return args


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.summarize_only:
        result = summarize_saved_results(arguments.output_dir)
        print(json.dumps(result, indent=2))
    else:
        run_finalist(arguments)
