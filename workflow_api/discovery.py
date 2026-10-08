"""Bounded, allowlisted discovery for local campaign inspection."""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workflow_api.mot_2d import read_campaign as read_2d_campaign
from workflow_api.mot_3d import read_campaign as read_3d_campaign
from workflow_api.mot_2d_validation import (
    modern_contract,
    sealed_final_is_valid,
    validated_progress,
)

MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_CAMPAIGNS_PER_KIND = 250
ROOTS = {
    "mot_2d": Path("data/optimization/mot_2d"),
    "mot_3d": Path("data/optimization/mot_3d"),
}
SUPPORTED_KINDS = {
    "mot_2d": "mot_2d_s0_campaign",
    "mot_3d": "mot_3d_campaign_v2",
}


class DiscoveryError(Exception):
    """A safe, client-facing discovery error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RegistryEntry:
    campaign_id: str
    family: str
    manifest: Path
    relative_root: Path


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _read_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise DiscoveryError("invalid_manifest", "Campaign record is not a trusted regular file.")
    try:
        size = path.stat().st_size
    except OSError as error:
        raise DiscoveryError("unavailable_manifest", "Campaign record is unavailable.") from error
    if size > MAX_MANIFEST_BYTES:
        raise DiscoveryError("oversized_manifest", "Campaign record is too large to inspect safely.")
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise DiscoveryError("oversized_manifest", "Campaign record is too large to inspect safely.")
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise DiscoveryError("invalid_manifest", "Campaign record is not valid JSON.") from error
    if not isinstance(payload, dict):
        raise DiscoveryError("invalid_manifest", "Campaign record must contain a JSON object.")
    return payload


def _identifier(family: str, relative_root: Path) -> str:
    digest = hashlib.sha256(f"{family}:{relative_root.as_posix()}".encode()).hexdigest()[:20]
    return f"{family}-{digest}"


def build_registry(repository_root: Path) -> dict[str, RegistryEntry]:
    repository_root = repository_root.resolve()
    registry: dict[str, RegistryEntry] = {}
    for family, relative in ROOTS.items():
        discovery_root = (repository_root / relative).resolve()
        if not _within(discovery_root, repository_root) or not discovery_root.is_dir():
            continue
        count = 0
        for directory in discovery_root.iterdir():
            if count >= MAX_CAMPAIGNS_PER_KIND:
                break
            if directory.is_symlink() or not directory.is_dir():
                continue
            manifest = directory / "campaign.json"
            if not manifest.is_file() or manifest.is_symlink():
                continue
            resolved = manifest.resolve()
            if not _within(resolved, discovery_root):
                continue
            relative_root = directory.resolve().relative_to(repository_root)
            campaign_id = _identifier(family, relative_root)
            registry[campaign_id] = RegistryEntry(campaign_id, family, resolved, relative_root)
            count += 1
    return registry


def _warning(text: str, severity: str = "attention") -> dict[str, str]:
    return {"severity": severity, "message": text}


def _modern_3d_contract(payload: dict[str, Any], progress: list[dict[str, Any]]) -> tuple[bool, tuple[str, ...]]:
    errors: list[str] = []
    provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
    design = payload.get("design") if isinstance(payload.get("design"), dict) else {}
    upstream = payload.get("upstream_2d_campaign") if isinstance(payload.get("upstream_2d_campaign"), dict) else {}
    roles = payload.get("input_roles") if isinstance(payload.get("input_roles"), dict) else {}
    if not provenance.get("git_commit") or len(str(provenance.get("physical_model_sha256", ""))) != 64:
        errors.append("3D immutable code and physical-model provenance is incomplete")
    required_design = ("families", "solver", "screening_dt_s", "production_dt_s", "timestep_status", "optimization_bounds", "selection_statistics")
    if any(key not in design for key in required_design) or design.get("solver") != "RK4StHybridCustom":
        errors.append("3D scientific design is incomplete")
    families = design.get("families")
    if not isinstance(families, list) or not all(isinstance(item, str) for item in families) or set(families) != {"angled_donut", "single_pass"}:
        errors.append("3D geometry registry is incomplete")
    required_upstream = ("campaign_path", "campaign_sha256", "final_report_path", "final_report_sha256", "sealed_seed_pairs", "expected_survivor_design", "expected_survivor_parameters")
    if any(not upstream.get(key) for key in required_upstream):
        errors.append("validated upstream 2D handoff is incomplete")
    if not roles or any(not isinstance(records, list) or not records for records in roles.values()):
        errors.append("frozen 3D input roles are incomplete")
    else:
        for records in roles.values():
            for record in records:
                if not isinstance(record, dict) or any(record.get(key) is None for key in ("path", "metadata_path", "sha256", "metadata_sha256", "shape", "dtype", "zeeman_seed", "mot_seed", "source_design", "source_parameters")):
                    errors.append("frozen 3D input record is incomplete")
                    break
    if payload.get("stage") != "dt_validation_required":
        dt_row = next((row for row in progress if row.get("stage") == "dt_validation"), None)
        if not dt_row or dt_row.get("status") != "complete":
            errors.append("approved paired timestep evidence is unavailable")
    # The canonical 3D manifest freezes upstream reports and every survivor
    # ensemble. Milestone 2 does not yet revalidate that complete cross-file
    # chain, so it must not grant continuation trust from structural checks.
    errors.append("full frozen 3D upstream and input artifact validation is not available in this milestone")
    return not errors, tuple(dict.fromkeys(errors))


def _role(kind: str, stage: str, sealed_final: bool, trusted: bool) -> str:
    if not trusted:
        return "historical-evidence"
    if kind == "mot_2d_s0_campaign":
        return "sealed-final-validation" if sealed_final else "candidate-selection"
    return "sealed-final-validation" if sealed_final else "candidate-selection"


def _safe_plan(plan: dict[str, Any] | None, repository_root: Path) -> dict[str, Any] | None:
    if not plan:
        return None
    command: list[str] = []
    for token in plan.get("command", []):
        candidate = Path(token)
        if candidate.is_absolute():
            try:
                token = candidate.resolve().relative_to(repository_root).as_posix()
            except ValueError:
                return None
        command.append(token)
    return {
        "label": plan.get("label", "Copy next command"),
        "command": command,
        "mode": "copy-only",
        "scheduler_status": "unchecked",
        "operation_scope": "remote-submission" if command and command[0] in {"qsub", "bash"} else "local-mutation",
        "executes_automatically": False,
        "display_command": shlex.join(command),
    }


def _progress_aware_plan(
    summary: dict[str, Any], progress: list[dict[str, Any]], root: Path, repository_root: Path
) -> dict[str, Any] | None:
    stage = summary.get("stage")
    if stage == "complete":
        return None
    row = next((item for item in progress if item.get("stage") == stage), None)
    if row and row.get("status") == "inconsistent":
        return None
    if row and row.get("status") == "in-progress":
        return None
    if row and row.get("status") == "complete":
        relative = root.relative_to(repository_root).as_posix()
        command = ["python", "-m", "studies.mot_2d_s0_campaign", "advance", "--campaign", relative]
        return {
            "label": f"Advance validated {str(stage).replace('_', ' ')} stage",
            "command": command,
            "mode": "copy-only",
            "scheduler_status": "unchecked",
            "operation_scope": "local-mutation",
            "executes_automatically": False,
            "display_command": shlex.join(command),
        }
    return _safe_plan(summary.get("next_plan"), repository_root)


def inspect_entry(entry: RegistryEntry, repository_root: Path) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    payload = _read_manifest(entry.manifest)
    expected_kind = SUPPORTED_KINDS[entry.family]
    if payload.get("kind") != expected_kind:
        raise DiscoveryError("unsupported_campaign", "Campaign record has an unsupported workflow kind.")
    try:
        reader = read_2d_campaign if entry.family == "mot_2d" else read_3d_campaign
        summary = reader(entry.manifest, manifest=payload).to_dict()
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise DiscoveryError("invalid_campaign", "Campaign files could not be validated for inspection.") from error
    raw_warnings = [str(item) for item in summary.get("warnings", [])]
    contract_errors: tuple[str, ...] = ()
    sealed_final = False
    if summary["kind"] == "mot_2d_s0_campaign":
        contract_ok, contract_errors = modern_contract(payload, repository_root)
        try:
            validated = validated_progress(entry.manifest.parent, payload) if contract_ok else ()
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            validated = ()
            contract_ok = False
            contract_errors = (*contract_errors, "local outputs could not be validated")
        progress = [row.to_dict() for row in validated]
        sealed_final = contract_ok and sealed_final_is_valid(
            entry.manifest.parent, payload, validated, repository_root
        )
    else:
        progress = list(summary.get("progress", []))
        contract_ok, contract_errors = _modern_3d_contract(payload, progress)
        sealed_final = any(row.get("stage") == "final_validation" and row.get("status") == "complete" for row in progress) and summary.get("stage") == "complete"
        if not contract_ok:
            progress = []
            sealed_final = False
    inconsistent = any(row.get("status") in ("unknown", "inconsistent") for row in progress)
    trust = "trusted-current" if contract_ok and not inconsistent else "legacy-incomplete"
    raw_warnings.extend(f"Modern campaign contract check failed: {error}." for error in contract_errors)
    warnings = [_warning(item) for item in raw_warnings]
    current_progress = next((row for row in progress if row.get("stage") == summary.get("stage")), None)
    if trust == "trusted-current" and current_progress and current_progress.get("status") == "in-progress":
        warnings.append(_warning(
            "Validated local outputs are partial. No submission command is shown because scheduler state is not checked; verify the existing job externally.",
            "info",
        ))
    if trust != "trusted-current":
        warnings.insert(0, _warning("This campaign is incomplete or uses an older record format. Inspect it only; do not continue from this view.", "blocked"))
    safe_plan = _progress_aware_plan(summary, progress, entry.manifest.parent, repository_root) if trust == "trusted-current" and not raw_warnings else None
    if safe_plan:
        message = (
            "Scheduler state is not checked. This command is shown for review and copying only."
            if safe_plan["operation_scope"] == "remote-submission"
            else "This local state-changing command is shown for review and copying only; the application will not run it."
        )
        warnings.append(_warning(message, "info"))
    return {
        "id": entry.campaign_id,
        "family": entry.family,
        "kind": summary["kind"],
        "name": summary["name"],
        "path": entry.relative_root.as_posix(),
        "stage": summary["stage"],
        "stage_semantics": "prepared-workflow-stage",
        "scheduler_status": "unchecked",
        "trust": trust,
        "scientific_role": _role(summary["kind"], summary["stage"], sealed_final, trust == "trusted-current"),
        "progress": progress,
        "warnings": warnings,
        "next_plan": safe_plan,
        "s0_values": summary.get("s0_values", []),
        "families": summary.get("families", []),
        "git_commit": summary.get("git_commit"),
    }


def list_campaigns(repository_root: Path) -> dict[str, Any]:
    campaigns: list[dict[str, Any]] = []
    invalid_count = 0
    for entry in build_registry(repository_root).values():
        try:
            campaigns.append(inspect_entry(entry, repository_root))
        except (DiscoveryError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            invalid_count += 1
    campaigns.sort(key=lambda row: (row["name"].casefold(), row["id"]))
    return {"campaigns": campaigns, "invalid_count": invalid_count, "total": len(campaigns)}


def get_campaign(repository_root: Path, campaign_id: str) -> dict[str, Any]:
    if not campaign_id or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in campaign_id):
        raise DiscoveryError("invalid_campaign_id", "Campaign identifier is invalid.")
    entry = build_registry(repository_root).get(campaign_id)
    if entry is None:
        raise DiscoveryError("campaign_not_found", "Campaign was not found.")
    return inspect_entry(entry, repository_root)
