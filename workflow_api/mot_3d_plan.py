"""Pure, fail-closed preparation of a canonical 3D-MOT Discovery campaign."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping

from config import MOT_3D_SIM_CONFIG
from studies.mot_3d_campaign import (
    FAMILIES,
    build_campaign_manifest,
    freeze_inputs,
    render_discovery_jobs,
    validate_upstream_2d_campaign,
)


APPROVAL_PATH = Path("lab_setup/specifications/mot_3d_timestep_approval_v1.json")
APPROVAL_VERSION = "mot-3d-timestep-approval-v1"


class Approved3DTimestepMissing(ValueError):
    """The one-off 3D timestep study has not yet been canonically approved."""


def canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _no_symlink_components(root: Path, path: Path) -> None:
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Approved 3D timestep paths may not contain symlinks.")


def _safe_repo_path(root: Path, raw: Path | str) -> Path:
    relative = Path(raw)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError("Approved 3D timestep path is invalid.")
    candidate = root.joinpath(*relative.parts)
    _no_symlink_components(root, candidate)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(
            "Approved 3D timestep path is outside the repository."
        ) from error
    return resolved


def _strict_json(
    root: Path, path: Path, *, limit: int = 1024 * 1024
) -> tuple[dict[str, Any], str]:
    _no_symlink_components(root, path)
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Approved 3D timestep record must be a regular file.")
        if before.st_size > limit:
            raise ValueError("Approved 3D timestep record is oversized.")
        raw = bytearray()
        while len(raw) <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
        identity = lambda row: (
            row.st_dev,
            row.st_ino,
            row.st_size,
            row.st_mtime_ns,
            row.st_ctime_ns,
        )
        if len(raw) != before.st_size or identity(before) != identity(after):
            raise ValueError("Approved 3D timestep record changed while reading.")
    finally:
        os.close(descriptor)

    def reject_duplicate(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate approval key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=reject_duplicate
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Approved 3D timestep record is invalid JSON.") from error
    if not isinstance(value, dict):
        raise ValueError("Approved 3D timestep record must be an object.")
    return value, hashlib.sha256(raw).hexdigest()


def _finite_positive(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Approved timestep values must be numeric.")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("Approved timestep values must be finite and positive.")
    return result


def input_registry_digest(roles: Mapping[str, list[dict[str, Any]]]) -> str:
    """Hash portable identities for all frozen 2D survivor ensembles."""
    rows = []
    for role in ("discovery", "refinement", "preliminary_check"):
        for record in roles[role]:
            rows.append(
                {
                    "role": role,
                    "zeeman_seed": record["zeeman_seed"],
                    "mot_seed": record["mot_seed"],
                    "sha256": record["sha256"],
                    "metadata_sha256": record["metadata_sha256"],
                    "shape": record["shape"],
                    "dtype": record["dtype"],
                    "n_survivors": record["n_survivors"],
                    "source_design": record["source_design"],
                    "source_parameters": record["source_parameters"],
                }
            )
    return canonical_digest(rows)


def load_approved_timestep(
    repository_root: Path,
    *,
    path: Path | None = None,
) -> tuple[dict[str, Any], str]:
    """Load the separately reviewed approval or fail closed when absent."""
    repository_root = Path(repository_root).resolve()
    approval_path = _safe_repo_path(repository_root, path or APPROVAL_PATH)
    if not approval_path.is_file():
        raise Approved3DTimestepMissing(
            "Canonical 3D timestep approval is not configured. Complete and review "
            "the one-off convergence study before preparing Discovery."
        )
    value, approval_sha256 = _strict_json(repository_root, approval_path)
    expected = {
        "spec_version",
        "status",
        "solver",
        "screening_dt_s",
        "production_dt_s",
        "evidence",
        "source_handoff",
    }
    evidence = value.get("evidence")
    handoff = value.get("source_handoff")
    if (
        set(value) != expected
        or value.get("spec_version") != APPROVAL_VERSION
        or value.get("status") != "approved"
        or value.get("solver") != MOT_3D_SIM_CONFIG["solver"]
        or _finite_positive(value.get("screening_dt_s"))
        != MOT_3D_SIM_CONFIG["screening_dt_s"]
        or _finite_positive(value.get("production_dt_s"))
        != MOT_3D_SIM_CONFIG["production_dt_s"]
        or not isinstance(evidence, dict)
        or set(evidence) != {"path", "sha256"}
        or not isinstance(handoff, dict)
        or set(handoff)
        != {"campaign_sha256", "final_report_sha256", "input_registry_sha256"}
        or any(
            not isinstance(handoff.get(key), str)
            or re.fullmatch(r"[0-9a-f]{64}", handoff[key]) is None
            for key in handoff
        )
        or not isinstance(evidence.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"]) is None
    ):
        raise ValueError("Canonical 3D timestep approval record is invalid.")
    evidence_path = _safe_repo_path(repository_root, str(evidence.get("path", "")))
    if not evidence_path.is_file():
        raise ValueError("Approved 3D timestep evidence is missing or changed.")
    evidence_payload, evidence_sha256 = _strict_json(
        repository_root, evidence_path, limit=64 * 1024 * 1024
    )
    if evidence_sha256 != evidence["sha256"]:
        raise ValueError("Approved 3D timestep evidence is missing or changed.")
    from studies.mot_3d.timestep_validation import (
        BOOTSTRAP_REPLICATES,
        EVIDENCE_FORMAT_VERSION,
        PARTICLES_PER_ENSEMBLE,
        PRODUCTION_TOLERANCE,
        RECOIL_SEEDS,
        SCREENING_TOLERANCE,
        T_MAX_S,
    )

    evidence_keys = {
        "kind",
        "format_version",
        "status",
        "screening_dt_s",
        "production_dt_s",
        "reference_dt_s",
        "tested_dt_s",
        "capture_bias_passed",
        "paired_decision_passed",
        "screening_absolute_bias_tolerance",
        "production_absolute_bias_tolerance",
        "classification_disagreement_is_diagnostic_only",
        "reference_capture_fraction_by_sentinel",
        "sentinels_informative",
        "largest_approved_screening_dt_s",
        "largest_approved_production_dt_s",
        "multiplicity",
        "per_comparison_alpha",
        "bootstrap_replicates",
        "campaign_manifest_sha256",
        "tasks_sha256",
        "raw_result_registry_sha256",
        "campaign_commit",
        "physical_model_sha256",
        "particles_per_ensemble",
        "ensemble_count",
        "recoil_seeds",
        "t_max_s",
        "comparisons",
        "new_campaign_required_if_selected_dt_changes",
    }
    if (
        set(evidence_payload) != evidence_keys
        or evidence_payload.get("kind") != "mot_3d_timestep_validation"
        or evidence_payload.get("status") != "approved"
        or evidence_payload.get("screening_dt_s") != value["screening_dt_s"]
        or evidence_payload.get("production_dt_s") != value["production_dt_s"]
        or evidence_payload.get("reference_dt_s")
        != MOT_3D_SIM_CONFIG["dt_validation_reference_s"]
        or evidence_payload.get("tested_dt_s")
        != list(MOT_3D_SIM_CONFIG["dt_validation_candidates_s"])
        or evidence_payload.get("capture_bias_passed") is not True
        or evidence_payload.get("paired_decision_passed") is not True
        or evidence_payload.get("sentinels_informative") is not True
        or evidence_payload.get("ensemble_count") != 20
        or evidence_payload.get("format_version") != EVIDENCE_FORMAT_VERSION
        or evidence_payload.get("particles_per_ensemble") != PARTICLES_PER_ENSEMBLE
        or evidence_payload.get("recoil_seeds") != list(RECOIL_SEEDS)
        or evidence_payload.get("t_max_s") != T_MAX_S
        or evidence_payload.get("bootstrap_replicates") != BOOTSTRAP_REPLICATES
        or evidence_payload.get("screening_absolute_bias_tolerance")
        != SCREENING_TOLERANCE
        or evidence_payload.get("production_absolute_bias_tolerance")
        != PRODUCTION_TOLERANCE
        or re.fullmatch(r"[0-9a-f]{64}", str(evidence_payload.get("tasks_sha256", "")))
        is None
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(evidence_payload.get("raw_result_registry_sha256", "")),
        )
        is None
    ):
        raise ValueError("Canonical 3D timestep evidence is not an approved design.")
    return value, approval_sha256


def render_discovery_bootstrap(
    *,
    repository_root: Path,
    destination: Path,
    name: str,
    upstream_campaign: Path,
    survivor_directory: Path,
    revision: str,
    physical_model_sha256: str,
    approval_path: Path | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Validate the 2D handoff and render a Discovery-ready campaign."""
    repository_root = Path(repository_root).resolve()
    destination = Path(destination).resolve()
    upstream_campaign = Path(upstream_campaign).resolve()
    survivor_directory = Path(survivor_directory).resolve()
    allowed_destination_root = (repository_root / "data/optimization/mot_3d").resolve()
    allowed_upstream_root = (repository_root / "data/optimization/mot_2d").resolve()
    allowed_survivor_root = (
        repository_root / "data/particle_states/after_2d_mot"
    ).resolve()
    try:
        destination.relative_to(allowed_destination_root)
        upstream_campaign.relative_to(allowed_upstream_root)
        survivor_directory.relative_to(allowed_survivor_root)
    except ValueError as error:
        raise ValueError(
            "3D bootstrap paths must use canonical repository roots."
        ) from error
    for guarded_path in (
        allowed_destination_root,
        destination.parent,
        upstream_campaign,
        survivor_directory,
    ):
        if guarded_path.exists():
            _no_symlink_components(repository_root, guarded_path)
    if destination.exists():
        raise FileExistsError("3D campaign destination already exists.")
    if (
        not isinstance(name, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", name)
        or destination.name != name
        or not re.fullmatch(r"[0-9a-f]{40}", revision)
        or not re.fullmatch(r"[0-9a-f]{64}", physical_model_sha256)
    ):
        raise ValueError("Invalid 3D campaign identity or provenance.")
    upstream = validate_upstream_2d_campaign(upstream_campaign, survivor_directory)
    expected_pairs = {
        row["zeeman_seed"]: row["mot_seed"] for row in upstream["sealed_seed_pairs"]
    }
    roles = freeze_inputs(
        survivor_directory,
        expected_seed_pairs=expected_pairs,
        expected_design=upstream["expected_survivor_design"],
        expected_parameters=upstream["expected_survivor_parameters"],
    )
    approval, approval_sha256 = load_approved_timestep(
        repository_root, path=approval_path
    )
    handoff = approval["source_handoff"]
    if handoff != {
        "campaign_sha256": upstream["campaign_sha256"],
        "final_report_sha256": upstream["final_report_sha256"],
        "input_registry_sha256": input_registry_digest(roles),
    }:
        raise ValueError(
            "Approved 3D timestep evidence is not bound to this completed 2D handoff."
        )
    evidence_path = (repository_root / approval["evidence"]["path"]).resolve()
    evidence_identity = {
        "path": evidence_path.relative_to(repository_root).as_posix(),
        "sha256": approval["evidence"]["sha256"],
        "approval_spec_version": APPROVAL_VERSION,
        "approval_sha256": approval_sha256,
        "source_handoff": dict(handoff),
    }
    portable_survivors = survivor_directory.relative_to(repository_root)
    portable_upstream = dict(upstream)
    portable_upstream["campaign_path"] = (
        (upstream_campaign / "campaign.json").relative_to(repository_root).as_posix()
    )
    portable_upstream["final_report_path"] = (
        (upstream_campaign / "final_report.json")
        .relative_to(repository_root)
        .as_posix()
    )
    portable_selected = dict(portable_upstream["selected_result"])
    portable_selected["survivor_states_directory"] = portable_survivors.as_posix()
    portable_upstream["selected_result"] = portable_selected
    portable_roles: dict[str, list[dict[str, Any]]] = {}
    for role, records in roles.items():
        portable_roles[role] = []
        for record in records:
            portable = dict(record)
            portable["path"] = (
                Path(record["path"]).relative_to(repository_root).as_posix()
            )
            portable["metadata_path"] = (
                Path(record["metadata_path"]).relative_to(repository_root).as_posix()
            )
            portable_roles[role].append(portable)
    manifest = build_campaign_manifest(
        name=name,
        input_directory=portable_survivors,
        upstream=portable_upstream,
        roles=portable_roles,
        revision=revision,
        physical_model_sha256=physical_model_sha256,
        stage="discovery",
        timestep_status="approved_by_paired_convergence_validation",
        timestep_evidence=evidence_identity,
    )
    manifest["input_directory"] = portable_survivors.as_posix()
    portable_destination = destination.relative_to(repository_root)
    jobs, smoke, rounds, submitter = render_discovery_jobs(
        destination,
        revision,
        survivor_directory,
        command_campaign=portable_destination,
        command_input=portable_survivors,
    )
    manifest["jobs"] = {
        "smoke": {
            key: str(portable_destination / value.relative_to(destination))
            for key, value in smoke.items()
        },
        "discovery_rounds": {
            family: [
                str(portable_destination / path.relative_to(destination))
                for path in rounds[family]
            ]
            for family in FAMILIES
        },
        "discovery_submit_chain": str(
            portable_destination / submitter.relative_to(destination)
        ),
        "dependency": "afterok",
    }
    files = {name: text.encode("utf-8") for name, text in jobs.items()}
    files["campaign.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return files, manifest
