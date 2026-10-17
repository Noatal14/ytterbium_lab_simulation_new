"""Guarded finalist-selection -> final-validation-input transition."""

from __future__ import annotations

import hashlib
from workflow_api.platform_io import os

from workflow_api.mot_3d_discovery_transition import _DIRECTORY_FLAGS, _strict_json
from workflow_api.mot_3d_finalist_results import FINALIST_RESULT_REASON_CODES
from workflow_api.mot_3d_finalist_submission import (
    FILES,
    Mot3DFinalistSubmissionCoordinator,
)
from workflow_api.mot_3d_preliminary_transition import (
    Mot3DPreliminaryTransitionCoordinator,
    Mot3DPreliminaryTransitionError,
    _read_relative,
)
from workflow_api.mot_3d_stage_topology import FINALIST_SELECTION_TOPOLOGY, FAMILIES
from workflow_api.zeus_discovery_submission import canonical_digest

EXPECTED_RESULT_FILES = 44
EXPECTED_TRANSFER_FILES = 50
GENERATED_PATHS = frozenset(
    {
        "campaign.json",
        "selection/locked_nominals.json",
        "jobs/final_validation_inputs/01_generate_zeeman.pbs",
        "jobs/final_validation_inputs/02_generate_2d_survivors.pbs",
        "jobs/final_validation_inputs/03_freeze_inputs.pbs",
    }
)
CODE_PATHS = frozenset(
    {
        "config.py",
        "simulations/mot_3d.py",
        "studies/mot_3d_campaign.py",
        "studies/mot_3d/integrity.py",
        "studies/mot_3d/discovery/optimize.py",
        "studies/mot_3d/finalists/run.py",
        "studies/mot_3d/finalists/merge.py",
        "workflow_api/mot_3d_finalist_results.py",
        "workflow_api/mot_3d_finalist_submission.py",
        "workflow_api/mot_3d_finalist_transition.py",
        "workflow_api/mot_3d_finalist_transition_remote.py",
        "workflow_api/mot_3d_preliminary_transition_remote.py",
        "workflow_api/mot_3d_stage_topology.py",
        "lab_setup/specifications/laboratory_physical_v1.json",
        "lab_setup/specifications/mot_3d_timestep_policy_v1.json",
    }
)


class Mot3DFinalistTransitionError(Mot3DPreliminaryTransitionError):
    pass


class Mot3DFinalistTransitionCoordinator(Mot3DPreliminaryTransitionCoordinator):
    topology = FINALIST_SELECTION_TOPOLOGY
    sync_name = "finalist_selection_to_final_validation_inputs"
    from_stage = "finalist_selection"
    to_stage = "final_validation_input_generation"
    prepared_lifecycle = "final_validation_input_generation_prepared"
    result_reason_codes = FINALIST_RESULT_REASON_CODES
    public_stage_key = "finalist_selection"
    expected_result_files = EXPECTED_RESULT_FILES
    expected_transfer_files = EXPECTED_TRANSFER_FILES
    open_action = "open_final_validation_inputs"
    created_selection_files = 1
    created_job_files = 3
    not_ready_error = "finalist_selection_not_ready"
    effects = {
        "synchronize_finalist_selection": True,
        "prepare_final_validation_inputs": True,
        "submit_final_validation_inputs": False,
        "start_simulation": False,
        "overwrite_existing": False,
    }

    def _preview_extension(self, state):
        selection = state.winner_selection
        if not isinstance(selection, dict):
            raise Mot3DFinalistTransitionError("remote_response_invalid")
        return {"winner_selection": selection}

    def _default_transport(self, profile):
        from workflow_api.mot_3d_finalist_transition_remote_client import (
            PinnedSshMot3DFinalistTransitionTransport,
        )

        return PinnedSshMot3DFinalistTransitionTransport(self.root, self.ssh, profile)

    def __init__(self, *args, transport_factory=None, **kwargs):
        super().__init__(
            *args,
            transport_factory=transport_factory or self._default_transport,
            **kwargs,
        )

    def _plan(self, request):
        try:
            base = Mot3DFinalistSubmissionCoordinator(
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
                transfer_paths = self._expected_paths(campaign_fd)
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
            if len(transfer_paths) != self.expected_transfer_files:
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
                transfer_paths,
            )
        except Mot3DFinalistTransitionError:
            raise
        except Exception as exc:
            raise Mot3DFinalistTransitionError(
                getattr(exc, "code", "finalist_selection_preparation_invalid")
            ) from exc

    def _expected_paths(self, campaign_fd):
        from workflow_api.mot_3d_finalist_results import expected_paths

        selections = {
            family: _strict_json(
                _read_relative(campaign_fd, f"selection/finalists/{family}.json")
            )
            for family in FAMILIES
        }
        return (
            frozenset(expected_paths(selections))
            | {"finalist_selection_submission.json"}
            | GENERATED_PATHS
        )

    def status(self, request):
        try:
            return super().status(request)
        except Mot3DPreliminaryTransitionError as exc:
            raise Mot3DFinalistTransitionError(exc.code) from exc

    def preview(self, request, *, session_id):
        try:
            return super().preview(request, session_id=session_id)
        except Mot3DPreliminaryTransitionError as exc:
            raise Mot3DFinalistTransitionError(exc.code) from exc

    def confirm(self, request, *, session_id):
        try:
            return super().confirm(request, session_id=session_id)
        except Mot3DPreliminaryTransitionError as exc:
            raise Mot3DFinalistTransitionError(exc.code) from exc
