"""Screen local 2D-MOT sensitivity around the selected final configuration.

The laser intensity is not treated as a quantity to minimize.  The study has
two complementary parts:

* a local detuning/radius grid at the selected reference intensity; and
* an intensity response scan at the selected detuning and radius.

All points use identical Zeeman ensembles, particle subsets, and MOT seeds so
that their differences from the reference point are paired.
"""

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


REFERENCE_PARAMETERS = {
    "s0": 1.4744970,
    "detuning_gamma": -1.1840645,
    "magnet_radius": 0.049217614,
}
FINAL_DT_S = 0.625e-6
S0_SCAN = (1.40, 1.425, 1.45, REFERENCE_PARAMETERS["s0"], 1.50)
DETUNING_OFFSETS_GAMMA = (-0.02, 0.0, 0.02)
RADIUS_OFFSETS_M = (-0.10e-3, 0.0, 0.10e-3)


def point_definitions():
    points = []
    for detuning_offset in DETUNING_OFFSETS_GAMMA:
        for radius_offset in RADIUS_OFFSETS_M:
            points.append(
                {
                    "name": (
                        f"local_d{detuning_offset:+.3f}_"
                        f"r{radius_offset * 1e3:+.2f}mm"
                    ),
                    "scan_axis": "detuning_radius_grid",
                    "parameters": {
                        "s0": REFERENCE_PARAMETERS["s0"],
                        "detuning_gamma": (
                            REFERENCE_PARAMETERS["detuning_gamma"]
                            + detuning_offset
                        ),
                        "magnet_radius": (
                            REFERENCE_PARAMETERS["magnet_radius"]
                            + radius_offset
                        ),
                    },
                    "offsets": {
                        "s0": 0.0,
                        "detuning_gamma": detuning_offset,
                        "magnet_radius_m": radius_offset,
                    },
                }
            )

    # The reference intensity is already present in the local grid.
    for s0 in S0_SCAN:
        if s0 == REFERENCE_PARAMETERS["s0"]:
            continue
        points.append(
            {
                "name": f"s0_{s0:.6f}",
                "scan_axis": "s0_response",
                "parameters": {**REFERENCE_PARAMETERS, "s0": s0},
                "offsets": {
                    "s0": s0 - REFERENCE_PARAMETERS["s0"],
                    "detuning_gamma": 0.0,
                    "magnet_radius_m": 0.0,
                },
            }
        )
    return tuple(points)


POINTS = point_definitions()
REFERENCE_INDEX = next(
    index
    for index, point in enumerate(POINTS)
    if point["parameters"] == REFERENCE_PARAMETERS
)


def paired_comparison(point, reference):
    point_rows = point["evaluation"]["replicates"]
    reference_rows = reference["evaluation"]["replicates"]
    identity = ("zeeman_seed", "mot_seed", "n_input", "subset_seed")
    differences = []
    for point_row, reference_row in zip(point_rows, reference_rows):
        if any(point_row[key] != reference_row[key] for key in identity):
            raise ValueError("Sensitivity replicates are not aligned for pairing.")
        differences.append(
            point_row["conditional_efficiency"]
            - reference_row["conditional_efficiency"]
        )
    mean, low, high, half_width = student_mean_interval(differences)
    return {
        "mean_paired_difference_fraction": mean,
        "paired_95_ci_fraction": [low, high],
        "paired_95_ci_half_width_fraction": half_width,
        "paired_differences_fraction": differences,
    }


def run_point(args):
    point = POINTS[args.point_index]
    ensembles = load_production_ensembles(
        max_ensembles=args.n_ensembles,
        particles_per_ensemble=args.particles_per_ensemble,
    )
    evaluation = evaluate_configuration(
        **point["parameters"],
        ensembles=ensembles,
        mot_seed_start=args.mot_seed_start,
        npools=args.npools,
        dt_s=FINAL_DT_S,
        stochastic_sim_function=RK4StHybridCustom,
    )
    result = {
        "kind": "mot_2d_final_sensitivity_point",
        "point_index": args.point_index,
        **point,
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
    save_file_json(output_dir / f"point_{args.point_index:02d}.json", result)
    print(
        "MOT_2D_FINAL_SENSITIVITY_RESULT "
        f"point={args.point_index} name={point['name']} "
        "mean_conditional_percent="
        f"{100 * evaluation['statistics']['mean_conditional_efficiency']:.6f}"
    )
    return result


def summarize_saved_results(output_dir):
    output_dir = Path(output_dir)
    results = [
        json.loads((output_dir / f"point_{index:02d}.json").read_text())
        for index in range(len(POINTS))
    ]
    design = results[0]["design"]
    if any(result["design"] != design for result in results[1:]):
        raise ValueError("Sensitivity results do not share one paired design.")
    reference = results[REFERENCE_INDEX]
    summary = {
        "kind": "mot_2d_final_sensitivity_summary",
        "reference_point_index": REFERENCE_INDEX,
        "reference_parameters": REFERENCE_PARAMETERS,
        "design": design,
        "points": [],
    }
    for result in results:
        row = {
            "point_index": result["point_index"],
            "name": result["name"],
            "scan_axis": result["scan_axis"],
            "parameters": result["parameters"],
            "offsets": result["offsets"],
            "statistics": result["evaluation"]["statistics"],
        }
        if result["point_index"] != REFERENCE_INDEX:
            row["paired_comparison_to_reference"] = paired_comparison(
                result, reference
            )
        summary["points"].append(row)
    save_file_json(output_dir / "summary.json", summary)
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--point-index", type=int, choices=range(len(POINTS)))
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--list-points", action="store_true")
    parser.add_argument("--n-ensembles", type=int, default=3)
    parser.add_argument("--particles-per-ensemble", type=int, default=2_000)
    parser.add_argument("--mot-seed-start", type=int, default=13_000)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument(
        "--output-dir",
        default=str(MOT_2D_OPTIMIZATION_DIR / "final_sensitivity_v20_screening"),
    )
    args = parser.parse_args(argv)
    selected_modes = sum((args.summarize_only, args.list_points))
    if selected_modes > 1:
        parser.error("Choose only one of --summarize-only or --list-points.")
    if not selected_modes and args.point_index is None:
        parser.error("--point-index is required when running a point.")
    return args


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.list_points:
        print(json.dumps({"reference_index": REFERENCE_INDEX, "points": POINTS}, indent=2))
    elif arguments.summarize_only:
        print(json.dumps(summarize_saved_results(arguments.output_dir), indent=2))
    else:
        run_point(arguments)
