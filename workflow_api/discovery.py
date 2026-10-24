"""Bounded, allowlisted discovery for local campaign inspection."""

from __future__ import annotations

import hashlib
import itertools
import json
import shlex
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from workflow_api.mot_2d import read_campaign as read_2d_campaign
from workflow_api.mot_3d import read_campaign as read_3d_campaign
from workflow_api.manifest_codec import (
    ManifestCodecError,
    ManifestFailure,
    read_manifest,
)
from workflow_api.mot_2d_validation import (
    modern_contract,
    sealed_final_is_valid,
    validated_progress,
)
from workflow_api.mot_3d_provenance import input_registry_digest

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
CURRENT_3D_STAGES = (
    "discovery",
    "preliminary_check",
    "refinement",
    "closure",
    "finalist_selection",
    "final_validation_input_generation",
    "final_validation",
    "complete",
    "final_validation_extension_required",
)
CURRENT_3D_ROLE_SEEDS = {
    "discovery": tuple(range(3015, 3027)),
    "refinement": tuple(range(3027, 3031)),
    "preliminary_check": tuple(range(3031, 3035)),
}
CURRENT_3D_SEED_PAIRS = tuple(
    {"zeeman_seed": seed, "mot_seed": 40000 + seed} for seed in range(3015, 3035)
)


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
    try:
        return read_manifest(path).model
    except ManifestCodecError as error:
        translations = {
            ManifestFailure.NOT_REGULAR: (
                "invalid_manifest",
                "Campaign record is not a trusted regular file.",
            ),
            ManifestFailure.UNAVAILABLE: (
                "unavailable_manifest",
                "Campaign record is unavailable.",
            ),
            ManifestFailure.OVERSIZED: (
                "oversized_manifest",
                "Campaign record is too large to inspect safely.",
            ),
            ManifestFailure.NON_OBJECT: (
                "invalid_manifest",
                "Campaign record must contain a JSON object.",
            ),
            ManifestFailure.UNSUPPORTED_KIND: (
                "unsupported_campaign",
                "Campaign record has an unsupported workflow kind.",
            ),
            ManifestFailure.FAMILY_MISMATCH: (
                "unsupported_campaign",
                "Campaign record has an unsupported workflow kind.",
            ),
        }
        code, message = translations.get(
            error.reason,
            ("invalid_manifest", "Campaign record is not valid JSON."),
        )
        raise DiscoveryError(code, message) from error


def _identifier(family: str, relative_root: Path) -> str:
    digest = hashlib.sha256(f"{family}:{relative_root.as_posix()}".encode()).hexdigest()[:20]
    return f"{family}-{digest}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_registry(repository_root: Path) -> dict[str, RegistryEntry]:
    repository_root = repository_root.resolve()
    registry: dict[str, RegistryEntry] = {}
    for family, relative in ROOTS.items():
        discovery_root = (repository_root / relative).resolve()
        if not _within(discovery_root, repository_root) or not discovery_root.is_dir():
            continue
        count = 0
        acceptance_root = discovery_root / "ui_acceptance"
        acceptance_directories = acceptance_root.iterdir() if acceptance_root.is_dir() and not acceptance_root.is_symlink() else ()
        for directory in itertools.chain(discovery_root.iterdir(), acceptance_directories):
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


def _trusted_regular(repository_root: Path, recorded: Any) -> Path | None:
    if not isinstance(recorded, str) or not recorded or "\x00" in recorded:
        return None
    candidate = Path(recorded)
    candidate = candidate if candidate.is_absolute() else repository_root / candidate
    try:
        relative = candidate.relative_to(repository_root)
    except ValueError:
        return None
    current = repository_root
    try:
        for part in relative.parts:
            if part in {"", ".", ".."}:
                return None
            current /= part
            if current.is_symlink():
                return None
        info = current.stat()
    except OSError:
        return None
    return current if stat.S_ISREG(info.st_mode) else None


def _same_json(left: Any, right: Any) -> bool:
    try:
        return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
            right, sort_keys=True, allow_nan=False
        )
    except (TypeError, ValueError):
        return False


