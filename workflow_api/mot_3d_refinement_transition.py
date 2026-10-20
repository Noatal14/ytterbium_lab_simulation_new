"""Guarded local synchronization for Refinement -> Closure."""

from __future__ import annotations

import hashlib
from workflow_api.platform_io import os
from pathlib import Path
from typing import Mapping

from workflow_api.mot_3d_discovery_transition import _DIRECTORY_FLAGS, _strict_json
from workflow_api.mot_3d_preliminary_transition import (
    Mot3DPreliminaryTransitionCoordinator,
    Mot3DPreliminaryTransitionError,
    _read_relative,
)
from workflow_api.mot_3d_refinement_results import REFINEMENT_RESULT_REASON_CODES
from workflow_api.mot_3d_refinement_submission import (
    FILES as REFINEMENT_SUBMISSION_FILES,
    Mot3DRefinementSubmissionCoordinator,
    Mot3DRefinementSubmissionError,
)
from workflow_api.mot_3d_stage_topology import FAMILIES, REFINEMENT_TOPOLOGY
from workflow_api.zeus_discovery_submission import canonical_digest


EXPECTED_TRANSFER_FILES = 208
EXPECTED_RESULT_FILES = 200
GENERATED_PATHS = frozenset(
    {
        "campaign.json",
        *(f"selection/closure/{family}.json" for family in FAMILIES),
        *(
            f"jobs/closure/{family}_{kind}.pbs"
            for family in FAMILIES
            for kind in ("array", "merge")
        ),
    }
)
CODE_PATHS = frozenset(
    {
        "config.py",
        "simulations/mot_3d.py",
        "studies/mot_3d_campaign.py",
        "studies/mot_3d/integrity.py",
        "studies/mot_3d/refinement/run.py",
        "studies/mot_3d/refinement/merge.py",
        "studies/mot_3d/refinement/select_closure.py",
        "workflow_api/mot_3d_refinement_results.py",
        "workflow_api/mot_3d_refinement_submission.py",
        "workflow_api/mot_3d_refinement_transition.py",
        "workflow_api/mot_3d_refinement_transition_remote.py",
        "workflow_api/mot_3d_preliminary_transition_remote.py",
        "workflow_api/mot_3d_stage_topology.py",
        "lab_setup/specifications/laboratory_physical_v1.json",
        "lab_setup/specifications/mot_3d_timestep_policy_v2.json",
    }
)


class Mot3DRefinementTransitionError(Mot3DPreliminaryTransitionError):
    """Closed public error for the Refinement -> Closure transition."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class Mot3DRefinementTransitionCoordinator(Mot3DPreliminaryTransitionCoordinator):
    topology = REFINEMENT_TOPOLOGY
    sync_name = "refinement_to_closure"
    from_stage = "refinement"
    to_stage = "closure"
    prepared_lifecycle = "closure_prepared"
    result_reason_codes = REFINEMENT_RESULT_REASON_CODES
    public_stage_key = "refinement"
    expected_result_files = EXPECTED_RESULT_FILES
    expected_transfer_files = EXPECTED_TRANSFER_FILES
    open_action = "open_closure"
    not_ready_error = "refinement_not_ready"
    effects = {
        "synchronize_refinement": True,
        "prepare_closure": True,
        "submit_closure": False,
        "start_simulation": False,
        "overwrite_existing": False,
    }

    def _default_transport(self, profile):
        from workflow_api.mot_3d_refinement_transition_remote_client import (
            PinnedSshMot3DRefinementTransitionTransport,
        )

        return PinnedSshMot3DRefinementTransitionTransport(self.root, self.ssh, profile)

    def __init__(self, *args, transport_factory=None, **kwargs):
        super().__init__(
            *args,
            transport_factory=transport_factory or self._default_transport,
            **kwargs,
        )

    def _plan(self, request: Mapping[str, object]):
        try:
            base = Mot3DRefinementSubmissionCoordinator(
                self.root,
                self.ssh,
                self.git,
                transport_factory=lambda _profile: None,
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
                    name: _sha(_read_relative(campaign_fd, name))
                    for name in REFINEMENT_SUBMISSION_FILES
                }
                code_files = {
                    name: _sha(_read_relative(root_fd, name)) for name in CODE_PATHS
                }
            finally:
                os.close(root_fd)
                os.close(campaign_fd)
            identity = {
                "source_files": source_files,
                "code_files": code_files,
                # The Stage-4 authority has already descriptor-validated the exact
                # prior sync receipt and rehashed its closed 160-file registry.
                # Reuse that immutable attestation instead of reopening the receipt.
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
        except Mot3DRefinementTransitionError:
            raise
        except (Mot3DRefinementSubmissionError, Exception) as exc:
            raise Mot3DRefinementTransitionError(
                getattr(exc, "code", "refinement_preparation_invalid")
            ) from exc

    def _expected_paths(self, campaign_fd: int) -> frozenset[str]:
        # Keep the HTTP server import boundary free of scientific/study modules.
        from workflow_api.mot_3d_refinement_results import expected_paths

        selections = {
            family: _strict_json(
                _read_relative(campaign_fd, f"selection/refinement/{family}.json")
            )
            for family in FAMILIES
        }
        return (
            frozenset(expected_paths(selections))
            | {"refinement_submission.json"}
            | GENERATED_PATHS
        )

    def status(self, request):
        try:
            return super().status(request)
        except Mot3DPreliminaryTransitionError as exc:
            raise Mot3DRefinementTransitionError(exc.code) from exc

    def preview(self, request, *, session_id: str):
        try:
            return super().preview(request, session_id=session_id)
        except Mot3DPreliminaryTransitionError as exc:
            raise Mot3DRefinementTransitionError(exc.code) from exc

    def confirm(self, request, *, session_id: str):
        try:
            return super().confirm(request, session_id=session_id)
        except Mot3DPreliminaryTransitionError as exc:
            raise Mot3DRefinementTransitionError(exc.code) from exc
