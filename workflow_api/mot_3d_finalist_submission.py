"""Guarded submission facade for the canonical 3D finalist-selection chain."""

from __future__ import annotations

from workflow_api import mot_3d_workload as workload

from workflow_api.mot_3d_closure_submission import (
    Mot3DClosureSubmissionCoordinator,
    Mot3DClosureSubmissionError,
)
from workflow_api.mot_3d_closure_transition import Mot3DClosureTransitionCoordinator
from workflow_api.mot_3d_selection_submission import validate_selection_submission_state
from workflow_api.mot_3d_stage_topology import (
    FAMILIES,
    FINALIST_SELECTION_SCIENTIFIC_DESIGN,
    FINALIST_SELECTION_TOPOLOGY,
)

FILES = frozenset(
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
CODE_FILES = frozenset(
    {
        "config.py",
        "simulations/mot_3d.py",
        "studies/mot_3d_campaign.py",
        "studies/mot_3d/integrity.py",
        "studies/mot_3d/finalists/run.py",
        "studies/mot_3d/finalists/merge.py",
        "studies/mot_3d/finalists/select.py",
        "studies/mot_3d/discovery/optimize.py",
        "workflow_api/mot_3d_closure_results.py",
        "workflow_api/mot_3d_closure_transition.py",
        "workflow_api/mot_3d_closure_transition_remote.py",
        "workflow_api/mot_3d_stage_topology.py",
        "workflow_api/mot_3d_selection_submission.py",
        "workflow_api/mot_3d_finalist_submission.py",
        "workflow_api/mot_3d_selection_submission_remote.py",
        "workflow_api/mot_3d_finalist_submission_remote.py",
        "lab_setup/specifications/laboratory_physical_v1.json",
        "lab_setup/specifications/mot_3d_timestep_policy_v2.json",
    }
)


class Mot3DFinalistSubmissionError(Mot3DClosureSubmissionError):
    """Closed public error for finalist-selection submission."""


class Mot3DFinalistSubmissionCoordinator(Mot3DClosureSubmissionCoordinator):
    topology = FINALIST_SELECTION_TOPOLOGY
    stage_id = "finalist_selection"
    stage_label = "Finalist Selection"
    submit_effect = "submit_finalist_selection"
    already_started_code = "finalist_selection_already_started"
    partial_code = "finalist_selection_partial_submission"
    outcome_unknown_code = "finalist_selection_submission_outcome_unknown"
    authority_class = Mot3DClosureTransitionCoordinator
    expected_stage = "finalist_selection"
    sync_receipt_name = "closure_to_finalist_selection.json"
    files = FILES
    code_files = CODE_FILES
    preparation_error = "finalist_selection_preparation_invalid"
    validation_candidates = FINALIST_SELECTION_TOPOLOGY.candidates_per_family

    @staticmethod
    def _validate(state, operation: str):
        validate_selection_submission_state(
            state, operation, error=Mot3DFinalistSubmissionError
        )

    def _default_transport(self, profile):
        from workflow_api.mot_3d_finalist_submission_remote_client import (
            PinnedSshMot3DFinalistSubmissionTransport,
        )

        return PinnedSshMot3DFinalistSubmissionTransport(self.root, self.ssh, profile)

    def _science(self, manifest):
        design = manifest.get("design", {})
        policy = FINALIST_SELECTION_SCIENTIFIC_DESIGN
        return workload.submission_science(manifest, "finalist_selection", {
            "classification": "final_candidate_selection_not_unbiased_validation",
            "candidates_per_family": FINALIST_SELECTION_TOPOLOGY.candidates_per_family,
            "input_ensembles": policy.input_ensembles,
            "recoil_seeds": list(policy.recoil_seeds),
            "dt_s": design.get("screening_dt_s"),
            "t_max_s": policy.t_max_s,
            "solver": design.get("solver"),
            "npools": 200,
            "bootstrap_replicates": policy.bootstrap_replicates,
            "bootstrap_seed": policy.bootstrap_seed,
        })

    def status(self, request):
        try:
            return super().status(request)
        except Mot3DClosureSubmissionError as exc:
            raise Mot3DFinalistSubmissionError(exc.code) from exc

    def preview(self, request, *, session_id: str):
        try:
            return super().preview(request, session_id=session_id)
        except Mot3DClosureSubmissionError as exc:
            raise Mot3DFinalistSubmissionError(exc.code) from exc

    def confirm(self, request, *, session_id: str):
        try:
            return super().confirm(request, session_id=session_id)
        except Mot3DClosureSubmissionError as exc:
            raise Mot3DFinalistSubmissionError(exc.code) from exc
