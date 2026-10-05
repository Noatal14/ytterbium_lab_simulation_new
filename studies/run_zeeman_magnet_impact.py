"""Run the paired corrected-Zeeman impact check through the frozen 3D finalists."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
from scipy.stats import ks_2samp

from config import (
    MOT_3D_SIM_CONFIG,
    ZEEMAN_MAGNET_PROFILES,
)
from simulations.mot_3d import mot_3d_simulation
from simulations.zeeman import run_and_save_zeeman
from studies.compare_3d_mot_retention import analyze_results
from studies.optimize_2d_mot_joint import evaluate_configuration
from utils.RK4StHybridCustom import RK4StHybridCustom
from utils.data_paths import load_particle_states, save_particle_states


ROOT = Path("data/validation/mot_3d/zeeman_magnet_impact_v1")
PROFILE_NAME = "corrected_projectant_19ring_20261005"
SEEDS = (3000, 3001, 3002, 3003)
RECOIL_SEEDS = (44001, 44002, 44003)
N_INITIAL = 50_000
OLD_ZEEMAN = Path("data/particle_states/after_zeeman")
OLD_2D = Path("data/particle_states/after_2d_mot/final_ensemble_s0_1.47")
NEW_ZEEMAN = ROOT / "corrected_after_zeeman"
NEW_2D = ROOT / "corrected_after_2d_mot"
FINALIST_ROOT = Path("data/optimization/mot_3d/finalist_selection_v1/selection")

MOT_2D_PARAMETERS = {
    "s0": 1.474497,
    "detuning_gamma": -1.1840645,
    "magnet_radius": 0.049217614,
}
MOT_2D_DT_S = 6.25e-7
MOT_SEED_OFFSET = 15_000


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(temporary, path)


def corrected_field():
    radii, positions, tilts = ZEEMAN_MAGNET_PROFILES[PROFILE_NAME]
    if not (len(radii) == len(positions) == len(tilts) == 19):
        raise ValueError("The corrected Zeeman profile must contain 19 complete rings.")
    arrays = [np.asarray(values, dtype=float) for values in (radii, positions, tilts)]
    if not all(np.all(np.isfinite(values)) for values in arrays):
        raise ValueError("The corrected Zeeman profile contains non-finite values.")
    if np.any(np.diff(arrays[1]) <= 0):
        raise ValueError("Corrected Zeeman positions must be strictly increasing.")
    return {"radii_m": radii, "positions_m": positions, "tilt_angles_deg": tilts}


def corrected_zeeman_path(seed):
    return NEW_ZEEMAN / f"corrected_zeeman_n50000_dt40us_seed{seed}.npy"


def corrected_2d_path(seed):
    return (
        NEW_2D
        / f"mot_2d_survivors_zeeman_seed{seed}_mot_seed{seed + MOT_SEED_OFFSET}.npy"
    )


def old_zeeman_path(seed):
    return OLD_ZEEMAN / f"production_zeeman_n50000_dt40us_seed{seed}.npy"


def old_2d_path(seed):
    return (
        OLD_2D
        / f"mot_2d_survivors_zeeman_seed{seed}_mot_seed{seed + MOT_SEED_OFFSET}.npy"
    )


def run_upstream(seed, npools):
    if seed not in SEEDS:
        raise ValueError(f"Seed {seed} is outside the predeclared paired set {SEEDS}.")
    destination = corrected_2d_path(seed)
    if destination.exists() and destination.with_suffix(".json").exists():
        print(f"Skipping completed corrected upstream seed {seed}")
        return
    zeeman_path = corrected_zeeman_path(seed)
    if not zeeman_path.exists():
        run_and_save_zeeman(
            zeeman_path,
            N_particles=N_INITIAL,
            seed=seed,
            dt=4e-5,
            npools=npools,
            stochastic=True,
            collimation_angle_deg=1.5,
            zeeman_field_config=corrected_field(),
        )
    zeeman_states = load_particle_states(zeeman_path)
    ensemble = {
        "states": zeeman_states,
        "path": zeeman_path,
        "zeeman_seed": seed,
        "n_available": len(zeeman_states),
        "selection_method": "all_available_particles",
        "subset_seed": None,
        "zeeman_survival_fraction": len(zeeman_states) / N_INITIAL,
    }
    evaluation = evaluate_configuration(
        **MOT_2D_PARAMETERS,
        ensembles=[ensemble],
        mot_seed_start=seed + MOT_SEED_OFFSET,
        mot_seeds=[seed + MOT_SEED_OFFSET],
        npools=npools,
        dt_s=MOT_2D_DT_S,
        stochastic_sim_function=RK4StHybridCustom,
        include_survivor_states=True,
    )
    states = evaluation.pop("survivor_state_ensembles")[0]
    save_particle_states(destination, states)
    row = evaluation["replicates"][0]
    payload = {
        "kind": "corrected_zeeman_paired_2d_mot_ensemble",
        "profile_name": PROFILE_NAME,
        "zeeman_seed": seed,
        "mot_seed": seed + MOT_SEED_OFFSET,
        "n_initial_oven_atoms": N_INITIAL,
        "n_zeeman_survivors": len(zeeman_states),
        "n_2d_mot_survivors": len(states),
        "mot_2d_parameters": MOT_2D_PARAMETERS,
        "mot_2d_dt_s": MOT_2D_DT_S,
        "replicate": row,
        "states_file": str(destination),
    }
    _atomic_json(destination.with_suffix(".json"), payload)
    print(json.dumps(payload, indent=2), flush=True)


def _selection(family):
    path = FINALIST_ROOT / f"{family}_finalists.json"
    data = json.loads(path.read_text())
    if data["family"] != family:
        raise ValueError("Finalist-selection family mismatch.")
    return data["candidates"][0]


def _load_population(population):
    path_function = old_2d_path if population == "old" else corrected_2d_path
    states, ids, provenance = [], [], []
    for ensemble_id, seed in enumerate(SEEDS):
        path = path_function(seed)
        values = load_particle_states(path)
        states.append(values)
        ids.extend([ensemble_id] * len(values))
        provenance.append(
            {
                "ensemble_id": ensemble_id,
                "seed": seed,
                "file": str(path),
                "count": len(values),
            }
        )
    return np.concatenate(states), np.asarray(ids, dtype=int), provenance


def run_3d(population, family, recoil_seed, npools):
    if population not in ("old", "corrected"):
        raise ValueError("Population must be old or corrected.")
    if recoil_seed not in RECOIL_SEEDS:
        raise ValueError(f"Unexpected recoil seed {recoil_seed}.")
    candidate = _selection(family)
    states, ensemble_ids, provenance = _load_population(population)
    output_dir = ROOT / "mot_3d" / population / family
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{family}_{population}_seed_{recoil_seed}"
    json_path = output_dir / f"{stem}.json"
    npz_path = output_dir / f"{stem}.npz"
    if json_path.exists() and npz_path.exists():
        print(f"Skipping completed {stem}")
        return
    dt = MOT_3D_SIM_CONFIG["dt_s"]
    t_max = 0.1
    time_points = np.linspace(0.0, t_max, int(np.ceil(t_max / dt)) + 1)
    started = time.time()
    trajectories, _ = mot_3d_simulation(
        states,
        _3d_mot_config=candidate["resolved_profile"],
        gravity_enabled=True,
        npools=npools,
        dt=dt,
        t_max=t_max,
        seed=recoil_seed,
    )
    analysis = analyze_results(trajectories, time_points)
    usable = np.asarray(analysis["eligible_masks"][:, -1], dtype=bool)
    temporary = output_dir / f".{stem}.{os.getpid()}.npz"
    np.savez_compressed(temporary, usable_at_end=usable, ensemble_ids=ensemble_ids)
    os.replace(temporary, npz_path)
    payload = {
        "kind": "zeeman_magnet_impact_3d_result",
        "population": population,
        "family": family,
        "candidate_id": candidate["candidate_id"],
        "recoil_seed": recoil_seed,
        "input_particle_count": len(states),
        "usable_at_end_count": int(usable.sum()),
        "usable_at_end_fraction": float(usable.mean()),
        "ensemble_provenance": provenance,
        "outcomes_path": str(npz_path),
        "elapsed_seconds": time.time() - started,
    }
    _atomic_json(json_path, payload)
    print(json.dumps(payload, indent=2), flush=True)


def _state_summary(paths):
    arrays = [load_particle_states(path) for path in paths]
    combined = np.concatenate(arrays)
    labels = ("x_m", "y_m", "z_m", "vx_m_s", "vy_m_s", "vz_m_s")
    return combined, {
        "particle_count": len(combined),
        "per_ensemble_counts": [len(values) for values in arrays],
        "correlation_matrix": np.corrcoef(combined, rowvar=False).tolist(),
        "correlation_labels": list(labels),
        "dimensions": {
            label: {
                "mean": float(np.mean(combined[:, index])),
                "std": float(np.std(combined[:, index], ddof=1)),
                "quantiles": [
                    float(x) for x in np.quantile(combined[:, index], [0.05, 0.5, 0.95])
                ],
            }
            for index, label in enumerate(labels)
        },
    }


def merge(bootstrap_replicates=10_000, bootstrap_seed=54001):
    labels = ("x_m", "y_m", "z_m", "vx_m_s", "vy_m_s", "vz_m_s")
    stages = {}
    for stage, old_fn, new_fn in (
        ("after_zeeman", old_zeeman_path, corrected_zeeman_path),
        ("after_2d_mot", old_2d_path, corrected_2d_path),
    ):
        old, old_summary = _state_summary([old_fn(seed) for seed in SEEDS])
        new, new_summary = _state_summary([new_fn(seed) for seed in SEEDS])
        stages[stage] = {
            "old": old_summary,
            "corrected": new_summary,
            "ks_statistics": {
                label: {
                    "statistic": float(
                        ks_2samp(old[:, index], new[:, index]).statistic
                    ),
                    "pvalue": float(ks_2samp(old[:, index], new[:, index]).pvalue),
                }
                for index, label in enumerate(labels)
            },
        }

    rng = np.random.default_rng(bootstrap_seed)
    mot3d = {}
    for family in ("angled_donut", "single_pass"):
        outcomes = {}
        for population in ("old", "corrected"):
            rows = []
            ensemble_ids = None
            for recoil_seed in RECOIL_SEEDS:
                path = (
                    ROOT
                    / "mot_3d"
                    / population
                    / family
                    / f"{family}_{population}_seed_{recoil_seed}.npz"
                )
                with np.load(path) as data:
                    rows.append(np.asarray(data["usable_at_end"], dtype=float))
                    current = np.asarray(data["ensemble_ids"], dtype=int)
                    if ensemble_ids is None:
                        ensemble_ids = current
                    elif not np.array_equal(ensemble_ids, current):
                        raise ValueError(
                            "Ensemble grouping differs between recoil seeds."
                        )
            outcomes[population] = (np.stack(rows), ensemble_ids)
        boot_old = np.empty(bootstrap_replicates)
        boot_new = np.empty(bootstrap_replicates)
        boot_yield_old = np.empty(bootstrap_replicates)
        boot_yield_new = np.empty(bootstrap_replicates)
        for replicate in range(bootstrap_replicates):
            seed_indices = rng.integers(0, len(RECOIL_SEEDS), size=len(RECOIL_SEEDS))
            group_indices = rng.integers(0, len(SEEDS), size=len(SEEDS))
            for destination, population in ((boot_old, "old"), (boot_new, "corrected")):
                values, ids = outcomes[population]
                particle_indices = np.concatenate(
                    [np.flatnonzero(ids == group) for group in group_indices]
                )
                destination[replicate] = values[seed_indices][
                    :, particle_indices
                ].mean()
                yield_destination = (
                    boot_yield_old if population == "old" else boot_yield_new
                )
                captured = 0.0
                for seed_index in seed_indices:
                    for group in group_indices:
                        captured += values[seed_index, ids == group].sum()
                yield_destination[replicate] = captured / (
                    len(RECOIL_SEEDS) * len(SEEDS) * N_INITIAL
                )
        old_mean = float(outcomes["old"][0].mean())
        new_mean = float(outcomes["corrected"][0].mean())
        difference = boot_new - boot_old
        yield_difference = boot_yield_new - boot_yield_old
        old_end_to_end = float(
            outcomes["old"][0].sum() / (len(RECOIL_SEEDS) * len(SEEDS) * N_INITIAL)
        )
        new_end_to_end = float(
            outcomes["corrected"][0].sum()
            / (len(RECOIL_SEEDS) * len(SEEDS) * N_INITIAL)
        )
        mot3d[family] = {
            "old_fraction": old_mean,
            "corrected_fraction": new_mean,
            "difference_percentage_points": 100 * (new_mean - old_mean),
            "paired_bootstrap_95_ci_percentage_points": [
                float(100 * np.quantile(difference, 0.025)),
                float(100 * np.quantile(difference, 0.975)),
            ],
            "old_end_to_end_captured_per_initial_atom": old_end_to_end,
            "corrected_end_to_end_captured_per_initial_atom": new_end_to_end,
            "end_to_end_difference_percentage_points": 100
            * (new_end_to_end - old_end_to_end),
            "end_to_end_paired_bootstrap_95_ci_percentage_points": [
                float(100 * np.quantile(yield_difference, 0.025)),
                float(100 * np.quantile(yield_difference, 0.975)),
            ],
            "old_particle_count": int(outcomes["old"][0].shape[1]),
            "corrected_particle_count": int(outcomes["corrected"][0].shape[1]),
            "recoil_seeds": list(RECOIL_SEEDS),
        }
    summary = {
        "kind": "paired_corrected_zeeman_impact_summary",
        "corrected_profile": PROFILE_NAME,
        "thermal_zeeman_seeds": list(SEEDS),
        "n_initial_atoms_per_seed": N_INITIAL,
        "mot_2d_parameters_frozen_to_historical_3d_input": MOT_2D_PARAMETERS,
        "phase_space": stages,
        "mot_3d_finalists": mot3d,
        "bootstrap_replicates": bootstrap_replicates,
        "bootstrap_structure": (
            "Paired crossed bootstrap: resample the four upstream ensemble "
            "seeds and the three 3D recoil seeds independently; apply the same "
            "draws to old and corrected populations."
        ),
    }
    _atomic_json(ROOT / "merged" / "zeeman_magnet_impact_summary.json", summary)
    print(json.dumps(summary, indent=2))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    upstream = subparsers.add_parser("upstream")
    upstream.add_argument("--seed", type=int, required=True)
    upstream.add_argument("--npools", type=int, default=200)
    mot3d = subparsers.add_parser("mot3d")
    mot3d.add_argument("--population", choices=("old", "corrected"), required=True)
    mot3d.add_argument(
        "--family", choices=("angled_donut", "single_pass"), required=True
    )
    mot3d.add_argument("--recoil-seed", type=int, required=True)
    mot3d.add_argument("--npools", type=int, default=200)
    merged = subparsers.add_parser("merge")
    merged.add_argument("--bootstrap-replicates", type=int, default=10_000)
    merged.add_argument("--bootstrap-seed", type=int, default=54001)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.command == "upstream":
        run_upstream(args.seed, args.npools)
    elif args.command == "mot3d":
        run_3d(args.population, args.family, args.recoil_seed, args.npools)
    else:
        merge(args.bootstrap_replicates, args.bootstrap_seed)


if __name__ == "__main__":
    main()
