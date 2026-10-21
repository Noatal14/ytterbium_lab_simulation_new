"""Frozen v1 error semantics for the local workflow API.

The HTTP handler uses this catalog as the authoritative mapping from internal
workflow failures to stable public API errors.
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

LOCAL_READ = _frozen(
    {
        "invalid_campaign_id": _spec(
            HTTPStatus.BAD_REQUEST, "Campaign identifier is invalid."
        ),
        "campaign_not_found": _spec(HTTPStatus.NOT_FOUND, "Campaign was not found."),
        "invalid_manifest#not_regular": ErrorSpec(
            HTTPStatus.BAD_REQUEST,
            "Campaign record is not a trusted regular file.",
            "invalid_manifest",
        ),
        "invalid_manifest#json": ErrorSpec(
            HTTPStatus.BAD_REQUEST,
            "Campaign record is not valid JSON.",
            "invalid_manifest",
        ),
        "invalid_manifest#object": ErrorSpec(
            HTTPStatus.BAD_REQUEST,
            "Campaign record must contain a JSON object.",
            "invalid_manifest",
        ),
        "unavailable_manifest": _spec(
            HTTPStatus.BAD_REQUEST, "Campaign record is unavailable."
        ),
        "oversized_manifest": _spec(
            HTTPStatus.BAD_REQUEST, "Campaign record is too large to inspect safely."
        ),
        "unsupported_campaign": _spec(
            HTTPStatus.BAD_REQUEST, "Campaign record has an unsupported workflow kind."
        ),
        "invalid_campaign": _spec(
            HTTPStatus.BAD_REQUEST,
            "Campaign files could not be validated for inspection.",
        ),
    },
    _spec(HTTPStatus.INTERNAL_SERVER_ERROR, "Campaign inspection failed safely."),
    "inspection_failed",
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
        "local_files_changed": _spec(
            HTTPStatus.PRECONDITION_FAILED,
            "Reviewed simulation files have uncommitted changes. Commit or stash them, then validate again.",
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
        "invalid_request#laboratory_provenance": ErrorSpec(
            HTTPStatus.PRECONDITION_FAILED,
            "This source cannot create a new campaign without explicit laboratory provenance. Select a source with verified laboratory provenance; existing campaigns can still use this source.",
            "invalid_request",
        ),
        "invalid_request#source_unavailable": ErrorSpec(
            HTTPStatus.BAD_REQUEST,
            "The selected Zeeman source is unavailable.",
            "invalid_request",
        ),
        "invalid_request#profile_fields": ErrorSpec(
            HTTPStatus.BAD_REQUEST,
            "Connection profile fields are invalid.",
            "invalid_request",
        ),
        "invalid_request#username": ErrorSpec(
            HTTPStatus.BAD_REQUEST, "Technion username is invalid.", "invalid_request"
        ),
        "invalid_request#project_directory": ErrorSpec(
            HTTPStatus.BAD_REQUEST,
            "Remote project directory is invalid.",
            "invalid_request",
        ),
        "invalid_request#project_checkout": ErrorSpec(
            HTTPStatus.BAD_REQUEST,
            "Remote project directory does not match the supported Zeus checkout.",
            "invalid_request",
        ),
    },
    _spec(HTTPStatus.PRECONDITION_FAILED, "Local campaign creation failed safely."),
    "creation_failed",
)

ROUTE_UNAVAILABLE = _frozen(
    {
        "creation_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE, "Local campaign creation is unavailable."
        ),
        "mot_3d_bootstrap_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE, "3D campaign preparation is unavailable."
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
        "zeus_confirmation_submission_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "Zeus confirmation submission is unavailable.",
        ),
        "zeus_sensitivity_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "Zeus Sensitivity preparation is unavailable.",
        ),
        "zeus_sensitivity_submission_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "Zeus Sensitivity submission is unavailable.",
        ),
        "zeus_production_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "Zeus Production preparation is unavailable.",
        ),
        "zeus_production_submission_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE, "Zeus Production submission is unavailable."
        ),
        "zeus_finalization_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE, "Zeus campaign finalization is unavailable."
        ),
        "zeus_mot_3d_discovery_submission_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "Zeus 3D Discovery submission is unavailable.",
        ),
        "mot_3d_discovery_transition_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "3D Discovery result synchronization is unavailable.",
        ),
        "mot_3d_preliminary_submission_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "3D Preliminary-check submission is unavailable.",
        ),
        "mot_3d_refinement_submission_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "3D Refinement submission is unavailable.",
        ),
        "mot_3d_closure_submission_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "3D Closure submission is unavailable.",
        ),
        "mot_3d_finalist_submission_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "3D Finalist Selection submission is unavailable.",
        ),
        "mot_3d_final_validation_submission_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "3D Final Validation submission is unavailable.",
        ),
        "mot_3d_preliminary_transition_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "3D Preliminary-check result synchronization is unavailable.",
        ),
        "mot_3d_refinement_transition_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "3D Refinement result synchronization is unavailable.",
        ),
        "mot_3d_closure_transition_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "3D Closure result synchronization is unavailable.",
        ),
        "mot_3d_finalist_transition_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "3D Finalist result synchronization is unavailable.",
        ),
        "mot_3d_final_input_submission_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "3D final-validation input submission is unavailable.",
        ),
        "mot_3d_final_validation_transition_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "3D final-validation preparation is unavailable.",
        ),
        "mot_3d_final_validation_completion_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "3D final-validation completion is unavailable.",
        ),
        "individual_zeeman_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "Individual Zeeman runs are unavailable.",
        ),
        "individual_mot_2d_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "Individual 2D-MOT runs are unavailable.",
        ),
        "individual_mot_3d_unavailable": _spec(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "Individual 3D-MOT runs are unavailable.",
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
    _spec(HTTPStatus.PRECONDITION_FAILED, "Zeus preparation could not be verified."),
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
    _spec(HTTPStatus.PRECONDITION_FAILED, "Zeus smoke submission could not be verified."),
    "zeus_submission_failed",
)

SMOKE_TRANSITION = _frozen(
    {
        "request_invalid": _spec(
            HTTPStatus.BAD_REQUEST,
            "Smoke inspection or screening preparation could not be verified.",
        ),
        "profile_invalid": _spec(
            HTTPStatus.BAD_REQUEST,
            "Smoke inspection or screening preparation could not be verified.",
        ),
        "campaign_not_found": _spec(
            HTTPStatus.NOT_FOUND,
            "Smoke inspection or screening preparation could not be verified.",
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
        "Smoke inspection or screening preparation could not be verified.",
    ),
    "zeus_screening_failed",
)

SCREEN_SUBMISSION = _frozen(
    {
        "request_invalid": _spec(
            HTTPStatus.BAD_REQUEST, "Screening submission could not be verified."
        ),
        "profile_invalid": _spec(
            HTTPStatus.BAD_REQUEST, "Screening submission could not be verified."
        ),
        "campaign_not_found": _spec(
            HTTPStatus.NOT_FOUND, "Screening submission could not be verified."
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
    _spec(HTTPStatus.PRECONDITION_FAILED, "Screening submission could not be verified."),
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
        entries[code] = _spec(status, (
            "The operation outcome is unknown. Check the current campaign status. "
            "Do not retry or submit again automatically."
        ) if code.endswith("_outcome_unknown") else message)
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
    "Refinement preparation could not be verified.",
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
        "transition_outcome_unknown",
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
    "Refinement submission could not be verified.",
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
        "refinement_submission_outcome_unknown",
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
    "Confirmation preparation could not be verified.",
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
            HTTPStatus.PRECONDITION_FAILED, "Confirmation preparation could not be verified."
        ),
    },
    CONFIRMATION_TRANSITION.fallback,
    CONFIRMATION_TRANSITION.fallback_code,
)
CONFIRMATION_SUBMISSION = _generic_stage(
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
        "confirmation_not_prepared",
        "confirmation_preparation_invalid",
        "confirmation_already_submitted",
        "confirmation_submission_busy",
        "confirmation_submission_outcome_unknown",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "Confirmation submission could not be verified.",
    {
        "confirmation_already_submitted",
        "confirmation_submission_busy",
        "confirmation_submission_outcome_unknown",
    },
    "confirmation_submission_failed",
)
SENSITIVITY_TRANSITION = _generic_stage(
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
        "confirmation_not_complete",
        "confirmation_outputs_pending",
        "confirmation_outputs_invalid",
        "sensitivity_already_prepared",
        "transition_busy",
        "transition_conflict",
        "transition_outcome_unknown",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "Sensitivity preparation could not be verified.",
    {
        "sensitivity_already_prepared",
        "transition_busy",
        "transition_conflict",
        "transition_outcome_unknown",
    },
    "sensitivity_preparation_failed",
)
SENSITIVITY_SUBMISSION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "campaign_not_canonical",
        "local_checkout_mismatch",
        "local_files_changed",
        "remote_response_invalid",
        "too_many_pending_previews",
        "sensitivity_invalid",
        "sensitivity_expired",
        "sensitivity_not_prepared",
        "sensitivity_preparation_invalid",
        "sensitivity_already_submitted",
        "sensitivity_submission_busy",
        "sensitivity_submission_outcome_unknown",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "Sensitivity submission could not be verified.",
    {
        "sensitivity_already_submitted",
        "sensitivity_submission_busy",
        "sensitivity_submission_outcome_unknown",
    },
    "sensitivity_submission_failed",
)
PRODUCTION_TRANSITION = _generic_stage(
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
        "sensitivity_not_complete",
        "sensitivity_preparation_invalid",
        "transition_busy",
        "transition_conflict",
        "transition_outcome_unknown",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "Production preparation could not be verified.",
    {"transition_busy", "transition_conflict", "transition_outcome_unknown"},
    "production_preparation_failed",
)
PRODUCTION_SUBMISSION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "campaign_not_canonical",
        "local_checkout_mismatch",
        "local_files_changed",
        "remote_response_invalid",
        "too_many_pending_previews",
        "production_invalid",
        "production_expired",
        "production_not_prepared",
        "production_preparation_invalid",
        "production_already_submitted",
        "production_submission_busy",
        "production_submission_outcome_unknown",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "Production submission could not be verified.",
    {
        "production_already_submitted",
        "production_submission_busy",
        "production_submission_outcome_unknown",
    },
    "production_submission_failed",
)
FINALIZATION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "campaign_not_canonical",
        "local_checkout_mismatch",
        "remote_response_invalid",
        "too_many_pending_previews",
        "confirmation_invalid",
        "confirmation_expired",
        "production_not_complete",
        "remote_files_changed",
        "finalization_outcome_unknown",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "Campaign finalization could not be verified.",
    {"remote_files_changed", "finalization_outcome_unknown"},
    "finalization_failed",
)
MOT_3D_DISCOVERY_SUBMISSION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "discovery_not_prepared",
        "discovery_preparation_invalid",
        "discovery_already_submitted",
        "discovery_submission_outcome_unknown",
        "remote_response_invalid",
        "too_many_pending_previews",
        "discovery_invalid",
        "discovery_expired",
        "local_files_changed",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "3D Discovery submission could not be verified.",
    {"discovery_already_submitted", "discovery_submission_outcome_unknown"},
    "mot_3d_discovery_submission_failed",
)
MOT_3D_DISCOVERY_TRANSITION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "discovery_not_prepared",
        "discovery_preparation_invalid",
        "discovery_not_complete",
        "remote_response_invalid",
        "too_many_pending_previews",
        "confirmation_invalid",
        "confirmation_expired",
        "local_or_remote_evidence_changed",
        "transition_busy",
        "transition_conflict",
        "transition_outcome_unknown",
        "transition_bundle_too_large",
        "local_sync_conflict",
        "local_sync_outcome_unknown",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "3D Discovery result synchronization could not be verified.",
    {
        "transition_busy",
        "transition_conflict",
        "transition_outcome_unknown",
        "local_sync_conflict",
        "local_sync_outcome_unknown",
    },
    "mot_3d_discovery_transition_failed",
)
MOT_3D_PRELIMINARY_SUBMISSION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "preliminary_preparation_invalid",
        "preliminary_already_started",
        "preliminary_partial_submission",
        "preliminary_submission_outcome_unknown",
        "remote_checkout_mismatch",
        "remote_response_invalid",
        "local_files_changed",
        "too_many_pending_previews",
        "confirmation_invalid",
        "confirmation_expired",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "3D Preliminary-check submission could not be verified.",
    {
        "preliminary_already_started",
        "preliminary_partial_submission",
        "preliminary_submission_outcome_unknown",
    },
    "mot_3d_preliminary_submission_failed",
)
MOT_3D_REFINEMENT_SUBMISSION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "refinement_preparation_invalid",
        "refinement_already_started",
        "refinement_partial_submission",
        "refinement_submission_outcome_unknown",
        "remote_checkout_mismatch",
        "remote_response_invalid",
        "local_files_changed",
        "too_many_pending_previews",
        "confirmation_invalid",
        "confirmation_expired",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "3D Refinement submission could not be verified.",
    {
        "refinement_already_started",
        "refinement_partial_submission",
        "refinement_submission_outcome_unknown",
    },
    "mot_3d_refinement_submission_failed",
)
MOT_3D_CLOSURE_SUBMISSION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "closure_preparation_invalid",
        "closure_already_started",
        "closure_partial_submission",
        "closure_submission_outcome_unknown",
        "remote_checkout_mismatch",
        "remote_response_invalid",
        "local_files_changed",
        "too_many_pending_previews",
        "confirmation_invalid",
        "confirmation_expired",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "3D Closure submission could not be verified.",
    {
        "closure_already_started",
        "closure_partial_submission",
        "closure_submission_outcome_unknown",
    },
    "mot_3d_closure_submission_failed",
)
MOT_3D_FINALIST_SUBMISSION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "finalist_selection_preparation_invalid",
        "finalist_selection_already_started",
        "finalist_selection_partial_submission",
        "finalist_selection_submission_outcome_unknown",
        "remote_checkout_mismatch",
        "remote_response_invalid",
        "local_files_changed",
        "too_many_pending_previews",
        "confirmation_invalid",
        "confirmation_expired",
        "zeus_authentication_required",
        "zeus_host_key_untrusted",
        "zeus_timeout",
        "zeus_unreachable",
    },
    "3D Finalist Selection submission could not be verified.",
    {
        "finalist_selection_already_started",
        "finalist_selection_partial_submission",
        "finalist_selection_submission_outcome_unknown",
    },
    "mot_3d_finalist_submission_failed",
)
MOT_3D_FINAL_VALIDATION_SUBMISSION = _generic_stage(
    {
        "request_invalid", "profile_invalid", "campaign_not_found",
        "final_validation_preparation_invalid", "final_validation_already_started",
        "final_validation_partial_submission", "final_validation_submission_outcome_unknown",
        "remote_checkout_mismatch", "remote_response_invalid", "local_files_changed",
        "too_many_pending_previews", "confirmation_invalid", "confirmation_expired",
        "zeus_authentication_required", "zeus_host_key_untrusted", "zeus_timeout",
        "zeus_unreachable",
    },
    "3D Final Validation submission could not be verified.",
    {"final_validation_already_started", "final_validation_partial_submission",
     "final_validation_submission_outcome_unknown"},
    "mot_3d_final_validation_submission_failed",
)
MOT_3D_PRELIMINARY_TRANSITION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "preliminary_not_ready",
        "preliminary_already_started",
        "preliminary_partial_submission",
        "preliminary_submission_outcome_unknown",
        "preliminary_preparation_invalid",
        "remote_response_invalid",
        "local_files_changed",
        "too_many_pending_previews",
        "confirmation_invalid",
        "confirmation_expired",
        "local_or_remote_evidence_changed",
        "local_sync_conflict",
        "local_sync_outcome_unknown",
        "transition_outcome_unknown",
        "invalid_request",
        "remote_checkout_mismatch",
        "preliminary_transition_conflict",
        "preliminary_transition_busy",
        "preliminary_transition_outcome_unknown",
        "preliminary_transition_not_prepared",
        "zeus_unavailable",
        "zeus_timeout",
    },
    "3D Preliminary-check result synchronization could not be verified.",
    {
        "preliminary_transition_conflict",
        "preliminary_transition_busy",
        "preliminary_transition_outcome_unknown",
        "transition_outcome_unknown",
        "preliminary_already_started",
        "preliminary_partial_submission",
        "preliminary_submission_outcome_unknown",
        "local_sync_conflict",
        "local_sync_outcome_unknown",
    },
    "mot_3d_preliminary_transition_failed",
)
MOT_3D_REFINEMENT_TRANSITION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "refinement_not_ready",
        "refinement_already_started",
        "refinement_partial_submission",
        "refinement_submission_outcome_unknown",
        "refinement_preparation_invalid",
        "remote_response_invalid",
        "local_files_changed",
        "too_many_pending_previews",
        "confirmation_invalid",
        "confirmation_expired",
        "local_or_remote_evidence_changed",
        "local_sync_conflict",
        "local_sync_outcome_unknown",
        "transition_outcome_unknown",
        "invalid_request",
        "remote_checkout_mismatch",
        "refinement_transition_conflict",
        "refinement_transition_busy",
        "refinement_transition_outcome_unknown",
        "refinement_transition_not_prepared",
        "zeus_unavailable",
        "zeus_timeout",
    },
    "3D Refinement result synchronization could not be verified.",
    {
        "refinement_transition_conflict",
        "refinement_transition_busy",
        "refinement_transition_outcome_unknown",
        "transition_outcome_unknown",
        "refinement_already_started",
        "refinement_partial_submission",
        "refinement_submission_outcome_unknown",
        "local_sync_conflict",
        "local_sync_outcome_unknown",
    },
    "mot_3d_refinement_transition_failed",
)
MOT_3D_CLOSURE_TRANSITION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "closure_not_ready",
        "closure_already_started",
        "closure_partial_submission",
        "closure_submission_outcome_unknown",
        "closure_preparation_invalid",
        "remote_response_invalid",
        "local_files_changed",
        "too_many_pending_previews",
        "confirmation_invalid",
        "confirmation_expired",
        "local_or_remote_evidence_changed",
        "local_sync_conflict",
        "local_sync_outcome_unknown",
        "transition_outcome_unknown",
        "invalid_request",
        "remote_checkout_mismatch",
        "closure_transition_conflict",
        "closure_transition_busy",
        "closure_transition_outcome_unknown",
        "closure_transition_not_prepared",
        "zeus_unavailable",
        "zeus_timeout",
    },
    "3D Closure result synchronization could not be verified.",
    {
        "closure_transition_conflict",
        "closure_transition_busy",
        "closure_transition_outcome_unknown",
        "transition_outcome_unknown",
        "closure_already_started",
        "closure_partial_submission",
        "closure_submission_outcome_unknown",
        "local_sync_conflict",
        "local_sync_outcome_unknown",
    },
    "mot_3d_closure_transition_failed",
)
MOT_3D_FINALIST_TRANSITION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "finalist_selection_not_ready",
        "finalist_selection_already_started",
        "finalist_selection_partial_submission",
        "finalist_selection_submission_outcome_unknown",
        "finalist_selection_preparation_invalid",
        "remote_response_invalid",
        "local_files_changed",
        "too_many_pending_previews",
        "confirmation_invalid",
        "confirmation_expired",
        "local_or_remote_evidence_changed",
        "local_sync_conflict",
        "local_sync_outcome_unknown",
        "transition_outcome_unknown",
        "invalid_request",
        "remote_checkout_mismatch",
        "finalist_transition_conflict",
        "finalist_transition_busy",
        "finalist_transition_outcome_unknown",
        "finalist_transition_not_prepared",
        "zeus_unavailable",
        "zeus_timeout",
    },
    "3D Finalist result synchronization could not be verified.",
    {
        "finalist_transition_conflict",
        "finalist_transition_busy",
        "finalist_transition_outcome_unknown",
        "transition_outcome_unknown",
        "finalist_selection_already_started",
        "finalist_selection_partial_submission",
        "finalist_selection_submission_outcome_unknown",
        "local_sync_conflict",
        "local_sync_outcome_unknown",
    },
    "mot_3d_finalist_transition_failed",
)
MOT_3D_FINAL_INPUT_SUBMISSION = _generic_stage(
    {
        "request_invalid",
        "profile_invalid",
        "campaign_not_found",
        "final_input_preparation_invalid",
        "local_files_changed",
        "remote_response_invalid",
        "final_input_already_started",
        "final_input_partial_submission",
        "final_input_submission_outcome_unknown",
        "too_many_pending_previews",
        "confirmation_invalid",
        "confirmation_expired",
        "local_or_remote_evidence_changed",
        "invalid_request",
        "remote_checkout_mismatch",
        "final_input_submission_conflict",
        "final_input_submission_busy",
        "zeus_unavailable",
        "zeus_timeout",
    },
    "3D final-validation input submission could not be verified.",
    {
        "final_input_partial_submission",
        "final_input_submission_outcome_unknown",
        "final_input_submission_conflict",
        "final_input_submission_busy",
    },
    "mot_3d_final_input_submission_failed",
)
MOT_3D_FINAL_VALIDATION_TRANSITION = _generic_stage(
    {
        "request_invalid", "profile_invalid", "campaign_not_found",
        "final_validation_inputs_not_ready", "final_input_preparation_invalid",
        "final_input_already_started", "final_input_partial_submission",
        "final_input_submission_outcome_unknown", "remote_response_invalid",
        "local_files_changed", "too_many_pending_previews", "confirmation_invalid",
        "confirmation_expired", "local_or_remote_evidence_changed",
        "local_sync_conflict", "local_sync_outcome_unknown",
        "transition_outcome_unknown", "invalid_request", "remote_checkout_mismatch",
        "final_validation_transition_conflict", "final_validation_transition_busy",
        "final_validation_transition_outcome_unknown",
        "final_validation_transition_not_prepared", "zeus_unavailable", "zeus_timeout",
    },
    "3D final-validation preparation could not be verified.",
    {
        "final_input_partial_submission", "final_input_submission_outcome_unknown",
        "final_validation_transition_conflict", "final_validation_transition_busy",
        "final_validation_transition_outcome_unknown", "transition_outcome_unknown",
        "local_sync_conflict", "local_sync_outcome_unknown",
    },
    "mot_3d_final_validation_transition_failed",
)
MOT_3D_FINAL_VALIDATION_COMPLETION = _generic_stage(
    {
        "request_invalid", "profile_invalid", "campaign_not_found",
        "final_validation_completion_not_ready", "final_validation_preparation_invalid",
        "final_validation_already_started", "final_validation_partial_submission",
        "final_validation_submission_outcome_unknown", "remote_response_invalid",
        "local_files_changed", "too_many_pending_previews", "confirmation_invalid",
        "confirmation_expired", "local_or_remote_evidence_changed",
        "local_sync_conflict", "local_sync_outcome_unknown",
        "transition_outcome_unknown", "invalid_request", "remote_checkout_mismatch",
        "final_validation_completion_invalid",
        "final_validation_completion_conflict", "final_validation_completion_busy",
        "final_validation_completion_outcome_unknown",
        "final_validation_completion_not_prepared", "zeus_unavailable", "zeus_timeout",
    },
    "3D final-validation completion could not be verified.",
    {
        "final_validation_partial_submission", "final_validation_submission_outcome_unknown",
        "final_validation_completion_conflict", "final_validation_completion_busy",
        "final_validation_completion_outcome_unknown", "transition_outcome_unknown",
        "local_sync_conflict", "local_sync_outcome_unknown",
    },
    "mot_3d_final_validation_completion_failed",
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
        "campaign_not_canonical",
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
        "local_read": LOCAL_READ,
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
        "confirmation_submission": CONFIRMATION_SUBMISSION,
        "sensitivity_transition": SENSITIVITY_TRANSITION,
        "sensitivity_submission": SENSITIVITY_SUBMISSION,
        "production_transition": PRODUCTION_TRANSITION,
        "production_submission": PRODUCTION_SUBMISSION,
        "finalization": FINALIZATION,
        "mot_3d_discovery_submission": MOT_3D_DISCOVERY_SUBMISSION,
        "mot_3d_discovery_transition": MOT_3D_DISCOVERY_TRANSITION,
        "mot_3d_preliminary_submission": MOT_3D_PRELIMINARY_SUBMISSION,
        "mot_3d_refinement_submission": MOT_3D_REFINEMENT_SUBMISSION,
        "mot_3d_closure_submission": MOT_3D_CLOSURE_SUBMISSION,
        "mot_3d_finalist_submission": MOT_3D_FINALIST_SUBMISSION,
        "mot_3d_final_validation_submission": MOT_3D_FINAL_VALIDATION_SUBMISSION,
        "mot_3d_preliminary_transition": MOT_3D_PRELIMINARY_TRANSITION,
        "mot_3d_refinement_transition": MOT_3D_REFINEMENT_TRANSITION,
        "mot_3d_closure_transition": MOT_3D_CLOSURE_TRANSITION,
        "mot_3d_finalist_transition": MOT_3D_FINALIST_TRANSITION,
        "mot_3d_final_input_submission": MOT_3D_FINAL_INPUT_SUBMISSION,
        "mot_3d_final_validation_transition": MOT_3D_FINAL_VALIDATION_TRANSITION,
        "mot_3d_final_validation_completion": MOT_3D_FINAL_VALIDATION_COMPLETION,
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


def resolve_wire_error(
    domain_name: str, wire_code: object, message: object
) -> ResolvedError:
    """Resolve a closed, already-safe wire pair without passing it through."""
    domain = ERROR_DOMAINS[domain_name]
    matches = [
        (case, spec)
        for case, spec in domain.entries.items()
        if (spec.wire_code or case) == wire_code and spec.message == message
    ]
    if len(matches) != 1:
        return resolve_error(domain_name, object())
    case, _ = matches[0]
    return resolve_error(domain_name, case)
