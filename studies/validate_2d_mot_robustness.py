"""Validate local laboratory-setting robustness around the selected 2D MOT.

The 3x3x3 grid represents one provisional experimental control step in each
direction.  Array tasks write one point each; summarization uses paired
differences and Bonferroni-adjusted intervals for a simultaneous 95% statement
across every non-central point.
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

from config import DEFAULT_NUM_POOLS, MOT_2D_SIM_CONFIG
from studies.optimize_2d_mot_joint import evaluate_configuration
from utils.data_paths import MOT_2D_OPTIMIZATION_DIR
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles, student_mean_interval


SELECTED_PARAMETERS = {
    "s0": 1.4598658484197036,
    "detuning_gamma": -1.285675899102664,
    "magnet_radius": 0.049080790136605164,
}
CONTROL_STEPS = {
    "s0": 0.01,
    "detuning_gamma": 0.01,
    "magnet_radius": 0.01e-3,  # 0.01 mm
}
NONINFERIORITY_MARGIN_FRACTION = 0.0005  # 0.05 percentage points
OFFSETS = tuple(itertools.product((-1, 0, 1), repeat=3))
CENTER_INDEX = OFFSETS.index((0, 0, 0))


def point_definition(index):
    if not 0 <= index < len(OFFSETS):
        raise ValueError(f"point-index must be between 0 and {len(OFFSETS) - 1}.")
    offset = OFFSETS[index]
    parameters = {
        key: SELECTED_PARAMETERS[key] + delta * CONTROL_STEPS[key]
        for key, delta in zip(SELECTED_PARAMETERS, offset)
    }
    return {
        "point_index": index,
        "offset_steps": dict(zip(SELECTED_PARAMETERS, offset)),
        "parameters": parameters,
    }


def paired_interval(point, center, confidence):
    point_rows = point["evaluation"]["replicates"]
    center_rows = center["evaluation"]["replicates"]
    if len(point_rows) != len(center_rows):
        raise ValueError("Robustness points have different replicate counts.")
    differences = []
    identity = ("zeeman_seed", "mot_seed", "n_input", "subset_seed")
    for point_row, center_row in zip(point_rows, center_rows):
        if any(point_row[key] != center_row[key] for key in identity):
            raise ValueError("Robustness replicates are not aligned for pairing.")
        differences.append(
            point_row["conditional_efficiency"]
            - center_row["conditional_efficiency"]
        )
    mean, low, high, half_width = student_mean_interval(
        differences, confidence=confidence
    )
    return {
        "confidence": confidence,
        "mean_difference_fraction": mean,
        "confidence_interval_fraction": [low, high],
        "confidence_interval_half_width_fraction": half_width,
    }


def build_summary(points, familywise_comparisons=None):
    center = next(
        (point for point in points if point["point_index"] == CENTER_INDEX),
        None,
    )
    if center is None:
        raise ValueError(f"Point {CENTER_INDEX} is required as the center reference.")
    comparisons_count = len(points) - 1
    correction_count = familywise_comparisons or comparisons_count
    if correction_count < comparisons_count or correction_count < 1:
        raise ValueError(
            "familywise_comparisons must cover every reported comparison."
        )
    simultaneous_confidence = 1.0 - 0.05 / correction_count
    comparisons = []
    for point in points:
        if point["point_index"] == CENTER_INDEX:
            continue
        ordinary = paired_interval(point, center, confidence=0.95)
        simultaneous = paired_interval(
            point, center, confidence=simultaneous_confidence
        )
        comparisons.append(
            {
                "point_index": point["point_index"],
                "offset_steps": point["offset_steps"],
                "parameters": point["parameters"],
                "ordinary_95": ordinary,
                "simultaneous_95_familywise": simultaneous,
                "passes_0p05_pp_margin_simultaneously": bool(
                    simultaneous["confidence_interval_fraction"][0]
                    >= -NONINFERIORITY_MARGIN_FRACTION
                ),
            }
        )
    return {
        "kind": "mot_2d_local_robustness_summary",
        "selected_parameters": SELECTED_PARAMETERS,
        "control_steps": CONTROL_STEPS,
        "center_point_index": CENTER_INDEX,
        "n_points": len(points),
        "n_comparisons": comparisons_count,
        "familywise_correction_comparisons": correction_count,
        "familywise_confidence": 0.95,
        "per_comparison_bonferroni_confidence": simultaneous_confidence,
        "noninferiority_margin_fraction": NONINFERIORITY_MARGIN_FRACTION,
        "center_statistics": center["evaluation"]["statistics"],
        "comparisons_to_center": comparisons,
        "all_points_pass_simultaneous_margin": all(
            row["passes_0p05_pp_margin_simultaneously"] for row in comparisons
        ),
    }


def run_point(args):
    definition = point_definition(args.point_index)
    particles_per_ensemble = (
        None if args.all_particles else args.particles_per_ensemble
    )
    ensembles = load_production_ensembles(
        max_ensembles=args.n_ensembles,
        particles_per_ensemble=particles_per_ensemble,
    )
    if len(ensembles) != args.n_ensembles:
        raise ValueError(
            f"Requested {args.n_ensembles} ensembles but found {len(ensembles)}."
        )
    design = {
        "n_ensembles": len(ensembles),
        "particles_per_ensemble": particles_per_ensemble,
        "uses_all_available_particles": args.all_particles,
        "mot_seed_start": args.mot_seed_start,
        "dt_s": args.dt,
        "npools": args.npools,
        "paired_design": True,
    }
    evaluation = evaluate_configuration(
        **definition["parameters"],
        ensembles=ensembles,
        mot_seed_start=args.mot_seed_start,
        npools=args.npools,
        dt_s=args.dt,
    )
    result = {
        "kind": "mot_2d_local_robustness_point",
        **definition,
        "control_steps": CONTROL_STEPS,
        "design": design,
        "evaluation": evaluation,
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    save_file_json(output_dir / f"point_{args.point_index:02d}.json", result)
    print(
        "MOT_2D_ROBUSTNESS_RESULT "
        f"point={args.point_index} "
        f"mean_conditional_percent="
        f"{100 * evaluation['statistics']['mean_conditional_efficiency']:.6f}"
    )
    return result


def summarize_saved_points(
    output_dir, point_indices=None, familywise_comparisons=None
):
    output_dir = Path(output_dir)
    points = []
    if point_indices is None:
        point_indices = range(len(OFFSETS))
    for index in point_indices:
        path = output_dir / f"point_{index:02d}.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing robustness result: {path}")
        points.append(json.loads(path.read_text(encoding="utf-8")))
    design = points[0]["design"]
    if any(point["design"] != design for point in points[1:]):
        raise ValueError("Robustness files do not share one paired design.")
    summary = build_summary(
        points, familywise_comparisons=familywise_comparisons
    )
    summary["design"] = design
    save_file_json(output_dir / "summary.json", summary)
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--point-index", type=int)
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--n-ensembles", type=int, default=10)
    parser.add_argument("--particles-per-ensemble", type=int, default=10_000)
    parser.add_argument(
        "--all-particles",
        action="store_true",
        help="Use every available survivor in each Zeeman ensemble.",
    )
    parser.add_argument("--mot-seed-start", type=int, default=7000)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--dt", type=float, default=MOT_2D_SIM_CONFIG["dt_s"])
    parser.add_argument(
        "--output-dir",
        default=str(MOT_2D_OPTIMIZATION_DIR / "robustness_v6_n10000x10"),
    )
    parser.add_argument(
        "--summary-point-indices",
        type=int,
        nargs="+",
        help="Subset of point files to combine; must include the center.",
    )
    parser.add_argument(
        "--familywise-comparisons",
        type=int,
        help="Number of comparisons used in the Bonferroni correction.",
    )
    args = parser.parse_args(argv)
    if not args.summarize_only and args.point_index is None:
        parser.error("--point-index is required unless --summarize-only is used")
    return args


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.summarize_only:
        print(
            json.dumps(
                summarize_saved_points(
                    arguments.output_dir,
                    point_indices=arguments.summary_point_indices,
                    familywise_comparisons=arguments.familywise_comparisons,
                ),
                indent=2,
            )
        )
    else:
        run_point(arguments)
