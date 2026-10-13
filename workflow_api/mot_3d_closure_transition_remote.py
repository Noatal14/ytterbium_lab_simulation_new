"""Pinned Closure -> finalist-selection receiver."""

from workflow_api.mot_3d_preliminary_transition_remote import (
    TransitionDescriptor,
    descriptor_scope,
    main as _main,
)
from workflow_api.mot_3d_closure_transition import CODE_PATHS, GENERATED_PATHS
from workflow_api.mot_3d_closure_submission import FILES

DESCRIPTOR = TransitionDescriptor(
    from_stage="closure",
    to_stage="finalist_selection",
    sync_name="closure_to_finalist_selection",
    source_result_count=200,
    transfer_file_count=208,
    source_submission_receipt="closure_submission.json",
    prior_local_sync_receipt=".mot_ui/sync/refinement_to_closure.json",
    generated_paths=GENERATED_PATHS,
    source_identity_paths=FILES,
    code_paths=CODE_PATHS | {"workflow_api/mot_3d_closure_transition_remote.py"},
    prepared_status="finalist_selection_prepared",
    pending_status="finalist_selection_pending",
    error_prefix="closure_transition",
    selection_stage="closure",
    prior_transition_name="refinement_to_closure",
    prior_transition_status="closure_prepared",
    prior_transition_file_count=208,
)


def main(*, trusted_root_override=None):
    with descriptor_scope(DESCRIPTOR):
        return _main(trusted_root_override=trusted_root_override)


if __name__ == "__main__":
    main()
