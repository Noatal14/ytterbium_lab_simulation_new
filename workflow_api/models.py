"""Serializable models shared by future CLI and UI adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WorkflowDescriptor:
    workflow_id: str
    label: str
    maturity: str
    entrypoint: str
    capabilities: tuple[str, ...]
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


@dataclass(frozen=True)
class ArtifactRef:
    path: Path
    kind: str
    exists: bool

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["schema_version"] = SCHEMA_VERSION
        result["path"] = str(self.path)
        return result


@dataclass(frozen=True)
class JobPlan:
    label: str
    command: tuple[str, ...]
    artifacts: tuple[ArtifactRef, ...] = ()
    submission_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["schema_version"] = SCHEMA_VERSION
        result["command"] = list(self.command)
        result["artifacts"] = [item.to_dict() for item in self.artifacts]
        return result


@dataclass(frozen=True)
class StageProgress:
    stage: str
    completed: int
    expected: int | None
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


@dataclass(frozen=True)
class CampaignSummary:
    kind: str
    name: str
    root: Path
    stage: str
    s0_values: tuple[float, ...]
    git_commit: str | None
    zeeman_profile: str | None
    progress: tuple[StageProgress, ...] = ()
    next_plan: JobPlan | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["schema_version"] = SCHEMA_VERSION
        result["root"] = str(self.root)
        result["s0_values"] = list(self.s0_values)
        result["progress"] = [item.to_dict() for item in self.progress]
        result["next_plan"] = self.next_plan.to_dict() if self.next_plan else None
        result["warnings"] = list(self.warnings)
        return result


@dataclass(frozen=True)
class Mot3dCampaignSummary:
    kind: str
    name: str
    root: Path
    stage: str
    families: tuple[str, ...]
    git_commit: str | None
    upstream_2d_campaign: str | None
    progress: tuple[StageProgress, ...] = ()
    next_plan: JobPlan | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["schema_version"] = SCHEMA_VERSION
        result["root"] = str(self.root)
        result["families"] = list(self.families)
        result["progress"] = [item.to_dict() for item in self.progress]
        result["next_plan"] = self.next_plan.to_dict() if self.next_plan else None
        result["warnings"] = list(self.warnings)
        return result
