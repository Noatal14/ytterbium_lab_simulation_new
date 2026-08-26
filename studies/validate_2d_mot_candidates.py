"""Validate shortlisted 2D-MOT candidates with paired independent replicates.

The candidates were selected by the v4 refinement study.  This validation uses
new MOT seeds and larger fixed subsets, so the comparison is independent of the
random realizations used to shortlist the candidates.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from config import DEFAULT_NUM_POOLS, MOT_2D_SIM_CONFIG
from studies.optimize_2d_mot_joint import evaluate_configuration
from utils.data_paths import MOT_2D_OPTIMIZATION_DIR
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles, student_mean_interval


SOURCE_STUDY = "joint_refinement_v4_n5000x5"
NONINFERIORITY_MARGIN_FRACTION = 0.0005  # 0.05 percentage points

CANDIDATES = (
    {
        "name": "maximum_capture",
        "source_trial": 11,
        "s0": 1.4932290341911787,
        "detuning_gamma": -1.2326140031998183,
        "magnet_radius": 0.049418961579403425,
    },
    {
        "name": "intermediate_power",
        "source_trial": 1,
        "s0": 1.4598658484197036,
        "detuning_gamma": -1.285675899102664,
        "magnet_radius": 0.049080790136605164,
    },
    {
        "name": "low_power_near_optimum",
        "source_trial": 15,
        "s0": 1.4318286250124808,
        "detuning_gamma": -1.2847881534418586,
        "magnet_radius": 0.04918508443553798,
    },
)


def paired_comparison(candidate, reference, confidence=0.95):
    """Compare aligned candidate/reference replicates using paired differences."""
    candidate_rows = candidate["evaluation"]["replicates"]
    reference_rows = reference["evaluation"]["replicates"]
    if len(candidate_rows) != len(reference_rows):
        raise ValueError("Paired candidates must contain the same replicate count.")

    differences = []
    for candidate_row, reference_row in zip(candidate_rows, reference_rows):
        identity = ("zeeman_seed", "mot_seed", "n_input", "subset_seed")
        if any(candidate_row[key] != reference_row[key] for key in identity):
            raise ValueError("Candidate replicates are not aligned for pairing.")
        differences.append(
            candidate_row["conditional_efficiency"]
            - reference_row["conditional_efficiency"]
        )

    mean, low, high, half_width = student_mean_interval(
        differences, confidence=confidence
    )
    return {
        "candidate": candidate["name"],
        "reference": reference["name"],
        "paired_differences_fraction": differences,
        "mean_paired_difference_fraction": mean,
        "paired_95_ci_fraction": [low, high],
        "paired_95_ci_half_width_fraction": half_width,
        "noninferiority_margin_fraction": NONINFERIORITY_MARGIN_FRACTION,
        "passes_noninferiority_at_95_percent": (
            low is not None and low >= -NONINFERIORITY_MARGIN_FRACTION
        ),
    }


def build_summary(results, design):
    comparisons = []
    if len(results) > 1:
        reference = results[0]
        comparisons.extend(
            paired_comparison(candidate, reference)
            for candidate in results[1:]
        )
    return {
        "kind": "mot_2d_candidate_validation_summary",
        "source_study": SOURCE_STUDY,
        "design": design,
        "completed_candidates": [
            {
                "name": row["name"],
                "source_trial": row["source_trial"],
                "parameters": row["parameters"],
                "statistics": row["evaluation"]["statistics"],
                "batch_elapsed_seconds": row["evaluation"][
                    "batch_elapsed_seconds"
                ],
            }
            for row in results
        ],
        "paired_comparisons_to_maximum_capture": comparisons,
    }


def run_validation(args):
    ensembles = load_production_ensembles(
        max_ensembles=args.n_ensembles,
        particles_per_ensemble=args.particles_per_ensemble,
    )
    if len(ensembles) != args.n_ensembles:
        raise ValueError(
            f"Requested {args.n_ensembles} ensembles but found {len(ensembles)}."
        )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    design = {
        "n_ensembles": len(ensembles),
        "particles_per_ensemble": args.particles_per_ensemble,
        "mot_seed_start": args.mot_seed_start,
        "dt_s": args.dt,
        "npools": args.npools,
        "paired_design": True,
    }

    results = []
    for candidate in CANDIDATES:
        parameters = {
            key: candidate[key]
            for key in ("s0", "detuning_gamma", "magnet_radius")
        }
        evaluation = evaluate_configuration(
            **parameters,
            ensembles=ensembles,
            mot_seed_start=args.mot_seed_start,
            npools=args.npools,
            dt_s=args.dt,
        )
        result = {
            "kind": "mot_2d_candidate_validation_result",
            "name": candidate["name"],
            "source_study": SOURCE_STUDY,
            "source_trial": candidate["source_trial"],
            "parameters": parameters,
            "design": design,
            "evaluation": evaluation,
        }
        results.append(result)
        save_file_json(output_dir / f"{candidate['name']}.json", result)
        save_file_json(output_dir / "summary.json", build_summary(results, design))
        print(
            "MOT_2D_CANDIDATE_RESULT "
            f"name={candidate['name']} "
            f"mean_conditional_percent="
            f"{100 * evaluation['statistics']['mean_conditional_efficiency']:.6f}"
        )

    return build_summary(results, design)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-ensembles", type=int, default=10)
    parser.add_argument("--particles-per-ensemble", type=int, default=10_000)
    parser.add_argument("--mot-seed-start", type=int, default=6000)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--dt", type=float, default=MOT_2D_SIM_CONFIG["dt_s"])
    parser.add_argument(
        "--output-dir",
        default=str(
            MOT_2D_OPTIMIZATION_DIR / "candidate_validation_v5_n10000x10"
        ),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_validation(parse_args())
