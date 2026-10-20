"""Guarded final-input-generation -> final-validation transition."""

from __future__ import annotations

import json

import hashlib
from workflow_api.platform_io import os
from typing import Mapping

from workflow_api.mot_3d_discovery_transition import _DIRECTORY_FLAGS
from workflow_api.mot_3d_final_input_results import (
    FINAL_INPUT_RESULT_REASON_CODES,
    expected_paths,
)
from workflow_api.mot_3d_final_input_submission import (
    FILES,
    Mot3DFinalInputSubmissionCoordinator,
)
from workflow_api.mot_3d_preliminary_transition import (
    ARRAY,
    HEX64,
    SCALAR,
    MAX_TOTAL_BYTES,
    Mot3DPreliminaryTransitionCoordinator,
    Mot3DPreliminaryTransitionError,
    _matches,
    _read_relative,
)
from workflow_api.mot_3d_final_validation_transition_remote import (
    CODE_PATHS,
    GENERATED_PATHS,
)
from workflow_api.verified_artifact_bundle import (
    MAX_REVIEWED_FILE_BYTES,
    MAX_REVIEWED_TOTAL_BYTES,
)
from workflow_api.zeus_discovery_submission import canonical_digest


class Mot3DFinalValidationTransitionError(Mot3DPreliminaryTransitionError):
    pass


