"""Run and summarize unbiased 3D-MOT validation on newly generated survivors."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np

from simulations.mot_3d import mot_3d_simulation
from studies.compare_3d_mot_retention import analyze_results
from studies.mot_3d_stage_integrity import sha256, validate_completed_result
from utils.data_paths import load_particle_states
from utils.file_helpers import save_file_json


RECOIL_SEEDS = (44_001, 44_002, 44_003)
TARGET_HALF_WIDTH = 0.0075


def load_sealed_inputs(input_manifest, campaign_manifest, locked_nominals):
    from studies.mot_3d_campaign import validate_final_validation_inputs

    campaign = json.loads(Path(campaign_manifest).read_text(encoding="utf-8"))
    manifest = json.loads(Path(input_manifest).read_text(encoding="utf-8"))
    validate_final_validation_inputs(Path(campaign_manifest).parent, campaign)
    if manifest.get("locked_nominals_sha256") != sha256(locked_nominals):
        raise ValueError("Sealed inputs do not match the locked nominal points.")
    states, ensemble_ids = [], []
    for ensemble_id, row in enumerate(manifest["ensembles"]):
        path = Path(row["path"])
        if sha256(path) != row["sha256"] or sha256(row["metadata_path"]) != row["metadata_sha256"]:
            raise ValueError(f"Sealed input hash mismatch: {path}")
        values = np.asarray(load_particle_states(path), dtype=float)
        if len(values) == 0 or list(values.shape) != row["shape"] or not np.all(np.isfinite(values)):
            raise ValueError(f"Invalid sealed input array: {path}")
        states.append(values)
        ensemble_ids.extend([ensemble_id] * len(values))
    return np.concatenate(states), np.asarray(ensemble_ids), manifest


def run(args):
    locked = json.loads(Path(args.locked_nominals).read_text(encoding="utf-8"))
    campaign = json.loads(Path(args.campaign_manifest).read_text(encoding="utf-8"))
    if args.dt != campaign["design"]["production_dt_s"]:
        raise ValueError("Final validation must use the campaign production timestep.")
    candidate = locked["families"][args.family]
    states, ensemble_ids, inputs = load_sealed_inputs(
        args.input_manifest, args.campaign_manifest, args.locked_nominals
    )
    design = {
        "campaign_manifest_sha256": sha256(args.campaign_manifest),
        "locked_nominals_sha256": sha256(args.locked_nominals),
        "input_manifest_sha256": sha256(args.input_manifest),
        "family": args.family,
        "recoil_seed": args.recoil_seed,
        "dt_s": args.dt,
        "t_max_s": args.t_max,
        "solver": inputs["solver"],
        "classification": "sealed_unbiased_final_validation",
    }
    output = Path(args.output)
    archive = output.with_suffix(".npz")
    if validate_completed_result(
        output,
        archive,
        kind="mot_3d_sealed_final_validation_seed_result",
        family=args.family,
        candidate_id=candidate["candidate_id"],
        recoil_seed=args.recoil_seed,
        design=design,
    ):
        print(f"Skipping completed sealed validation: {output}")
        return
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    trajectories, _ = mot_3d_simulation(
        states,
        _3d_mot_config=candidate["resolved_profile"],
        gravity_enabled=True,
        npools=args.npools,
        dt=args.dt,
        t_max=args.t_max,
        seed=args.recoil_seed,
    )
    analysis = analyze_results(trajectories, time_points)
    usable_end = np.asarray(analysis["eligible_masks"][:, -1], dtype=bool)
    usable_ever = np.any(analysis["eligible_masks"], axis=1)
    archive.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{archive.name}.", suffix=".npz", dir=archive.parent
    )
    os.close(descriptor)
    try:
        np.savez_compressed(
            temporary,
            usable_at_end=usable_end,
            usable_ever=usable_ever,
            ensemble_ids=ensemble_ids,
        )
        with open(temporary, "rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, archive)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    save_file_json(output, {
        "kind": "mot_3d_sealed_final_validation_seed_result",
        "family": args.family,
        "candidate_id": candidate["candidate_id"],
        "recoil_seed": args.recoil_seed,
        "input_particle_count": len(states),
        "usable_at_end_count": int(usable_end.sum()),
        "usable_ever_count": int(usable_ever.sum()),
        "outcomes_path": str(archive.resolve()),
        "outcomes_sha256": sha256(archive),
        "design": design,
    })


def _bootstrap(outcomes, ensemble_ids, replicates, seed):
    groups = [np.flatnonzero(ensemble_ids == value) for value in np.unique(ensemble_ids)]
    rng = np.random.default_rng(seed)
    draws = np.empty(replicates)
    for index in range(replicates):
        sampled_recoil = rng.integers(0, outcomes.shape[0], size=outcomes.shape[0])
        sampled_groups = rng.integers(0, len(groups), size=len(groups))
        particles = np.concatenate([
            rng.choice(groups[group], size=len(groups[group]), replace=True)
            for group in sampled_groups
        ])
        draws[index] = outcomes[sampled_recoil][:, particles].mean()
    return draws


def merge(args):
    root = Path(args.input_root)
    destination = Path(args.output)
    expected_json = {f"seed_{seed}.json" for seed in RECOIL_SEEDS}
    expected_npz = {f"seed_{seed}.npz" for seed in RECOIL_SEEDS}
    observed_json = {path.name for path in root.glob("seed_*.json")}
    observed_npz = {path.name for path in root.glob("seed_*.npz")}
    allowed = expected_json | expected_npz
    if destination.parent.resolve() == root.resolve():
        allowed.add(destination.name)
    unexpected = {
        path.name for path in root.iterdir()
        if path.is_file() and path.suffix in (".json", ".npz") and path.name not in allowed
    }
    if observed_json != expected_json or observed_npz != expected_npz:
        raise RuntimeError("Final-validation artifact registry is incomplete or contaminated.")
    if unexpected:
        raise RuntimeError(f"Unexpected final-validation artifacts: {sorted(unexpected)}")
    paths = sorted(root / name for name in expected_json)
    records = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if len(records) != len(RECOIL_SEEDS):
        raise RuntimeError(f"Expected {len(RECOIL_SEEDS)} recoil results, found {len(records)}.")
    if {row.get("recoil_seed") for row in records} != set(RECOIL_SEEDS):
        raise ValueError("Final-validation recoil seed registry mismatch.")
    if any(
        row.get("kind") != "mot_3d_sealed_final_validation_seed_result"
        or row.get("family") != records[0].get("family")
        or row.get("candidate_id") != records[0].get("candidate_id")
        for row in records
    ):
        raise ValueError("Final-validation result metadata mismatch.")
    locked = json.loads(Path(args.locked_nominals).read_text(encoding="utf-8"))
    campaign = json.loads(Path(args.campaign_manifest).read_text(encoding="utf-8"))
    if args.dt != campaign["design"]["production_dt_s"]:
        raise ValueError("Final-validation merge timestep disagrees with the campaign.")
    expected_candidate = locked["families"][args.family]["candidate_id"]
    input_manifest = json.loads(Path(args.input_manifest).read_text(encoding="utf-8"))
    expected_particles = input_manifest["total_survivors"]
    expected_design = {
        "campaign_manifest_sha256": sha256(args.campaign_manifest),
        "locked_nominals_sha256": sha256(args.locked_nominals),
        "input_manifest_sha256": sha256(args.input_manifest),
        "family": args.family,
        "dt_s": args.dt,
        "t_max_s": 0.1,
        "solver": campaign["design"]["solver"],
        "classification": "sealed_unbiased_final_validation",
    }
    for path, row in zip(paths, records):
        seed = row["recoil_seed"]
        expected_archive = root / f"seed_{seed}.npz"
        normalized_design = {key: value for key, value in row["design"].items() if key != "recoil_seed"}
        if (
            row["family"] != args.family
            or row["candidate_id"] != expected_candidate
            or row["input_particle_count"] != expected_particles
            or Path(row["outcomes_path"]).resolve() != expected_archive.resolve()
            or normalized_design != expected_design
            or path.name != f"seed_{seed}.json"
        ):
            raise ValueError(f"Foreign or stale final-validation result: {path}")
    designs = [row.get("design") for row in records]
    normalized = [{key: value for key, value in row.items() if key != "recoil_seed"} for row in designs]
    if any(value != normalized[0] for value in normalized[1:]):
        raise ValueError("Final-validation results contain mixed designs.")
    arrays, ensemble_ids = [], None
    for row in sorted(records, key=lambda value: value["recoil_seed"]):
        archive = Path(row["outcomes_path"])
        if sha256(archive) != row["outcomes_sha256"]:
            raise ValueError(f"Final-validation outcome hash mismatch: {archive}")
        with np.load(archive) as data:
            required = {"usable_at_end", "usable_ever", "ensemble_ids"}
            if not required.issubset(data.files):
                raise ValueError(f"Incomplete final-validation archive: {archive}")
            arrays.append(np.asarray(data["usable_at_end"], dtype=bool))
            current = np.asarray(data["ensemble_ids"], dtype=int)
            if len(arrays[-1]) != row["input_particle_count"] or len(current) != len(arrays[-1]):
                raise ValueError(f"Final-validation outcome length mismatch: {archive}")
            if ensemble_ids is None:
                ensemble_ids = current
            elif not np.array_equal(ensemble_ids, current):
                raise ValueError("Final-validation particle grouping mismatch.")
    outcomes = np.stack(arrays)
    draws = _bootstrap(outcomes, ensemble_ids, args.bootstrap_replicates, args.bootstrap_seed)
    estimate = float(outcomes.mean())
    interval = np.quantile(draws, [0.025, 0.975])
    half_width = float((interval[1] - interval[0]) / 2)
    ensemble_rates = np.asarray([
        outcomes[:, ensemble_ids == group].mean()
        for group in np.unique(ensemble_ids)
    ])
    recoil_rates = outcomes.mean(axis=1)
    group_sizes = np.asarray([
        np.count_nonzero(ensemble_ids == group) for group in np.unique(ensemble_ids)
    ])
    rng = np.random.default_rng(args.bootstrap_seed + 1)
    predictive = np.empty(args.bootstrap_replicates)
    ensemble_effects = ensemble_rates - estimate
    recoil_effects = recoil_rates - estimate
    for index in range(args.bootstrap_replicates):
        probability = float(np.clip(
            estimate
            + rng.choice(ensemble_effects)
            + rng.choice(recoil_effects),
            0.0,
            1.0,
        ))
        size = int(rng.choice(group_sizes))
        predictive[index] = rng.binomial(size, probability) / size
    summary = {
        "kind": "mot_3d_sealed_final_validation_summary",
        "classification": "sealed_unbiased_estimate_pending_precision_gate",
        "family": records[0]["family"],
        "candidate_id": records[0]["candidate_id"],
        "estimand": "survivor-weighted conditional capture fraction",
        "input_particle_count": int(outcomes.shape[1]),
        "ensemble_count": int(len(np.unique(ensemble_ids))),
        "recoil_seed_count": int(outcomes.shape[0]),
        "conditional_efficiency": estimate,
        "bootstrap_95_ci": [float(value) for value in interval],
        "ci_half_width": half_width,
        "target_half_width": TARGET_HALF_WIDTH,
        "precision_target_met": half_width <= TARGET_HALF_WIDTH,
        "expected_usable_per_10m_2d_survivors": 10_000_000 * estimate,
        "expected_usable_per_10m_95_ci": [10_000_000 * float(value) for value in interval],
        "new_ensemble_rate_sd": float(ensemble_rates.std(ddof=1)),
        "new_equivalent_ensemble_predictive_95_interval": [
            float(value) for value in np.quantile(predictive, [0.025, 0.975])
        ],
        "predictive_method": "empirical random-effects bootstrap of ensemble and recoil effects plus finite-particle binomial variation",
        "bootstrap_method": "crossed ensemble/recoil bootstrap with within-ensemble particle resampling",
        "bootstrap_replicates": args.bootstrap_replicates,
        "bootstrap_seed": args.bootstrap_seed,
        "design": normalized[0],
    }
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if existing != summary:
            raise ValueError(f"Existing final-validation summary is incompatible: {destination}")
        print(f"Skipping identical final-validation summary: {destination}")
        return
    save_file_json(destination, summary)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("run")
    command.add_argument("--family", choices=("angled_donut", "single_pass"), required=True)
    command.add_argument("--recoil-seed", type=int, choices=RECOIL_SEEDS, required=True)
    command.add_argument("--locked-nominals", required=True)
    command.add_argument("--input-manifest", required=True)
    command.add_argument("--campaign-manifest", required=True)
    command.add_argument("--output", required=True)
    command.add_argument("--npools", type=int, default=200)
    command.add_argument("--dt", type=float, required=True)
    command.add_argument("--t-max", type=float, default=0.1)
    command.set_defaults(func=run)
    command = commands.add_parser("merge")
    command.add_argument("--input-root", required=True)
    command.add_argument("--output", required=True)
    command.add_argument("--family", choices=("angled_donut", "single_pass"), required=True)
    command.add_argument("--locked-nominals", required=True)
    command.add_argument("--input-manifest", required=True)
    command.add_argument("--campaign-manifest", required=True)
    command.add_argument("--dt", type=float, required=True)
    command.add_argument("--bootstrap-replicates", type=int, default=20_000)
    command.add_argument("--bootstrap-seed", type=int, default=92_001)
    command.set_defaults(func=merge)
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = parse_args()
    arguments.func(arguments)
