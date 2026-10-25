"""Jointly optimize s0, detuning, and magnet radius for the 2D MOT.

Every trial uses the same Zeeman ensembles, particle subsets, and MOT seeds so
that candidate comparisons are paired.
"""

from __future__ import annotations

import argparse
import json
import hashlib
import subprocess
import time
from pathlib import Path

import numpy as np
import optuna

from utils.optuna_replay import SequentialReplaySampler

from config import DEFAULT_NUM_POOLS, DEFAULT_RANDOM_SEED, MOT_2D_SIM_CONFIG
from simulations.mot_2d import mot_simulation_paired_ensembles
from utils.RK4StCustom import RK4StCustom
from utils.RK4StHybridCustom import RK4StHybridCustom
from utils.data_paths import MOT_2D_OPTIMIZATION_DIR
from utils.file_helpers import save_file_json
from utils.mot_2d_study import load_production_ensembles, summarize_replicates

# Follow-up bounds after the broad v1/v2 screens.  Updated experimental
# information permits a 45 mm radius.  The available laser power limits s0 to
# approximately 1.5, while s0=1.4 is known to be available.  Search only this
# experimentally relevant interval and retain the power/capture trade-off
# instead of spending trials on powers that would never be selected.
BOUNDS_S0 = (1.4, 1.5)
BOUNDS_DETUNING = (-1.55, -0.85)
BOUNDS_MAGNET_RADIUS_M = (0.045, 0.051)


def remaining_complete_trials(target, states):
    """Return the exact resume budget for an immutable total-trial target."""
    complete = sum(state == optuna.trial.TrialState.COMPLETE for state in states)
    if complete > target:
        raise RuntimeError(
            f"Study already has {complete} complete trials, exceeding target {target}."
        )
    return target - complete


def suggest_parameters(trial, fixed_s0, bounds_s0, bounds_detuning, bounds_radius):
    """The ordered public sampling contract, shared by execution and replay."""
    return {
        "s0": float(fixed_s0) if fixed_s0 is not None else trial.suggest_float("s0", *bounds_s0),
        "detuning_gamma": trial.suggest_float("detuning_gamma", *bounds_detuning),
        "magnet_radius": trial.suggest_float("magnet_radius", *bounds_radius),
    }


def restore_sampler(study, *, seed, suggest, enqueue_points):
    """Reconstruct a sequential sampler stream using verified public Optuna APIs.

    Unverifiable interrupted/legacy history fails closed; replay never evaluates
    physics or modifies the persisted trials.
    """
    trials = study.get_trials(deepcopy=True)
    if not trials:
        return
    replay = optuna.create_study(
        directions=study.directions, sampler=optuna.samplers.TPESampler(seed=seed),
        pruner=optuna.pruners.NopPruner(),
    )
    for point in enqueue_points:
        replay.enqueue_trial(dict(point))
    waiting = False
    for number, saved in enumerate(trials):
        if (saved.number != number or saved.user_attrs or saved.intermediate_values
                or any(key != "fixed_params" and not key.startswith("tpe:relative_params:")
                       for key in saved.system_attrs)):
            raise RuntimeError("Optuna sampler history cannot be replayed exactly.")
        if saved.state == optuna.trial.TrialState.WAITING:
            waiting = True
            queued = replay.get_trials(deepcopy=True)
            if (number >= len(queued) or queued[number].state != saved.state
                    or queued[number].system_attrs != saved.system_attrs
                    or saved.params or saved.distributions or saved.values is not None):
                raise RuntimeError("Optuna queued history cannot be replayed exactly.")
            continue
        if waiting or saved.state not in (
            optuna.trial.TrialState.COMPLETE, optuna.trial.TrialState.FAIL,
        ):
            raise RuntimeError("Optuna interrupted history cannot be replayed exactly.")
        trial = replay.ask()
        suggest(trial)
        rebuilt = replay.get_trials(deepcopy=True)[number]
        if (rebuilt.params != saved.params or rebuilt.distributions != saved.distributions
                or any(key not in rebuilt.system_attrs or rebuilt.system_attrs[key] != value
                       for key, value in saved.system_attrs.items())
                or rebuilt.system_attrs.get("fixed_params") != saved.system_attrs.get("fixed_params")):
            raise RuntimeError("Optuna sampler history does not match its frozen seed and bounds.")
        if saved.state == optuna.trial.TrialState.FAIL and saved.values is not None:
            raise RuntimeError("Optuna failed history has unexpected values.")
        replay.tell(trial, values=saved.values, state=saved.state)
    study.sampler = SequentialReplaySampler(replay, suggest)


