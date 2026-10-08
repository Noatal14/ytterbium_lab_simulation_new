"""Conservative validation of modern fixed-s0 2D campaign records."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from workflow_api.models import StageProgress

ROLE_NAMES = ("discovery", "refinement", "held_out_confirmation", "sealed_validation")
CANONICAL_ROLE_SEEDS = {
    "discovery": list(range(3000, 3005)),
    "refinement": list(range(3005, 3010)),
    "held_out_confirmation": list(range(3010, 3015)),
    "sealed_validation": list(range(3015, 3035)),
}
STAGE_ROLE = {
    "smoke": "discovery", "screen": "discovery", "refine": "refinement",
    "confirmation": "held_out_confirmation", "sensitivity": "held_out_confirmation",
    "production": "sealed_validation",
}
MAX_JSON_BYTES = 8 * 1024 * 1024


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _trusted_file(path: Path, root: Path | None = None) -> bool:
    if root is not None:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
        try:
            relative = resolved_path.relative_to(resolved_root)
        except ValueError:
            return False
        current = resolved_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return False
        if not _within(resolved_path, resolved_root):
            return False
    return not path.is_symlink() and path.is_file()


def _json(path: Path, *, root: Path | None = None) -> Any:
    if not _trusted_file(path, root) or path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("untrusted JSON artifact")
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("oversized JSON artifact")
    return json.loads(raw.decode("utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def modern_contract(
    manifest: dict[str, Any], repository_root: Path
) -> tuple[bool, tuple[str, ...]]:
    errors: list[str] = []
    provenance = _mapping(manifest.get("provenance"))
    fixed = _mapping(manifest.get("fixed_design"))
    source = _mapping(manifest.get("ensemble_source"))
    roles = _mapping(manifest.get("seed_roles"))
    mot_seeds = _mapping(manifest.get("mot_seeds"))
    frozen = _mapping(manifest.get("input_ensembles"))
    required_provenance = ("git_commit", "physical_model_sha256", "hashed_files", "capture_criterion_version")
    if any(not provenance.get(key) for key in required_provenance):
        errors.append("immutable code and physics provenance is incomplete")
    if len(str(provenance.get("physical_model_sha256", ""))) != 64:
        errors.append("physical-model hash is invalid")
    required_design = (
        "working_dt_s", "final_dt_s", "solver", "detuning_bounds_gamma",
        "magnet_radius_bounds_m", "particle_counts", "trial_budgets",
        "control_resolution", "stress_test_offsets",
    )
    if any(key not in fixed for key in required_design) or fixed.get("solver") != "RK4StHybridCustom":
        errors.append("fixed scientific design is incomplete")
    if not isinstance(source.get("directory"), str) or not isinstance(source.get("zeeman_profile"), str):
        errors.append("ensemble source is incomplete")
    all_seeds: list[int] = []
    for role in ROLE_NAMES:
        seeds = roles.get(role)
        paired = mot_seeds.get(role)
        records = frozen.get(role)
        if not isinstance(seeds, list) or not seeds or not all(isinstance(seed, int) for seed in seeds):
            errors.append(f"{role} seed role is incomplete")
            continue
        if seeds != CANONICAL_ROLE_SEEDS[role]:
            errors.append(f"{role} seed role is not the canonical frozen set")
        if not isinstance(paired, list) or len(paired) != len(seeds) or not all(isinstance(seed, int) for seed in paired):
            errors.append(f"{role} MOT seed pairing is incomplete")
        elif paired != [40_000 + seed for seed in seeds]:
            errors.append(f"{role} MOT seed pairing is not canonical")
        if not isinstance(records, list) or len(records) != len(seeds):
            errors.append(f"{role} frozen input records are incomplete")
        else:
            observed = []
            for record in records:
                item = _mapping(record)
                required = ("zeeman_seed", "path", "metadata_path", "sha256", "shape", "dtype", "survivor_count", "zeeman_profile", "source_git_commit", "generation")
                if any(item.get(key) is None for key in required):
                    errors.append(f"{role} frozen input record is incomplete")
                    break
                paths: list[Path] = []
                for key in ("path", "metadata_path"):
                    recorded = Path(item[key])
                    resolved = recorded.resolve() if recorded.is_absolute() else (repository_root / recorded).resolve()
                    unresolved = recorded if recorded.is_absolute() else repository_root / recorded
                    if not _trusted_file(unresolved, repository_root):
                        errors.append(f"{role} frozen input artifact is unavailable or outside the repository")
                        paths = []
                        break
                    paths.append(unresolved)
                if paths:
                    try:
                        metadata = _mapping(_json(paths[1], root=repository_root))
                        parameters = _mapping(metadata.get("parameters"))
                        software = _mapping(metadata.get("software"))
                        generation = _mapping(item.get("generation"))
                        metadata_generation = {
                            key: parameters.get(key)
                            for key in ("n_initial_atoms", "dt_s", "stochastic", "collimation_angle_deg")
                        }
                        if (
                            item.get("zeeman_profile") != source.get("zeeman_profile")
                            or _sha256(paths[0]) != item["sha256"]
                            or metadata.get("output_sha256") != item["sha256"]
                            or metadata.get("shape") != item["shape"]
                            or metadata.get("dtype") != item["dtype"]
                            or metadata.get("n_survivors") != item["survivor_count"]
                            or parameters.get("seed") != item.get("zeeman_seed")
                            or parameters.get("resolved_zeeman_magnet_profile") != source.get("zeeman_profile")
                            or software.get("git_commit") != item.get("source_git_commit")
                            or metadata_generation != generation
                        ):
                            errors.append(f"{role} frozen input provenance does not match local files")
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        errors.append(f"{role} frozen input provenance cannot be validated")
                observed.append(item.get("zeeman_seed"))
            if observed != seeds:
                errors.append(f"{role} frozen input seed order does not match")
        all_seeds.extend(seeds)
    if len(all_seeds) != len(set(all_seeds)):
        errors.append("seed roles overlap")
    return not errors, tuple(dict.fromkeys(errors))


def _design_matches(
    design: dict[str, Any], manifest: dict[str, Any], role: str, dt: float,
    repository_root: Path,
) -> bool:
    source = _mapping(manifest["ensemble_source"])
    recorded = Path(source["directory"])
    actual_dir = str(recorded.resolve() if recorded.is_absolute() else (repository_root / recorded).resolve())
    return (
        design.get("dt_s") == dt
        and design.get("stochastic_solver", design.get("solver")) == "RK4StHybridCustom"
        and design.get("git_commit") == manifest["provenance"]["git_commit"]
        and design.get("zeeman_seeds") == manifest["seed_roles"][role]
        and design.get("mot_seeds") == manifest["mot_seeds"][role]
        and isinstance(design.get("ensemble_dir"), str)
        and str(Path(design["ensemble_dir"]).resolve()) == actual_dir
    )


def _optimization_design_id(
    manifest: dict[str, Any], *, stage: str, s0: float, worker: int,
    particles: int, sampler_seed: int, bounds: dict[str, Any],
    zeeman_seeds: list[int] | None = None, mot_seeds: list[int] | None = None,
    repository_root: Path | None = None,
) -> str:
    role = STAGE_ROLE[stage]
    recorded_source = Path(manifest["ensemble_source"]["directory"])
    source = str(
        recorded_source.resolve() if recorded_source.is_absolute()
        else ((repository_root or Path.cwd()) / recorded_source).resolve()
    )
    design = {
        "fixed_s0": s0,
        "dt_s": manifest["fixed_design"]["working_dt_s"],
        "solver": "RK4StHybridCustom",
        "ensemble_dir": source,
        "zeeman_seeds": zeeman_seeds or manifest["seed_roles"][role],
        "mot_seeds": mot_seeds or manifest["mot_seeds"][role],
        "particles_per_ensemble": particles,
        "sampler_seed": sampler_seed + worker,
        "bounds": {
            "s0": [s0, s0],
            "detuning_gamma": list(bounds["detuning"]),
            "magnet_radius_m": list(bounds["radius"]),
        },
        "git_commit": manifest["provenance"]["git_commit"],
        "campaign_design_id": manifest["provenance"]["physical_model_sha256"],
    }
    return hashlib.sha256(json.dumps(design, sort_keys=True).encode()).hexdigest()


def _valid_trial(path: Path, manifest: dict[str, Any], stage: str, task: dict[str, Any], number: int, root: Path) -> bool:
    try:
        row = _mapping(_json(path, root=root))
        s0 = float(task["s0"]); worker = int(task["worker"])
        particles = int(manifest["fixed_design"]["particle_counts"][stage])
        sampler_seed = 137 if stage == "screen" else 701
        bounds = task.get("bounds") if stage == "refine" else None
        if not isinstance(bounds, dict):
            bounds = {
                "detuning": manifest["fixed_design"]["detuning_bounds_gamma"],
                "radius": manifest["fixed_design"]["magnet_radius_bounds_m"],
            }
        design = _mapping(row.get("design"))
        return (
            row.get("kind") == "mot_2d_joint_optimization_trial"
            and row.get("trial_number") == number
            and _mapping(row.get("parameters")).get("s0") == s0
            and design.get("particles_per_ensemble") == particles
            and design.get("design_id") == _optimization_design_id(
                manifest, stage=stage, s0=s0, worker=worker, particles=particles,
                sampler_seed=sampler_seed, bounds=bounds, repository_root=root.parents[3],
            )
            and _design_matches(
                design, manifest, STAGE_ROLE[stage], manifest["fixed_design"]["working_dt_s"],
                root.parents[3],
            )
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def _valid_smoke_trial(path: Path, manifest: dict[str, Any], s0: float, root: Path) -> bool:
    try:
        row = _mapping(_json(path, root=root)); design = _mapping(row.get("design"))
        zeeman = [manifest["seed_roles"]["discovery"][0]]
        mot = [manifest["mot_seeds"]["discovery"][0]]
        bounds = {
            "detuning": manifest["fixed_design"]["detuning_bounds_gamma"],
            "radius": manifest["fixed_design"]["magnet_radius_bounds_m"],
        }
        expected_id = _optimization_design_id(
            manifest, stage="smoke", s0=s0, worker=0, particles=2,
            sampler_seed=42, bounds=bounds, zeeman_seeds=zeeman, mot_seeds=mot,
            repository_root=root.parents[3],
        )
        recorded_source = Path(manifest["ensemble_source"]["directory"])
        source = str(
            recorded_source.resolve() if recorded_source.is_absolute()
            else (root.parents[3] / recorded_source).resolve()
        )
        return (
            row.get("kind") == "mot_2d_joint_optimization_trial"
            and row.get("trial_number") == 0
            and _mapping(row.get("parameters")).get("s0") == s0
            and design.get("design_id") == expected_id
            and design.get("particles_per_ensemble") == 2
            and design.get("git_commit") == manifest["provenance"]["git_commit"]
            and design.get("zeeman_seeds") == zeeman
            and design.get("mot_seeds") == mot
            and design.get("stochastic_solver") == "RK4StHybridCustom"
            and design.get("dt_s") == manifest["fixed_design"]["working_dt_s"]
            and str(Path(design.get("ensemble_dir", "")).resolve()) == source
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def _valid_evaluation(path: Path, manifest: dict[str, Any], stage: str, task: dict[str, Any], root: Path) -> bool:
    try:
        row = _mapping(_json(path, root=root))
        design = _mapping(row.get("design"))
        index_key = "candidate_index" if stage == "confirmation" else "point_index"
        return (
            row.get("kind") == f"mot_2d_campaign_{stage}"
            and row.get(index_key) == task.get(index_key)
            and row.get("s0") == task.get("s0")
            and row.get("parameters") == task.get("parameters")
            and design.get("physical_model_sha256") == manifest["provenance"]["physical_model_sha256"]
            and design.get("git_commit") == manifest["provenance"]["git_commit"]
            and design.get("solver") == "RK4StHybridCustom"
            and design.get("dt_s") == manifest["fixed_design"]["final_dt_s"]
            and design.get("n_ensembles") == len(manifest["seed_roles"][STAGE_ROLE[stage]])
            and design.get("particles_per_ensemble") == manifest["fixed_design"]["particle_counts"][stage]
            and design.get("zeeman_seeds") == manifest["seed_roles"][STAGE_ROLE[stage]]
            and design.get("mot_seeds") == manifest["mot_seeds"][STAGE_ROLE[stage]]
            and design.get("ensemble_source") == manifest["ensemble_source"]
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def _progress(stage: str, complete: int, expected: int, invalid: bool = False) -> StageProgress:
    if invalid:
        status = "inconsistent"
    elif complete == 0:
        status = "not-started"
    elif complete < expected:
        status = "in-progress"
    else:
        status = "complete"
    return StageProgress(stage, complete, expected, status)


def validated_progress(root: Path, manifest: dict[str, Any]) -> tuple[StageProgress, ...]:
    rows: list[StageProgress] = []
    values = [float(value) for value in manifest["s0_values"]]
    smoke_valid = 0
    smoke_invalid = False
    for value in values:
        key = f"s0_{value:.6f}".replace(".", "p")
        directory = root / "smoke" / key
        path = directory / "summary.json"
        if not path.exists():
            continue
        try:
            row = _mapping(_json(path, root=root)); design = _mapping(row.get("design"))
            valid = (
                row.get("kind") == "mot_2d_joint_optimization_summary"
                and row.get("fixed_s0") == value
                and row.get("n_finished_trials") == 1
                and design.get("stochastic_solver") == "RK4StHybridCustom"
                and design.get("dt_s") == manifest["fixed_design"]["working_dt_s"]
                and _valid_smoke_trial(directory / "trials" / "trial_0000.json", manifest, value, root)
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            valid = False
        smoke_valid += int(valid); smoke_invalid |= not valid
    rows.append(_progress("smoke", smoke_valid, len(values), smoke_invalid))

    stages = _mapping(manifest.get("stages"))
    for stage in ("screen", "refine", "confirmation", "sensitivity"):
        if stage not in stages and not (root / stage).exists():
            continue
        tasks_path = root / stage / "tasks.json"
        try:
            tasks = _json(tasks_path, root=root)
            if not isinstance(tasks, list) or len(tasks) != _mapping(stages.get(stage)).get("tasks"):
                raise ValueError("task registry mismatch")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            rows.append(_progress(stage, 0, int(_mapping(stages.get(stage)).get("tasks") or 0), True)); continue
        identity_key = "worker" if stage in ("screen", "refine") else "candidate_index" if stage == "confirmation" else "point_index"
        identities = []
        malformed_tasks = False
        for task in tasks:
            item = _mapping(task)
            index = item.get(identity_key)
            s0 = item.get("s0")
            if not isinstance(index, int) or isinstance(index, bool) or index < 0 or not isinstance(s0, (int, float)) or isinstance(s0, bool) or float(s0) not in values:
                malformed_tasks = True
                break
            identities.append((float(s0), index))
        if malformed_tasks or len(identities) != len(set(identities)):
            rows.append(_progress(stage, 0, len(tasks), True)); continue
        if stage in ("screen", "refine") and set(identities) != {
            (value, worker) for value in values for worker in range(3)
        }:
            rows.append(_progress(stage, 0, len(tasks), True)); continue
        complete = 0; invalid = False
        if stage in ("screen", "refine"):
            budget = manifest["fixed_design"]["trial_budgets"][f"{stage}_per_worker"]
            expected = len(tasks) * budget
            for task in tasks:
                task = _mapping(task); s0 = task.get("s0"); worker = task.get("worker")
                key = f"s0_{float(s0):.6f}".replace(".", "p")
                directory = root / stage / key / f"worker{worker}" / "trials"
                files = sorted(directory.glob("trial_*.json"))
                for number in range(budget):
                    path = directory / f"trial_{number:04d}.json"
                    if path.exists():
                        valid = _valid_trial(path, manifest, stage, task, number, root)
                        complete += int(valid); invalid |= not valid
                invalid |= len(files) > budget
        else:
            expected = len(tasks)
            for task in tasks:
                task = _mapping(task); s0 = float(task.get("s0")); key = f"s0_{s0:.6f}".replace(".", "p")
                index_key = "candidate_index" if stage == "confirmation" else "point_index"
                path = root / stage / key / f"point_{int(task.get(index_key)):02d}.json"
                if path.exists():
                    valid = _valid_evaluation(path, manifest, stage, task, root)
                    complete += int(valid); invalid |= not valid
        rows.append(_progress(stage, complete, expected, invalid))

    if "production" in stages or (root / "production").exists():
        tasks_path = root / "production" / "tasks.json"
        try:
            tasks = _json(tasks_path, root=root)
            if not isinstance(tasks, list) or len(tasks) != _mapping(stages.get("production")).get("tasks"):
                raise ValueError("task registry mismatch")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            rows.append(_progress("production", 0, int(_mapping(stages.get("production")).get("tasks") or 0), True))
        else:
            complete = 0; invalid = False
            identities = []
            expected_pairs = dict(zip(manifest["seed_roles"]["sealed_validation"], manifest["mot_seeds"]["sealed_validation"]))
            for task in tasks:
                item = _mapping(task); seed = item.get("zeeman_seed"); mot_seed = item.get("mot_seed"); s0 = item.get("s0")
                if not isinstance(seed, int) or isinstance(seed, bool) or not isinstance(mot_seed, int) or isinstance(mot_seed, bool) or expected_pairs.get(seed) != mot_seed or not isinstance(s0, (int, float)) or isinstance(s0, bool) or float(s0) not in values:
                    invalid = True; break
                identities.append((float(s0), seed, mot_seed))
            if invalid or len(identities) != len(set(identities)):
                rows.append(_progress("production", 0, len(tasks), True))
            elif set(identities) != {
                (value, seed, expected_pairs[seed])
                for value in values for seed in manifest["seed_roles"]["sealed_validation"]
            }:
                rows.append(_progress("production", 0, len(tasks), True))
            else:
                for task in tasks:
                    task = _mapping(task); s0 = float(task.get("s0")); key = f"s0_{s0:.6f}".replace(".", "p")
                    path = root / "production" / key / "replicates" / f"zeeman_seed{task.get('zeeman_seed')}.json"
                    if not path.exists(): continue
                    try:
                        row = _mapping(_json(path, root=root)); replicate = _mapping(row.get("replicate")); design = _mapping(row.get("design"))
                        expected_design = {
                            "dt_s": manifest["fixed_design"]["final_dt_s"],
                            "stochastic_solver": "RK4StHybridCustom",
                            "uses_all_available_particles": True,
                            "npools": 150,
                            "ensemble_dir": manifest["ensemble_source"]["directory"],
                            "zeeman_profile": manifest["ensemble_source"]["zeeman_profile"],
                            "git_commit": manifest["provenance"]["git_commit"],
                        }
                        valid = (
                            row.get("kind") == "mot_2d_final_production_replicate"
                            and row.get("parameters") == task.get("parameters")
                            and replicate.get("zeeman_seed") == task.get("zeeman_seed")
                            and replicate.get("mot_seed") == task.get("mot_seed")
                            and design == expected_design
                        )
                    except (OSError, ValueError, TypeError, json.JSONDecodeError): valid = False
                    complete += int(valid); invalid |= not valid
                rows.append(_progress("production", complete, len(tasks), invalid))
    return tuple(rows)


def sealed_final_is_valid(
    root: Path, manifest: dict[str, Any], progress: tuple[StageProgress, ...],
    repository_root: Path,
) -> bool:
    production = next((row for row in progress if row.stage == "production"), None)
    if manifest.get("stage") != "complete" or production is None or production.status != "complete":
        return False
    sealed = manifest["seed_roles"]["sealed_validation"]
    mot_seeds = manifest["mot_seeds"]["sealed_validation"]
    expected_pairs = dict(zip(sealed, mot_seeds))
    values = [float(value) for value in manifest["s0_values"]]
    if sealed != CANONICAL_ROLE_SEEDS["sealed_validation"]:
        return False
    report_record = _mapping(manifest.get("stages")).get("final_report")
    report = root / "final_report.json"
    if not isinstance(report_record, str) or Path(report_record).name != report.name:
        return False
    try:
        tasks = _json(root / "production" / "tasks.json", root=root)
        if not isinstance(tasks, list):
            return False
        task_by_identity: dict[tuple[float, int, int], dict[str, Any]] = {}
        for raw in tasks:
            task = _mapping(raw)
            identity = (float(task["s0"]), int(task["zeeman_seed"]), int(task["mot_seed"]))
            if identity in task_by_identity:
                return False
            task_by_identity[identity] = task
        expected_identities = {
            (value, seed, expected_pairs[seed]) for value in values for seed in sealed
        }
        if set(task_by_identity) != expected_identities:
            return False

        payload = _mapping(_json(report, root=root)); results = _list(payload.get("results"))
        if payload.get("kind") != "mot_2d_s0_campaign_final_report" or len(results) != len(values):
            return False
        result_by_s0 = {float(_mapping(item)["s0"]): _mapping(item) for item in results}
        if set(result_by_s0) != set(values):
            return False
        frozen_by_seed = {
            int(item["zeeman_seed"]): _mapping(item)
            for item in manifest["input_ensembles"]["sealed_validation"]
        }
        expected_design = {
            "dt_s": manifest["fixed_design"]["final_dt_s"],
            "stochastic_solver": "RK4StHybridCustom",
            "uses_all_available_particles": True,
            "npools": 150,
            "ensemble_dir": manifest["ensemble_source"]["directory"],
            "zeeman_profile": manifest["ensemble_source"]["zeeman_profile"],
            "git_commit": manifest["provenance"]["git_commit"],
        }
        for value in values:
            key = f"s0_{float(value):.6f}".replace(".", "p")
            summary = _mapping(_json(root / "production" / key / "summary.json", root=root))
            replicates = _list(summary.get("replicates"))
            if (
                summary.get("kind") != "mot_2d_final_production_summary"
                or summary.get("zeeman_seeds") != sealed
                or summary.get("design") != expected_design
                or len(replicates) != len(sealed)
            ):
                return False
            replicate_by_seed = {int(row["zeeman_seed"]): _mapping(row) for row in replicates}
            if set(replicate_by_seed) != set(sealed):
                return False
            parameters = summary.get("parameters")
            if not isinstance(parameters, dict):
                return False
            for seed in sealed:
                replicate = replicate_by_seed[seed]
                task = task_by_identity[(value, seed, expected_pairs[seed])]
                if (
                    replicate.get("mot_seed") != expected_pairs[seed]
                    or task.get("parameters") != parameters
                    or replicate.get("captured") is None
                    or replicate.get("n_input") is None
                ):
                    return False
            result = result_by_s0[value]
            if (
                result.get("recommended_parameters") != parameters
                or result.get("prediction") != summary.get("prediction_for_10m_zeeman_survivors")
            ):
                return False
            recorded_states = Path(result["survivor_states_directory"])
            states = recorded_states.resolve() if recorded_states.is_absolute() else (repository_root / recorded_states).resolve()
            if not _within(states, repository_root.resolve()) or not states.is_dir():
                return False
            for seed, mot_seed in zip(sealed, mot_seeds):
                state = states / f"mot_2d_survivors_zeeman_seed{seed}_mot_seed{mot_seed}.npy"
                metadata = state.with_suffix(".json")
                meta = _mapping(_json(metadata, root=repository_root))
                if not _trusted_file(state, repository_root) or meta.get("output_sha256") != _sha256(state):
                    return False
                array = np.load(state, mmap_mode="r", allow_pickle=False)
                replicate = replicate_by_seed[seed]
                source_path = str(Path(frozen_by_seed[seed]["path"]).resolve())
                if (
                    meta.get("kind") != "mot_2d_final_survivor_ensemble"
                    or meta.get("zeeman_seed") != seed or meta.get("mot_seed") != mot_seed
                    or meta.get("n_input") != replicate.get("n_input")
                    or meta.get("n_survivors") != replicate.get("captured")
                    or meta.get("shape") != list(array.shape)
                    or meta.get("dtype") != str(array.dtype)
                    or array.ndim != 2 or array.shape[1] != 6
                    or not np.all(np.isfinite(array))
                    or meta.get("parameters") != parameters
                    or meta.get("design") != expected_design
                    or str(Path(meta.get("source_zeeman_ensemble", "")).resolve()) != source_path
                ):
                    return False
    except (OSError, ValueError, TypeError, KeyError, StopIteration, json.JSONDecodeError):
        return False
    return True