def _survivor_design_matches(payload: dict[str, Any], observed: Any, expected: Any) -> bool:
    # Preserve the existing exact scientific contract, including callers that
    # inspect a normalized partial record after separate kind validation.
    if "acceptance" not in payload and payload.get("kind") != "mot_3d_ui_acceptance_v1" and _same_json(observed, expected):
        return True
    from workflow_api.acceptance_profile import policy_for_manifest

    if payload.get("kind") not in {"mot_3d_campaign_v2", "mot_3d_ui_acceptance_v1"}:
        return False
    profile = policy_for_manifest(payload)
    if not isinstance(observed, dict) or not isinstance(expected, dict):
        return False
    # These are the additional fields written by the normal Production worker,
    # not additional physical parameters or an open-ended metadata allowance.
    extras = {"npools": profile.stage("mot_2d", "production")["npools"] if profile else 150,
              "uses_all_available_particles": True}
    if profile is not None:
        from workflow_api.acceptance_profile import source_profile_for_consumer
        extras["acceptance"] = source_profile_for_consumer(
            profile.profile_id, payload.get("upstream_2d_campaign")
        ).provenance()
    return not set(expected).intersection(extras) and _same_json(observed, {**expected, **extras})


def _discovery_jobs_match(payload: dict[str, Any], root: Path | None, repository_root: Path) -> bool:
    if root is None:
        return False
    relative = root.relative_to(repository_root)
    expected = {
        "smoke": {family: (relative / "jobs" / f"01_smoke_{family}.pbs").as_posix()
                  for family in ("angled_donut", "single_pass")},
        "discovery_rounds": {
            family: [(relative / "jobs" / family / f"round_{index:02d}.pbs").as_posix()
                     for index in range(1, count + 1)]
            for family, count in (("angled_donut", 2), ("single_pass", 3))},
        "discovery_submit_chain": (relative / "jobs/02_submit_discovery_chain.sh").as_posix(),
        "dependency": "afterok",
    }
    paths = [*expected["smoke"].values(), expected["discovery_submit_chain"],
             *(p for rows in expected["discovery_rounds"].values() for p in rows)]
    return _same_json(payload.get("jobs"), expected) and all(
        _trusted_regular(repository_root, p) is not None for p in paths
    )


def _validated_3d_extension(payload: dict[str, Any], repository_root: Path, campaign_root: Path) -> bool:
    """Recompute the saved terminal outcome; summaries alone are not evidence."""
    from workflow_api.mot_3d_final_validation_results import (
        expected_paths, validate_final_validation_result_bytes,
    )
    from workflow_api.mot_3d_final_input_results import expected_paths as input_paths
    from workflow_api.platform_io import os
    from workflow_api.mot_3d_discovery_transition import _DIRECTORY_FLAGS, _READ_FLAGS, _open_parent_at

    def read(name: str) -> bytes:
        path = _trusted_regular(repository_root, str(campaign_root / name))
        if path is None:
            raise ValueError("untrusted terminal artifact")
        root_fd = os.open(repository_root, _DIRECTORY_FLAGS)
        parent_fd = -1
        fd = -1
        try:
            parts = path.relative_to(repository_root).parts
            parent_fd = _open_parent_at(root_fd, parts[:-1], create=False)
            fd = os.open(parts[-1], _READ_FLAGS, dir_fd=parent_fd)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= 2 * 1024 * 1024:
                raise ValueError("invalid terminal artifact")
            raw = os.read(fd, before.st_size + 1)
            identity = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid, row.st_nlink, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
            if len(raw) != before.st_size or identity(os.fstat(fd)) != identity(before) or identity(os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)) != identity(before):
                raise ValueError("terminal artifact changed")
            return raw
        finally:
            if fd >= 0:
                os.close(fd)
            if parent_fd >= 0:
                os.close(parent_fd)
            os.close(root_fd)

    relative = campaign_root.relative_to(repository_root).as_posix()
    root_fd = os.open(repository_root, _DIRECTORY_FLAGS)
    parent_fd = -1
    try:
        parent_fd = _open_parent_at(root_fd, PurePosixPath(relative).parts, create=False)
        try:
            os.stat("final_report.json", dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            return False
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)
        os.close(root_fd)
    original = json.loads(json.dumps(payload))
    if original["stages"].pop("final_validation_status") != relative + "/final_validation_status.json":
        return False
    original["stage"] = "final_validation"
    original_bytes = json.dumps(original, indent=2, ensure_ascii=False, allow_nan=False).encode()
    inputs_raw = read("final_validation_inputs/input_manifest.json")
    # These are logical producer paths, never host filesystem read locations.
    first = json.loads(inputs_raw)["ensembles"][0]["path"]
    if not isinstance(first, str):
        return False
    marker = "/" + relative + "/final_validation_inputs/"
    project = first.split(marker)[0]
    if first.count(marker) != 1 or not PurePosixPath(project).is_absolute() or str(PurePosixPath(project)) != project:
        return False
    validated = validate_final_validation_result_bytes(
        manifest_bytes=original_bytes,
        locked_nominals_bytes=read("selection/locked_nominals.json"),
        input_manifest_bytes=inputs_raw,
        generation_submission_bytes=read("final_validation_input_generation_submission.json"),
        submission_bytes=read("final_validation_submission.json"),
        job_files={f"jobs/final_validation/{family}_{kind}.pbs": read(f"jobs/final_validation/{family}_{kind}.pbs")
                   for family in ("angled_donut", "single_pass") for kind in ("array", "merge")},
        input_files={name: read(name) for name in input_paths(original)},
        result_files={name: read(name) for name in expected_paths()},
        logical_campaign_root=relative, project_directory=project,
        campaign_absolute_path=project + "/" + relative,
    )
    return (
        validated.outcome == payload["stage"] == "final_validation_extension_required"
        and validated.terminal_name == "final_validation_status.json"
        and validated.campaign_bytes == read("campaign.json")
        and validated.terminal_bytes == read("final_validation_status.json")
    )