def evaluate_configuration(
    s0,
    detuning_gamma,
    magnet_radius,
    ensembles,
    mot_seed_start,
    npools,
    dt_s,
    mot_seeds=None,
    stochastic_sim_function=RK4StHybridCustom,
    include_survivor_states=False,
):
    """Evaluate one point on fixed paired replicates and return its summary."""
    if mot_seeds is None:
        mot_seeds = [mot_seed_start + index for index in range(len(ensembles))]
    if len(mot_seeds) != len(ensembles):
        raise ValueError("Provide exactly one MOT seed per Zeeman ensemble.")
    started = time.time()
    grouped_results = mot_simulation_paired_ensembles(
        survivor_state_ensembles=[row["states"] for row in ensembles],
        seeds=mot_seeds,
        _2d_mot_config={
            "s0": s0,
            "detuning_gamma": detuning_gamma,
            "swap_polarization": False,
        },
        magnet_radius=magnet_radius,
        stochastic=True,
        npools=npools,
        dt=dt_s,
        stochastic_sim_function=stochastic_sim_function,
    )
    batch_elapsed = time.time() - started

    replicates = []
    survivor_state_ensembles = []
    for index, (ensemble, result) in enumerate(zip(ensembles, grouped_results)):
        _, captured, survivor_states = result
        mot_seed = mot_seeds[index]
        n_input = len(ensemble["states"])
        conditional = captured / n_input
        replicates.append(
            {
                "ensemble_file": ensemble["path"].name,
                "zeeman_seed": ensemble["zeeman_seed"],
                "mot_seed": mot_seed,
                "n_available": ensemble["n_available"],
                "selection_method": ensemble["selection_method"],
                "subset_seed": ensemble["subset_seed"],
                "n_input": n_input,
                "captured": int(captured),
                "conditional_efficiency": float(conditional),
                "estimated_total_efficiency": float(
                    conditional * ensemble["zeeman_survival_fraction"]
                ),
                "batch_elapsed_seconds": float(batch_elapsed),
            }
        )
        if include_survivor_states:
            survivor_state_ensembles.append(np.asarray(survivor_states))
    evaluation = {
        "batch_elapsed_seconds": float(batch_elapsed),
        "replicates": replicates,
        "statistics": summarize_replicates(replicates),
    }
    if include_survivor_states:
        evaluation["survivor_state_ensembles"] = survivor_state_ensembles
    return evaluation


