"""Pinned finalist-selection -> final-validation-input receiver."""

from workflow_api.mot_3d_preliminary_transition_remote import (
    TransitionDescriptor,
    descriptor_scope,
    main as _main,
)
from workflow_api.mot_3d_finalist_transition import CODE_PATHS, GENERATED_PATHS
from workflow_api.mot_3d_finalist_submission import FILES

DESCRIPTOR = TransitionDescriptor(
    from_stage="finalist_selection",
    to_stage="final_validation_input_generation",
    sync_name="finalist_selection_to_final_validation_inputs",
    source_result_count=44,
    transfer_file_count=50,
    source_submission_receipt="finalist_selection_submission.json",
    prior_local_sync_receipt=".mot_ui/sync/closure_to_finalist_selection.json",
    generated_paths=GENERATED_PATHS,
    source_identity_paths=FILES,
    code_paths=CODE_PATHS | {"workflow_api/mot_3d_finalist_transition_remote.py"},
    prepared_status="final_validation_input_generation_prepared",
    pending_status="final_validation_input_generation_pending",
    error_prefix="finalist_transition",
    selection_stage="finalists",
    prior_transition_name="closure_to_finalist_selection",
    prior_transition_status="finalist_selection_prepared",
    prior_transition_file_count=208,
)


def main(*, trusted_root_override=None):
    with descriptor_scope(DESCRIPTOR):
        return _main(trusted_root_override=trusted_root_override)


if __name__ == "__main__":
    main()
