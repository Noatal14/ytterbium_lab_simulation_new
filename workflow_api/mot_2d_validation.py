"""Conservative validation of modern fixed-s0 2D campaign records."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
    attest_canonical_zeeman_metadata,
    validate_laboratory_provenance_identity,
)
from workflow_api.repository_paths import resolve_repo_relative

from workflow_api.models import StageProgress
from workflow_api.mot_2d_spec import validate_campaign_policy, stage_npools, survivor_states_directory
from utils.mot_2d_study import summarize_replicates
from workflow_api.mot_2d_late_stage import derive_production_transition
from workflow_api.mot_2d_prediction import final_prediction

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


def _finite_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("expected a finite number")
    return number


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
    try:
        validate_campaign_policy(manifest)
    except ValueError as error:
        errors.append(str(error))
    provenance = _mapping(manifest.get("provenance"))
    if provenance.get("path_contract") != "repository-relative-v1":
        errors.append("campaign uses a legacy non-portable path contract")
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
    laboratory_keys = {
        "laboratory_spec_version", "laboratory_spec_sha256", "zeeman_profile_sha256"
    }
    source_laboratory_keys = laboratory_keys.intersection(source)
    if source_laboratory_keys and source_laboratory_keys != laboratory_keys:
        errors.append("ensemble source laboratory provenance is incomplete")
    source_identity_valid = True
    if source_laboratory_keys == laboratory_keys:
        try:
            validate_laboratory_provenance_identity(
                source.get("laboratory_spec_version"),
                source.get("laboratory_spec_sha256"),
                source.get("zeeman_profile_sha256"),
                allow_legacy=True,
            )
        except ValueError:
            source_identity_valid = False
    if (not isinstance(source.get("directory"), str)
            or source.get("zeeman_profile") != CANONICAL_ZEEMAN_PROFILE_NAME
            or not source_identity_valid):
        errors.append("ensemble source is incomplete")
    else:
        try:
            resolve_repo_relative(repository_root, source["directory"], allowed_root="data/particle_states/after_zeeman", require="dir")
        except ValueError:
            errors.append("ensemble source path is not a trusted repository-relative directory")
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
                required = (
                    "zeeman_seed", "path", "metadata_path", "sha256",
                    "metadata_sha256", "shape", "dtype", "survivor_count",
                    "zeeman_profile", "source_git_commit", "generation",
                )
                if any(item.get(key) is None for key in required):
                    errors.append(f"{role} frozen input record is incomplete")
                    break
                paths: list[Path] = []
                for key in ("path", "metadata_path"):
                    recorded = Path(item[key])
                    try:
                        unresolved = resolve_repo_relative(repository_root, item[key], allowed_root="data/particle_states/after_zeeman", require="file")
                    except ValueError:
                        errors.append(f"{role} frozen input artifact is unavailable or outside the repository")
                        paths = []
                        break
                    paths.append(unresolved)
                if paths:
                    try:
                        source_directory = resolve_repo_relative(
                            repository_root, source["directory"],
                            allowed_root="data/particle_states/after_zeeman", require="dir",
                        )
                        if any(not path.is_relative_to(source_directory) for path in paths):
                            raise ValueError("frozen input is outside the selected source")
                        metadata = _mapping(_json(paths[1], root=repository_root))
                        parameters = _mapping(metadata.get("parameters"))
                        software = _mapping(metadata.get("software"))
                        generation = _mapping(item.get("generation"))
                        metadata_generation = {
                            key: parameters.get(key)
                            for key in ("n_initial_atoms", "dt_s", "stochastic", "collimation_angle_deg")
                        }
                        laboratory = attest_canonical_zeeman_metadata(
                            metadata, allow_legacy=True
                        )
                        record_laboratory_keys = laboratory_keys.intersection(item)
                        if record_laboratory_keys and record_laboratory_keys != laboratory_keys:
                            raise ValueError("partial frozen laboratory provenance")
                        if (
                            item.get("zeeman_profile") != source.get("zeeman_profile")
                            or _sha256(paths[0]) != item["sha256"]
                            or _sha256(paths[1]) != item["metadata_sha256"]
                            or metadata.get("output_sha256") != item["sha256"]
                            or metadata.get("shape") != item["shape"]
                            or metadata.get("dtype") != item["dtype"]
                            or metadata.get("n_survivors") != item["survivor_count"]
                            or parameters.get("seed") != item.get("zeeman_seed")
                            or parameters.get("resolved_zeeman_magnet_profile") != source.get("zeeman_profile")
                            or (record_laboratory_keys and any(
                                item.get(key) != laboratory[key]
                                for key in laboratory_keys
                            ))
                            or software.get("git_commit") != item.get("source_git_commit")
                            or metadata_generation != generation
                        ):
                            errors.append(f"{role} frozen input provenance does not match local files")
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        errors.append(f"{role} frozen input provenance does not match local files")
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
    return (
        design.get("dt_s") == dt
        and design.get("stochastic_solver", design.get("solver")) == "RK4StHybridCustom"
        and design.get("git_commit") == manifest["provenance"]["git_commit"]
        and design.get("zeeman_seeds") == manifest["seed_roles"][role]
        and design.get("mot_seeds") == manifest["mot_seeds"][role]
        and design.get("ensemble_dir") == source["directory"]
    )


def _optimization_design_id(
    manifest: dict[str, Any], *, stage: str, s0: float, worker: int,
    particles: int, sampler_seed: int, bounds: dict[str, Any],
    zeeman_seeds: list[int] | None = None, mot_seeds: list[int] | None = None,
    repository_root: Path | None = None,
) -> str:
    role = STAGE_ROLE[stage]
    source = manifest["ensemble_source"]["directory"]
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
    if validate_campaign_policy(manifest):
        design["acceptance"] = manifest["acceptance"]
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
        source = manifest["ensemble_source"]["directory"]
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
            and design.get("ensemble_dir") == source
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def _validated_evaluation(
    path: Path,
    manifest: dict[str, Any],
    stage: str,
    task: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    row = _mapping(_json(path, root=root))
    design = _mapping(row.get("design"))
    index_key = "candidate_index" if stage == "confirmation" else "point_index"
    role = STAGE_ROLE[stage]
    zeeman_seeds = manifest["seed_roles"][role]
    mot_seeds = manifest["mot_seeds"][role]
    particles = manifest["fixed_design"]["particle_counts"][stage]
    if not (
        row.get("kind") == f"mot_2d_campaign_{stage}"
        and row.get(index_key) == task.get(index_key)
        and row.get("s0") == task.get("s0")
        and row.get("parameters") == task.get("parameters")
        and design.get("physical_model_sha256") == manifest["provenance"]["physical_model_sha256"]
        and design.get("git_commit") == manifest["provenance"]["git_commit"]
        and design.get("solver") == "RK4StHybridCustom"
        and design.get("dt_s") == manifest["fixed_design"]["final_dt_s"]
        and design.get("n_ensembles") == len(zeeman_seeds)
        and design.get("particles_per_ensemble") == particles
        and design.get("zeeman_seeds") == zeeman_seeds
        and design.get("mot_seeds") == mot_seeds
        and design.get("ensemble_source") == manifest["ensemble_source"]
    ):
        raise ValueError(f"Invalid {stage} result identity or frozen design.")
    if validate_campaign_policy(manifest) and design.get("acceptance") != manifest["acceptance"]:
        raise ValueError("Acceptance result lost its frozen provenance.")
    if stage == "sensitivity" and (
        row.get("offsets") != task.get("offsets")
        or row.get("requested_offsets") != task.get("requested_offsets")
    ):
        raise ValueError("Sensitivity offsets differ from the frozen task.")

    evaluation = _mapping(row.get("evaluation"))
    replicates = _list(evaluation.get("replicates"))
    if len(replicates) != len(zeeman_seeds):
        raise ValueError(f"Invalid {stage} replicate count.")
    frozen = {
        int(item["zeeman_seed"]): _mapping(item)
        for item in manifest["input_ensembles"][role]
    }
    expected_replicate_keys = {
        "ensemble_file", "zeeman_seed", "mot_seed", "n_available",
        "selection_method", "subset_seed", "n_input", "captured",
        "conditional_efficiency", "estimated_total_efficiency",
        "batch_elapsed_seconds",
    }
    batch_elapsed = _finite_number(evaluation.get("batch_elapsed_seconds"))
    if batch_elapsed < 0:
        raise ValueError(f"Invalid {stage} elapsed time.")
    for index, raw in enumerate(replicates):
        replicate = _mapping(raw)
        seed = zeeman_seeds[index]
        source = frozen.get(seed, {})
        captured = replicate.get("captured")
        if (
            set(replicate) != expected_replicate_keys
            or replicate.get("ensemble_file") != Path(source.get("path", "")).name
            or replicate.get("zeeman_seed") != seed
            or replicate.get("mot_seed") != mot_seeds[index]
            or replicate.get("n_available") != source.get("survivor_count")
            or replicate.get("selection_method") != "deterministic_random_without_replacement"
            or replicate.get("subset_seed") != 100_000 + seed
            or replicate.get("n_input") != particles
            or not isinstance(captured, int)
            or isinstance(captured, bool)
            or not 0 <= captured <= particles
            or _finite_number(replicate.get("batch_elapsed_seconds")) != batch_elapsed
            or _finite_number(replicate.get("conditional_efficiency")) != captured / particles
        ):
            raise ValueError(f"Invalid {stage} replicate provenance or counts.")
        generation = _mapping(source.get("generation"))
        initial = generation.get("n_initial_atoms")
        if not isinstance(initial, int) or isinstance(initial, bool) or initial <= 0:
            raise ValueError(f"Invalid {stage} source population.")
        expected_total = (captured / particles) * (source["survivor_count"] / initial)
        if not math.isclose(
            _finite_number(replicate.get("estimated_total_efficiency")),
            expected_total,
            rel_tol=1e-15,
            abs_tol=0.0,
        ):
            raise ValueError(f"Invalid {stage} total efficiency.")
    statistics = _mapping(evaluation.get("statistics"))
    if statistics != summarize_replicates(replicates):
        raise ValueError(f"Invalid {stage} aggregate statistics.")
    return row


def _expected_confirmation_tasks(
    root: Path, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    """Re-render the authoritative refinement-to-confirmation task registry."""
    from workflow_api.mot_2d_plan import render_confirmation_transition
    from workflow_api.mot_2d_screen import validate_refine_outputs

    repository_root = root.parents[3]
    rendered = render_confirmation_transition(
        manifest, root, repository_root, validate_refine_outputs(root, manifest)
    )
    tasks = json.loads(rendered["confirmation/tasks.json"].decode("utf-8"))
    if not isinstance(tasks, list):
        raise ValueError("Invalid authoritative confirmation task registry.")
    return tasks


def expected_sensitivity_tasks(
    manifest: dict[str, Any], confirmation_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Derive the canonical clamped/deduplicated sensitivity task registry."""
    fixed = _mapping(manifest.get("fixed_design"))
    detuning_bounds = fixed["detuning_bounds_gamma"]
    radius_bounds = fixed["magnet_radius_bounds_m"]
    control = _mapping(fixed.get("control_resolution"))
    stress = _mapping(fixed.get("stress_test_offsets"))
    tasks: list[dict[str, Any]] = []
    for value in manifest["s0_values"]:
        rows = [row for row in confirmation_rows if row["s0"] == value]
        rows.sort(key=lambda row: (
            -row["evaluation"]["statistics"]["conditional_95_ci"][0],
            -row["evaluation"]["statistics"]["mean_conditional_efficiency"],
            row["candidate_index"],
        ))
        if len(rows) != 5:
            raise ValueError(f"Invalid confirmation candidate count for s0={value}.")
        reference = rows[0]["parameters"]
        neighborhoods = (
            (
                "provisional_control_resolution",
                _finite_number(control["detuning_gamma"]),
                _finite_number(control["magnet_radius_m"]),
            ),
            (
                "broader_stress_test",
                _finite_number(stress["detuning_gamma"]),
                _finite_number(stress["magnet_radius_m"]),
            ),
        )
        unique: dict[tuple[float, float], dict[str, Any]] = {}
        for neighborhood, detuning_delta, radius_delta in neighborhoods:
            for detuning_offset in (-detuning_delta, 0.0, detuning_delta):
                for radius_offset in (-radius_delta, 0.0, radius_delta):
                    parameters = {
                        "s0": value,
                        "detuning_gamma": min(max(
                            reference["detuning_gamma"] + detuning_offset,
                            detuning_bounds[0],
                        ), detuning_bounds[1]),
                        "magnet_radius": min(max(
                            reference["magnet_radius"] + radius_offset,
                            radius_bounds[0],
                        ), radius_bounds[1]),
                    }
                    identity = (
                        parameters["detuning_gamma"], parameters["magnet_radius"]
                    )
                    requested = {
                        "neighborhood": neighborhood,
                        "detuning_gamma": detuning_offset,
                        "magnet_radius_m": radius_offset,
                    }
                    if identity in unique:
                        unique[identity]["requested_offsets"].append(requested)
                    else:
                        unique[identity] = {
                            "s0": value,
                            "parameters": parameters,
                            "offsets": {
                                "detuning_gamma": (
                                    parameters["detuning_gamma"]
                                    - reference["detuning_gamma"]
                                ),
                                "magnet_radius_m": (
                                    parameters["magnet_radius"]
                                    - reference["magnet_radius"]
                                ),
                            },
                            "requested_offsets": [requested],
                        }
        tasks.extend(
            {"point_index": point, **spec}
            for point, spec in enumerate(unique.values())
        )
    return tasks


