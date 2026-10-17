"""Guarded synchronization and deterministic completion of Final Validation."""

from __future__ import annotations

import hashlib
import math
from workflow_api.platform_io import os
from typing import Mapping

from workflow_api.mot_3d_discovery_transition import _DIRECTORY_FLAGS
from workflow_api.mot_3d_final_validation_results import (
    FINAL_VALIDATION_RESULT_REASON_CODES,
    expected_paths,
)
from workflow_api.mot_3d_final_validation_submission import (
    FILES,
    Mot3DFinalValidationSubmissionCoordinator,
)
from workflow_api.mot_3d_final_validation_completion_remote import (
    CODE_PATHS,
    GENERATED_PATHS,
)
from workflow_api.mot_3d_preliminary_transition import (
    Mot3DPreliminaryTransitionCoordinator,
    Mot3DPreliminaryTransitionError,
    _read_relative,
)
from workflow_api.zeus_discovery_submission import canonical_digest

TERMINAL = frozenset({"complete", "final_validation_extension_required"})


class Mot3DFinalValidationCompletionError(Mot3DPreliminaryTransitionError):
    pass


class Mot3DFinalValidationCompletionCoordinator(Mot3DPreliminaryTransitionCoordinator):
    sync_name = "final_validation_completion"
    from_stage = "final_validation"
    to_stage = "final_validation_completion"
    prepared_lifecycle = "final_validation_completed"
    result_reason_codes = FINAL_VALIDATION_RESULT_REASON_CODES
    public_stage_key = "final_validation"
    expected_result_files = 14
    expected_transfer_files = 17
    open_action = "open_final_report"
    created_selection_files = 0
    created_job_files = 0
    not_ready_error = "final_validation_completion_not_ready"
    expected_array_tasks = 6
    expected_merge_jobs = 2
    effects = {
        "synchronize_final_validation": True,
        "complete_final_validation": True,
        "submit_extension": False,
        "start_simulation": False,
        "overwrite_existing": False,
    }

    def _default_transport(self, profile):
        from workflow_api.mot_3d_final_validation_completion_remote_client import (
            PinnedSshMot3DFinalValidationCompletionTransport,
        )

        return PinnedSshMot3DFinalValidationCompletionTransport(
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
            base = Mot3DFinalValidationSubmissionCoordinator(
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
            if manifest.get("stage") != "final_validation":
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
            # The exact terminal path is chosen only after sealed validation.
            transfer_candidates = (
                frozenset(expected_paths())
                | {"final_validation_submission.json"}
                | GENERATED_PATHS
            )
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
                transfer_candidates,
            )
        except Mot3DFinalValidationCompletionError:
            raise
        except Exception as exc:
            try:
                return self._recovery_plan(request)
            except Exception as recovery_exc:
                raise Mot3DFinalValidationCompletionError(
                    getattr(exc, "code", "final_validation_completion_invalid")
                ) from recovery_exc

    @staticmethod
    def _is_terminal(state):
        return state.lifecycle in TERMINAL or (
            isinstance(state.receipt, Mapping)
            and state.receipt.get("status") in TERMINAL
        )

    def _inspect(self, request, operation="inspect"):
        plan = self._plan(request)
        transport = self.transport_factory(plan[1])
        state = getattr(transport, operation)(**self._payload(plan))
        self._validate_state(state)
        if self._is_terminal(state):
            self._validate_prepared(state, plan)
            if state.lifecycle in TERMINAL:
                state = type(state)(
                    self.prepared_lifecycle,
                    state.branch,
                    state.jobs,
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
        return plan, transport, state

    @classmethod
    def _validate_state(cls, state, *, allow_chunk=False):
        original = state.lifecycle
        if original in TERMINAL:
            state = type(state)(
                cls.prepared_lifecycle,
                state.branch,
                state.jobs,
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
        Mot3DPreliminaryTransitionCoordinator._validate_state.__func__(
            cls, state, allow_chunk=allow_chunk
        )
        detail = state.winner_selection
        if state.validation == "valid":
            if (
                not isinstance(detail, Mapping)
                or set(detail) != {"outcome", "families", "evidence_sha256"}
                or detail["outcome"] not in TERMINAL
                or detail["evidence_sha256"] != state.evidence_sha256
                or not isinstance(detail["families"], list)
                or len(detail["families"]) != 2
            ):
                raise Mot3DFinalValidationCompletionError("remote_response_invalid")
            seen = []
            precision = []
            for row in detail["families"]:
                if (
                    not isinstance(row, Mapping)
                    or set(row)
                    != {
                        "family",
                        "candidate_id",
                        "conditional_efficiency",
                        "bootstrap_95_ci",
                        "ci_half_width",
                        "precision_target_met",
                    }
                    or row["family"] not in {"angled_donut", "single_pass"}
                    or type(row["candidate_id"]) is not str
                    or not row["candidate_id"]
                    or type(row["conditional_efficiency"]) not in {int, float}
                    or not math.isfinite(row["conditional_efficiency"])
                    or not isinstance(row["bootstrap_95_ci"], list)
                    or len(row["bootstrap_95_ci"]) != 2
                    or any(
                        type(value) not in {int, float} or not math.isfinite(value)
                        for value in row["bootstrap_95_ci"]
                    )
                    or type(row["ci_half_width"]) not in {int, float}
                    or not math.isfinite(row["ci_half_width"])
                    or type(row["precision_target_met"]) is not bool
                ):
                    raise Mot3DFinalValidationCompletionError("remote_response_invalid")
                low, high = row["bootstrap_95_ci"]
                estimate = row["conditional_efficiency"]
                half_width = (high - low) / 2.0
                if (
                    not 0.0 <= low <= estimate <= high <= 1.0
                    or row["ci_half_width"] != half_width
                    or row["precision_target_met"] != (half_width <= 0.0075)
                ):
                    raise Mot3DFinalValidationCompletionError("remote_response_invalid")
                seen.append(row["family"])
                precision.append(row["precision_target_met"])
            if seen != ["angled_donut", "single_pass"] or (
                detail["outcome"] == "complete"
            ) != all(precision):
                raise Mot3DFinalValidationCompletionError("remote_response_invalid")
        elif detail is not None:
            raise Mot3DFinalValidationCompletionError("remote_response_invalid")

    @classmethod
    def _validate_prepared(cls, state, plan):
        if not cls._is_terminal(state):
            raise Mot3DFinalValidationCompletionError("remote_response_invalid")
        exact = frozenset(state.receipt.get("files", {}))
        generated = exact - set(expected_paths()) - {"final_validation_submission.json"}
        if generated not in (
            {"campaign.json", "final_report.json"},
            {"campaign.json", "final_validation_status.json"},
        ):
            raise Mot3DFinalValidationCompletionError("remote_response_invalid")
        adjusted = list(plan)
        adjusted[9] = exact
        proxy = type(state)(
            cls.prepared_lifecycle,
            state.branch,
            state.jobs,
            state.completed_array_tasks,
            state.completed_merge_jobs,
            state.validation,
            state.reason_code,
            state.evidence_sha256,
            {**state.receipt, "status": cls.prepared_lifecycle},
            state.bundle,
            state.chunk,
            state.winner_selection,
        )
        Mot3DPreliminaryTransitionCoordinator._validate_prepared.__func__(
            cls, proxy, tuple(adjusted)
        )

    def _synchronize(self, plan, transport, state):
        adjusted = list(plan)
        adjusted[9] = frozenset(state.receipt["files"])
        return super()._synchronize(tuple(adjusted), transport, state)

    def _bundle_to_stage(self, state):
        status = (
            state.receipt.get("status") if isinstance(state.receipt, Mapping) else None
        )
        if status not in TERMINAL:
            raise Mot3DFinalValidationCompletionError("remote_response_invalid")
        return status

    def _expected_paths(self, campaign_fd):
        generated = {"campaign.json"}
        found = []
        for name in ("final_report.json", "final_validation_status.json"):
            try:
                _read_relative(campaign_fd, name)
                found.append(name)
            except FileNotFoundError:
                continue
        if len(found) != 1:
            raise Mot3DFinalValidationCompletionError("local_sync_conflict")
        generated.add(found[0])
        return (
            frozenset(expected_paths())
            | {"final_validation_submission.json"}
            | generated
        )

    @staticmethod
    def _status_action(state, *, outcome, synchronized):
        if synchronized:
            return (
                "open_final_report"
                if outcome == "complete"
                else "review_extension_required"
            )
        if outcome is not None:
            return "synchronize_results"
        if state.lifecycle == "ready_to_advance":
            return "review_completion"
        if state.validation == "scientifically_invalid" or state.lifecycle in {
            "held",
            "completed_failed",
            "status_unknown",
            "outcome_unknown",
            "partial",
        }:
            return "inspect_zeus"
        return "wait"

    def status(self, request):
        plan, _, state = self._inspect(request, "status")
        synchronized = False
        receipt_sha = None
        if self._is_terminal(state):
            receipt_sha = self._verify_local_snapshot(plan[2], state)
            synchronized = receipt_sha is not None
        outcome = state.receipt["status"] if self._is_terminal(state) else None
        return {
            "source": "zeus",
            "campaign": {
                "id": plan[0],
                "name": plan[3]["name"],
                "stage": outcome if synchronized else "final_validation",
            },
            "final_validation": {
                "status": outcome or state.lifecycle,
                "chain": self._public_chain(state.jobs),
            },
            "scheduler": {
                "completed_array_tasks": state.completed_array_tasks,
                "expected_array_tasks": 6,
                "completed_merge_jobs": state.completed_merge_jobs,
                "expected_merge_jobs": 2,
            },
            "validation": {
                "status": state.validation,
                "result_artifacts": 14 if state.validation == "valid" else 0,
                "expected_result_artifacts": 14,
                "reason_code": state.reason_code,
            },
            "completion": {
                "status": outcome or "not_completed",
                "detail": state.winner_selection if synchronized else None,
            },
            "next_action": self._status_action(
                state,
                outcome=outcome,
                synchronized=synchronized,
            ),
            "local_sync": {
                "status": "synchronized" if synchronized else "not_synchronized",
                "receipt_sha256": receipt_sha,
            },
        }

    def preview(self, request, *, session_id):
        result = super().preview(request, session_id=session_id)
        result["to_stage"] = "complete_or_extension_required"
        result["artifacts"]["create"] = {"terminal_files": 1}
        return result

    def _preview_extension(self, state):
        return {"completion": state.winner_selection}

    def confirm(self, request, *, session_id):
        record = (
            self._previews.get(request.get("preview_token"))
            if isinstance(request, Mapping)
            else None
        )
        pending = record.value if record else None
        result = super().confirm(request, session_id=session_id)
        if pending is None:
            raise Mot3DFinalValidationCompletionError("confirmation_invalid")
        campaign = self.root / pending.relative
        campaign_fd = os.open(campaign, _DIRECTORY_FLAGS)
        try:
            try:
                _read_relative(campaign_fd, "final_report.json")
                outcome = "complete"
            except FileNotFoundError:
                _read_relative(campaign_fd, "final_validation_status.json")
                outcome = "final_validation_extension_required"
        finally:
            os.close(campaign_fd)
        result["status"] = outcome
        result["stage"] = outcome
        return result
