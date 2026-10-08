"""Read-only adapter for fixed-s0 2D-MOT campaign manifests."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from workflow_api.models import (
    ArtifactRef,
    CampaignSummary,
    JobPlan,
    StageProgress,
)
from workflow_api.safe_json import read_json

SUPPORTED_KIND = "mot_2d_s0_campaign"
SUPPORTED_STAGES = {
    "smoke",
    "screen",
    "refine",
    "confirmation",
    "sensitivity",
    "production",
    "complete",
}


def _manifest_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate / "campaign.json" if candidate.is_dir() else candidate


def _read_json(path: Path) -> Any:
    return read_json(path)


def _count_files(root: Path, pattern: str) -> int:
    return sum(1 for path in root.glob(pattern) if path.is_file())


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _s0_values(value: Any) -> tuple[float, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("Campaign field 's0_values' must be a list of numbers.")
    result: list[float] = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Campaign field 's0_values' must contain only numbers."
            ) from error
        if not math.isfinite(number) or number <= 0:
            raise ValueError(
                "Campaign field 's0_values' must contain finite positive values."
            )
        result.append(number)
    return tuple(result)


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


def _contains_symlink(path: Path, root: Path) -> bool:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return True
    current = root.absolute()
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _resolve_artifact(campaign_root: Path, recorded_path: str | Path) -> Path | None:
    path = Path(recorded_path)
    repository_root = _repository_root(campaign_root)
    allowed_roots = (campaign_root.resolve(),)
    if repository_root is not None:
        allowed_roots += (repository_root.resolve(),)
    if path.is_absolute():
        resolved = path.resolve()
        return resolved if any(_within(resolved, root) and not _contains_symlink(path, root) for root in allowed_roots) else None
    if repository_root is not None:
        repository_path = (repository_root / path).resolve()
        campaign_path = (campaign_root / path).resolve()
        if _within(repository_path, repository_root.resolve()) and not _contains_symlink(repository_root / path, repository_root) and (
            repository_path.exists() or not campaign_path.exists()
        ):
            return repository_path
        if _within(campaign_path, campaign_root.resolve()) and not _contains_symlink(campaign_root / path, campaign_root):
            return campaign_path
        return None
    resolved = (campaign_root / path).resolve()
    return resolved if _within(resolved, campaign_root.resolve()) and not _contains_symlink(campaign_root / path, campaign_root) else None


def _stage_progress(root: Path, manifest: dict[str, Any]) -> tuple[StageProgress, ...]:
    rows: list[StageProgress] = []
    stages = _mapping(manifest.get("stages"))

    smoke_expected = len(manifest.get("s0_values", []))
    smoke_completed = _count_files(root / "smoke", "s0_*/summary.json")
    if smoke_expected or smoke_completed:
        rows.append(_progress("smoke", smoke_completed, smoke_expected))

    for stage in ("screen", "refine", "confirmation", "sensitivity"):
        record = stages.get(stage)
        stage_root = root / stage
        if record is None and not stage_root.exists():
            continue
        tasks = _mapping(record).get("tasks")
        fixed_design = _mapping(manifest.get("fixed_design"))
        trial_budgets = _mapping(fixed_design.get("trial_budgets"))
        if stage == "screen":
            per_task = trial_budgets.get("screen_per_worker")
            completed = _count_files(stage_root, "s0_*/worker*/trials/trial_*.json")
            expected = tasks * per_task if tasks is not None and per_task else None
        elif stage == "refine":
            per_task = trial_budgets.get("refine_per_worker")
            completed = _count_files(stage_root, "s0_*/worker*/trials/trial_*.json")
            expected = tasks * per_task if tasks is not None and per_task else None
        else:
            completed = _count_files(stage_root, "s0_*/point_*.json")
            expected = tasks
        rows.append(_progress(stage, completed, expected))

    if "production" in stages or (root / "production").exists():
        completed = _count_files(
            root / "production", "s0_*/replicates/zeeman_seed*.json"
        )
        expected = _mapping(stages.get("production")).get("tasks")
        rows.append(_progress("production", completed, expected))
    return tuple(rows)


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


def _next_plan(
    root: Path, manifest: dict[str, Any]
) -> tuple[JobPlan | None, tuple[str, ...]]:
    stage = manifest.get("stage")
    if stage == "complete":
        return None, ()
    if stage not in SUPPORTED_STAGES:
        return None, ("Campaign stage is unknown; no next action is available.",)
    stages = _mapping(manifest.get("stages"))
    stage_record = _mapping(stages.get(stage))
    if stage_record.get("submit_chain"):
        chain = _resolve_artifact(root, stage_record["submit_chain"])
        resolved_jobs = tuple(
            _resolve_artifact(root, item) for item in stage_record.get("round_job_files", [])
        )
        if chain is None or any(item is None for item in resolved_jobs):
            return None, ("A recorded job artifact is outside the trusted repository.",)
        round_jobs = tuple(
            ArtifactRef(item, "pbs", item.exists()) for item in resolved_jobs if item is not None
        )
        artifacts = (ArtifactRef(chain, "submission-script", chain.exists()), *round_jobs)
        warnings = () if all(item.exists for item in artifacts) else (
            "One or more recorded refinement job artifacts are missing locally.",
        )
        return (
            JobPlan(
                label=f"Submit {stage} dependency chain",
                command=("bash", str(chain)),
                artifacts=artifacts,
                submission_enabled=False,
            ),
            warnings,
        )
    recorded_job = stage_record.get("job_file")
    if recorded_job:
        job = _resolve_artifact(root, recorded_job)
        if job is None:
            return None, ("The recorded job artifact is outside the trusted repository.",)
        warning = () if job.exists() else (
            "The recorded next-job artifact is missing locally.",
        )
        return (
            JobPlan(
                label=f"Submit {stage} job",
                command=("qsub", str(job)),
                artifacts=(ArtifactRef(job, "pbs", job.exists()),),
                submission_enabled=False,
            ),
            warning,
        )
    if stage == "smoke":
        job = (root / "jobs" / "01_smoke.pbs").resolve()
        if job.exists():
            return (
                JobPlan(
                    label="Submit smoke job",
                    command=("qsub", str(job)),
                    artifacts=(ArtifactRef(job, "pbs", True),),
                    submission_enabled=False,
                ),
                (),
            )
    return None, ("Current stage has no recorded job artifact; no action was inferred.",)


def read_campaign(path: str | Path, *, manifest: dict[str, Any] | None = None) -> CampaignSummary:
    """Read a campaign without changing its files or importing submit modules."""
    manifest_path = _manifest_path(path)
    manifest = _read_json(manifest_path) if manifest is None else manifest
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
    elif stage not in SUPPORTED_STAGES:
        warnings.append("Campaign manifest records an unsupported current stage.")
    s0_values = _s0_values(manifest.get("s0_values"))
    normalized_manifest = {**manifest, "name": name, "stage": stage, "s0_values": s0_values}
    provenance = _mapping(manifest.get("provenance"))
    ensemble_source = _mapping(manifest.get("ensemble_source"))
    if not provenance.get("git_commit"):
        warnings.append("Campaign manifest does not record a pinned Git revision.")
    if not ensemble_source.get("zeeman_profile"):
        warnings.append("Campaign manifest does not record a Zeeman profile.")
    plan, plan_warnings = _next_plan(root, normalized_manifest)
    warnings.extend(plan_warnings)
    return CampaignSummary(
        kind=manifest["kind"],
        name=name,
        root=root,
        stage=stage,
        s0_values=s0_values,
        git_commit=provenance.get("git_commit"),
        zeeman_profile=ensemble_source.get("zeeman_profile"),
        progress=_stage_progress(root, normalized_manifest),
        next_plan=plan,
        warnings=tuple(warnings),
    )
