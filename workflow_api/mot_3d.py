"""Read-only adapter for canonical 3D-MOT campaign manifests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from workflow_api.models import (
    ArtifactRef,
    JobPlan,
    Mot3dCampaignSummary,
    StageProgress,
)
from workflow_api.safe_json import read_json

SUPPORTED_KIND = "mot_3d_campaign_v2"
SELECTION_STAGES = (
    "preliminary_check",
    "refinement",
    "closure",
    "finalist_selection",
)


def _manifest_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate / "campaign.json" if candidate.is_dir() else candidate


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _progress(stage: str, completed: int, expected: int | None) -> StageProgress:
    if expected is None:
        status = "unknown"
    elif completed == 0:
        status = "not-started"
    elif completed < expected:
        status = "in-progress"
    elif completed == expected:
        status = "complete"
    else:
        status = "inconsistent"
    return StageProgress(stage, completed, expected, status)


def _count(root: Path, pattern: str) -> int:
    return sum(1 for path in root.glob(pattern) if path.is_file())


def _valid_json(path: Path, expected: dict[str, Any]) -> bool:
    try:
        payload = _mapping(read_json(path))
    except (OSError, ValueError, TypeError):
        return False
    return all(payload.get(key) == value for key, value in expected.items())


def _valid_discovery_trial(path: Path, family: str) -> bool:
    try:
        worker_index = int(path.parent.parent.name.removeprefix("worker_"))
        trial_number = int(path.stem.removeprefix("trial_"))
    except ValueError:
        return False
    return _valid_json(
        path,
        {
            "kind": "mot_3d_full_optuna_trial",
            "family": family,
            "worker_index": worker_index,
            "trial_number": trial_number,
        },
    )


def _repository_root(campaign_root: Path) -> Path | None:
    for candidate in (campaign_root, *campaign_root.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_artifact(
    campaign_root: Path, recorded_path: str | Path
) -> Path | None:
    path = Path(recorded_path)
    repository_root = _repository_root(campaign_root)
    allowed_roots = (campaign_root.resolve(),)
    if repository_root is not None:
        allowed_roots += (repository_root.resolve(),)
    if path.is_absolute():
        resolved = path.resolve()
        return resolved if any(_within(resolved, root) for root in allowed_roots) else None
    if repository_root is not None:
        repository_path = (repository_root / path).resolve()
        campaign_path = (campaign_root / path).resolve()
        if _within(repository_path, repository_root.resolve()) and (
            repository_path.exists() or not campaign_path.exists()
        ):
            return repository_path
        if _within(campaign_path, campaign_root.resolve()):
            return campaign_path
        return None
    resolved = (campaign_root / path).resolve()
    return resolved if _within(resolved, campaign_root.resolve()) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestep_validation(
    root: Path, manifest: dict[str, Any]
) -> tuple[bool, tuple[str, ...]]:
    design = _mapping(manifest.get("design"))
    evidence = _mapping(design.get("timestep_evidence"))
    if design.get("timestep_status") != "approved_by_paired_convergence_validation":
        return False, ()
    recorded_path = evidence.get("path")
    recorded_sha = evidence.get("sha256")
    path = _resolve_artifact(root, recorded_path) if recorded_path else None
    if path is None:
        return False, ("Approved timestep evidence path is outside the trusted repository.",)
    if not path.is_file():
        return False, ("Approved timestep evidence file is missing locally.",)
    if not recorded_sha or _sha256(path) != recorded_sha:
        return False, ("Approved timestep evidence hash does not match its frozen record.",)
    return True, ()


def _stage_progress(
    root: Path, manifest: dict[str, Any], timestep_approved: bool
) -> tuple[StageProgress, ...]:
    rows: list[StageProgress] = []
    stage = manifest.get("stage")
    design = _mapping(manifest.get("design"))
    bounds = _mapping(design.get("optimization_bounds"))
    families = tuple(design.get("families") or ())

    rows.append(_progress("dt_validation", int(timestep_approved), 1))

    expected_discovery = 0
    for family in families:
        expected_discovery += int(
            _mapping(bounds.get(family)).get("total_discovery_trials") or 0
        )
    completed_discovery = sum(
        _valid_discovery_trial(path, family)
        for family in families
        for path in (root / "discovery" / family).glob(
            "worker_*/trials/trial_*.json"
        )
    )
    if expected_discovery or completed_discovery or stage != "dt_validation_required":
        rows.append(
            _progress(
                "discovery",
                completed_discovery,
                expected_discovery or None,
            )
        )

    summary_designs = {
        "preliminary_check": (
            "early_check_summary.json",
            "merged_mot_3d_early_independent_check",
        ),
        "refinement": (
            "refinement_summary.json",
            "merged_mot_3d_focused_refinement",
        ),
        "closure": (
            "refinement_summary.json",
            "merged_mot_3d_focused_refinement",
        ),
        "finalist_selection": (
            "finalist_summary.json",
            "merged_mot_3d_finalist_selection",
        ),
    }
    stages = _mapping(manifest.get("stages"))
    for stage_name, (summary_name, expected_kind) in summary_designs.items():
        if stage_name not in stages and not (root / stage_name).exists():
            continue
        completed = sum(
            _valid_json(
                root / stage_name / family / "merged" / summary_name,
                {"kind": expected_kind, "family": family},
            )
            for family in families
        )
        rows.append(_progress(stage_name, completed, len(families) or None))

    input_stage = _mapping(stages.get("final_validation_input_generation"))
    if input_stage or (root / "final_validation_inputs").exists():
        recorded_manifest = input_stage.get("input_manifest")
        input_manifest = (
            _resolve_artifact(root, recorded_manifest)
            if recorded_manifest
            else None
        )
        completed = 0
        if input_manifest is not None and input_manifest.is_file():
            try:
                payload = _mapping(read_json(input_manifest))
                ensembles = payload.get("ensembles", [])
                expected_seeds = input_stage.get("zeeman_seeds", [])
                if (
                    payload.get("kind") == "mot_3d_final_validation_inputs"
                    and isinstance(ensembles, list)
                    and [row.get("zeeman_seed") for row in ensembles] == expected_seeds
                ):
                    completed = len(ensembles)
            except (OSError, ValueError, TypeError):
                completed = 0
        expected = len(input_stage.get("zeeman_seeds", [])) or None
        rows.append(_progress("final_validation_inputs", completed, expected))

    if "final_validation" in stages or (root / "final_validation").exists():
        completed = sum(
            _valid_json(
                root / "final_validation" / family / "final_validation_summary.json",
                {"kind": "mot_3d_sealed_final_validation_summary", "family": family},
            )
            for family in families
        )
        rows.append(_progress("final_validation", completed, len(families) or None))
    return tuple(rows)


def _artifacts(
    root: Path, paths: list[str] | tuple[str, ...], kind: str
) -> tuple[tuple[ArtifactRef, ...], tuple[str, ...]]:
    resolved = tuple(_resolve_artifact(root, path) for path in paths)
    artifacts = tuple(
        ArtifactRef(path, kind, path.is_file())
        for path in resolved
        if path is not None
    )
    warnings = () if len(artifacts) == len(paths) else (
        "One or more recorded artifact paths are outside the trusted repository.",
    )
    return artifacts, warnings


def _submission_state(
    path: Path, *, expected_kind: str, expected_stage: str | None = None
) -> tuple[str | None, tuple[str, ...]]:
    if not path.is_file():
        return None, ()
    try:
        record = _mapping(read_json(path))
    except (OSError, ValueError, TypeError):
        return "invalid", ("Submission record is unreadable or invalid; recovery is required.",)
    status = record.get("status")
    if record.get("kind") != expected_kind or (
        expected_stage is not None and record.get("stage") != expected_stage
    ):
        return "invalid", (
            "Submission record identity does not match the current campaign stage.",
        )
    if status not in ("submitting", "submitted", "partial_failure"):
        return "invalid", ("Submission record has an unknown status; recovery is required.",)
    return status, ()


def _stage_is_complete(progress: tuple[StageProgress, ...], name: str) -> bool:
    return any(row.stage == name and row.status == "complete" for row in progress)


def _next_plan(
    root: Path,
    manifest: dict[str, Any],
    progress: tuple[StageProgress, ...],
) -> tuple[JobPlan | None, tuple[str, ...]]:
    stage = manifest.get("stage")
    if stage == "complete":
        return None, ()
    if stage == "dt_validation_required":
        return None, (
            "Paired 3D timestep validation must be approved before discovery can be submitted.",
        )
    if stage == "final_validation_extension_required":
        status_path = _mapping(manifest.get("stages")).get("final_validation_status")
        warnings = [
            "The final precision target was not met; an approved extension or new-campaign decision is required."
        ]
        if status_path and _resolve_artifact(root, status_path) is None:
            warnings.append("The recorded final-validation status path is outside the trusted repository.")
        return None, tuple(warnings)
    command_base = ("python", "-m", "studies.mot_3d_campaign")
    submission_name = (
        "discovery_submission.json"
        if stage == "discovery"
        else "final_validation_input_generation_submission.json"
        if stage == "final_validation_input_generation"
        else f"{stage}_submission.json"
    )
    expected_submission_kind = (
        "mot_3d_discovery_submission"
        if stage == "discovery"
        else "mot_3d_final_validation_input_submission"
        if stage == "final_validation_input_generation"
        else "mot_3d_selection_stage_submission"
    )
    expected_submission_stage = (
        stage
        if stage in SELECTION_STAGES or stage == "final_validation"
        else None
    )
    submission_status, submission_warnings = _submission_state(
        root / submission_name,
        expected_kind=expected_submission_kind,
        expected_stage=expected_submission_stage,
    )
    if submission_warnings:
        return None, submission_warnings
    progress_name = (
        "final_validation_inputs"
        if stage == "final_validation_input_generation"
        else stage
    )
    if submission_status == "submitted":
        if _stage_is_complete(progress, progress_name):
            return (
                JobPlan(
                    f"Advance completed {stage.replace('_', ' ')} stage",
                    (*command_base, "advance", "--campaign", str(root)),
                    (),
                    False,
                ),
                (),
            )
        return None, (
            f"The {stage.replace('_', ' ')} stage was submitted and is not complete; monitor its jobs and outputs.",
        )
    if submission_status == "submitting":
        return None, ("Submission is still being recorded; do not submit the stage again.",)
    if submission_status == "partial_failure":
        return None, ("Submission failed partially; explicit recovery is required before continuing.",)
    if submission_status == "invalid":
        return None, ("Submission record is invalid; explicit recovery is required.",)
    if stage == "discovery":
        chain = _mapping(manifest.get("jobs")).get("discovery_submit_chain")
        if not chain:
            return None, ("Discovery has no recorded submission chain.",)
        artifacts, path_warnings = _artifacts(root, [chain], "submission-script")
        plan = JobPlan(
            "Submit discovery dependency chain",
            (*command_base, "submit-discovery", "--campaign", str(root)),
            artifacts,
            False,
        )
    elif stage in SELECTION_STAGES or stage == "final_validation":
        record = _mapping(_mapping(manifest.get("stages")).get(stage))
        families = tuple(_mapping(manifest.get("design")).get("families") or ())
        worker_jobs = _mapping(record.get("worker_jobs"))
        merge_jobs = _mapping(record.get("merge_jobs"))
        if not families or set(worker_jobs) != set(families) or set(merge_jobs) != set(families):
            return None, (
                "The stage job registry is incomplete or does not match the frozen families.",
            )
        paths = [worker_jobs[family] for family in families] + [
            merge_jobs[family] for family in families
        ]
        artifacts, path_warnings = _artifacts(root, paths, "pbs")
        plan = JobPlan(
            f"Submit {stage.replace('_', ' ')} jobs",
            (*command_base, "submit-stage", "--campaign", str(root)),
            artifacts,
            False,
        )
    elif stage == "final_validation_input_generation":
        record = _mapping(
            _mapping(manifest.get("stages")).get("final_validation_input_generation")
        )
        paths = [
            record[key]
            for key in ("zeeman_job", "mot_job", "freeze_job")
            if record.get(key)
        ]
        if len(paths) != 3:
            return None, ("The final-input generation job registry is incomplete.",)
        artifacts, path_warnings = _artifacts(root, paths, "pbs")
        plan = JobPlan(
            "Submit sealed final-input generation chain",
            (*command_base, "submit-final-inputs", "--campaign", str(root)),
            artifacts,
            False,
        )
    else:
        return None, (f"Unsupported or unknown 3D campaign stage: {stage!r}.",)
    if path_warnings:
        return None, path_warnings
    if not artifacts or not all(item.exists for item in artifacts):
        return None, ("One or more recorded job artifacts are missing locally.",)
    return plan, ()


def read_campaign(path: str | Path, *, manifest: dict[str, Any] | None = None) -> Mot3dCampaignSummary:
    """Inspect a 3D campaign without importing simulation code or changing files."""
    manifest_path = _manifest_path(path)
    manifest = read_json(manifest_path) if manifest is None else manifest
    if manifest.get("kind") != SUPPORTED_KIND:
        raise ValueError(
            f"Unsupported campaign kind {manifest.get('kind')!r}; expected {SUPPORTED_KIND!r}."
        )
    root = manifest_path.parent.resolve()
    warnings: list[str] = []
    name = manifest.get("name")
    if not isinstance(name, str) or not name.strip():
        name = root.name
        warnings.append("Campaign manifest does not record a valid name.")
    stage = manifest.get("stage")
    if not isinstance(stage, str) or not stage.strip():
        stage = "unknown"
        warnings.append("Campaign manifest does not record a valid current stage.")
    provenance = _mapping(manifest.get("provenance"))
    if not provenance.get("git_commit"):
        warnings.append("Campaign manifest does not record a pinned Git revision.")
    design = _mapping(manifest.get("design"))
    families = tuple(design.get("families") or ())
    if not families:
        warnings.append("Campaign manifest does not record any 3D-MOT families.")
    upstream = _mapping(manifest.get("upstream_2d_campaign"))
    upstream_path = upstream.get("campaign_path") or upstream.get("path")
    if not upstream:
        warnings.append("Campaign manifest does not record its upstream 2D campaign.")
    normalized = {**manifest, "stage": stage}
    timestep_approved, timestep_warnings = _timestep_validation(root, normalized)
    warnings.extend(timestep_warnings)
    final_input_stage = _mapping(
        _mapping(normalized.get("stages")).get("final_validation_input_generation")
    )
    recorded_input_manifest = final_input_stage.get("input_manifest")
    if recorded_input_manifest and _resolve_artifact(root, recorded_input_manifest) is None:
        warnings.append(
            "The recorded final-input manifest path is outside the trusted repository."
        )
    progress = _stage_progress(root, normalized, timestep_approved)
    plan, plan_warnings = _next_plan(root, normalized, progress)
    warnings.extend(plan_warnings)
    return Mot3dCampaignSummary(
        kind=manifest["kind"],
        name=name,
        root=root,
        stage=stage,
        families=families,
        git_commit=provenance.get("git_commit"),
        upstream_2d_campaign=str(upstream_path) if upstream_path else None,
        progress=progress,
        next_plan=plan,
        warnings=tuple(warnings),
    )
