"""Guarded submission facade for the sealed 3D final-validation chain."""

from __future__ import annotations

from workflow_api.mot_3d_closure_submission import (
    Mot3DClosureSubmissionCoordinator,
    Mot3DClosureSubmissionError,
)
from workflow_api.mot_3d_final_validation_transition import (
    Mot3DFinalValidationTransitionCoordinator,
)
from workflow_api.mot_3d_selection_submission import validate_selection_submission_state
from workflow_api.mot_3d_stage_topology import (
    FINAL_VALIDATION_SCIENTIFIC_DESIGN,
    FINAL_VALIDATION_TOPOLOGY,
)

FILES = frozenset(
    {
        "campaign.json",
        "selection/locked_nominals.json",
        "final_validation_inputs/input_manifest.json",
        *(
            path
            for row in FINAL_VALIDATION_TOPOLOGY.jobs.values()
            for path in row.values()
        ),
    }
)
CODE_FILES = frozenset(
    {
        "config.py",
        "simulations/mot_3d.py",
        "studies/mot_3d_campaign.py",
        "studies/mot_3d/final_validation.py",
        "studies/mot_3d/integrity.py",
        "workflow_api/mot_3d_final_input_results.py",
        "workflow_api/mot_3d_final_input_submission.py",
        "workflow_api/mot_3d_final_validation_transition.py",
        "workflow_api/mot_3d_final_validation_transition_remote.py",
        "workflow_api/mot_3d_stage_topology.py",
        "workflow_api/mot_3d_selection_submission.py",
        "workflow_api/mot_3d_final_validation_submission.py",
        "workflow_api/mot_3d_selection_submission_remote.py",
        "workflow_api/mot_3d_final_validation_submission_remote.py",
        "lab_setup/specifications/laboratory_physical_v1.json",
        "lab_setup/specifications/mot_3d_timestep_policy_v1.json",
    }
)


class Mot3DFinalValidationSubmissionError(Mot3DClosureSubmissionError):
    """Closed public error for final-validation submission."""


class Mot3DFinalValidationSubmissionCoordinator(Mot3DClosureSubmissionCoordinator):
    topology = FINAL_VALIDATION_TOPOLOGY
    stage_id = "final_validation"
    stage_label = "Final Validation"
    submit_effect = "submit_final_validation"
    already_started_code = "final_validation_already_started"
    partial_code = "final_validation_partial_submission"
    outcome_unknown_code = "final_validation_submission_outcome_unknown"
    authority_class = Mot3DFinalValidationTransitionCoordinator
    expected_stage = "final_validation"
    sync_receipt_name = "final_validation_inputs_to_final_validation.json"
    files = FILES
    code_files = CODE_FILES
    preparation_error = "final_validation_preparation_invalid"
    validation_candidates = 1
    expected_dt_s = FINAL_VALIDATION_SCIENTIFIC_DESIGN.dt_s
    expected_solver = FINAL_VALIDATION_SCIENTIFIC_DESIGN.solver

    @staticmethod
    def _validate(state, operation: str):
        validate_selection_submission_state(
            state, operation, error=Mot3DFinalValidationSubmissionError
        )

    def _default_transport(self, profile):
        from workflow_api.mot_3d_final_validation_submission_remote_client import (
            PinnedSshMot3DFinalValidationSubmissionTransport,
        )

        return PinnedSshMot3DFinalValidationSubmissionTransport(
            self.root, self.ssh, profile
        )

    def _science(self, manifest):
        policy = FINAL_VALIDATION_SCIENTIFIC_DESIGN
        design = manifest.get("design", {})
        return {
            "classification": "sealed_unbiased_final_validation",
            "candidates_per_family": 1,
            "input_ensembles": policy.input_ensembles,
            "recoil_seeds": list(policy.recoil_seeds),
            "dt_s": design.get("production_dt_s"),
            "t_max_s": policy.t_max_s,
            "solver": design.get("solver"),
            "npools": policy.npools,
            "bootstrap_replicates": policy.bootstrap_replicates,
            "bootstrap_seed": policy.bootstrap_seed,
        }

    def status(self, request):
        try:
            return super().status(request)
        except Mot3DClosureSubmissionError as exc:
            raise Mot3DFinalValidationSubmissionError(exc.code) from exc

    def preview(self, request, *, session_id: str):
        try:
            return super().preview(request, session_id=session_id)
        except Mot3DClosureSubmissionError as exc:
            raise Mot3DFinalValidationSubmissionError(exc.code) from exc

    def confirm(self, request, *, session_id: str):
        try:
            return super().confirm(request, session_id=session_id)
        except Mot3DClosureSubmissionError as exc:
            raise Mot3DFinalValidationSubmissionError(exc.code) from exc