def optimize_mot(args):
    bounds_s0 = tuple(args.s0_bounds)
    bounds_detuning = tuple(args.detuning_bounds)
    bounds_radius = tuple(args.magnet_radius_bounds_m)
    for label, bounds in (
        ("detuning", bounds_detuning),
        ("magnet radius", bounds_radius),
    ):
        if len(bounds) != 2 or bounds[0] >= bounds[1]:
            raise ValueError(f"Invalid {label} bounds: {bounds}")
    if args.fixed_s0 is None and bounds_s0[0] >= bounds_s0[1]:
        raise ValueError(f"Invalid s0 bounds: {bounds_s0}")
    if args.fixed_s0 is not None and args.fixed_s0 <= 0:
        raise ValueError("--fixed-s0 must be positive.")

    acceptance = _acceptance_request(args)
    ensembles = load_production_ensembles(
        max_ensembles=args.n_ensembles,
        particles_per_ensemble=args.particles_per_ensemble,
        directory=args.ensemble_dir,
        zeeman_seeds=args.zeeman_seeds,
        **({"acceptance_profile_id": args.acceptance_profile} if acceptance else {}),
    )
    output_dir = Path(args.output_dir)
    trials_dir = output_dir / "trials"
    trials_dir.mkdir(parents=True, exist_ok=True)
    stochastic_sim_function = (
        RK4StHybridCustom if args.stochastic_solver == "hybrid" else RK4StCustom
    )
    git_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    design = {
        "fixed_s0": args.fixed_s0,
        "dt_s": args.dt,
        "solver": stochastic_sim_function.__name__,
        "ensemble_dir": args.ensemble_identity if args.ensemble_identity else (
            str(Path(args.ensemble_dir).resolve()) if args.ensemble_dir else None
        ),
        "zeeman_seeds": [row["zeeman_seed"] for row in ensembles],
        "mot_seeds": list(args.mot_seeds) if args.mot_seeds else [args.mot_seed_start+i for i in range(len(ensembles))],
        "particles_per_ensemble": args.particles_per_ensemble,
        "sampler_seed": args.sampler_seed,
        "bounds": {"s0": [args.fixed_s0, args.fixed_s0] if args.fixed_s0 is not None else list(bounds_s0),
                   "detuning_gamma": list(bounds_detuning), "magnet_radius_m": list(bounds_radius)},
        "git_commit": git_commit,
        "campaign_design_id": args.campaign_design_id,
    }
    if acceptance:
        design["acceptance"] = acceptance
    design_id = hashlib.sha256(json.dumps(design, sort_keys=True).encode()).hexdigest()

    def objective(trial):
        parameters = suggest_parameters(
            trial, args.fixed_s0, bounds_s0, bounds_detuning, bounds_radius,
        )
        evaluation = evaluate_configuration(
            **parameters,
            ensembles=ensembles,
            mot_seed_start=args.mot_seed_start,
            mot_seeds=design["mot_seeds"],
            npools=args.npools,
            dt_s=args.dt,
            stochastic_sim_function=stochastic_sim_function,
        )
        payload = {
            "kind": "mot_2d_joint_optimization_trial",
            "trial_number": trial.number,
            "parameters": parameters,
            "design": {
                "dt_s": args.dt,
                "n_ensembles": len(ensembles),
                "particles_per_ensemble": args.particles_per_ensemble,
                "mot_seed_start": args.mot_seed_start,
                "stochastic_solver": stochastic_sim_function.__name__,
                "design_id": design_id,
                "git_commit": git_commit,
                "ensemble_dir": design["ensemble_dir"],
                "zeeman_seeds": design["zeeman_seeds"],
                "mot_seeds": design["mot_seeds"],
            },
            **evaluation,
        }
        if acceptance:
            payload["design"]["acceptance"] = acceptance
        save_file_json(trials_dir / f"trial_{trial.number:04d}.json", payload)
        value = evaluation["statistics"]["mean_conditional_efficiency"]
        print(
            "MOT_2D_OPTUNA_RESULT "
            f"trial={trial.number} s0={parameters['s0']:.8f} "
            f"detuning_gamma={parameters['detuning_gamma']:.8f} "
            f"magnet_radius={parameters['magnet_radius']:.8f} "
            f"mean_conditional_percent={100 * value:.6f}"
        )
        # Preserve the physical trade-off instead of forcing one arbitrary
        # compromise: maximize capture while independently minimizing the
        # required laser saturation parameter.
        return value if args.fixed_s0 is not None else (value, parameters["s0"])

    directions = ["maximize"] if args.fixed_s0 is not None else ["maximize", "minimize"]
    study = optuna.create_study(
        study_name=args.study_name,
        storage=f"sqlite:///{output_dir / 'joint_screening.db'}",
        directions=directions,
        sampler=optuna.samplers.TPESampler(seed=args.sampler_seed),
        # The three paired replicates share one worker pool and complete as a
        # single batch. Pruning after a partial replicate would require
        # rebuilding that expensive pool, so it is deliberately disabled.
        pruner=optuna.pruners.NopPruner(),
        load_if_exists=True,
    )
    existing_design = study.user_attrs.get("scientific_design")
    if existing_design is None:
        study.set_user_attr("scientific_design", design)
        study.set_user_attr("design_id", design_id)
    elif existing_design != design or study.user_attrs.get("design_id") != design_id:
        raise RuntimeError("Existing Optuna study has an incompatible scientific design.")
    running = [t for t in study.trials if t.state == optuna.trial.TrialState.RUNNING]
    for trial in running:
        study._storage.set_trial_state_values(
            trial._trial_id, optuna.trial.TrialState.FAIL
        )
    if not study.trials:
        for detuning_gamma, magnet_radius in args.enqueue_point:
            study.enqueue_trial(
                {
                    "detuning_gamma": float(detuning_gamma),
                    "magnet_radius": float(magnet_radius),
                }
            )
    restore_sampler(
        study, seed=args.sampler_seed,
        suggest=lambda trial: suggest_parameters(
            trial, args.fixed_s0, bounds_s0, bounds_detuning, bounds_radius,
        ),
        enqueue_points=[{"detuning_gamma": float(d), "magnet_radius": float(r)}
                        for d, r in args.enqueue_point],
    )
    remaining = remaining_complete_trials(args.n_trials, [t.state for t in study.trials])
    if remaining:
        study.optimize(objective, n_trials=remaining)
    complete_trials = [
        trial
        for trial in study.trials
        if trial.state == optuna.trial.TrialState.COMPLETE
    ]
    ranked_trials = sorted(
        complete_trials,
        key=lambda trial: (-trial.values[0], trial.number),
    )
    summary = {
        "kind": "mot_2d_joint_optimization_summary",
        "study_name": args.study_name,
        "objectives": (
            ["maximize_mean_conditional_efficiency"]
            if args.fixed_s0 is not None
            else ["maximize_mean_conditional_efficiency", "minimize_s0"]
        ),
        "fixed_s0": args.fixed_s0,
        "n_registered_trials": len(study.trials),
        "n_finished_trials": len(complete_trials),
        "ranked_trials": [
            {
                "trial_number": trial.number,
                "mean_conditional_efficiency": float(trial.values[0]),
                "parameters": {
                    "s0": (
                        float(args.fixed_s0)
                        if args.fixed_s0 is not None
                        else float(trial.params["s0"])
                    ),
                    "detuning_gamma": float(trial.params["detuning_gamma"]),
                    "magnet_radius": float(trial.params["magnet_radius"]),
                },
            }
            for trial in ranked_trials
        ],
        "pareto_front": (
            []
            if args.fixed_s0 is not None
            else [
                {
                    "trial_number": trial.number,
                    "mean_conditional_efficiency": float(trial.values[0]),
                    "s0": float(trial.values[1]),
                    "parameters": trial.params,
                }
                for trial in sorted(
                    study.best_trials,
                    key=lambda item: (item.params["s0"], -item.values[0]),
                )
            ]
        ),
        "design": {
            "dt_s": args.dt,
            "n_ensembles": len(ensembles),
            "particles_per_ensemble": args.particles_per_ensemble,
            "mot_seed_start": args.mot_seed_start,
            "stochastic_solver": stochastic_sim_function.__name__,
            "ensemble_dir": design["ensemble_dir"],
            "zeeman_seeds": [row["zeeman_seed"] for row in ensembles],
            "sampler_seed": args.sampler_seed,
            "bounds": {
                "s0": (
                    [float(args.fixed_s0), float(args.fixed_s0)]
                    if args.fixed_s0 is not None
                    else bounds_s0
                ),
                "detuning_gamma": bounds_detuning,
                "magnet_radius_m": bounds_radius,
            },
        },
    }
    if acceptance:
        summary["design"]["acceptance"] = acceptance
    save_file_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    return study



