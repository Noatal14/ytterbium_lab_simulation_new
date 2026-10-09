"""Frozen v1 error semantics for the local workflow API.

This module is deliberately not used by the HTTP handler yet.  P8.2A/B keeps
the active translators untouched while recording the exact behavior they must
preserve during the later migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
import json
from types import MappingProxyType
from typing import Mapping

ERROR_CATALOG_VERSION = 1


@dataclass(frozen=True)
class ErrorSpec:
    status: HTTPStatus
    message: str
    wire_code: str | None = None


@dataclass(frozen=True)
class ErrorDomain:
    entries: Mapping[str, ErrorSpec]
    fallback: ErrorSpec | None = None
    fallback_code: str | None = None


def _frozen(
    entries: dict[str, ErrorSpec],
    fallback: ErrorSpec | None = None,
    fallback_code: str | None = None,
) -> ErrorDomain:
    return ErrorDomain(MappingProxyType(dict(entries)), fallback, fallback_code)


def _spec(status: HTTPStatus, message: str) -> ErrorSpec:
    return ErrorSpec(status, message)


_SHARED_ZEUS = {
    "zeus_authentication_required": _spec(
        HTTPStatus.UNAUTHORIZED, "An existing SSH key or agent is required."
    ),
    "zeus_host_key_untrusted": _spec(
        HTTPStatus.PRECONDITION_FAILED,
        "The Zeus host key must be verified outside this application.",
    ),
    "zeus_unreachable": _spec(
        HTTPStatus.SERVICE_UNAVAILABLE, "Zeus could not be reached."
    ),
}

PROTOCOL = _frozen(
    {
        "unsupported_query": _spec(
            HTTPStatus.BAD_REQUEST, "Query parameters are not supported."
        ),
        "session_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE, "Local actions are unavailable."
        ),
        "untrusted_origin": _spec(
            HTTPStatus.FORBIDDEN, "Local creation requires a same-origin request."
        ),
        "invalid_campaign_id": _spec(
            HTTPStatus.BAD_REQUEST, "Campaign identifier is invalid."
        ),
        "inspection_failed": _spec(
            HTTPStatus.INTERNAL_SERVER_ERROR, "Campaign inspection failed safely."
        ),
        "source_inspection_failed": _spec(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "Zeeman sources could not be inspected safely.",
        ),
        "not_found": _spec(HTTPStatus.NOT_FOUND, "Not found."),
        "method_not_allowed": _spec(
            HTTPStatus.METHOD_NOT_ALLOWED, "This method is not available."
        ),
        "invalid_preview": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "Preview confirmation is invalid or expired.",
        ),
        "invalid_request_target": _spec(
            HTTPStatus.BAD_REQUEST, "Absolute request targets are not accepted."
        ),
        "untrusted_host": _spec(
            HTTPStatus.BAD_REQUEST,
            "This local service accepts only localhost requests.",
        ),
        "invalid_session": _spec(
            HTTPStatus.FORBIDDEN, "Local creation session is missing or expired."
        ),
        "invalid_csrf": _spec(
            HTTPStatus.FORBIDDEN, "Local creation request could not be verified."
        ),
    }
)

SESSION = _frozen(
    {
        "rate_limited": _spec(
            HTTPStatus.TOO_MANY_REQUESTS, "Too many local creation sessions."
        ),
    }
)

CREATION = _frozen(
    {
        "rate_limited": _spec(
            HTTPStatus.TOO_MANY_REQUESTS, "Too many local creation requests."
        ),
        "campaign_exists": _spec(
            HTTPStatus.CONFLICT, "A campaign already exists at this destination."
        ),
        "creation_failed": _spec(
            HTTPStatus.PRECONDITION_FAILED, "Local campaign creation failed safely."
        ),
        "invalid_request#confirmation": ErrorSpec(
            HTTPStatus.BAD_REQUEST,
            "Confirmation payload is invalid.",
            "invalid_request",
        ),
        "invalid_request#bounded_body": ErrorSpec(
            HTTPStatus.BAD_REQUEST,
            "A bounded JSON request body is required.",
            "invalid_request",
        ),
        "invalid_request#content_length": ErrorSpec(
            HTTPStatus.BAD_REQUEST, "Content-Length is required.", "invalid_request"
        ),
        "invalid_request#too_large": ErrorSpec(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            "Request body is too large.",
            "invalid_request",
        ),
        "invalid_request#json_object": ErrorSpec(
            HTTPStatus.BAD_REQUEST, "JSON body must be an object.", "invalid_request"
        ),
        "invalid_request#too_deep": ErrorSpec(
            HTTPStatus.BAD_REQUEST, "JSON body is too deeply nested.", "invalid_request"
        ),
        "invalid_request#string_keys": ErrorSpec(
            HTTPStatus.BAD_REQUEST,
            "JSON object keys must be strings.",
            "invalid_request",
        ),
        "invalid_request#preview_fields": ErrorSpec(
            HTTPStatus.BAD_REQUEST, "Preview fields are invalid.", "invalid_request"
        ),
        "invalid_request#source_unavailable": ErrorSpec(
            HTTPStatus.BAD_REQUEST,
            "The selected Zeeman source is unavailable.",
            "invalid_request",
        ),
    }
)

ROUTE_UNAVAILABLE = _frozen(
    {
        "creation_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE, "Local campaign creation is unavailable."
        ),
        "zeus_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE, "Read-only Zeus inspection is unavailable."
        ),
        "zeus_preparation_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE, "Zeus campaign preparation is unavailable."
        ),
        "zeus_submission_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE, "Zeus smoke submission is unavailable."
        ),
        "zeus_screening_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE, "Zeus smoke inspection is unavailable."
        ),
        "zeus_screen_submission_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE, "Zeus screening submission is unavailable."
        ),
        "zeus_refinement_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "Zeus refinement preparation is unavailable.",
        ),
        "zeus_refinement_submission_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE, "Zeus refinement submission is unavailable."
        ),
        "zeus_confirmation_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "Zeus confirmation preparation is unavailable.",
        ),
    }
)

SNAPSHOT = _frozen(
    {
        "rate_limited": _spec(
            HTTPStatus.TOO_MANY_REQUESTS, "Wait before checking Zeus again."
        ),
        **_SHARED_ZEUS,
        "zeus_timeout": _spec(
            HTTPStatus.GATEWAY_TIMEOUT, "The read-only Zeus check timed out."
        ),
        "remote_project_missing": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The remote project directory could not be verified.",
        ),
        "scheduler_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE, "The Zeus scheduler is unavailable."
        ),
        "malformed_remote_response": _spec(
            HTTPStatus.BAD_GATEWAY, "Zeus returned an invalid read-only snapshot."
        ),
        "zeus_check_failed": _spec(
            HTTPStatus.BAD_GATEWAY, "The read-only Zeus check failed safely."
        ),
    },
    _spec(HTTPStatus.BAD_GATEWAY, "The read-only Zeus check failed safely."),
    "zeus_check_failed",
)

TRANSFER = _frozen(
    {
        "request_invalid": _spec(
            HTTPStatus.BAD_REQUEST, "The Zeus preparation request is invalid."
        ),
        "profile_invalid": _spec(
            HTTPStatus.BAD_REQUEST, "The Zeus connection profile is invalid."
        ),
        "campaign_not_found": _spec(
            HTTPStatus.NOT_FOUND, "The selected campaign was not found."
        ),
        "confirmation_invalid": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The preparation preview is invalid or belongs to another session.",
        ),
        "confirmation_expired": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The preparation preview has expired. Review it again before continuing.",
        ),
        "too_many_pending_previews": _spec(
            HTTPStatus.TOO_MANY_REQUESTS, "Too many preparation previews are pending."
        ),
        **_SHARED_ZEUS,
        "zeus_timeout": _spec(
            HTTPStatus.GATEWAY_TIMEOUT, "The Zeus preparation check timed out."
        ),
        "remote_project_missing": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The remote project directory could not be verified.",
        ),
        "target_exists": _spec(
            HTTPStatus.CONFLICT,
            "A remote file appeared after review. Review the preparation again.",
        ),
        "remote_input_conflict": _spec(
            HTTPStatus.CONFLICT,
            "A required Zeus input differs from the frozen campaign input.",
        ),
        "remote_campaign_conflict": _spec(
            HTTPStatus.CONFLICT,
            "The Zeus campaign destination already contains different or incomplete files.",
        ),
        "local_checkout_mismatch": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The local checkout is not clean at the campaign commit.",
        ),
        "remote_checkout_mismatch": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The Zeus checkout is not clean at the campaign commit.",
        ),
    },
    _spec(HTTPStatus.PRECONDITION_FAILED, "Zeus preparation stopped safely."),
    "zeus_preparation_failed",
)

SMOKE_SUBMISSION = _frozen(
    {
        "request_invalid": _spec(
            HTTPStatus.BAD_REQUEST, "The smoke-submission request is invalid."
        ),
        "profile_invalid": _spec(
            HTTPStatus.BAD_REQUEST, "The Zeus connection profile is invalid."
        ),
        "campaign_not_found": _spec(
            HTTPStatus.NOT_FOUND, "The selected campaign was not found."
        ),
        "campaign_not_smoke": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "Only a campaign awaiting its smoke stage can be submitted.",
        ),
        "campaign_not_canonical": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The campaign does not match the canonical portable smoke plan.",
        ),
        "confirmation_invalid": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The submission preview is invalid or belongs to another session.",
        ),
        "confirmation_expired": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The submission preview has expired. Review it again before continuing.",
        ),
        "too_many_pending_previews": _spec(
            HTTPStatus.TOO_MANY_REQUESTS, "Too many submission previews are pending."
        ),
        **_SHARED_ZEUS,
        "zeus_timeout": _spec(
            HTTPStatus.GATEWAY_TIMEOUT, "The read-only submission check timed out."
        ),
        "remote_project_missing": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The remote project directory could not be verified.",
        ),
        "local_checkout_mismatch": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The local checkout is not clean at the campaign commit.",
        ),
        "local_files_changed": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The campaign changed after review. Review it again before submitting.",
        ),
        "remote_preparation_invalid": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The exact prepared campaign could not be verified on Zeus.",
        ),
        "submission_outcome_unknown": _spec(
            HTTPStatus.CONFLICT,
            "A previous submission attempt has an uncertain outcome. Automatic retry is blocked to prevent a duplicate job.",
        ),
        "already_submitted": _spec(
            HTTPStatus.CONFLICT,
            "This smoke stage already has a durable Zeus submission record.",
        ),
        "smoke_already_started": _spec(
            HTTPStatus.CONFLICT,
            "Smoke-stage outputs already exist on Zeus, so automatic submission is blocked.",
        ),
        "submission_record_invalid": _spec(
            HTTPStatus.CONFLICT,
            "The durable Zeus submission record is invalid or conflicting.",
        ),
        "submission_busy": _spec(
            HTTPStatus.CONFLICT,
            "Another submission operation is already checking this campaign.",
        ),
    },
    _spec(HTTPStatus.PRECONDITION_FAILED, "Zeus smoke submission stopped safely."),
    "zeus_submission_failed",
)

SMOKE_TRANSITION = _frozen(
    {
        "request_invalid": _spec(
            HTTPStatus.BAD_REQUEST,
            "Smoke inspection or screening preparation stopped safely.",
        ),
        "profile_invalid": _spec(
            HTTPStatus.BAD_REQUEST,
            "Smoke inspection or screening preparation stopped safely.",
        ),
        "campaign_not_found": _spec(
            HTTPStatus.NOT_FOUND,
            "Smoke inspection or screening preparation stopped safely.",
        ),
        "smoke_running": _spec(
            HTTPStatus.PRECONDITION_FAILED, "The smoke check is still running."
        ),
        "smoke_held": _spec(
            HTTPStatus.PRECONDITION_FAILED, "The smoke job needs attention on Zeus."
        ),
        "smoke_failed": _spec(
            HTTPStatus.PRECONDITION_FAILED, "The smoke job finished with an error."
        ),
        "smoke_status_unknown": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The smoke outcome could not be established safely.",
        ),
        "smoke_outputs_pending": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The smoke job succeeded; its output files are still becoming visible.",
        ),
        "smoke_outputs_invalid": _spec(
            HTTPStatus.PRECONDITION_FAILED, "The smoke outputs failed validation."
        ),
        "screening_already_prepared": _spec(
            HTTPStatus.CONFLICT, "Screening is already prepared on Zeus."
        ),
        "transition_outcome_unknown": _spec(
            HTTPStatus.CONFLICT,
            "Screening preparation may have changed Zeus. Inspect it before retrying.",
        ),
        "confirmation_invalid": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The screening preview is invalid or belongs to another session.",
        ),
        "confirmation_expired": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The screening preview expired. Review it again.",
        ),
        "local_checkout_mismatch": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The local checkout no longer matches the campaign commit.",
        ),
        "remote_checkout_mismatch": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The Zeus checkout no longer matches the campaign commit.",
        ),
        **_SHARED_ZEUS,
        "zeus_timeout": _spec(
            HTTPStatus.GATEWAY_TIMEOUT, "The Zeus inspection timed out."
        ),
        "scheduler_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "The Zeus scheduler history could not be read.",
        ),
        "transition_busy": _spec(
            HTTPStatus.CONFLICT, "Another screening preparation is in progress."
        ),
        "transition_conflict": _spec(
            HTTPStatus.CONFLICT,
            "A screening artifact conflicts with the reviewed plan.",
        ),
    },
    _spec(
        HTTPStatus.PRECONDITION_FAILED,
        "Smoke inspection or screening preparation stopped safely.",
    ),
    "zeus_screening_failed",
)

SCREEN_SUBMISSION = _frozen(
    {
        "request_invalid": _spec(
            HTTPStatus.BAD_REQUEST, "Screening submission stopped safely."
        ),
        "profile_invalid": _spec(
            HTTPStatus.BAD_REQUEST, "Screening submission stopped safely."
        ),
        "campaign_not_found": _spec(
            HTTPStatus.NOT_FOUND, "Screening submission stopped safely."
        ),
        "campaign_not_canonical": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The selected campaign does not match its frozen design.",
        ),
        "screening_not_prepared": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The exact Screening plan is not prepared on Zeus.",
        ),
        "screening_already_submitted": _spec(
            HTTPStatus.CONFLICT,
            "Screening already has a durable Zeus submission record.",
        ),
        "screening_already_started": _spec(
            HTTPStatus.CONFLICT,
            "Screening outputs already exist, so submission is blocked.",
        ),
        "screening_submission_busy": _spec(
            HTTPStatus.CONFLICT, "Another Screening submission check is in progress."
        ),
        "screening_submission_record_invalid": _spec(
            HTTPStatus.CONFLICT,
            "The Screening submission record is invalid or conflicting.",
        ),
        "screening_submission_outcome_unknown": _spec(
            HTTPStatus.CONFLICT,
            "A Screening submission attempt has an uncertain outcome. Automatic retry is blocked.",
        ),
        "confirmation_invalid": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The submission preview is invalid or belongs to another session.",
        ),
        "confirmation_expired": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The submission preview expired. Review it again.",
        ),
        "local_checkout_mismatch": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The local checkout no longer matches the campaign commit.",
        ),
        "local_files_changed": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The campaign changed after review. Review it again.",
        ),
        "remote_checkout_mismatch": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "The Zeus checkout no longer matches the campaign commit.",
        ),
        **_SHARED_ZEUS,
        "zeus_timeout": _spec(
            HTTPStatus.GATEWAY_TIMEOUT, "The Zeus submission check timed out."
        ),
    },
    _spec(HTTPStatus.PRECONDITION_FAILED, "Screening submission stopped safely."),
    "screening_submission_failed",
)


def _generic_stage(
    codes: set[str],
    message: str,
    conflicts: set[str],
    fallback_code: str,
) -> ErrorDomain:
    entries = {}
    for code in codes:
        status = (
            HTTPStatus.BAD_REQUEST
            if code in {"request_invalid", "profile_invalid"}
            else (
                HTTPStatus.NOT_FOUND
                if code == "campaign_not_found"
                else (
                    HTTPStatus.UNAUTHORIZED
                    if code == "zeus_authentication_required"
                    else (
                        HTTPStatus.CONFLICT
                        if code in conflicts
                        else HTTPStatus.PRECONDITION_FAILED
                    )
                )
            )
        )
        entries[code] = _spec(status, message)
    return _frozen(
        entries, _spec(HTTPStatus.PRECONDITION_FAILED, message), fallback_code
    )


REFINEMENT_TRANSITION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "campaign_not_canonical",
        "local_checkout_mismatch",
        "local_files_changed",
        "remote_response_invalid",
        "too_many_pending_previews",
        "confirmation_invalid",
        "confirmation_expired",
        "screen_queued",
        "screen_running",
        "screen_held",
        "screen_failed",
        "screen_status_unknown",
        "screen_outputs_pending",
        "screen_outputs_invalid",
        "refinement_already_prepared",
        "transition_busy",
        "transition_conflict",
        "transition_outcome_unknown",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
        "scheduler_unavailable",
    },
    "Refinement preparation stopped safely.",
    {
        "transition_busy",
        "transition_conflict",
        "transition_outcome_unknown",
        "refinement_already_prepared",
    },
    "refinement_preparation_failed",
)
REFINEMENT_SUBMISSION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "campaign_not_canonical",
        "local_checkout_mismatch",
        "local_files_changed",
        "remote_response_invalid",
        "too_many_pending_previews",
        "confirmation_invalid",
        "confirmation_expired",
        "refinement_not_prepared",
        "refinement_chain_already_submitted",
        "refinement_chain_partially_submitted",
        "refinement_submission_busy",
        "refinement_submission_outcome_unknown",
        "refinement_already_started",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "Refinement submission stopped safely.",
    {
        "refinement_chain_already_submitted",
        "refinement_chain_partially_submitted",
        "refinement_submission_busy",
        "refinement_submission_outcome_unknown",
        "refinement_already_started",
    },
    "refinement_submission_failed",
)
CONFIRMATION_TRANSITION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "campaign_not_canonical",
        "local_checkout_mismatch",
        "local_files_changed",
        "remote_response_invalid",
        "confirmation_invalid",
        "confirmation_expired",
        "refinement_chain_not_complete",
        "refine_outputs_pending",
        "refine_outputs_invalid",
        "confirmation_already_prepared",
        "transition_busy",
        "transition_conflict",
        "transition_outcome_unknown",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "Confirmation preparation stopped safely.",
    {
        "transition_busy",
        "transition_conflict",
        "transition_outcome_unknown",
        "confirmation_already_prepared",
    },
    "confirmation_preparation_failed",
)
CONFIRMATION_TRANSITION = _frozen(
    {
        **CONFIRMATION_TRANSITION.entries,
        "zeus_authentication_required": _spec(
            HTTPStatus.PRECONDITION_FAILED, "Confirmation preparation stopped safely."
        ),
    },
    CONFIRMATION_TRANSITION.fallback,
    CONFIRMATION_TRANSITION.fallback_code,
)


def _include_fallback_codes(domain: ErrorDomain, codes: set[str]) -> ErrorDomain:
    """Make every currently emitted public code explicit without changing fallback behavior."""
    if domain.fallback is None:
        raise ValueError("A fallback is required when freezing emitted fallback codes.")
    entries = dict(domain.entries)
    for code in codes:
        entries.setdefault(code, domain.fallback)
    return _frozen(entries, domain.fallback, domain.fallback_code)


TRANSFER = _include_fallback_codes(
    TRANSFER,
    {
        "campaign_commit_invalid",
        "campaign_inputs_changed",
        "campaign_inputs_invalid",
        "campaign_manifest_invalid",
        "campaign_not_portable_smoke",
        "campaign_path_untrusted",
        "campaign_smoke_job_invalid",
        "local_files_changed",
        "local_repository_unavailable",
        "remote_campaign_incomplete",
        "remote_inputs_incomplete",
        "remote_response_invalid",
        "session_invalid",
        "transfer_too_large",
    },
)
SMOKE_SUBMISSION = _include_fallback_codes(
    SMOKE_SUBMISSION, {"local_repository_unavailable", "remote_response_invalid"}
)
SMOKE_TRANSITION = _include_fallback_codes(
    SMOKE_TRANSITION,
    {
        "campaign_not_canonical",
        "campaign_not_smoke",
        "local_files_changed",
        "local_repository_unavailable",
        "remote_response_invalid",
        "request_invalid",
        "profile_invalid",
        "too_many_pending_previews",
        "invalid_request",
        "remote_preparation_invalid",
        "remote_project_missing",
        "smoke_not_submitted",
        "submission_record_invalid",
    },
)
SCREEN_SUBMISSION = _include_fallback_codes(
    SCREEN_SUBMISSION, {"remote_response_invalid", "too_many_pending_previews"}
)
SCREEN_SUBMISSION = _include_fallback_codes(
    SCREEN_SUBMISSION,
    {
        "remote_project_missing",
        "screening_already_started",
        "screening_not_prepared",
        "screening_submission_busy",
        "screening_submission_record_invalid",
        "invalid_request",
        "remote_preparation_invalid",
    },
)
REFINEMENT_TRANSITION = _include_fallback_codes(
    REFINEMENT_TRANSITION, set(TRANSFER.entries)
)
REFINEMENT_TRANSITION = _include_fallback_codes(
    REFINEMENT_TRANSITION, {"invalid_request", "remote_preparation_invalid"}
)
REFINEMENT_SUBMISSION = _include_fallback_codes(
    REFINEMENT_SUBMISSION, set(REFINEMENT_TRANSITION.entries)
)
CONFIRMATION_TRANSITION = _include_fallback_codes(
    CONFIRMATION_TRANSITION, set(REFINEMENT_SUBMISSION.entries)
)
CONFIRMATION_TRANSITION = _include_fallback_codes(
    CONFIRMATION_TRANSITION,
    {"campaign_not_refine", "refine_status_unknown", "submission_record_invalid"},
)

ERROR_DOMAINS: Mapping[str, ErrorDomain] = MappingProxyType(
    {
        "protocol": PROTOCOL,
        "session": SESSION,
        "creation": CREATION,
        "route_unavailable": ROUTE_UNAVAILABLE,
        "snapshot": SNAPSHOT,
        "transfer": TRANSFER,
        "smoke_submission": SMOKE_SUBMISSION,
        "smoke_transition": SMOKE_TRANSITION,
        "screen_submission": SCREEN_SUBMISSION,
        "refinement_transition": REFINEMENT_TRANSITION,
        "refinement_submission": REFINEMENT_SUBMISSION,
        "confirmation_transition": CONFIRMATION_TRANSITION,
    }
)


def catalog_payload() -> dict[str, object]:
    cases = []
    for domain, catalog in ERROR_DOMAINS.items():
        for code, spec in catalog.entries.items():
            cases.append(
                {
                    "domain": domain,
                    "case": code,
                    "code": spec.wire_code or code,
                    "status": int(spec.status),
                    "message": spec.message,
                }
            )
        if catalog.fallback is not None:
            cases.append(
                {
                    "domain": domain,
                    "case": "<fallback>",
                    "code": catalog.fallback_code,
                    "status": int(catalog.fallback.status),
                    "message": catalog.fallback.message,
                }
            )
    return {
        "schema_version": 1,
        "catalog_version": ERROR_CATALOG_VERSION,
        "wire_envelope": "unversioned-error",
        "cases": sorted(cases, key=lambda row: (row["domain"], row["case"])),
    }


def render_catalog() -> str:
    """Return the sole canonical on-disk representation."""
    return json.dumps(catalog_payload(), indent=2, sort_keys=False) + "\n"


@dataclass(frozen=True)
class ResolvedError:
    code: str
    status: HTTPStatus
    message: str


def resolve_error(domain_name: str, case_or_code: object) -> ResolvedError:
    """Resolve a catalog case, failing closed for any untrusted/unknown code.

    The HTTP handler does not call this in P8.2A/B; it defines and tests the
    future migration boundary without changing today's wire behavior.
    """
    domain = ERROR_DOMAINS[domain_name]
    if isinstance(case_or_code, str) and case_or_code in domain.entries:
        spec = domain.entries[case_or_code]
        return ResolvedError(spec.wire_code or case_or_code, spec.status, spec.message)
    if domain.fallback is None or domain.fallback_code is None:
        raise KeyError(
            f"No error case {case_or_code!r} in closed domain {domain_name!r}."
        )
    return ResolvedError(
        domain.fallback_code, domain.fallback.status, domain.fallback.message
    )