class Mot3DFinalValidationTransitionCoordinator(Mot3DPreliminaryTransitionCoordinator):
    sync_name = "final_validation_inputs_to_final_validation"
    from_stage = "final_validation_input_generation"
    to_stage = "final_validation"
    prepared_lifecycle = "final_validation_prepared"
    result_reason_codes = FINAL_INPUT_RESULT_REASON_CODES
    public_stage_key = "final_validation_input_generation"
    expected_result_files = 101
    expected_transfer_files = 107
    open_action = "open_final_validation"
    created_selection_files = 0
    created_job_files = 4
    not_ready_error = "final_validation_inputs_not_ready"
    bundle_max_total_bytes = MAX_REVIEWED_TOTAL_BYTES
    bundle_max_file_bytes = MAX_REVIEWED_FILE_BYTES
    expected_array_tasks = 40
    expected_merge_jobs = 1
    effects = {
        "synchronize_final_validation_inputs": True,
        "prepare_final_validation": True,
        "submit_final_validation": False,
        "start_simulation": False,
        "overwrite_existing": False,
    }

    def _default_transport(self, profile):
        from workflow_api.mot_3d_final_validation_transition_remote_client import (
            PinnedSshMot3DFinalValidationTransitionTransport,
        )

        return PinnedSshMot3DFinalValidationTransitionTransport(
            self.root, self.ssh, profile
        )

    def __init__(self, *args, transport_factory=None, **kwargs):
        super().__init__(
            *args,
            transport_factory=transport_factory or self._default_transport,
            **kwargs,
        )

    def _plan(self, request):
        try:
            base = Mot3DFinalInputSubmissionCoordinator(
                self.root, self.ssh, self.git, transport_factory=lambda _profile: None
            )._plan(request)
            (
                campaign_id,
                profile,
                campaign,
                manifest,
                commit,
                submission_identity,
                submission_key,
                relative,
            ) = base
            if manifest.get("stage") != self.from_stage:
                raise ValueError
            campaign_fd = os.open(campaign, _DIRECTORY_FLAGS)
            root_fd = os.open(self.root, _DIRECTORY_FLAGS)
            try:
                source_files = {
                    name: hashlib.sha256(_read_relative(campaign_fd, name)).hexdigest()
                    for name in FILES
                }
                code_files = {
                    name: hashlib.sha256(_read_relative(root_fd, name)).hexdigest()
                    for name in CODE_PATHS
                }
            finally:
                os.close(root_fd)
                os.close(campaign_fd)
            identity = {
                "source_files": source_files,
                "code_files": code_files,
                "stage3_local_sync_receipt_sha256": submission_identity[
                    "local_transition_receipt_sha256"
                ],
                "stage3_remote_receipt_sha256": submission_identity[
                    "remote_transition_receipt_sha256"
                ],
                "stage3_bundle_sha256": submission_identity["bundle_sha256"],
                "stage4_submission_identity": submission_identity,
            }
            transition_key = canonical_digest(
                {
                    "campaign": relative,
                    "commit": commit,
                    "submission_key": submission_key,
                    "identity": identity,
                }
            )
            transfer = (
                frozenset(
                    expected_paths(
                        json.loads(_read_relative(campaign_fd, "campaign.json"))
                    )
                )
                | {"final_validation_input_generation_submission.json"}
                | GENERATED_PATHS
            )
            if len(transfer) != self.expected_transfer_files:
                raise ValueError
            return (
                campaign_id,
                profile,
                campaign,
                manifest,
                commit,
                identity,
                submission_key,
                transition_key,
                relative,
                transfer,
            )
        except Mot3DFinalValidationTransitionError:
            raise
        except Exception as exc:
            raise Mot3DFinalValidationTransitionError(
                getattr(exc, "code", "final_validation_input_preparation_invalid")
            ) from exc

    def _expected_paths(self, campaign_fd):
        return (
            frozenset(
                expected_paths(json.loads(_read_relative(campaign_fd, "campaign.json")))
            )
            | {"final_validation_input_generation_submission.json"}
            | GENERATED_PATHS
        )

    @classmethod
    def _public_chain(cls, jobs):
        return {
            "dependency": "afterok linear chain",
            "jobs": [
                {"id": name, "job_id": jobs[name]}
                for name in ("zeeman", "mot_2d", "freeze")
            ],
        }

    @classmethod
    def _validate_state(cls, state, *, allow_chunk=False):
        jobs = state.jobs
        if not isinstance(jobs, Mapping) or set(jobs) != {"zeeman", "mot_2d", "freeze"}:
            raise Mot3DFinalValidationTransitionError("remote_response_invalid")
        if (
            not _matches(ARRAY, jobs["zeeman"])
            or not _matches(ARRAY, jobs["mot_2d"])
            or not _matches(SCALAR, jobs["freeze"])
            or len({value.split("[", 1)[0].split(".", 1)[0] for value in jobs.values()})
            != 3
        ):
            raise Mot3DFinalValidationTransitionError("remote_response_invalid")
        # Reuse the exact lifecycle/receipt checks after presenting the linear
        # chain through the established two-family validation shape.
        proxy = type(state)(
            state.lifecycle,
            state.branch,
            {
                "angled_donut": {"array": jobs["zeeman"], "merge": jobs["freeze"]},
                "single_pass": {"array": jobs["mot_2d"], "merge": jobs["freeze"]},
            },
            state.completed_array_tasks,
            state.completed_merge_jobs,
            state.validation,
            state.reason_code,
            state.evidence_sha256,
            state.receipt,
            state.bundle,
            state.chunk,
            state.winner_selection,
        )
        # Temporarily validate only common DTO invariants; the duplicate scalar
        # is an adapter representation and never exposed publicly.
        Mot3DPreliminaryTransitionCoordinator._validate_state.__func__(
            cls, proxy, allow_chunk=allow_chunk
        )

    def status(self, request):
        try:
            result = super().status(request)
            scheduler = result["scheduler"]
            scheduler["completed_scalar_jobs"] = scheduler.pop("completed_merge_jobs")
            scheduler["expected_scalar_jobs"] = scheduler.pop("expected_merge_jobs")
            return result
        except Mot3DPreliminaryTransitionError as exc:
            raise Mot3DFinalValidationTransitionError(exc.code) from exc

    def preview(self, request, *, session_id):
        try:
            return super().preview(request, session_id=session_id)
        except Mot3DPreliminaryTransitionError as exc:
            raise Mot3DFinalValidationTransitionError(exc.code) from exc

    def confirm(self, request, *, session_id):
        try:
            return super().confirm(request, session_id=session_id)
        except Mot3DPreliminaryTransitionError as exc:
            raise Mot3DFinalValidationTransitionError(exc.code) from exc
