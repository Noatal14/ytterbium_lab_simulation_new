"""Strict immutable authority for the pragmatic 3D-MOT timestep policy."""

from __future__ import annotations

import json
import re
from pathlib import Path

from lab_setup.strict_specification import (
    canonical_digest,
    freeze,
    read_strict_json,
    require_exact_keys,
    require_finite_number,
)


SPECIFICATION_PATH = (
    Path(__file__).with_name("specifications") / "mot_3d_timestep_policy_v1.json"
)
MAX_SPECIFICATION_BYTES = 16 * 1024
VERSION = "mot-3d-timestep-policy-v1"
STATUS = "pragmatic_user_approved_after_inconclusive_study"


def _optional_sha256(value: object, label: str) -> None:
    if value is not None and (
        not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
    ):
        raise ValueError(f"Invalid {label}.")


def _validate(value):
    require_exact_keys(
        value,
        {
            "spec_version",
            "status",
            "solver",
            "search_dt_s",
            "sealed_final_validation_dt_s",
            "convergence_claim",
            "decision",
            "inconclusive_evidence",
        },
        "3D timestep policy",
    )
    if (
        value["spec_version"] != VERSION
        or value["status"] != STATUS
        or value["solver"] != "RK4StHybridCustom"
        or value["convergence_claim"] != "not_established"
    ):
        raise ValueError("Invalid 3D timestep policy identity.")
    require_finite_number(value["search_dt_s"], "3D search timestep", lo=0)
    require_finite_number(
        value["sealed_final_validation_dt_s"],
        "3D sealed final-validation timestep",
        lo=0,
    )
    if (
        value["search_dt_s"] != 10e-6
        or value["sealed_final_validation_dt_s"] != 0.625e-6
    ):
        raise ValueError("Invalid approved 3D timestep policy values.")
    decision = value["decision"]
    require_exact_keys(
        decision,
        {"rationale", "requires_new_campaign", "legacy_campaign_mutation_forbidden"},
        "3D timestep decision",
    )
    if (
        not isinstance(decision["rationale"], str)
        or not decision["rationale"].strip()
        or decision["requires_new_campaign"] is not True
        or decision["legacy_campaign_mutation_forbidden"] is not True
    ):
        raise ValueError("Invalid 3D timestep decision.")
    evidence = value["inconclusive_evidence"]
    require_exact_keys(
        evidence,
        {
            "campaign_name",
            "study_date",
            "status",
            "artifact_availability",
            "archive_path",
            "evidence_sha256",
            "tasks_sha256",
            "raw_result_registry_sha256",
        },
        "3D timestep evidence provenance",
    )
    if (
        evidence["campaign_name"] != "mot_3d_s0_1p3_20261010_v1"
        or evidence["study_date"] != "2026-10-10"
        or evidence["status"] != "inconclusive_degenerate_sentinel"
        or evidence["artifact_availability"]
        != "reported_on_zeus_not_imported"
        or evidence["archive_path"]
        != "docs/evidence/mot_3d_timestep_20261010_inconclusive.json"
    ):
        raise ValueError("Invalid 3D timestep evidence provenance.")
    for key in ("evidence_sha256", "tasks_sha256", "raw_result_registry_sha256"):
        _optional_sha256(evidence[key], f"3D timestep {key}")
    return value


def _read_validated():
    return read_strict_json(
        SPECIFICATION_PATH,
        _validate,
        max_bytes=MAX_SPECIFICATION_BYTES,
        error_message="The bundled 3D timestep policy is invalid.",
    )


_VALUE = _read_validated()


def _validate_archive(value):
    require_exact_keys(
        value,
        {
            "kind",
            "campaign_name",
            "study_date",
            "reported_status",
            "interpretation",
            "artifact_availability",
            "tasks_sha256",
            "raw_result_registry_sha256",
        },
        "3D timestep evidence archive",
    )
    evidence = _VALUE["inconclusive_evidence"]
    if (
        value["kind"] != "mot_3d_timestep_study_archive_v1"
        or value["campaign_name"] != evidence["campaign_name"]
        or value["study_date"] != evidence["study_date"]
        or value["reported_status"] != evidence["status"]
        or value["artifact_availability"] != evidence["artifact_availability"]
        or not isinstance(value["interpretation"], str)
        or not value["interpretation"].strip()
        or value["tasks_sha256"] != evidence["tasks_sha256"]
        or value["raw_result_registry_sha256"]
        != evidence["raw_result_registry_sha256"]
    ):
        raise ValueError("Invalid 3D timestep evidence archive.")
    return value


_ARCHIVE = read_strict_json(
    Path(__file__).resolve().parents[1] / _VALUE["inconclusive_evidence"]["archive_path"],
    _validate_archive,
    max_bytes=MAX_SPECIFICATION_BYTES,
    error_message="The bundled 3D timestep evidence archive is invalid.",
)
if canonical_digest(_ARCHIVE) != _VALUE["inconclusive_evidence"]["evidence_sha256"]:
    raise RuntimeError("The bundled 3D timestep evidence archive digest is invalid.")

MOT_3D_TIMESTEP_POLICY = freeze(_VALUE)
MOT_3D_TIMESTEP_POLICY_VERSION = _VALUE["spec_version"]
MOT_3D_TIMESTEP_POLICY_SHA256 = canonical_digest(_VALUE)


def render_typescript_specification() -> str:
    """Render the checked-in browser contract from the validated authority."""

    body = json.dumps(_VALUE, indent=2, sort_keys=True)
    return (
        "// Generated from lab_setup/specifications/"
        "mot_3d_timestep_policy_v1.json; do not edit.\n"
        f"export const MOT_3D_TIMESTEP_POLICY_V1 = {body} as const;\n"
    )