def _modern_3d_contract(
    payload: dict[str, Any], progress: list[dict[str, Any]], repository_root: Path,
    campaign_root: Path | None = None,
) -> tuple[bool, tuple[str, ...]]:
    errors: list[str] = []
    provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
    design = payload.get("design") if isinstance(payload.get("design"), dict) else {}
    upstream = payload.get("upstream_2d_campaign") if isinstance(payload.get("upstream_2d_campaign"), dict) else {}
    roles = payload.get("input_roles") if isinstance(payload.get("input_roles"), dict) else {}
    source_marker = payload.get("acceptance")
    approved_survivors = None
    if "acceptance" in payload:
        from workflow_api.acceptance_profile import policy_for_manifest, source_profile_for_consumer
        profile = policy_for_manifest(payload)
        source_marker = source_profile_for_consumer(profile.profile_id, upstream).provenance()
        if profile.profile_id == "ui_acceptance_v2":
            approved_survivors = profile.family("mot_3d")["accepted_upstream"]["survivor_files"]
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
    if upstream.get("sealed_seed_pairs") != list(CURRENT_3D_SEED_PAIRS):
        errors.append("upstream sealed seed-pair registry is not canonical")
    if set(roles) != set(CURRENT_3D_ROLE_SEEDS) or any(
        not isinstance(roles.get(role), list)
        or tuple(record.get("zeeman_seed") for record in roles[role] if isinstance(record, dict)) != seeds
        for role, seeds in CURRENT_3D_ROLE_SEEDS.items()
    ):
        errors.append("frozen 3D input roles are incomplete")
    else:
        for records in roles.values():
            for record in records:
                if not isinstance(record, dict) or any(record.get(key) is None for key in ("path", "metadata_path", "sha256", "metadata_sha256", "shape", "dtype", "zeeman_seed", "mot_seed", "source_design", "source_parameters")):
                    errors.append("frozen 3D input record is incomplete")
                    break
    expected_pairs = {
        row.get("zeeman_seed"): row.get("mot_seed")
        for row in upstream.get("sealed_seed_pairs", ())
        if isinstance(row, dict)
    }
    if any(
        expected_pairs.get(record.get("zeeman_seed")) != record.get("mot_seed")
        for records in roles.values()
        if isinstance(records, list)
        for record in records
        if isinstance(record, dict)
    ):
        errors.append("frozen 3D seed-pair registry differs from the upstream handoff")
    frozen_records = [
        record
        for records in roles.values()
        if isinstance(records, list)
        for record in records
        if isinstance(record, dict)
    ]
    if (
        len({record.get("path") for record in frozen_records}) != len(frozen_records)
        or len({record.get("metadata_path") for record in frozen_records}) != len(frozen_records)
        or len({record.get("mot_seed") for record in frozen_records}) != len(frozen_records)
    ):
        errors.append("frozen 3D input registry contains duplicate identities")
    upstream_campaign = _trusted_regular(repository_root, upstream.get("campaign_path"))
    upstream_report = _trusted_regular(repository_root, upstream.get("final_report_path"))
    if upstream_campaign is None or _file_sha256(upstream_campaign) != upstream.get("campaign_sha256"):
        errors.append("upstream 2D campaign identity does not match its frozen bytes")
    if upstream_report is None or _file_sha256(upstream_report) != upstream.get("final_report_sha256"):
        errors.append("upstream 2D final-report identity does not match its frozen bytes")
    for records in roles.values():
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            array_path = _trusted_regular(repository_root, record.get("path"))
            metadata_path = _trusted_regular(repository_root, record.get("metadata_path"))
            if array_path is None or _file_sha256(array_path) != record.get("sha256"):
                errors.append("frozen 3D input array identity is invalid")
            if metadata_path is None or _file_sha256(metadata_path) != record.get("metadata_sha256"):
                errors.append("frozen 3D input metadata identity is invalid")
            if approved_survivors is not None and (
                array_path is None or metadata_path is None
                or record.get("sha256") != approved_survivors.get(array_path.name)
                or record.get("metadata_sha256") != approved_survivors.get(metadata_path.name)
            ):
                errors.append("versioned acceptance donor bytes differ from the reviewed original")
            if not _survivor_design_matches(payload, record.get("source_design"), upstream.get("expected_survivor_design")):
                errors.append("frozen 3D input design differs from the upstream handoff")
            if record.get("source_parameters") != upstream.get("expected_survivor_parameters"):
                errors.append("frozen 3D input parameters differ from the upstream handoff")
            if metadata_path is not None:
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    metadata = None
                if (
                    not isinstance(metadata, dict)
                    or metadata.get("kind") != "mot_2d_final_survivor_ensemble"
                    or metadata.get("zeeman_seed") != record.get("zeeman_seed")
                    or metadata.get("mot_seed") != record.get("mot_seed")
                    or metadata.get("shape") != record.get("shape")
                    or metadata.get("dtype") != record.get("dtype")
                    or metadata.get("n_survivors") != record.get("n_survivors")
                    or (("acceptance" in payload or not _same_json(record.get("source_design"), upstream.get("expected_survivor_design"))) and (
                        not _same_json(metadata.get("design"), record.get("source_design"))
                        or not _same_json(metadata.get("parameters"), record.get("source_parameters"))
                        or metadata.get("output_sha256") != record.get("sha256")
                        or ("acceptance" in payload and not _same_json(metadata.get("acceptance"), source_marker))
                    ))
                ):
                    errors.append("frozen 3D input metadata differs from its registry record")
    try:
        registry_sha256 = input_registry_digest(roles)
    except (KeyError, TypeError, ValueError):
        registry_sha256 = None
    handoff = (
        design.get("timestep_evidence", {}).get("source_handoff", {})
        if isinstance(design.get("timestep_evidence"), dict)
        else {}
    )
    if (
        registry_sha256 is None
        or handoff.get("input_registry_sha256") != registry_sha256
        or handoff.get("campaign_sha256") != upstream.get("campaign_sha256")
        or handoff.get("final_report_sha256") != upstream.get("final_report_sha256")
    ):
        errors.append("3D frozen handoff identity is inconsistent")
    stage = payload.get("stage")
    stages = payload.get("stages") if isinstance(payload.get("stages"), dict) else {}
    if stage not in CURRENT_3D_STAGES:
        errors.append("3D campaign stage is not part of the current guarded workflow")
    required_stage = "final_validation" if stage in {"complete", "final_validation_extension_required"} else stage
    if required_stage == "discovery":
        if not _discovery_jobs_match(payload, campaign_root, repository_root):
            errors.append("current 3D Discovery job registry is incomplete or noncanonical")
    elif required_stage in CURRENT_3D_STAGES and not isinstance(stages.get(required_stage), dict):
        errors.append("current 3D stage record is incomplete")
    if stage == "final_validation_extension_required":
        try:
            terminal_valid = campaign_root is not None and _validated_3d_extension(payload, repository_root, campaign_root)
        except (OSError, ValueError, TypeError, KeyError, IndexError):
            terminal_valid = False
        if not terminal_valid:
            errors.append("3D precision-extension terminal evidence is invalid or incomplete")
    timestep = next((row for row in progress if row.get("stage") == "dt_validation"), None)
    if not timestep or timestep.get("status") != "complete":
        errors.append("current 3D timestep policy validation is unavailable")
    if not progress or any(row.get("status") in {"unknown", "inconsistent"} for row in progress):
        errors.append("validated 3D stage progress is unavailable or inconsistent")
    return not errors, tuple(dict.fromkeys(errors))