def _expected_production_design(manifest: dict[str, Any]) -> dict[str, Any]:
    source = _mapping(manifest.get("ensemble_source"))
    design = {
        "dt_s": manifest["fixed_design"]["final_dt_s"],
        "stochastic_solver": "RK4StHybridCustom",
        "uses_all_available_particles": True,
        "npools": stage_npools(manifest, "production", 150),
        "ensemble_dir": source["directory"],
        "zeeman_profile": source["zeeman_profile"],
        "git_commit": manifest["provenance"]["git_commit"],
    }
    provenance_keys = (
        "laboratory_spec_version", "laboratory_spec_sha256",
        "zeeman_profile_sha256",
    )
    present = [key in source for key in provenance_keys]
    if any(present) and not all(present):
        raise ValueError("Incomplete laboratory provenance in ensemble source.")
    if all(present):
        design.update({key: source[key] for key in provenance_keys})
    if validate_campaign_policy(manifest):
        design["acceptance"] = manifest["acceptance"]
    return design


def _validated_production_replicate(
    path: Path,
    manifest: dict[str, Any],
    task: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    row = _mapping(_json(path, root=root))
    replicate = _mapping(row.get("replicate"))
    seed = task["zeeman_seed"]
    frozen = next(
        _mapping(item)
        for item in manifest["input_ensembles"]["sealed_validation"]
        if item["zeeman_seed"] == seed
    )
    expected_keys = {
        "ensemble_file", "zeeman_seed", "mot_seed", "n_available",
        "selection_method", "subset_seed", "n_input", "captured",
        "conditional_efficiency", "estimated_total_efficiency",
        "batch_elapsed_seconds",
    }
    n_input = frozen["survivor_count"]
    captured = replicate.get("captured")
    initial = _mapping(frozen.get("generation")).get("n_initial_atoms")
    if (
        row.get("kind") != "mot_2d_final_production_replicate"
        or row.get("parameters") != task.get("parameters")
        or row.get("design") != _expected_production_design(manifest)
        or set(replicate) != expected_keys
        or replicate.get("ensemble_file") != Path(frozen["path"]).name
        or replicate.get("zeeman_seed") != seed
        or replicate.get("mot_seed") != task.get("mot_seed")
        or replicate.get("n_available") != n_input
        or replicate.get("selection_method") != "all_particles"
        or replicate.get("subset_seed") != 100_000 + seed
        or not isinstance(n_input, int) or isinstance(n_input, bool) or n_input <= 0
        or replicate.get("n_input") != n_input
        or not isinstance(captured, int) or isinstance(captured, bool)
        or not 0 <= captured <= n_input
        or not isinstance(initial, int) or isinstance(initial, bool) or initial <= 0
        or _finite_number(replicate.get("batch_elapsed_seconds")) < 0
        or _finite_number(replicate.get("conditional_efficiency"))
        != captured / n_input
        or not math.isclose(
            _finite_number(replicate.get("estimated_total_efficiency")),
            captured / initial,
            rel_tol=1e-15,
            abs_tol=0.0,
        )
    ):
        raise ValueError("Invalid sealed production replicate evidence.")
    return replicate


def _valid_evaluation(path: Path, manifest: dict[str, Any], stage: str, task: dict[str, Any], root: Path) -> bool:
    try:
        _validated_evaluation(path, manifest, stage, task, root)
        return True
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def validated_evaluation_outputs(
    root: Path, manifest: dict[str, Any], stage: str
) -> list[dict[str, Any]]:
    """Return complete, identity-bound confirmation/sensitivity records.

    This is the advancement gate used by the campaign runner.  Merely naming
    the expected number of files is intentionally insufficient.
    """
    if stage not in ("confirmation", "sensitivity"):
        raise ValueError("Only confirmation and sensitivity are supported.")
    tasks = _json(root / stage / "tasks.json", root=root)
    stage_record = _mapping(_mapping(manifest.get("stages")).get(stage))
    expected_count = stage_record.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != expected_count:
        raise ValueError(f"Invalid {stage} task registry.")
    expected_tasks = _canonical_evaluation_tasks(root, manifest, stage)
    if tasks != expected_tasks:
        raise ValueError(f"{stage.capitalize()} task registry is not canonical.")
    index_key = "candidate_index" if stage == "confirmation" else "point_index"
    identities: set[tuple[float, int]] = set()
    rows: list[dict[str, Any]] = []
    expected_paths: set[Path] = set()
    for raw in tasks:
        task = _mapping(raw)
        index = task.get(index_key)
        s0 = task.get("s0")
        if (
            not isinstance(index, int) or isinstance(index, bool) or index < 0
            or isinstance(s0, bool) or not isinstance(s0, (int, float))
            or not math.isfinite(float(s0))
        ):
            raise ValueError(f"Invalid {stage} task identity.")
        identity = (float(s0), index)
        if identity in identities:
            raise ValueError(f"Duplicate {stage} task identity.")
        identities.add(identity)
        key = f"s0_{float(s0):.6f}".replace(".", "p")
        path = root / stage / key / f"point_{index:02d}.json"
        expected_paths.add(path)
        rows.append(_validated_evaluation(path, manifest, stage, task, root))
    observed_paths = set((root / stage).glob("s0_*/point_*.json"))
    if observed_paths != expected_paths:
        raise ValueError(f"Unexpected or missing {stage} result files.")
    return rows


def _canonical_evaluation_tasks(
    root: Path, manifest: dict[str, Any], stage: str
) -> list[dict[str, Any]]:
    if stage == "confirmation":
        return _expected_confirmation_tasks(root, manifest)
    confirmation_rows = validated_evaluation_outputs(root, manifest, "confirmation")
    return expected_sensitivity_tasks(manifest, confirmation_rows)


def validated_production_transition(
    root: Path, manifest: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate and return the derived sensitivity summary and production tasks."""
    confirmation_rows = validated_evaluation_outputs(root, manifest, "confirmation")
    sensitivity_rows = validated_evaluation_outputs(root, manifest, "sensitivity")
    expected_summary, expected_tasks = derive_production_transition(
        manifest, confirmation_rows, sensitivity_rows
    )
    observed_summary = _json(root / "sensitivity_summary.json", root=root)
    observed_tasks = _json(root / "production/tasks.json", root=root)
    if observed_summary != expected_summary or observed_tasks != expected_tasks:
        raise ValueError("Production transition artifacts are not canonical.")
    return expected_summary, expected_tasks


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
        if stage in ("confirmation", "sensitivity"):
            try:
                canonical_tasks = _canonical_evaluation_tasks(root, manifest, stage)
            except (OSError, ValueError, TypeError, KeyError, StopIteration, json.JSONDecodeError):
                rows.append(_progress(stage, 0, len(tasks), True)); continue
            if tasks != canonical_tasks:
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
            try:
                _, canonical_tasks = validated_production_transition(root, manifest)
            except (OSError, ValueError, TypeError, KeyError, StopIteration, json.JSONDecodeError):
                rows.append(_progress("production", 0, len(tasks), True))
                canonical_tasks = []
                invalid = True
            if not invalid and tasks != canonical_tasks:
                rows.append(_progress("production", 0, len(tasks), True))
                invalid = True
            if not invalid:
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
                    invalid = True
                    rows.append(_progress("production", 0, len(tasks), True))
            if not invalid:
                for task in tasks:
                    task = _mapping(task); s0 = float(task.get("s0")); key = f"s0_{s0:.6f}".replace(".", "p")
                    path = root / "production" / key / "replicates" / f"zeeman_seed{task.get('zeeman_seed')}.json"
                    if not path.exists(): continue
                    try:
                        _validated_production_replicate(path, manifest, task, root)
                        valid = True
                    except (OSError, ValueError, TypeError, KeyError, StopIteration, json.JSONDecodeError): valid = False
                    complete += int(valid); invalid |= not valid
                rows.append(_progress("production", complete, len(tasks), invalid))
    return tuple(rows)


def sealed_final_is_valid(
    root: Path, manifest: dict[str, Any], progress: tuple[StageProgress, ...],
    repository_root: Path,
) -> bool:
    production = next((row for row in progress if row.stage == "production"), None)
    sensitivity_progress = next(
        (row for row in progress if row.stage == "sensitivity"), None
    )
    if (
        manifest.get("stage") != "complete"
        or production is None or production.status != "complete"
        or sensitivity_progress is None or sensitivity_progress.status != "complete"
    ):
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
        sensitivity_by_s0, expected_production_tasks = validated_production_transition(
            root, manifest
        )
        if tasks != expected_production_tasks:
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
        if (
            payload.get("kind") != ("mot_2d_ui_acceptance_final_report_v1" if validate_campaign_policy(manifest) else "mot_2d_s0_campaign_final_report")
            or payload.get("always_returns_best_tested_result") is not True
            or len(results) != len(values)
        ):
            return False
        result_by_s0 = {float(_mapping(item)["s0"]): _mapping(item) for item in results}
        if set(result_by_s0) != set(values):
            return False
        frozen_by_seed = {
            int(item["zeeman_seed"]): _mapping(item)
            for item in manifest["input_ensembles"]["sealed_validation"]
        }
        expected_design = _expected_production_design(manifest)
        sensitivity_by_s0 = _mapping(sensitivity_by_s0)
        fixed_design = _mapping(manifest.get("fixed_design"))
        target = _finite_number(fixed_design.get("target_95_half_width_fraction"))
        reporting_survivors = fixed_design.get("reporting_zeeman_survivors")
        detuning_bounds = fixed_design.get("detuning_bounds_gamma")
        radius_bounds = fixed_design.get("magnet_radius_bounds_m")
        detuning_tolerance = _finite_number(
            fixed_design.get("detuning_resolution_gamma")
        ) / 2.0
        radius_tolerance = _finite_number(
            fixed_design.get("magnet_radius_resolution_m")
        ) / 2.0
        if (
            target <= 0
            or not isinstance(reporting_survivors, int)
            or isinstance(reporting_survivors, bool)
            or reporting_survivors <= 0
            or not isinstance(detuning_bounds, list) or len(detuning_bounds) != 2
            or not isinstance(radius_bounds, list) or len(radius_bounds) != 2
        ):
            return False
        for value in values:
            key = f"s0_{float(value):.6f}".replace(".", "p")
            replicate_directory = root / "production" / key / "replicates"
            expected_replicate_files = {
                replicate_directory / f"zeeman_seed{seed}.json" for seed in sealed
            }
            if set(replicate_directory.glob("zeeman_seed*.json")) != expected_replicate_files:
                return False
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
            validated_replicates: list[dict[str, Any]] = []
            parameters = summary.get("parameters")
            if not isinstance(parameters, dict):
                return False
            for seed in sealed:
                replicate = replicate_by_seed[seed]
                task = task_by_identity[(value, seed, expected_pairs[seed])]
                evidence_path = (
                    root / "production" / key / "replicates"
                    / f"zeeman_seed{seed}.json"
                )
                validated_replicate = _validated_production_replicate(
                    evidence_path, manifest, task, root
                )
                if (
                    replicate.get("mot_seed") != expected_pairs[seed]
                    or task.get("parameters") != parameters
                    or replicate != validated_replicate
                ):
                    return False
                validated_replicates.append(validated_replicate)
            recomputed_statistics = summarize_replicates(validated_replicates)
            recomputed_prediction = final_prediction(
                validated_replicates,
                reporting_survivors=reporting_survivors,
            )
            if (
                summary.get("replicate_statistics") != recomputed_statistics
                or summary.get("prediction_for_10m_zeeman_survivors")
                != recomputed_prediction
                or recomputed_prediction.get("reporting_zeeman_survivors")
                != reporting_survivors
            ):
                return False
            result = result_by_s0[value]
            sensitivity = _mapping(sensitivity_by_s0.get(key))
            selection = _mapping(sensitivity.get("production_selection"))
            prediction = _mapping(recomputed_prediction)
            half_width = _finite_number(prediction.get("predicted_95_half_width_fraction"))
            stopping_rule_passes = half_width <= target
            warnings: list[str] = []
            detuning = _finite_number(parameters.get("detuning_gamma"))
            radius = _finite_number(parameters.get("magnet_radius"))
            if abs(detuning - _finite_number(detuning_bounds[0])) <= detuning_tolerance:
                warnings.append("detuning_lower")
            if abs(detuning - _finite_number(detuning_bounds[1])) <= detuning_tolerance:
                warnings.append("detuning_upper")
            if abs(radius - _finite_number(radius_bounds[0])) <= radius_tolerance:
                warnings.append("radius_lower")
            if abs(radius - _finite_number(radius_bounds[1])) <= radius_tolerance:
                warnings.append("radius_upper")
            if not stopping_rule_passes:
                warnings.append("target_95_prediction_half_width_not_met")
            if sensitivity.get("robustness_status") != (
                "not_established_pending_adaptive_challenger_validation"
            ):
                return False
            warnings.append("robust_operating_region_not_established")
            if sensitivity.get("near_optimality_status") != (
                "not_established_pending_domain_challenger_elimination"
            ):
                return False
            warnings.append("epsilon_near_optimality_not_established")
            if (
                result.get("recommended_parameters") != parameters
                or result.get("prediction") != prediction
                or result.get("sensitivity") != sensitivity
                or selection.get("parameters") != parameters
                or result.get("target_uncertainty_passes") is not stopping_rule_passes
                or result.get("warnings") != warnings
                or summary.get("target_95_half_width_fraction") != target
                or summary.get("target_95_half_width_percentage_points") != 100 * target
                or summary.get("stopping_rule_passes") is not stopping_rule_passes
            ):
                return False
            states = resolve_repo_relative(
                repository_root,
                result["survivor_states_directory"],
                allowed_root=(root.relative_to(repository_root).as_posix() if validate_campaign_policy(manifest) else "data/particle_states/after_2d_mot"),
                require="dir",
            )
            if not states.is_dir():
                return False
            for seed, mot_seed in zip(sealed, mot_seeds):
                state = states / f"mot_2d_survivors_zeeman_seed{seed}_mot_seed{mot_seed}.npy"
                metadata = state.with_suffix(".json")
                meta = _mapping(_json(metadata, root=repository_root))
                if not _trusted_file(state, repository_root) or meta.get("output_sha256") != _sha256(state):
                    return False
                array = np.load(state, mmap_mode="r", allow_pickle=False)
                replicate = replicate_by_seed[seed]
                source_identity = frozen_by_seed[seed]["path"]
                source_recorded = meta.get("source_zeeman_ensemble", "")
                resolve_repo_relative(
                    repository_root, source_identity,
                    allowed_root="data/particle_states/after_zeeman", require="file",
                )
                resolve_repo_relative(
                    repository_root, source_recorded,
                    allowed_root="data/particle_states/after_zeeman", require="file",
                )
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
                    or source_recorded != source_identity
                ):
                    return False
    except (OSError, ValueError, TypeError, KeyError, StopIteration, json.JSONDecodeError):
        return False
    return True


def validated_sealed_production_outputs(
    root: Path, manifest: dict[str, Any], repository_root: Path,
) -> tuple[dict[str, Any], dict[float, list[dict[str, Any]]]]:
    """Validate raw sealed Production evidence without trusting summaries.

    The returned rows are safe inputs to the deterministic final-summary
    derivation.  Summary/report files are intentionally ignored here because
    finalization must be able to create them from the raw evidence.
    """
    if manifest.get("stage") != "production":
        raise ValueError("Campaign is not awaiting finalization.")
    sealed = manifest["seed_roles"]["sealed_validation"]
    mot_seeds = manifest["mot_seeds"]["sealed_validation"]
    if sealed != CANONICAL_ROLE_SEEDS["sealed_validation"] or len(mot_seeds) != 20:
        raise ValueError("Invalid sealed Production seed registry.")
    sensitivity, tasks = validated_production_transition(root, manifest)
    task_file = _json(root / "production" / "tasks.json", root=root)
    if task_file != tasks:
        raise ValueError("Production task registry is not authoritative.")
    expected_design = _expected_production_design(manifest)
    expected_pairs = dict(zip(sealed, mot_seeds))
    frozen_by_seed = {
        int(item["zeeman_seed"]): _mapping(item)
        for item in manifest["input_ensembles"]["sealed_validation"]
    }
    values = [float(value) for value in manifest["s0_values"]]
    result: dict[float, list[dict[str, Any]]] = {}
    for value in values:
        key = f"s0_{value:.6f}".replace(".", "p")
        selected = [task for task in tasks if float(task["s0"]) == value]
        if len(selected) != 20:
            raise ValueError("Production must contain exactly 20 sealed ensembles per s0.")
        replicate_directory = root / "production" / key / "replicates"
        expected_files = {
            replicate_directory / f"zeeman_seed{seed}.json" for seed in sealed
        }
        if set(replicate_directory.glob("zeeman_seed*.json")) != expected_files:
            raise ValueError("Production replicate registry is incomplete or contains stale files.")
        by_seed = {int(task["zeeman_seed"]): task for task in selected}
        if set(by_seed) != set(sealed):
            raise ValueError("Production task identities are incomplete.")
        rows: list[dict[str, Any]] = []
        value_label = f"{value:.6f}".rstrip("0").rstrip(".")
        state_directory = survivor_states_directory(manifest, root, value)
        state_identity = state_directory.relative_to(repository_root).as_posix() if state_directory.is_absolute() else state_directory.as_posix()
        states = resolve_repo_relative(
            repository_root, state_identity,
            allowed_root=(root.relative_to(repository_root).as_posix() if validate_campaign_policy(manifest) else "data/particle_states/after_2d_mot"), require="dir",
        )
        expected_state_names = {
            f"mot_2d_survivors_zeeman_seed{seed}_mot_seed{expected_pairs[seed]}.npy"
            for seed in sealed
        }
        if {path.name for path in states.glob("mot_2d_survivors_*.npy")} != expected_state_names:
            raise ValueError("Sealed survivor-state registry is incomplete or contains stale files.")
        for seed in sealed:
            task = by_seed[seed]
            evidence = replicate_directory / f"zeeman_seed{seed}.json"
            row = _validated_production_replicate(evidence, manifest, task, root)
            mot_seed = expected_pairs[seed]
            state = states / f"mot_2d_survivors_zeeman_seed{seed}_mot_seed{mot_seed}.npy"
            metadata = state.with_suffix(".json")
            meta = _mapping(_json(metadata, root=repository_root))
            if not _trusted_file(state, repository_root) or meta.get("output_sha256") != _sha256(state):
                raise ValueError("Sealed survivor-state digest mismatch.")
            array = np.load(state, mmap_mode="r", allow_pickle=False)
            frozen_source = frozen_by_seed[seed]
            source_identity = frozen_source["path"]
            source_path = resolve_repo_relative(
                repository_root, source_identity,
                allowed_root="data/particle_states/after_zeeman", require="file",
            )
            source_metadata = resolve_repo_relative(
                repository_root, frozen_source["metadata_path"],
                allowed_root="data/particle_states/after_zeeman", require="file",
            )
            if (_sha256(source_path) != frozen_source.get("sha256")
                    or _sha256(source_metadata)
                    != frozen_source.get("metadata_sha256")):
                raise ValueError("Frozen Zeeman input digest mismatch.")
            source_recorded = meta.get("source_zeeman_ensemble", "")
            resolve_repo_relative(
                repository_root, source_recorded,
                allowed_root="data/particle_states/after_zeeman", require="file",
            )
            if (
                meta.get("kind") != "mot_2d_final_survivor_ensemble"
                or meta.get("zeeman_seed") != seed
                or meta.get("mot_seed") != mot_seed
                or meta.get("n_input") != row.get("n_input")
                or meta.get("n_survivors") != row.get("captured")
                or meta.get("shape") != list(array.shape)
                or meta.get("dtype") != str(array.dtype)
                or array.ndim != 2 or array.shape[1] != 6
                or not np.all(np.isfinite(array))
                or meta.get("parameters") != task["parameters"]
                or meta.get("design") != expected_design
                or source_recorded != source_identity
            ):
                raise ValueError("Invalid sealed survivor-state evidence.")
            rows.append(row)
        result[value] = rows
    return sensitivity, result
