"""Pure canonical plan for a fixed-s0 2D-MOT campaign."""

from __future__ import annotations

import hashlib
import json
import math
from workflow_api.platform_io import os
import re
import shlex
import shutil
import tempfile
import ctypes
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workflow_api.mot_2d_sources import inspect_source
from workflow_api.mot_2d_spec import campaign_kind_matches, validate_campaign_policy, refinement_targets, survivor_states_directory
from workflow_api.repository_snapshot import RepositorySnapshot
from workflow_api.mot_2d_spec import RELEVANT_FILES, ROLE_SEEDS, build_manifest

SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class CampaignPlan:
    name: str; slug: str; s0_values: tuple[float, ...]; source_id: str
    destination: Path; manifest: dict[str, Any]; files: dict[str, bytes]
    source_fingerprint: str; plan_digest: str; snapshot: RepositorySnapshot
    semantic_fingerprint: str


def physical_model_hash(repository_root: Path) -> tuple[str, list[str]]:
    paths = [repository_root / path for path in RELEVANT_FILES]
    paths.extend(sorted((repository_root / "lab_setup").rglob("*.py")))
    digest = hashlib.sha256(); names: list[str] = []
    for path in paths:
        relative = path.relative_to(repository_root).as_posix()
        digest.update(relative.encode()); digest.update(path.read_bytes()); names.append(relative)
    return digest.hexdigest(), names


def normalize_s0(values: list[Any]) -> tuple[float, ...]:
    if not 1 <= len(values) <= 16:
        raise ValueError("Provide between 1 and 16 fixed s0 values.")
    normalized: list[float] = []
    for raw in values:
        if isinstance(raw, bool): raise ValueError("Every s0 value must be positive and finite.")
        value = float(raw)
        if not math.isfinite(value) or value <= 0: raise ValueError("Every s0 value must be positive and finite.")
        if value not in normalized: normalized.append(value)
    if len({f"{value:.6f}" for value in normalized}) != len(normalized):
        raise ValueError("Fixed s0 values must have distinct six-decimal output labels.")
    return tuple(normalized)


