"""Run and summarize the final conditional 2D-MOT production prediction.

The three Zeus workers receive disjoint Zeeman seeds.  Every available
survivor in each ensemble is simulated with the final hybrid solver.  The
summary predicts the captured count for 10,000,000 Zeeman survivors and uses
the larger of the empirical between-ensemble uncertainty and ideal binomial
uncertainty, so the reported interval is not artificially optimistic.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

from config import DEFAULT_NUM_POOLS
from studies.optimize_2d_mot_joint import evaluate_configuration
from utils.RK4StHybridCustom import RK4StHybridCustom
from utils.data_paths import MOT_2D_OPTIMIZATION_DIR
from utils.data_paths import AFTER_2D_MOT_DIR, save_particle_states
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles, summarize_replicates


FINAL_DT_S = 0.625e-6
MOT_SEED_OFFSET = 15_000
REPORTING_SURVIVORS = 10_000_000
TARGET_HALF_WIDTH_FRACTION = 0.0005  # 0.05 percentage points
DEFAULT_OUTPUT_DIR = MOT_2D_OPTIMIZATION_DIR / "final_production_v22"
DEFAULT_STATES_DIR = AFTER_2D_MOT_DIR / "final_production_v22"


def parameters_from_args(args):
    return {
        "s0": float(args.s0),
        "detuning_gamma": float(args.detuning_gamma),
        "magnet_radius": float(args.magnet_radius_mm) * 1e-3,
    }


def run_seeds(args):
    parameters = parameters_from_args(args)
    ensembles = load_production_ensembles(
        particles_per_ensemble=None,
        zeeman_seeds=args.zeeman_seeds,
    )
    mot_seeds = [seed + MOT_SEED_OFFSET for seed in args.zeeman_seeds]
    evaluation = evaluate_configuration(
        **parameters,
        ensembles=ensembles,
        mot_seed_start=mot_seeds[0],
        mot_seeds=mot_seeds,
        npools=args.npools,
        dt_s=FINAL_DT_S,
        stochastic_sim_function=RK4StHybridCustom,
        include_survivor_states=args.save_survivor_states,
    )
    survivor_state_ensembles = evaluation.pop("survivor_state_ensembles", None)
    output_dir = Path(args.output_dir) / "replicates"
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(evaluation["replicates"]):
        payload = {
            "kind": "mot_2d_final_production_replicate",
            "parameters": parameters,
            "design": {
                "dt_s": FINAL_DT_S,
                "stochastic_solver": RK4StHybridCustom.__name__,
                "uses_all_available_particles": True,
                "mot_seed_offset": MOT_SEED_OFFSET,
                "npools": args.npools,
            },
            "replicate": row,
        }
        path = output_dir / f"zeeman_seed{row['zeeman_seed']}.json"
        save_file_json(path, payload)
        if survivor_state_ensembles is not None:
            states_dir = Path(args.states_dir)
            states_path = states_dir / (
                f"mot_2d_survivors_zeeman_seed{row['zeeman_seed']}"
                f"_mot_seed{row['mot_seed']}.npy"
            )
            save_particle_states(states_path, survivor_state_ensembles[index])
            save_file_json(
                states_path.with_suffix(".json"),
                {
                    "kind": "mot_2d_final_survivor_ensemble",
                    "source_zeeman_ensemble": row["ensemble_file"],
                    "zeeman_seed": row["zeeman_seed"],
                    "mot_seed": row["mot_seed"],
                    "n_input": row["n_input"],
                    "n_survivors": row["captured"],
                    "state_layout": [
                        "x_m", "y_m", "z_m", "vx_m_s", "vy_m_s", "vz_m_s"
                    ],
                    "parameters": parameters,
                    "design": payload["design"],
                },
            )
            print(f"Saved 2D-MOT survivor states to: {states_path}")
        print(
            "MOT_2D_FINAL_PRODUCTION_RESULT "
            f"zeeman_seed={row['zeeman_seed']} mot_seed={row['mot_seed']} "
            f"captured={row['captured']} n_input={row['n_input']} "
            f"conditional_percent={100 * row['conditional_efficiency']:.6f}"
        )


def final_prediction(replicates, reporting_survivors=REPORTING_SURVIVORS):
    n_input = np.asarray([row["n_input"] for row in replicates], dtype=float)
    captured = np.asarray([row["captured"] for row in replicates], dtype=float)
    efficiencies = captured / n_input
    total_input = int(n_input.sum())
    total_captured = int(captured.sum())
    pooled_efficiency = float(total_captured / total_input)

    binomial_mean_variance = float(
        pooled_efficiency * (1.0 - pooled_efficiency) / total_input
    )
    empirical_mean_variance = float(
        np.var(efficiencies, ddof=1) / len(efficiencies)
    )
    use_empirical_variance = empirical_mean_variance > binomial_mean_variance
    selected_mean_variance = max(
        binomial_mean_variance,
        empirical_mean_variance,
    )
    future_counting_variance = float(
        pooled_efficiency
        * (1.0 - pooled_efficiency)
        / reporting_survivors
    )
    critical = float(
        student_t.ppf(0.975, len(replicates) - 1)
        if use_empirical_variance
        else 1.96
    )
    half_width = float(
        critical
        * np.sqrt(selected_mean_variance + future_counting_variance)
    )
    low = max(0.0, pooled_efficiency - half_width)
    high = min(1.0, pooled_efficiency + half_width)
    return {
        "reporting_zeeman_survivors": int(reporting_survivors),
        "simulated_zeeman_survivors": total_input,
        "simulated_captured_atoms": total_captured,
        "pooled_conditional_efficiency": pooled_efficiency,
        "expected_captured_atoms": int(round(pooled_efficiency * reporting_survivors)),
        "predicted_95_interval_fraction": [low, high],
        "predicted_95_captured_atoms_interval": [
            int(round(low * reporting_survivors)),
            int(round(high * reporting_survivors)),
        ],
        "predicted_95_half_width_fraction": half_width,
        "predicted_95_half_width_percentage_points": 100 * half_width,
        "binomial_mean_variance": binomial_mean_variance,
        "empirical_between_ensemble_mean_variance": empirical_mean_variance,
        "selected_mean_variance": selected_mean_variance,
        "selected_mean_variance_source": (
            "empirical_between_ensemble"
            if use_empirical_variance
            else "pooled_binomial"
        ),
        "critical_value": critical,
        "future_counting_variance": future_counting_variance,
        "uncertainty_method": (
            "95% prediction interval combining future binomial counting "
            "variance with the larger of pooled-binomial and empirical "
            "between-ensemble variance of the estimated mean; Student-t is "
            "used when empirical ensemble variance controls, otherwise the "
            "large-sample normal critical value is used"
        ),
    }


def summarize(output_dir):
    paths = sorted((Path(output_dir) / "replicates").glob("zeeman_seed*.json"))
    if not paths:
        raise FileNotFoundError("No final-production replicate files were found.")
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    parameters = payloads[0]["parameters"]
    design = payloads[0]["design"]
    if any(payload["parameters"] != parameters for payload in payloads[1:]):
        raise ValueError("Final-production files contain mixed parameter sets.")
    if any(payload["design"] != design for payload in payloads[1:]):
        raise ValueError("Final-production files contain mixed simulation designs.")
    replicates = [payload["replicate"] for payload in payloads]
    seeds = [int(row["zeeman_seed"]) for row in replicates]
    if len(seeds) != len(set(seeds)):
        raise ValueError("Final-production data contain duplicate Zeeman seeds.")
    replicates.sort(key=lambda row: row["zeeman_seed"])
    prediction = final_prediction(replicates)
    summary = {
        "kind": "mot_2d_final_production_summary",
        "parameters": parameters,
        "design": design,
        "target_95_half_width_fraction": TARGET_HALF_WIDTH_FRACTION,
        "target_95_half_width_percentage_points": 100 * TARGET_HALF_WIDTH_FRACTION,
        "stopping_rule_passes": bool(
            prediction["predicted_95_half_width_fraction"]
            <= TARGET_HALF_WIDTH_FRACTION
        ),
        "zeeman_seeds": seeds,
        "replicates": replicates,
        "replicate_statistics": summarize_replicates(replicates),
        "prediction_for_10m_zeeman_survivors": prediction,
    }
    output_path = Path(output_dir) / "summary.json"
    save_file_json(output_path, summary)
    print(json.dumps(summary, indent=2))
    print(f"Summary saved to: {output_path}")
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zeeman-seeds", type=int, nargs="+")
    parser.add_argument("--s0", type=float)
    parser.add_argument("--detuning-gamma", type=float)
    parser.add_argument("--magnet-radius-mm", type=float)
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--save-survivor-states",
        action="store_true",
        help="Save each captured (N, 6) ensemble for downstream 3D-MOT studies.",
    )
    parser.add_argument("--states-dir", default=str(DEFAULT_STATES_DIR))
    args = parser.parse_args(argv)
    if not args.summarize_only:
        missing = [
            name
            for name in ("zeeman_seeds", "s0", "detuning_gamma", "magnet_radius_mm")
            if getattr(args, name) is None
        ]
        if missing:
            parser.error("Missing required production arguments: " + ", ".join(missing))
    return args


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.summarize_only:
        summarize(arguments.output_dir)
    else:
        run_seeds(arguments)
