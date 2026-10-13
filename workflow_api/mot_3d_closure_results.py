"""Strict byte-bound validation for canonical 3D-MOT Closure results."""

from workflow_api.mot_3d_refinement_results import (
    FocusedResultPolicy,
    REFINEMENT_RESULT_REASON_CODES,
    RefinementResultError,
    expected_paths as _expected_paths,
    validate_refinement_result_bytes as _validate,
)


CLOSURE_RESULT_REASON_CODES = REFINEMENT_RESULT_REASON_CODES
CLOSURE_RESULT_POLICY = FocusedResultPolicy(
    stage="closure",
    selection_kind="mot_3d_local_closure_selection",
    candidate_label="closure",
    selection_seed=71_001,
    bootstrap_seed=72_001,
)
ClosureResultError = RefinementResultError


def expected_paths(selections):
    return _expected_paths(selections, CLOSURE_RESULT_POLICY)


def validate_closure_result_bytes(*args, **kwargs):
    return _validate(*args, **kwargs, policy=CLOSURE_RESULT_POLICY)
