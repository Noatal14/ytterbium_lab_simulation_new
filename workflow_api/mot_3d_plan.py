"""Pure, fail-closed preparation of a canonical 3D-MOT Discovery campaign."""

from __future__ import annotations

import hashlib
import json
from workflow_api.platform_io import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping

from config import MOT_3D_SIM_CONFIG
from lab_setup.mot_3d_timestep_policy import (
    MOT_3D_TIMESTEP_POLICY,
    MOT_3D_TIMESTEP_POLICY_SHA256,
    MOT_3D_TIMESTEP_POLICY_VERSION,
)
from studies.mot_3d_campaign import (
    FAMILIES,
    build_campaign_manifest,
    freeze_inputs,
    render_discovery_jobs,
    validate_upstream_2d_campaign,
)
from workflow_api.mot_3d_provenance import input_registry_digest


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


def load_timestep_policy() -> tuple[Mapping[str, Any], str]:
    """Return the immutable pragmatic policy after exact runtime parity checks."""
    if (
        MOT_3D_TIMESTEP_POLICY["solver"] != MOT_3D_SIM_CONFIG["solver"]
        or MOT_3D_TIMESTEP_POLICY["search_dt_s"]
        != MOT_3D_SIM_CONFIG["screening_dt_s"]
        or MOT_3D_TIMESTEP_POLICY["sealed_final_validation_dt_s"]
        != MOT_3D_SIM_CONFIG["production_dt_s"]
        or MOT_3D_TIMESTEP_POLICY["t_max_s"] != MOT_3D_SIM_CONFIG["t_max_s"]
    ):
        raise ValueError("3D timestep policy and runtime configuration disagree.")
    return MOT_3D_TIMESTEP_POLICY, MOT_3D_TIMESTEP_POLICY_SHA256


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
    if approval_path is not None:
        raise ValueError("External 3D timestep approval files are no longer accepted.")
    policy, policy_sha256 = load_timestep_policy()
    handoff = {
        "campaign_sha256": upstream["campaign_sha256"],
        "final_report_sha256": upstream["final_report_sha256"],
        "input_registry_sha256": input_registry_digest(roles),
    }
    evidence_identity = {
        "policy_spec_version": MOT_3D_TIMESTEP_POLICY_VERSION,
        "policy_sha256": policy_sha256,
        "policy_status": policy["status"],
        "convergence_claim": policy["convergence_claim"],
        "inconclusive_evidence": dict(policy["inconclusive_evidence"]),
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
        timestep_status="pragmatic_user_approved_not_converged",
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
            key: (portable_destination / value.relative_to(destination)).as_posix()
            for key, value in smoke.items()
        },
        "discovery_rounds": {
            family: [
                (portable_destination / path.relative_to(destination)).as_posix()
                for path in rounds[family]
            ]
            for family in FAMILIES
        },
        "discovery_submit_chain": (
            portable_destination / submitter.relative_to(destination)
        ).as_posix(),
        "dependency": "afterok",
    }
    files = {name: text.encode("utf-8") for name, text in jobs.items()}
    files["campaign.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return files, manifest