def render_campaign_files(
    manifest: dict[str, Any], destination: Path, repository_root: Path
) -> dict[str, bytes]:
    """Render the canonical initial files without touching the filesystem."""
    _validate_acceptance_destination(manifest, destination, repository_root)
    profile = validate_campaign_policy(manifest)
    if profile:
        from workflow_api.acceptance_profile import assert_acceptance_path
        assert_acceptance_path(destination, repository_root)
    values = manifest["s0_values"]
    try:
        campaign_argument = destination.relative_to(repository_root).as_posix()
    except ValueError as error:
        raise ValueError("Campaign destination must be inside the repository.") from error
    if not campaign_argument.startswith("data/optimization/mot_2d/"):
        raise ValueError("Campaign destination is outside the canonical 2D-MOT location.")
    array = "" if len(values) == 1 else f"#PBS -J 0-{len(values)-1}%1\n"
    scalar = "export PBS_ARRAY_INDEX=0\n" if len(values) == 1 else ""
    commit = manifest["provenance"]["git_commit"]
    pbs = f"""#!/bin/bash
#PBS -N mot2d_smoke
#PBS -q zeus_combined_q
{array}#PBS -l select=1:ncpus=1:mem=64gb
#PBS -l walltime=00:20:00

set -euo pipefail
PROJECT_ROOT="${{HOME}}/ytterbium_lab_simulation_new"
cd -- "${{PROJECT_ROOT}}" || exit 1
module load SPACK/apps
module load gcc/14.1.0
module load python/3.14.2
source "${{HOME}}/venvs/atomsmltr/bin/activate"
{scalar}EXPECTED_COMMIT={shlex.quote(commit)}
ACTUAL_COMMIT=$(git rev-parse HEAD)
if [ "${{ACTUAL_COMMIT}}" != "${{EXPECTED_COMMIT}}" ]; then
  echo "Commit mismatch: expected ${{EXPECTED_COMMIT}}, found ${{ACTUAL_COMMIT}}" >&2
  exit 42
fi
RUN_TMP="/tmp/${{USER}}_mot2d_smoke_${{PBS_JOBID}}_${{PBS_ARRAY_INDEX:-0}}"
mkdir -p "${{RUN_TMP}}"
export TMPDIR="${{RUN_TMP}}" TMP="${{RUN_TMP}}" TEMP="${{RUN_TMP}}"
trap 'rm -rf -- "${{RUN_TMP}}"' EXIT
python -m studies.mot_2d_s0_campaign smoke --campaign {shlex.quote(campaign_argument)} --s0-index $PBS_ARRAY_INDEX
""".encode()
    return {
        "campaign.json": (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
        "jobs/01_smoke.pbs": _acceptance_pbs(manifest, "smoke", pbs),
    }


def render_screen_transition(
    manifest: dict[str, Any], destination: Path, repository_root: Path
) -> dict[str, bytes]:
    """Purely render the canonical smoke-to-screen transition artifacts."""
    _validate_acceptance_destination(manifest, destination, repository_root)
    if not campaign_kind_matches(manifest) or manifest.get("stage") != "smoke":
        raise ValueError("Campaign is not awaiting screening preparation.")
    try:
        campaign_argument = destination.relative_to(repository_root).as_posix()
    except ValueError as error:
        raise ValueError("Campaign destination must be inside the repository.") from error
    if not campaign_argument.startswith("data/optimization/mot_2d/"):
        raise ValueError("Campaign destination is outside the canonical 2D-MOT location.")
    values = manifest.get("s0_values")
    if not isinstance(values, list) or not values:
        raise ValueError("Campaign has no fixed s0 values.")
    tasks = [{"s0": float(value), "worker": worker} for value in values for worker in range(3)]
    commit = manifest["provenance"]["git_commit"]
    task_path = f"{campaign_argument}/screen/tasks.json"
    job_path = f"{campaign_argument}/jobs/02_screen.pbs"
    pbs = f"""#!/bin/bash
#PBS -N mot2d_scree
#PBS -q zeus_combined_q
#PBS -J 0-{len(tasks)-1}%3
#PBS -l select=1:ncpus=200:mem=64gb
#PBS -l walltime=24:00:00

set -euo pipefail
PROJECT_ROOT="${{HOME}}/ytterbium_lab_simulation_new"
cd -- "${{PROJECT_ROOT}}" || exit 1
module load SPACK/apps
module load gcc/14.1.0
module load python/3.14.2
source "${{HOME}}/venvs/atomsmltr/bin/activate"
EXPECTED_COMMIT={shlex.quote(commit)}
ACTUAL_COMMIT=$(git rev-parse HEAD)
if [ "${{ACTUAL_COMMIT}}" != "${{EXPECTED_COMMIT}}" ]; then
  echo "Commit mismatch: expected ${{EXPECTED_COMMIT}}, found ${{ACTUAL_COMMIT}}" >&2
  exit 42
fi
RUN_TMP="/tmp/${{USER}}_mot2d_scree_${{PBS_JOBID}}_${{PBS_ARRAY_INDEX:-0}}"
mkdir -p "${{RUN_TMP}}"
export TMPDIR="${{RUN_TMP}}" TMP="${{RUN_TMP}}" TEMP="${{RUN_TMP}}"
trap 'rm -rf -- "${{RUN_TMP}}"' EXIT
python -m studies.mot_2d_s0_campaign screen-task --campaign {shlex.quote(campaign_argument)} --task-index $PBS_ARRAY_INDEX
""".encode()
    updated = deepcopy(manifest)
    updated["stage"] = "screen"
    updated.setdefault("stages", {})["screen"] = {"tasks": len(tasks), "job_file": job_path}
    return {
        "screen/tasks.json": (json.dumps(tasks, indent=2, sort_keys=True) + "\n").encode(),
        "jobs/02_screen.pbs": _acceptance_pbs(manifest, "screen", pbs),
        "campaign.json": (json.dumps(updated, indent=2, sort_keys=True) + "\n").encode(),
    }


def render_refine_transition(
    manifest: dict[str, Any], destination: Path, repository_root: Path,
    validated_rows: list[dict[str, Any]],
) -> dict[str, bytes]:
    """Purely render the canonical Screening-to-Refinement transition."""
    _validate_acceptance_destination(manifest, destination, repository_root)
    if not campaign_kind_matches(manifest) or manifest.get("stage") != "screen":
        raise ValueError("Campaign is not awaiting Refinement preparation.")
    campaign_argument = destination.relative_to(repository_root).as_posix()
    if not campaign_argument.startswith("data/optimization/mot_2d/"):
        raise ValueError("Campaign destination is outside the canonical 2D-MOT location.")
    d_res=0.01; r_res=0.01e-3
    selected: dict[str,list[dict[str,Any]]] = {}; specs=[]
    detuning_bounds=manifest["fixed_design"]["detuning_bounds_gamma"]
    radius_bounds=manifest["fixed_design"]["magnet_radius_bounds_m"]
    for raw in manifest["s0_values"]:
        value=float(raw); rows=sorted((row for row in validated_rows if row["s0"]==value),key=lambda row:(-row["mean_conditional_efficiency"],row["detuning_gamma"],row["magnet_radius"]))
        chosen=[];cells=set()
        for row in rows:
            cell=(round(row["detuning_gamma"]/d_res),round(row["magnet_radius"]/r_res))
            if cell in cells:continue
            cells.add(cell);chosen.append(row)
            if len(chosen)==3:break
        if len(chosen)!=3:raise ValueError("Screening has fewer than three distinguishable candidates.")
        label=f"s0_{value:.6f}".replace(".","p");selected[label]=chosen
        for worker,candidate in enumerate(chosen):
            specs.append({"s0":value,"worker":worker,"center":candidate,"bounds":{"detuning":[max(detuning_bounds[0],candidate["detuning_gamma"]-0.08),min(detuning_bounds[1],candidate["detuning_gamma"]+0.08)],"radius":[max(radius_bounds[0],candidate["magnet_radius"]-0.5e-3),min(radius_bounds[1],candidate["magnet_radius"]+0.5e-3)]}})
    commit=manifest["provenance"]["git_commit"];files={
        "screening_candidates.json":(json.dumps(selected,indent=2,sort_keys=True)+"\n").encode(),
        "refine/tasks.json":(json.dumps(specs,indent=2,sort_keys=True)+"\n").encode(),
    };round_paths=[]
    def pbs(name:str,target:int)->bytes:
        command=f"python -m studies.mot_2d_s0_campaign refine-task --campaign {shlex.quote(campaign_argument)} --task-index $PBS_ARRAY_INDEX --target-trials {target}"
        return f'''#!/bin/bash
#PBS -N {name}
#PBS -q zeus_combined_q
#PBS -J 0-{len(specs)-1}%3
#PBS -l select=1:ncpus=200:mem=64gb
#PBS -l walltime=20:00:00

set -euo pipefail
PROJECT_ROOT="${{HOME}}/ytterbium_lab_simulation_new"
cd -- "${{PROJECT_ROOT}}" || exit 1
module load SPACK/apps
module load gcc/14.1.0
module load python/3.14.2
source "${{HOME}}/venvs/atomsmltr/bin/activate"
EXPECTED_COMMIT={commit}
ACTUAL_COMMIT=$(git rev-parse HEAD)
if [ "${{ACTUAL_COMMIT}}" != "${{EXPECTED_COMMIT}}" ]; then
  echo "Commit mismatch: expected ${{EXPECTED_COMMIT}}, found ${{ACTUAL_COMMIT}}" >&2
  exit 42
fi
RUN_TMP="/tmp/${{USER}}_{name}_${{PBS_JOBID}}_${{PBS_ARRAY_INDEX:-0}}"
mkdir -p "${{RUN_TMP}}"
export TMPDIR="${{RUN_TMP}}" TMP="${{RUN_TMP}}" TEMP="${{RUN_TMP}}"
trap 'rm -rf -- "${{RUN_TMP}}"' EXIT
{command}
'''.encode()
    for index,target in enumerate(refinement_targets(manifest),start=1):
        name=f"jobs/03_refine_round_{index:02d}.pbs";files[name]=_acceptance_pbs(manifest,"refine",pbs(f"mot2d_ref{index}",target));round_paths.append(f"{campaign_argument}/{name}")
    lines=["#!/bin/bash","set -euo pipefail"]
    for index,path in enumerate(round_paths):
        lines.append(f'previous=$(qsub "{path}")' if index==0 else f'previous=$(qsub -W depend=afterok:"${{previous}}" "{path}")')
        lines.append(f'echo "submitted refinement round {index+1}: ${{previous}}"')
    files["jobs/03_submit_refinement_chain.sh"]=("\n".join(lines)+"\n").encode()
    updated=deepcopy(manifest);updated["stage"]="refine";updated.setdefault("stages",{})["refine"]={"tasks":len(specs),"cumulative_trial_targets":list(refinement_targets(manifest)),"round_job_files":round_paths,"submit_chain":f"{campaign_argument}/jobs/03_submit_refinement_chain.sh","dependency":"afterok"}
    files["campaign.json"]=(json.dumps(updated,indent=2,sort_keys=True)+"\n").encode()
    return files


def render_confirmation_transition(manifest:dict[str,Any],destination:Path,repository_root:Path,validated_rows:list[dict[str,Any]])->dict[str,bytes]:
    """Render the deterministic Refinement-to-Confirmation transition."""
    _validate_acceptance_destination(manifest, destination, repository_root)
    selected={};specs=[]
    for value in manifest["s0_values"]:
        rows=sorted((row for row in validated_rows if float(row["s0"])==float(value)),key=lambda row:(-row["mean_conditional_efficiency"],row["detuning_gamma"],row["magnet_radius"]));chosen=[];cells=set()
        for row in rows:
            cell=(round(row["detuning_gamma"]/0.01),round(row["magnet_radius"]/0.00001))
            if cell in cells:continue
            cells.add(cell);chosen.append(row)
            if len(chosen)==5:break
        if len(chosen)!=5:raise ValueError("Fewer than five distinguishable Refinement candidates were validated.")
        label=f"s0_{float(value):.6f}".replace(".","p");selected[label]=chosen
        for index,row in enumerate(chosen):specs.append({"s0":value,"candidate_index":index,"parameters":{"s0":row["s0"],"detuning_gamma":row["detuning_gamma"],"magnet_radius":row["magnet_radius"]}})
    argument=destination.relative_to(repository_root).as_posix();commit=manifest["provenance"]["git_commit"];command=f"python -m studies.mot_2d_s0_campaign confirmation-task --campaign {shlex.quote(argument)} --task-index $PBS_ARRAY_INDEX"
    pbs=f'''#!/bin/bash
#PBS -N mot2d_confi
#PBS -q zeus_combined_q
#PBS -J 0-{len(specs)-1}%3
#PBS -l select=1:ncpus=200:mem=64gb
#PBS -l walltime=10:00:00

set -euo pipefail
PROJECT_ROOT="${{HOME}}/ytterbium_lab_simulation_new"
cd -- "${{PROJECT_ROOT}}" || exit 1
module load SPACK/apps
module load gcc/14.1.0
module load python/3.14.2
source "${{HOME}}/venvs/atomsmltr/bin/activate"
EXPECTED_COMMIT={commit}
ACTUAL_COMMIT=$(git rev-parse HEAD)
if [ "${{ACTUAL_COMMIT}}" != "${{EXPECTED_COMMIT}}" ]; then
  echo "Commit mismatch: expected ${{EXPECTED_COMMIT}}, found ${{ACTUAL_COMMIT}}" >&2
  exit 42
fi
RUN_TMP="/tmp/${{USER}}_mot2d_confi_${{PBS_JOBID}}_${{PBS_ARRAY_INDEX:-0}}"
mkdir -p "${{RUN_TMP}}"
export TMPDIR="${{RUN_TMP}}" TMP="${{RUN_TMP}}" TEMP="${{RUN_TMP}}"
trap 'rm -rf -- "${{RUN_TMP}}"' EXIT
{command}
'''.encode()
    updated=deepcopy(manifest);updated["stage"]="confirmation";updated.setdefault("stages",{})["confirmation"]={"tasks":len(specs),"job_file":f"{argument}/jobs/04_confirmation.pbs"}
    return {"refined_candidates.json":(json.dumps(selected,indent=2,sort_keys=True)+"\n").encode(),"confirmation/tasks.json":(json.dumps(specs,indent=2,sort_keys=True)+"\n").encode(),"jobs/04_confirmation.pbs":_acceptance_pbs(manifest,"confirmation",pbs),"campaign.json":(json.dumps(updated,indent=2,sort_keys=True)+"\n").encode()}


def render_sensitivity_transition(
    manifest: dict[str, Any], destination: Path, repository_root: Path,
    confirmation_rows: list[dict[str, Any]],
) -> dict[str, bytes]:
    """Render the validated Confirmation-to-Sensitivity transition exactly."""
    _validate_acceptance_destination(manifest, destination, repository_root)
    from workflow_api.mot_2d_late_stage import paired_comparison
    from workflow_api.mot_2d_validation import expected_sensitivity_tasks

    if not campaign_kind_matches(manifest) or manifest.get("stage") != "confirmation":
        raise ValueError("Campaign is not awaiting Sensitivity preparation.")
    argument = destination.relative_to(repository_root).as_posix()
    if not argument.startswith("data/optimization/mot_2d/"):
        raise ValueError("Campaign destination is outside the canonical 2D-MOT location.")
    tasks = expected_sensitivity_tasks(manifest, confirmation_rows)
    winners: dict[str, Any] = {}
    fixed = manifest["fixed_design"]
    detuning_bounds = fixed["detuning_bounds_gamma"]
    radius_bounds = fixed["magnet_radius_bounds_m"]
    for raw in manifest["s0_values"]:
        value = float(raw)
        rows = sorted(
            (row for row in confirmation_rows if float(row["s0"]) == value),
            key=lambda row: (
                -row["evaluation"]["statistics"]["conditional_95_ci"][0],
                -row["evaluation"]["statistics"]["mean_conditional_efficiency"],
                row["candidate_index"],
            ),
        )
        if len(rows) != 5:
            raise ValueError(f"Invalid confirmation candidate count for s0={value}.")
        winner = deepcopy(rows[0])
        parameters = winner["parameters"]
        flags = []
        for name, observed, bounds, tolerance in (
            ("detuning", parameters["detuning_gamma"], detuning_bounds, 0.005),
            ("radius", parameters["magnet_radius"], radius_bounds, 0.005e-3),
        ):
            if abs(observed - bounds[0]) <= tolerance: flags.append(f"{name}_lower")
            if abs(observed - bounds[1]) <= tolerance: flags.append(f"{name}_upper")
        winner["boundary_flags"] = flags
        winner["comparisons_to_other_candidates"] = [
            paired_comparison(row, winner) for row in rows[1:]
        ]
        winners[f"s0_{value:.6f}".replace(".", "p")] = winner
    commit = manifest["provenance"]["git_commit"]
    command = (
        "python -m studies.mot_2d_s0_campaign sensitivity-task "
        f"--campaign {shlex.quote(argument)} --task-index $PBS_ARRAY_INDEX"
    )
    pbs = f'''#!/bin/bash
#PBS -N mot2d_sensi
#PBS -q zeus_combined_q
#PBS -J 0-{len(tasks)-1}%3
#PBS -l select=1:ncpus=200:mem=64gb
#PBS -l walltime=10:00:00

set -euo pipefail
PROJECT_ROOT="${{HOME}}/ytterbium_lab_simulation_new"
cd -- "${{PROJECT_ROOT}}" || exit 1
module load SPACK/apps
module load gcc/14.1.0
module load python/3.14.2
source "${{HOME}}/venvs/atomsmltr/bin/activate"
EXPECTED_COMMIT={commit}
ACTUAL_COMMIT=$(git rev-parse HEAD)
if [ "${{ACTUAL_COMMIT}}" != "${{EXPECTED_COMMIT}}" ]; then
  echo "Commit mismatch: expected ${{EXPECTED_COMMIT}}, found ${{ACTUAL_COMMIT}}" >&2
  exit 42
fi
RUN_TMP="/tmp/${{USER}}_mot2d_sensi_${{PBS_JOBID}}_${{PBS_ARRAY_INDEX:-0}}"
mkdir -p "${{RUN_TMP}}"
export TMPDIR="${{RUN_TMP}}" TMP="${{RUN_TMP}}" TEMP="${{RUN_TMP}}"
trap 'rm -rf -- "${{RUN_TMP}}"' EXIT
{command}
'''.encode()
    updated = deepcopy(manifest)
    updated["stage"] = "sensitivity"
    updated.setdefault("stages", {})["sensitivity"] = {
        "tasks": len(tasks),
        "job_file": f"{argument}/jobs/05_sensitivity.pbs",
    }
    return {
        "winners.json": (json.dumps(winners, indent=2, sort_keys=True) + "\n").encode(),
        "sensitivity/tasks.json": (json.dumps(tasks, indent=2, sort_keys=True) + "\n").encode(),
        "jobs/05_sensitivity.pbs": _acceptance_pbs(manifest, "sensitivity", pbs),
        "campaign.json": (json.dumps(updated, indent=2, sort_keys=True) + "\n").encode(),
    }


def render_production_transition(
    manifest: dict[str, Any], destination: Path, repository_root: Path,
    confirmation_rows: list[dict[str, Any]],
    sensitivity_rows: list[dict[str, Any]],
) -> dict[str, bytes]:
    """Render the validated Sensitivity-to-Production transition exactly.

    This is deliberately a pure renderer.  Both the CLI and the UI use these
    bytes, so preparation cannot silently choose a different sealed point,
    seed registry, or Production job design.
    """
    _validate_acceptance_destination(manifest, destination, repository_root)
    from workflow_api.mot_2d_late_stage import derive_production_transition

    if not campaign_kind_matches(manifest) or manifest.get("stage") != "sensitivity":
        raise ValueError("Campaign is not awaiting Production preparation.")
    try:
        argument = destination.relative_to(repository_root).as_posix()
    except ValueError as error:
        raise ValueError("Campaign destination must be inside the repository.") from error
    if not argument.startswith("data/optimization/mot_2d/"):
        raise ValueError("Campaign destination is outside the canonical 2D-MOT location.")

    sensitivity, tasks = derive_production_transition(
        manifest, confirmation_rows, sensitivity_rows
    )
    return render_production_artifacts(manifest, destination, repository_root, sensitivity, tasks)


def render_production_artifacts(manifest, destination, repository_root, sensitivity, tasks):
    """Encode already validated canonical selection without recomputing statistics."""
    _validate_acceptance_destination(manifest, destination, repository_root)
    argument = destination.relative_to(repository_root).as_posix()
    if manifest.get("stage") != "sensitivity" or not argument.startswith("data/optimization/mot_2d/"):
        raise ValueError("Campaign is not awaiting Production preparation.")
    sealed = manifest["seed_roles"]["sealed_validation"]
    if len(sealed) != 20 or len(tasks) != 20 * len(manifest["s0_values"]):
        raise ValueError("Production must contain exactly 20 sealed ensembles per s0.")
    commit = manifest["provenance"]["git_commit"]
    command = (
        "python -m studies.mot_2d_s0_campaign production-task "
        f"--campaign {shlex.quote(argument)} --task-index $PBS_ARRAY_INDEX"
    )
    pbs = f'''#!/bin/bash
#PBS -N mot2d_produ
#PBS -q zeus_combined_q
#PBS -J 0-{len(tasks)-1}%4
#PBS -l select=1:ncpus=150:mem=64gb
#PBS -l walltime=12:00:00

set -euo pipefail
PROJECT_ROOT="${{HOME}}/ytterbium_lab_simulation_new"
cd -- "${{PROJECT_ROOT}}" || exit 1
module load SPACK/apps
module load gcc/14.1.0
module load python/3.14.2
source "${{HOME}}/venvs/atomsmltr/bin/activate"
EXPECTED_COMMIT={commit}
ACTUAL_COMMIT=$(git rev-parse HEAD)
if [ "${{ACTUAL_COMMIT}}" != "${{EXPECTED_COMMIT}}" ]; then
  echo "Commit mismatch: expected ${{EXPECTED_COMMIT}}, found ${{ACTUAL_COMMIT}}" >&2
  exit 42
fi
RUN_TMP="/tmp/${{USER}}_mot2d_produ_${{PBS_JOBID}}_${{PBS_ARRAY_INDEX:-0}}"
mkdir -p "${{RUN_TMP}}"
export TMPDIR="${{RUN_TMP}}" TMP="${{RUN_TMP}}" TEMP="${{RUN_TMP}}"
trap 'rm -rf -- "${{RUN_TMP}}"' EXIT
{command}
'''.encode()
    updated = deepcopy(manifest)
    updated["stage"] = "production"
    updated.setdefault("stages", {})["production"] = {
        "tasks": len(tasks),
        "job_file": f"{argument}/jobs/06_production.pbs",
    }
    encode = lambda value: (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    return {
        "sensitivity_summary.json": encode(sensitivity),
        "production/tasks.json": encode(tasks),
        "jobs/06_production.pbs": _acceptance_pbs(manifest, "production", pbs),
        "campaign.json": encode(updated),
    }


def render_finalization(
    manifest: dict[str, Any], destination: Path, repository_root: Path,
) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    """Validate sealed evidence and render canonical final artifacts."""
    _validate_acceptance_destination(manifest, destination, repository_root)
    from studies.mot_2d.production import build_summary
    from workflow_api.mot_2d_validation import (
        _expected_production_design,
        validated_sealed_production_outputs,
    )

    sensitivity, rows_by_s0 = validated_sealed_production_outputs(
        destination, manifest, repository_root
    )
    fixed = manifest["fixed_design"]
    target = float(fixed["target_95_half_width_fraction"])
    reporting = fixed["reporting_zeeman_survivors"]
    detuning_bounds = fixed["detuning_bounds_gamma"]
    radius_bounds = fixed["magnet_radius_bounds_m"]
    detuning_tolerance = float(fixed["detuning_resolution_gamma"]) / 2.0
    radius_tolerance = float(fixed["magnet_radius_resolution_m"]) / 2.0
    design = _expected_production_design(manifest)
    files: dict[str, bytes] = {}
    results: list[dict[str, Any]] = []
    public_results: list[dict[str, Any]] = []
    encode = lambda value: (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    for raw in manifest["s0_values"]:
        value = float(raw)
        key = f"s0_{value:.6f}".replace(".", "p")
        selection = sensitivity[key]["production_selection"]
        parameters = selection["parameters"]
        summary = build_summary(
            parameters=parameters, design=design, replicates=rows_by_s0[value],
            reporting_survivors=reporting,
            target_half_width_fraction=target,
        )
        files[f"production/{key}/summary.json"] = encode(summary)
        warnings: list[str] = []
        detuning = float(parameters["detuning_gamma"])
        radius = float(parameters["magnet_radius"])
        if abs(detuning - float(detuning_bounds[0])) <= detuning_tolerance:
            warnings.append("detuning_lower")
        if abs(detuning - float(detuning_bounds[1])) <= detuning_tolerance:
            warnings.append("detuning_upper")
        if abs(radius - float(radius_bounds[0])) <= radius_tolerance:
            warnings.append("radius_lower")
        if abs(radius - float(radius_bounds[1])) <= radius_tolerance:
            warnings.append("radius_upper")
        if not summary["stopping_rule_passes"]:
            warnings.append("target_95_prediction_half_width_not_met")
        if sensitivity[key]["robustness_status"] != "established":
            warnings.append("robust_operating_region_not_established")
        if sensitivity[key]["near_optimality_status"] != "established":
            warnings.append("epsilon_near_optimality_not_established")
        value_label = f"{value:.6f}".rstrip("0").rstrip(".")
        states_path = survivor_states_directory(manifest, destination, value)
        states = states_path.relative_to(repository_root).as_posix() if states_path.is_absolute() else states_path.as_posix()
        result = {
            "s0": raw, "recommended_parameters": parameters,
            "warnings": warnings, "sensitivity": sensitivity[key],
            "prediction": summary["prediction_for_10m_zeeman_survivors"],
            "target_uncertainty_passes": summary["stopping_rule_passes"],
            "survivor_states_directory": states,
        }
        results.append(result)
        public_results.append({
            "s0": raw, "n_ensembles": len(rows_by_s0[value]),
            "total_input": sum(int(row["n_input"]) for row in rows_by_s0[value]),
            "total_survivors": sum(int(row["captured"]) for row in rows_by_s0[value]),
            "recommended_parameters": parameters,
            "prediction": summary["prediction_for_10m_zeeman_survivors"],
            "target_uncertainty_passes": summary["stopping_rule_passes"],
            "robustness_status": sensitivity[key]["robustness_status"],
            "near_optimality_status": sensitivity[key]["near_optimality_status"],
            "warnings": warnings,
            "retention": "retained",
            "output_suitability": "acceptance_only" if validate_campaign_policy(manifest) else "eligible_as_3d_campaign_input",
        })
    report = {
        "kind": "mot_2d_ui_acceptance_final_report_v1" if validate_campaign_policy(manifest) else "mot_2d_s0_campaign_final_report",
        "always_returns_best_tested_result": True,
        "results": results,
    }
    if validate_campaign_policy(manifest):
        report["acceptance"] = deepcopy(manifest["acceptance"])
        report["suitability"] = "acceptance_only"
        report["banner"] = "TEST ONLY — UI acceptance; no scientific promotion"
    files["final_report.json"] = encode(report)
    updated = deepcopy(manifest)
    updated["stage"] = "complete"
    updated.setdefault("stages", {})["final_report"] = (
        destination.relative_to(repository_root) / "final_report.json"
    ).as_posix()
    files["campaign.json"] = encode(updated)
    return files, public_results


def plan_from_frozen_manifest(
    *, repository_root: Path, destination: Path, manifest: dict[str, Any]
) -> CampaignPlan:
    """Build the same atomic write plan for the canonical CLI and local UI."""
    snapshot = RepositorySnapshot(str(manifest["provenance"]["git_commit"]))
    frozen = [
        row for role in ROLE_SEEDS
        for row in manifest["input_ensembles"][role]
    ]
    source_payload = json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    source_fingerprint = hashlib.sha256(source_payload).hexdigest()
    files = render_campaign_files(manifest, destination, repository_root)
    plan_digest = hashlib.sha256(b"".join(name.encode() + b"\0" + data for name, data in sorted(files.items()))).hexdigest()
    semantic = hashlib.sha256(json.dumps({
        "s0": sorted(map(float, manifest["s0_values"])),
        "source": source_fingerprint,
        "model": manifest["provenance"]["physical_model_sha256"],
        "design": manifest["fixed_design"],
        **({"execution_checkout": manifest["execution_checkout"]} if "execution_checkout" in manifest else {}),    }, sort_keys=True).encode()).hexdigest()
    return CampaignPlan(
        str(manifest["name"]), destination.name, tuple(map(float, manifest["s0_values"])),
        "canonical-cli", destination, manifest, files, source_fingerprint,
        plan_digest, snapshot, semantic,
    )


def build_plan(repository_root: Path, *, name: str, slug: str, s0_values: list[Any], source: dict[str, Any], snapshot: RepositorySnapshot, acceptance_profile_id: str | None = None, execution_checkout: str | None = None) -> CampaignPlan:
    repository_root = repository_root.resolve(); name = name.strip()
    if not name or len(name) > 120: raise ValueError("Campaign name is required and must be at most 120 characters.")
    if not SLUG.fullmatch(slug): raise ValueError("Campaign folder is invalid.")
    values = normalize_s0(s0_values)
    destination = repository_root / "data/optimization/mot_2d" / ("ui_acceptance" if acceptance_profile_id else "") / slug
    if destination.exists() or destination.is_symlink(): raise FileExistsError("Campaign destination already exists.")
    source_path = repository_root / source["path"]
    frozen = inspect_source(source_path, repository_root, include_records=True, **({"acceptance_profile_id": acceptance_profile_id} if acceptance_profile_id else {}))
    if frozen["id"] != source["id"] or frozen["fingerprint"] != source["fingerprint"]:
        raise ValueError("Zeeman source changed after selection.")
    records = frozen.pop("records")
    by_seed = {row["zeeman_seed"]: row for row in records}
    model_hash, hashed_files = physical_model_hash(repository_root)
    manifest = build_manifest(
        name=name, s0_values=list(values), ensemble_directory=source["path"],
        zeeman_profile=frozen["profile"],
        frozen_inputs={role: [by_seed[seed] for seed in seeds] for role, seeds in ROLE_SEEDS.items()},
        git_commit=snapshot.commit, physical_model_sha256=model_hash,
        hashed_files=hashed_files, acceptance_profile_id=acceptance_profile_id, execution_checkout=execution_checkout,
    )
    files = render_campaign_files(manifest, destination, repository_root)
    plan_digest = hashlib.sha256(b"".join(name.encode() + b"\0" + data for name, data in sorted(files.items()))).hexdigest()
    semantic = hashlib.sha256(json.dumps({
        "s0": sorted(values), "source": source["fingerprint"],
        "model": model_hash, "design": manifest["fixed_design"],
        **({"execution_checkout": manifest["execution_checkout"]} if "execution_checkout" in manifest else {}),
    }, sort_keys=True).encode()).hexdigest()
    return CampaignPlan(name, slug, values, source["id"], destination, manifest, files, source["fingerprint"], plan_digest, snapshot, semantic)


def materialize(plan: CampaignPlan, precommit_validate: Any | None = None) -> None:
    parent = plan.destination.parent; parent.mkdir(parents=True, exist_ok=True)
    lock_paths = sorted({
        parent / f".{plan.semantic_fingerprint}.creation.lock",
        parent / f".{plan.slug}.destination.lock",
    }, key=lambda path: path.name)
    locks: list[tuple[Path, int]] = []
    temporary: Path | None = None
    try:
        for lock_path in lock_paths:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            locks.append((lock_path, descriptor))
        temporary = Path(tempfile.mkdtemp(prefix=f".{plan.slug}.creating-", dir=parent))
        for relative, content in plan.files.items():
            path = temporary / relative; path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o755 if path.suffix == ".pbs" else 0o644)
            with os.fdopen(descriptor, "wb") as stream: stream.write(content); stream.flush(); os.fsync(stream.fileno())
        for directory in (temporary / "jobs", temporary):
            descriptor = os.open(directory, os.O_RDONLY); os.fsync(descriptor); os.close(descriptor)
        if precommit_validate is not None: precommit_validate(temporary)
        if plan.destination.exists(): raise FileExistsError("Campaign destination already exists.")
        _rename_no_replace(temporary, plan.destination)
        try:
            descriptor = os.open(parent, os.O_RDONLY); os.fsync(descriptor); os.close(descriptor)
        except OSError:
            # Publication already succeeded atomically. A retry must observe
            # the exact published plan rather than reporting a false failure.
            pass
    except Exception:
        if temporary is not None and temporary.exists(): shutil.rmtree(temporary)
        raise
    finally:
        for lock_path, descriptor in reversed(locks):
            os.close(descriptor)
            try: lock_path.unlink()
            except FileNotFoundError: pass


def _rename_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without ever replacing a destination."""
    if sys.platform == "win32":
        os.rename(source, destination)
        return
    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source); destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin":
        function = library.renamex_np
        function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        result = function(source_bytes, destination_bytes, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        function = library.renameat2
        function.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        result = function(-100, source_bytes, -100, destination_bytes, 1)  # RENAME_NOREPLACE
    else:
        raise RuntimeError("Atomic no-replace publication is unsupported on this platform.")
    if result != 0:
        error = ctypes.get_errno()
        if error in {17, 39, 66}:  # EEXIST / ENOTEMPTY platform variants
            raise FileExistsError("Campaign destination already exists.")
        raise OSError(error, os.strerror(error), str(destination))


def _acceptance_pbs(manifest: dict[str, Any], stage: str, rendered: bytes) -> bytes:
    """Apply authenticated resources to the normal stage renderer's PBS header."""
    profile = validate_campaign_policy(manifest)
    if profile is None:
        from workflow_api.campaign_deployment import render_normal_deployment
        return render_normal_deployment(manifest, rendered)
    policy = profile.stage('mot_2d', stage)
    seconds = policy['walltime_seconds']
    walltime = f'{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'
    text = rendered.decode('utf-8')
    vnode = profile.policy.get('scheduler', {}).get('vnode')
    placement = f':vnode={vnode}' if vnode else ''
    text = re.sub(r'^#PBS -l select=1:ncpus=\d+:mem=\d+gb$',
                  f"#PBS -l select=1:ncpus={policy['ncpus']}:mem={policy['memory_gb']}gb{placement}", text, flags=re.M)
    text = re.sub(r'^#PBS -l walltime=\S+$', f'#PBS -l walltime={walltime}', text, flags=re.M)
    # A dedicated checkout is mandatory; submission still owns the configured target.
    text = text.replace('${HOME}/ytterbium_lab_simulation_new', '${HOME}/ytterbium_lab_simulation_ui_acceptance')
    text = text.replace('${HOME}/venvs/atomsmltr/bin/activate', '${HOME}/venvs/atomsmltr-ui-test/bin/activate')
    return text.encode('utf-8')


def _validate_acceptance_destination(manifest, destination, repository_root):
    profile = validate_campaign_policy(manifest)
    if profile:
        from workflow_api.acceptance_profile import assert_acceptance_path
        assert_acceptance_path(destination, repository_root)
        assert_acceptance_path(manifest['ensemble_source']['directory'], repository_root)


PRODUCTION_PLAN_SOURCE_KEYS = frozenset({
    "campaign", "commit", "sensitivity_files", "sensitivity_transition_nonce",
    "sensitivity_transition_digest", "sensitivity_submission_key",
    "sensitivity_submission_nonce", "sensitivity_job_id",
})


def encode_production_plan(payload, rendered, confirmation_rows, sensitivity_rows):
    """Closed byte plan produced only by the canonical remote renderer."""
    import base64
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    if set(rendered) != {"sensitivity_summary.json", "production/tasks.json", "jobs/06_production.pbs", "campaign.json"}:
        raise ValueError("Invalid Production plan registry")
    return {
        "version": 1,
        "source_digest": digest({key: payload[key] for key in PRODUCTION_PLAN_SOURCE_KEYS}),
        "confirmation_rows_digest": digest(confirmation_rows),
        "sensitivity_rows_digest": digest(sensitivity_rows),
        "files": {name: {"sha256": hashlib.sha256(raw).hexdigest(), "base64": base64.b64encode(raw).decode("ascii")}
                  for name, raw in rendered.items()},
    }
