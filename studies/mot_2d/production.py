"""Run and summarize the final conditional 2D-MOT production prediction.

Every available survivor in each sealed ensemble is simulated with an explicit
manifest-pinned MOT seed and the final hybrid solver.  Final uncertainty uses a
cluster-aware parametric bootstrap targeting the survivor-weighted pooled
conditional efficiency reported as the point estimate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

from config import DEFAULT_NUM_POOLS, MOT_2D_SIM_CONFIG
from studies.mot_2d.optimization import evaluate_configuration
from utils.RK4StHybridCustom import RK4StHybridCustom
from utils.data_paths import MOT_2D_OPTIMIZATION_DIR
from utils.data_paths import AFTER_2D_MOT_DIR, save_particle_states
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles, summarize_replicates


FINAL_DT_S = MOT_2D_SIM_CONFIG["dt_s"]
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
        directory=args.ensemble_dir,
        expected_profile=args.expected_zeeman_profile,
    )
    current_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if args.expected_git_commit and current_commit != args.expected_git_commit:
        raise RuntimeError("Production Git revision does not match campaign revision.")
    mot_seeds = list(args.mot_seeds)
    if len(mot_seeds) != len(args.zeeman_seeds):
        raise ValueError("Provide exactly one explicit MOT seed per Zeeman seed.")
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
                "npools": args.npools,
                "ensemble_dir": str(args.ensemble_dir) if args.ensemble_dir else None,
                "zeeman_profile": args.expected_zeeman_profile,
                "git_commit": current_commit,
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
            states_sha256 = hashlib.sha256(states_path.read_bytes()).hexdigest()
            save_file_json(
                states_path.with_suffix(".json"),
                {
                    "kind": "mot_2d_final_survivor_ensemble",
                    "source_zeeman_ensemble": row["ensemble_file"],
                    "zeeman_seed": row["zeeman_seed"],
                    "mot_seed": row["mot_seed"],
                    "n_input": row["n_input"],
                    "n_survivors": row["captured"],
                    "state_layout": ["x_m", "y_m", "z_m", "vx_m_s", "vy_m_s", "vz_m_s"],
                    "parameters": parameters,
                    "design": payload["design"],
                    "shape": list(np.asarray(survivor_state_ensembles[index]).shape),
                    "dtype": str(np.asarray(survivor_state_ensembles[index]).dtype),
                    "output_sha256": states_sha256,
                },
            )
            print(f"Saved 2D-MOT survivor states to: {states_path}")
        print(
            "MOT_2D_FINAL_PRODUCTION_RESULT "
            f"zeeman_seed={row['zeeman_seed']} mot_seed={row['mot_seed']} "
            f"captured={row['captured']} n_input={row['n_input']} "
            f"conditional_percent={100 * row['conditional_efficiency']:.6f}"
        )


def cluster_bootstrap_prediction(
    replicates,
    reporting_survivors=REPORTING_SURVIVORS,
    draws=20_000,
    random_seed=20261005,
):
    """Sample the survivor-weighted pooled efficiency and future count."""
    n_input = np.asarray([row["n_input"] for row in replicates], dtype=float)
    captured = np.asarray([row["captured"] for row in replicates], dtype=float)
    rng = np.random.default_rng(random_seed)
    bootstrap = np.empty(draws)
    for index in range(draws):
        selected = rng.integers(0, len(replicates), len(replicates))
        selected_n = n_input[selected]
        probabilities = rng.beta(
            captured[selected] + 0.5,
            selected_n - captured[selected] + 0.5,
        )
        pooled_probability = float(
            np.sum(probabilities * selected_n) / np.sum(selected_n)
        )
        bootstrap[index] = (
            rng.binomial(reporting_survivors, pooled_probability)
            / reporting_survivors
        )
    return bootstrap


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
    empirical_mean_variance = float(np.var(efficiencies, ddof=1) / len(efficiencies))
    use_empirical_variance = empirical_mean_variance > binomial_mean_variance
    selected_mean_variance = max(
        binomial_mean_variance,
        empirical_mean_variance,
    )
    future_counting_variance = float(
        pooled_efficiency * (1.0 - pooled_efficiency) / reporting_survivors
    )
    critical = float(
        student_t.ppf(0.975, len(replicates) - 1) if use_empirical_variance else 1.96
    )
    half_width = float(
        critical * np.sqrt(selected_mean_variance + future_counting_variance)
    )
    low = max(0.0, pooled_efficiency - half_width)
    high = min(1.0, pooled_efficiency + half_width)
    # Cluster-aware uncertainty: resample independent Zeeman/MOT ensemble
    # pairs, then sample each cluster's finite-count uncertainty and the new
    # reporting population.  This respects the actual crossed pair structure.
    bootstrap = cluster_bootstrap_prediction(replicates, reporting_survivors)
    bootstrap_low, bootstrap_high = map(float, np.quantile(bootstrap, [0.025, 0.975]))
    bootstrap_half = (bootstrap_high - bootstrap_low) / 2.0
    return {
        "reporting_zeeman_survivors": int(reporting_survivors),
        "simulated_zeeman_survivors": total_input,
        "simulated_captured_atoms": total_captured,
        "pooled_conditional_efficiency": pooled_efficiency,
        "expected_captured_atoms": int(round(pooled_efficiency * reporting_survivors)),
        "predicted_95_interval_fraction": [bootstrap_low, bootstrap_high],
        "predicted_95_captured_atoms_interval": [
            int(round(bootstrap_low * reporting_survivors)),
            int(round(bootstrap_high * reporting_survivors)),
        ],
        "predicted_95_half_width_fraction": bootstrap_half,
        "predicted_95_half_width_percentage_points": 100 * bootstrap_half,
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
            "20,000-draw cluster-aware parametric bootstrap: independent "
            "Zeeman/MOT ensemble pairs are resampled as clusters, finite "
            "within-cluster capture uncertainty is sampled with a Jeffreys "
            "beta model, cluster probabilities are pooled with their resampled "
            "survivor counts as weights, and future counting noise is sampled "
            "binomially"
        ),
        "bootstrap_replicates": 20_000,
    }


def summarize(
    output_dir,
    expected_seeds=None,
    expected_seed_pairs=None,
    states_dir=None,
    expected_design=None,
):
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
    if expected_seeds is not None and sorted(seeds) != sorted(expected_seeds):
        raise ValueError(
            f"Final-production seed mismatch: expected {sorted(expected_seeds)}, "
            f"found {sorted(seeds)}"
        )
    if expected_seed_pairs is not None:
        found_pairs = {
            int(row["zeeman_seed"]): int(row["mot_seed"])
            for row in replicates
        }
        expected_pairs = {
            int(zeeman_seed): int(mot_seed)
            for zeeman_seed, mot_seed in expected_seed_pairs.items()
        }
        if found_pairs != expected_pairs:
            raise ValueError(
                "Final-production Zeeman/MOT seed-pair mismatch: "
                f"expected {expected_pairs}, found {found_pairs}"
            )
    if expected_design:
        for field, expected in expected_design.items():
            if design.get(field) != expected:
                raise ValueError(
                    f"Final-production design mismatch for {field}: "
                    f"{design.get(field)!r} != {expected!r}"
                )
    if states_dir is not None:
        states_dir = Path(states_dir)
        expected_names = set()
        for row in replicates:
            state_path = states_dir / (
                f"mot_2d_survivors_zeeman_seed{row['zeeman_seed']}"
                f"_mot_seed{row['mot_seed']}.npy"
            )
            expected_names.add(state_path.name)
            metadata_path = state_path.with_suffix(".json")
            if not state_path.exists() or not metadata_path.exists():
                raise FileNotFoundError(f"Missing sealed state/metadata: {state_path}")
            states = np.load(state_path, mmap_mode="r")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if states.ndim != 2 or states.shape[1] != 6 or not np.all(np.isfinite(states)):
                raise ValueError(f"Invalid sealed survivor array: {state_path}")
            if len(states) != row["captured"] or metadata.get("n_survivors") != len(states):
                raise ValueError(f"Sealed survivor count mismatch: {state_path}")
            if metadata.get("shape") != list(states.shape):
                raise ValueError(f"Sealed survivor shape metadata mismatch: {state_path}")
            if metadata.get("output_sha256") != hashlib.sha256(state_path.read_bytes()).hexdigest():
                raise ValueError(f"Sealed survivor SHA-256 mismatch: {state_path}")
        stale = {path.name for path in states_dir.glob("mot_2d_survivors_*.npy")} - expected_names
        if stale:
            raise ValueError(f"Unexpected stale survivor arrays: {sorted(stale)}")
    replicates.sort(key=lambda row: row["zeeman_seed"])
    prediction = final_prediction(replicates)
    summary = {
        "kind": "mot_2d_final_production_summary",
        "parameters": parameters,
        "design": design,
        "target_95_half_width_fraction": TARGET_HALF_WIDTH_FRACTION,
        "target_95_half_width_percentage_points": 100 * TARGET_HALF_WIDTH_FRACTION,
        "stopping_rule_passes": bool(
            prediction["predicted_95_half_width_fraction"] <= TARGET_HALF_WIDTH_FRACTION
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
    parser.add_argument("--mot-seeds", type=int, nargs="+")
    parser.add_argument(
        "--ensemble-dir",
        help="Directory containing the authoritative Zeeman ensemble files.",
    )
    parser.add_argument("--expected-zeeman-profile")
    parser.add_argument("--expected-git-commit")
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
            for name in ("zeeman_seeds", "mot_seeds", "s0", "detuning_gamma", "magnet_radius_mm")
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
