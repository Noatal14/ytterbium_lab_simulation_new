"""Guarded local synchronization for Closure -> finalist selection."""

from __future__ import annotations

import hashlib
from workflow_api.platform_io import os

from workflow_api.mot_3d_closure_results import CLOSURE_RESULT_REASON_CODES
from workflow_api.mot_3d_closure_submission import (
    FILES,
    Mot3DClosureSubmissionCoordinator,
    Mot3DClosureSubmissionError,
)
from workflow_api.mot_3d_discovery_transition import _DIRECTORY_FLAGS, _strict_json
from workflow_api.mot_3d_preliminary_transition import (
    Mot3DPreliminaryTransitionCoordinator,
    Mot3DPreliminaryTransitionError,
    _read_relative,
)
from workflow_api.mot_3d_stage_topology import CLOSURE_TOPOLOGY, FAMILIES
from workflow_api.zeus_discovery_submission import canonical_digest

EXPECTED_RESULT_FILES = 200
EXPECTED_TRANSFER_FILES = 208
GENERATED_PATHS = frozenset(
    {
        "campaign.json",
        *(f"selection/finalists/{family}.json" for family in FAMILIES),
        *(
            f"jobs/finalist_selection/{family}_{kind}.pbs"
            for family in FAMILIES
            for kind in ("array", "merge")
        ),
    }
)
CODE_PATHS = frozenset(
    {
        "workflow_api/mot_3d_selection_submission_remote.py",
        "config.py",
        "simulations/mot_3d.py",
        "studies/mot_3d_campaign.py",
        "studies/mot_3d/integrity.py",
        "studies/mot_3d/discovery/optimize.py",
        "utils/optuna_replay.py",
        "studies/mot_3d/refinement/run.py",
        "studies/mot_3d/refinement/merge.py",
        "studies/mot_3d/finalists/select.py",
        "workflow_api/mot_3d_closure_results.py",
        "workflow_api/mot_3d_refinement_results.py",
        "workflow_api/mot_3d_closure_submission.py",
        "workflow_api/mot_3d_closure_transition.py",
        "workflow_api/mot_3d_closure_transition_remote.py",
        "workflow_api/mot_3d_preliminary_transition_remote.py",
        "workflow_api/mot_3d_stage_topology.py",
        "lab_setup/specifications/laboratory_physical_v1.json",
        "lab_setup/specifications/mot_3d_timestep_policy_v2.json",
    }
)


class Mot3DClosureTransitionError(Mot3DPreliminaryTransitionError):
    pass


class Mot3DClosureTransitionCoordinator(Mot3DPreliminaryTransitionCoordinator):
    topology = CLOSURE_TOPOLOGY
    sync_name = "closure_to_finalist_selection"
    from_stage = "closure"
    to_stage = "finalist_selection"
    prepared_lifecycle = "finalist_selection_prepared"
    result_reason_codes = CLOSURE_RESULT_REASON_CODES
    public_stage_key = "closure"
    expected_result_files = EXPECTED_RESULT_FILES
    expected_transfer_files = EXPECTED_TRANSFER_FILES
    open_action = "open_finalist_selection"
    not_ready_error = "closure_not_ready"
    effects = {
        "synchronize_closure": True,
        "prepare_finalist_selection": True,
        "submit_finalists": False,
        "start_simulation": False,
        "overwrite_existing": False,
    }

    def _default_transport(self, profile):
        from workflow_api.mot_3d_closure_transition_remote_client import (
            PinnedSshMot3DClosureTransitionTransport,
        )

        return PinnedSshMot3DClosureTransitionTransport(self.root, self.ssh, profile)

    def __init__(self, *args, transport_factory=None, **kwargs):
        super().__init__(
            *args,
            transport_factory=transport_factory or self._default_transport,
            **kwargs,
        )

    def _plan(self, request):
        try:
            base = Mot3DClosureSubmissionCoordinator(
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
            campaign_fd, root_fd = os.open(campaign, _DIRECTORY_FLAGS), os.open(
                self.root, _DIRECTORY_FLAGS
            )
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
                # Legacy-neutral names are retained by the shared transition
                # engine; their values are the immediately preceding guarded
                # transition/submission authority for this stage.
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
            campaign_fd = os.open(campaign, _DIRECTORY_FLAGS)
            try:
                transfer_paths = self._expected_paths(campaign_fd)
            finally:
                os.close(campaign_fd)
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
        except Mot3DClosureTransitionError:
            raise
        except Exception as exc:
            raise Mot3DClosureTransitionError(
                getattr(exc, "code", "closure_preparation_invalid")
            ) from exc

    def _expected_paths(self, campaign_fd):
        from workflow_api.mot_3d_closure_results import expected_paths

        selections = {
            family: _strict_json(
                _read_relative(campaign_fd, f"selection/closure/{family}.json")
            )
            for family in FAMILIES
        }
        return (
            frozenset(expected_paths(selections))
            | {"closure_submission.json"}
            | GENERATED_PATHS
        )

    def status(self, request):
        try:
            return super().status(request)
        except Mot3DPreliminaryTransitionError as exc:
            raise Mot3DClosureTransitionError(exc.code) from exc

    def preview(self, request, *, session_id):
        try:
            return super().preview(request, session_id=session_id)
        except Mot3DPreliminaryTransitionError as exc:
            raise Mot3DClosureTransitionError(exc.code) from exc

    def confirm(self, request, *, session_id):
        try:
            return super().confirm(request, session_id=session_id)
        except Mot3DPreliminaryTransitionError as exc:
            raise Mot3DClosureTransitionError(exc.code) from exc