def _role(kind: str, stage: str, sealed_final: bool, trusted: bool) -> str:
    if kind in {"mot_2d_ui_acceptance_v1", "mot_3d_ui_acceptance_v1"}:
        return "acceptance-only"
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
        if summary.get("kind") in {"mot_3d_campaign_v2", "mot_3d_ui_acceptance_v1"}:
            return None
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
    from workflow_api.acceptance_profile import ACCEPTANCE_KINDS, policy_for_manifest, assert_acceptance_path
    if payload.get("kind") not in {expected_kind, ACCEPTANCE_KINDS[entry.family]}:
        raise DiscoveryError("unsupported_campaign", "Campaign record has an unsupported workflow kind.")
    if policy_for_manifest(payload) is not None:
        assert_acceptance_path(entry.manifest, repository_root)
    elif "ui_acceptance" in entry.relative_root.parts:
        raise DiscoveryError("unsupported_campaign", "Scientific campaigns cannot use TEST ONLY paths.")
    try:
        reader = read_2d_campaign if entry.family == "mot_2d" else read_3d_campaign
        summary = reader(entry.manifest, manifest=payload).to_dict()
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise DiscoveryError("invalid_campaign", "Campaign files could not be validated for inspection.") from error
    raw_warnings = [str(item) for item in summary.get("warnings", [])]
    contract_errors: tuple[str, ...] = ()
    remote_preparation = {"status": "unavailable", "reason_code": "incomplete-portability-record"}
    sealed_final = False
    if entry.family == "mot_2d":
        contract_ok, contract_errors = modern_contract(payload, repository_root)
        portability = payload.get("provenance", {}).get("path_contract") if isinstance(payload.get("provenance"), dict) else None
        remote_preparation = (
            {"status": "ready", "reason_code": None}
            if contract_ok else
            {"status": "legacy-local-only", "reason_code": "absolute-input-paths"}
            if portability is None else
            {"status": "unavailable", "reason_code": (
                "incomplete-portability-record"
                if any("path" in error or "portable" in error for error in contract_errors)
                else "campaign-validation-failed"
            )}
        )
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
        contract_ok, contract_errors = _modern_3d_contract(payload, progress, repository_root, entry.manifest.parent)
        remote_preparation = (
            {"status": "ready", "reason_code": None}
            if contract_ok
            else {"status": "unavailable", "reason_code": "campaign-validation-failed"}
        )
        sealed_final = any(row.get("stage") == "final_validation" and row.get("status") == "complete" for row in progress) and summary.get("stage") == "complete"
        if not contract_ok:
            progress = []
            sealed_final = False
    inconsistent = any(row.get("status") in ("unknown", "inconsistent") for row in progress)
    trust = "trusted-current" if contract_ok and not inconsistent else "legacy-incomplete"
    raw_warnings.extend(f"Modern campaign contract check failed: {error}." for error in contract_errors)
    warnings = [_warning(item) for item in raw_warnings]
    if payload.get("kind") in ACCEPTANCE_KINDS.values():
        warnings.insert(0, _warning("TEST ONLY — UI acceptance; these results have no scientific validation or promotion status.", "info"))
    current_progress = next((row for row in progress if row.get("stage") == summary.get("stage")), None)
    if trust == "trusted-current" and current_progress and current_progress.get("status") == "in-progress":
        warnings.append(_warning(
            "Saved local outputs are partial. This saved inspection does not query the scheduler; use a fresh Zeus status check to verify the existing job.",
            "info",
        ))
    if trust != "trusted-current":
        warnings.insert(0, _warning("This campaign is incomplete or uses an older record format. Inspect it only; do not continue from this view.", "blocked"))
    safe_plan = _progress_aware_plan(summary, progress, entry.manifest.parent, repository_root) if trust == "trusted-current" and not raw_warnings else None
    if safe_plan:
        message = (
            "This saved inspection does not query the scheduler. Use a fresh Zeus status check; the displayed command is for review and copying only."
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
        "remote_preparation": remote_preparation,
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