def _acceptance_request(args):
    profile_id = getattr(args, 'acceptance_profile', None)
    input_manifest = getattr(args, 'input_manifest', None)
    if not profile_id and not input_manifest:
        return None
    if not profile_id or not input_manifest:
        raise ValueError('Acceptance optimization requires both profile and input manifest.')
    from workflow_api.acceptance_profile import assert_acceptance_path
    from workflow_api.mot_2d_spec import validate_campaign_policy, refinement_targets
    manifest_path = Path(input_manifest).resolve()
    manifest = json.loads(manifest_path.read_text())
    profile = validate_campaign_policy(manifest)
    if profile is None or profile.profile_id != profile_id:
        raise ValueError('Acceptance optimization profile mismatch.')
    repository = Path(__file__).resolve().parents[2]
    assert_acceptance_path(manifest_path, repository)
    assert_acceptance_path(args.output_dir, repository)
    stage = 'smoke' if 'smoke' in Path(args.output_dir).parts else manifest['stage']
    if stage not in ('smoke', 'screen', 'refine'):
        raise ValueError('Invalid acceptance optimization stage.')
    policy = profile.stage('mot_2d', stage)
    valid_trials = refinement_targets(manifest) if stage == 'refine' else (policy['trials_per_worker'],)
    role = policy['input_role']
    seeds = manifest['seed_roles'][role][:1] if stage == 'smoke' else manifest['seed_roles'][role]
    mot_seeds = manifest['mot_seeds'][role][:1] if stage == 'smoke' else manifest['mot_seeds'][role]
    expected_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if (args.n_trials not in valid_trials or args.particles_per_ensemble != policy['particles_per_ensemble']
            or args.npools != policy['npools'] or args.dt != manifest['fixed_design']['working_dt_s']
            or args.stochastic_solver != 'hybrid' or args.zeeman_seeds != seeds
            or args.mot_seeds != mot_seeds or args.n_ensembles != len(seeds)
            or args.fixed_s0 not in manifest['s0_values']
            or args.campaign_design_id != manifest['provenance']['physical_model_sha256']
            or expected_commit != manifest['provenance']['git_commit']
            or args.ensemble_identity != manifest['ensemble_source']['directory']):
        raise ValueError('Acceptance optimization arguments differ from frozen policy.')
    return manifest['acceptance']

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-trials", type=int, default=50)
    parser.add_argument("--campaign-design-id")
    parser.add_argument("--acceptance-profile")
    parser.add_argument("--input-manifest")
    parser.add_argument(
        "--fixed-s0",
        type=float,
        help="Hold s0 fixed and optimize only detuning and magnet radius.",
    )
    parser.add_argument("--n-ensembles", type=int, default=3)
    parser.add_argument("--particles-per-ensemble", type=int, default=2000)
    parser.add_argument(
        "--ensemble-dir",
        help="Directory containing the authoritative Zeeman ensemble files.",
    )
    parser.add_argument(
        "--ensemble-identity",
        help="Portable repository-relative ensemble identity recorded in results.",
    )
    parser.add_argument(
        "--zeeman-seeds",
        type=int,
        nargs="+",
        help="Optional explicit Zeeman-seed order to load from --ensemble-dir.",
    )
    parser.add_argument("--mot-seed-start", type=int, default=4000)
    parser.add_argument("--mot-seeds", type=int, nargs="+")
    parser.add_argument("--sampler-seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--dt", type=float, default=MOT_2D_SIM_CONFIG["dt_s"])
    parser.add_argument(
        "--stochastic-solver",
        choices=("gaussian", "hybrid"),
        default="hybrid",
    )
    parser.add_argument(
        "--s0-bounds",
        type=float,
        nargs=2,
        metavar=("MIN", "MAX"),
        default=BOUNDS_S0,
    )
    parser.add_argument(
        "--detuning-bounds",
        type=float,
        nargs=2,
        metavar=("MIN", "MAX"),
        default=BOUNDS_DETUNING,
    )
    parser.add_argument(
        "--magnet-radius-bounds-m",
        type=float,
        nargs=2,
        metavar=("MIN", "MAX"),
        default=BOUNDS_MAGNET_RADIUS_M,
    )
    parser.add_argument(
        "--study-name",
        default="mot_2d_joint_pareto_v3_radius45to51mm",
    )
    parser.add_argument(
        "--enqueue-point",
        type=float,
        nargs=2,
        action="append",
        default=[],
        metavar=("DETUNING_GAMMA", "MAGNET_RADIUS_M"),
        help="Evaluate an explicit detuning/radius point before sampled trials.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(MOT_2D_OPTIMIZATION_DIR / "joint_pareto_v3_radius45to51mm"),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    optimize_mot(parse_args())
