"""Restart-safe Optuna discovery for the donut and yz single-pass 3D MOTs."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import time
from pathlib import Path

import numpy as np
import optuna

from config import (
    DEFAULT_NUM_POOLS,
    DEFAULT_RANDOM_SEED,
    MOT_3D_CONFIGURATIONS,
    MOT_3D_OPTIMIZATION_CONFIG,
    MOT_3D_SIM_CONFIG,
)
from simulations.mot_3d import mot_3d_simulation
from studies.compare_3d_mot_retention import DEFAULT_INPUT, analyze_results
from utils.data_paths import load_particle_states


FAMILIES = ("angled_donut", "single_pass")


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n")
    os.replace(temporary, path)


def _json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot JSON-serialize {type(value).__name__}.")


def _git_revision():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_balanced_discovery_particles(input_dir, ensemble_count, per_ensemble, seed):
    input_dir = Path(input_dir)
    files = sorted(input_dir.glob("*.npy"))[:ensemble_count]
    if len(files) != ensemble_count:
        raise ValueError(
            f"Expected {ensemble_count} discovery ensembles in {input_dir}, "
            f"found {len(files)}."
        )
    states = []
    provenance = []
    for ensemble_index, path in enumerate(files):
        available = np.asarray(load_particle_states(path), dtype=float)
        if len(available) < per_ensemble:
            raise ValueError(
                f"{path} contains {len(available)} particles; need {per_ensemble}."
            )
        rng = np.random.default_rng(np.random.SeedSequence([seed, ensemble_index]))
        indices = np.sort(rng.choice(len(available), size=per_ensemble, replace=False))
        states.append(available[indices])
        provenance.append(
            {
                "file": str(path),
                "available_count": len(available),
                "selected_indices": indices.tolist(),
            }
        )
    return np.concatenate(states, axis=0), provenance


def _suggest_common(trial):
    common = MOT_3D_OPTIMIZATION_CONFIG["common"]
    return {
        "green_s0": trial.suggest_float("green_s0", *common["green_s0_bounds"]),
        "green_detuning_gamma": trial.suggest_float(
            "green_detuning_gamma", *common["green_detuning_gamma_bounds"]
        ),
        "green_waist_m": trial.suggest_float(
            "green_waist_m", *common["green_waist_m_bounds"]
        ),
        "blue_s0": trial.suggest_float("blue_s0", *common["blue_s0_bounds"]),
        "blue_waist_m": trial.suggest_float(
            "blue_waist_m", *common["blue_waist_m_bounds"]
        ),
        "magnetic_gradient_G_cm": trial.suggest_float(
            "magnetic_gradient_G_cm", *common["magnetic_gradient_G_cm_bounds"]
        ),
    }


def _single_pass_reference_field_G():
    settings = MOT_3D_OPTIMIZATION_CONFIG["single_pass"]
    z_slow_m = (
        settings["reference_crossing_z_offset_m"]
        - settings["slowing_position_waist_factor"]
        * settings["reference_blue_waist_m"]
    )
    # The single-pass profile has y as the quadrupole strong axis. On the
    # transport axis (x=y=0), |B| = G * |z| with G in G/cm and z in cm.
    return settings["reference_gradient_G_cm"] * abs(100.0 * z_slow_m)


def resolve_single_pass_detuning(anchor_gamma, gradient_G_cm, crossing_z_m, waist_m):
    settings = MOT_3D_OPTIMIZATION_CONFIG["single_pass"]
    z_slow_m = crossing_z_m - settings["slowing_position_waist_factor"] * waist_m
    field_G = gradient_G_cm * abs(100.0 * z_slow_m)
    reference_field_G = _single_pass_reference_field_G()
    detuning = anchor_gamma + settings["blue_zeeman_gamma_per_G"] * (
        field_G - reference_field_G
    )
    return float(detuning), float(z_slow_m), float(field_G)


def build_trial_profile(family, trial):
    parameters = _suggest_common(trial)
    profile = copy.deepcopy(MOT_3D_CONFIGURATIONS[family])
    profile["556"].update(
        s0=parameters["green_s0"],
        detuning_gamma=parameters["green_detuning_gamma"],
        waist_m=parameters["green_waist_m"],
    )
    profile["399"].update(
        s0=parameters["blue_s0"], waist_m=parameters["blue_waist_m"]
    )
    profile["magnetic_gradient_G_cm"] = parameters["magnetic_gradient_G_cm"]
    derived = {}

    if family == "angled_donut":
        bounds = MOT_3D_OPTIMIZATION_CONFIG[family][
            "blue_detuning_gamma_bounds"
        ]
        parameters["blue_detuning_gamma"] = trial.suggest_float(
            "blue_detuning_gamma", *bounds
        )
        profile["399"]["detuning_gamma"] = parameters["blue_detuning_gamma"]
    elif family == "single_pass":
        settings = MOT_3D_OPTIMIZATION_CONFIG[family]
        parameters["blue_detuning_anchor_gamma"] = trial.suggest_float(
            "blue_detuning_anchor_gamma",
            *settings["blue_detuning_anchor_gamma_bounds"],
        )
        parameters["blue_crossing_angle_deg"] = trial.suggest_float(
            "blue_crossing_angle_deg",
            *settings["blue_crossing_angle_deg_bounds"],
        )
        parameters["blue_crossing_z_offset_m"] = trial.suggest_float(
            "blue_crossing_z_offset_m",
            *settings["blue_crossing_z_offset_m_bounds"],
        )
        profile["blue_crossing_angle_deg"] = parameters[
            "blue_crossing_angle_deg"
        ]
        profile["blue_crossing_z_offset_m"] = parameters[
            "blue_crossing_z_offset_m"
        ]
        profile["maximum_blue_center_relative_intensity"] = settings[
            "maximum_blue_center_relative_intensity"
        ]
        detuning, z_slow_m, field_G = resolve_single_pass_detuning(
            parameters["blue_detuning_anchor_gamma"],
            parameters["magnetic_gradient_G_cm"],
            parameters["blue_crossing_z_offset_m"],
            parameters["blue_waist_m"],
        )
        profile["399"]["detuning_gamma"] = detuning
        derived = {
            "blue_detuning_gamma": detuning,
            "effective_slowing_z_offset_m": z_slow_m,
            "effective_slowing_field_G": field_G,
            "reference_slowing_field_G": _single_pass_reference_field_G(),
        }
    else:
        raise ValueError(f"Unsupported family {family!r}.")
    return profile, parameters, derived


def _seed_parameters(family, worker_index):
    common = {
        "green_s0": 30.0,
        "green_detuning_gamma": -25.0,
        "green_waist_m": 0.0075,
        "blue_waist_m": 0.0075,
        "magnetic_gradient_G_cm": 2.5,
    }
    if family == "single_pass":
        seeds = (
            dict(blue_s0=0.25, blue_detuning_anchor_gamma=-2.75, blue_crossing_angle_deg=45.0, blue_crossing_z_offset_m=-0.050),
            dict(blue_s0=0.25, blue_detuning_anchor_gamma=-2.75, blue_crossing_angle_deg=45.0, blue_crossing_z_offset_m=-0.045),
            dict(blue_s0=0.25, blue_detuning_anchor_gamma=-2.75, blue_crossing_angle_deg=50.0, blue_crossing_z_offset_m=-0.050),
        )
    else:
        seeds = (
            dict(blue_s0=1.5, blue_detuning_gamma=-3.0),
            dict(blue_s0=1.2, blue_detuning_gamma=-3.0),
            dict(blue_s0=1.5, blue_detuning_gamma=-2.5),
        )
    return {**common, **seeds[worker_index % len(seeds)]}


def _worker_summary(study, args, output_dir, provenance, revision):
    complete = [
        trial for trial in study.trials if trial.state == optuna.trial.TrialState.COMPLETE
    ]
    ranked = sorted(complete, key=lambda trial: (-float(trial.value), trial.number))
    payload = {
        "kind": "mot_3d_full_optuna_worker_summary",
        "family": args.family,
        "worker_index": args.worker_index,
        "study_name": study.study_name,
        "target_completed_trials": args.target_completed_trials,
        "registered_trials": len(study.trials),
        "completed_trials": len(complete),
        "software_revision": revision,
        "design": {
            "particle_count": sum(len(row["selected_indices"]) for row in provenance),
            "ensemble_count": len(provenance),
            "simulation_seed": args.simulation_seed,
            "selection_seed": args.selection_seed,
            "dt_s": args.dt,
            "t_max_s": args.t_max,
        },
        "ranked_trials": [
            {
                "trial_number": trial.number,
                "usable_at_end_fraction": float(trial.value),
                "parameters": trial.params,
                "resolved_parameters": trial.user_attrs.get("resolved_parameters"),
                "usable_at_end_count": trial.user_attrs.get("usable_at_end_count"),
                "runtime_seconds": trial.user_attrs.get("runtime_seconds"),
            }
            for trial in ranked
        ],
    }
    _atomic_json(output_dir / "summary.json", payload)


def optimize(args):
    if args.family not in FAMILIES:
        raise ValueError(f"family must be one of {FAMILIES}.")
    states, provenance = load_balanced_discovery_particles(
        args.input,
        ensemble_count=args.ensemble_count,
        per_ensemble=args.particles_per_ensemble,
        seed=args.selection_seed,
    )
    if len(states) != args.ensemble_count * args.particles_per_ensemble:
        raise AssertionError("Balanced discovery particle count is inconsistent.")
    output_dir = Path(args.output_dir) / f"worker_{args.worker_index}"
    trials_dir = output_dir / "trials"
    trials_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(output_dir / "particle_selection.json", provenance)
    revision = _git_revision()
    storage = optuna.storages.RDBStorage(
        url=f"sqlite:///{output_dir / 'study.db'}",
        engine_kwargs={"connect_args": {"timeout": 60}},
    )
    study = optuna.create_study(
        study_name=f"mot3d_{args.family}_worker_{args.worker_index}",
        storage=storage,
        direction="maximize",
        sampler=optuna.samplers.TPESampler(
            seed=args.sampler_seed,
            multivariate=True,
            n_startup_trials=args.startup_trials,
        ),
        pruner=optuna.pruners.NopPruner(),
        load_if_exists=True,
    )
    study.enqueue_trial(
        _seed_parameters(args.family, args.worker_index),
        user_attrs={"source": "physics_seed"},
        skip_if_exists=True,
    )
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    deadline = time.monotonic() + args.timeout_s

    def objective(trial):
        started = time.monotonic()
        profile, parameters, derived = build_trial_profile(args.family, trial)
        print(
            f"MOT3D_TRIAL_START family={args.family} worker={args.worker_index} "
            f"trial={trial.number} parameters={json.dumps(parameters, sort_keys=True)}",
            flush=True,
        )
        try:
            trajectories, _ = mot_3d_simulation(
                states,
                _3d_mot_config=profile,
                gravity_enabled=True,
                npools=args.npools,
                dt=args.dt,
                t_max=args.t_max,
                seed=args.simulation_seed,
            )
            analysis = analyze_results(trajectories, time_points)
            usable_at_end = analysis["eligible_masks"][:, -1]
            usable_ever = np.any(analysis["eligible_masks"], axis=1)
            diagnostics = analysis["diagnostics"]
            runtime = time.monotonic() - started
            resolved = {
                **parameters,
                **derived,
                "profile_blue_detuning_gamma": profile["399"]["detuning_gamma"],
            }
            trial.set_user_attr("resolved_parameters", resolved)
            trial.set_user_attr("usable_at_end_count", int(usable_at_end.sum()))
            trial.set_user_attr("usable_ever_count", int(usable_ever.sum()))
            trial.set_user_attr("entered_capture_region_count", int(diagnostics["entered_capture_region_count"]))
            trial.set_user_attr("slow_inside_count", int(diagnostics["slow_inside_count"]))
            trial.set_user_attr("runtime_seconds", float(runtime))
            payload = {
                "kind": "mot_3d_full_optuna_trial",
                "family": args.family,
                "worker_index": args.worker_index,
                "trial_number": trial.number,
                "parameters": parameters,
                "derived_parameters": derived,
                "resolved_profile": profile,
                "input_particle_count": len(states),
                "usable_at_end_count": int(usable_at_end.sum()),
                "usable_at_end_fraction": float(usable_at_end.mean()),
                "usable_ever_count": int(usable_ever.sum()),
                "peak_usable_count": int(analysis["peak_count"]),
                "entered_capture_region_count": int(diagnostics["entered_capture_region_count"]),
                "slow_inside_count": int(diagnostics["slow_inside_count"]),
                "runtime_seconds": float(runtime),
                "simulation_seed": args.simulation_seed,
                "software_revision": revision,
            }
            _atomic_json(trials_dir / f"trial_{trial.number:04d}.json", payload)
            print(
                f"MOT3D_TRIAL_RESULT family={args.family} worker={args.worker_index} "
                f"trial={trial.number} usable={usable_at_end.sum()}/{len(states)} "
                f"fraction={usable_at_end.mean():.6f} runtime_s={runtime:.1f}",
                flush=True,
            )
            return float(usable_at_end.mean())
        except Exception as error:
            _atomic_json(
                trials_dir / f"trial_{trial.number:04d}_failed.json",
                {
                    "kind": "mot_3d_full_optuna_failed_trial",
                    "family": args.family,
                    "worker_index": args.worker_index,
                    "trial_number": trial.number,
                    "parameters": parameters,
                    "derived_parameters": derived,
                    "runtime_seconds": time.monotonic() - started,
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "software_revision": revision,
                },
            )
            raise

    while time.monotonic() < deadline:
        completed = sum(
            trial.state == optuna.trial.TrialState.COMPLETE for trial in study.trials
        )
        if completed >= args.target_completed_trials:
            break
        study.optimize(objective, n_trials=1, catch=(Exception,))
        _worker_summary(study, args, output_dir, provenance, revision)
        recent_states = [trial.state for trial in study.trials[-args.max_consecutive_failures :]]
        if (
            len(recent_states) == args.max_consecutive_failures
            and all(state == optuna.trial.TrialState.FAIL for state in recent_states)
        ):
            raise RuntimeError(
                f"Stopping after {args.max_consecutive_failures} consecutive failed trials."
            )
    _worker_summary(study, args, output_dir, provenance, revision)
    return study


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=FAMILIES, required=True)
    parser.add_argument("--worker-index", type=int, required=True)
    parser.add_argument("--target-completed-trials", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--ensemble-count", type=int, default=12)
    parser.add_argument("--particles-per-ensemble", type=int, default=50)
    parser.add_argument("--selection-seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument("--simulation-seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument("--sampler-seed", type=int, required=True)
    parser.add_argument("--startup-trials", type=int, default=24)
    parser.add_argument("--max-consecutive-failures", type=int, default=5)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=0.1)
    parser.add_argument("--timeout-s", type=float, default=82_800.0)
    return parser.parse_args(argv)


if __name__ == "__main__":
    optimize(parse_args())
