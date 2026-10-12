"""Pinned Refinement -> Closure receiver bound to the shared transition engine."""

from __future__ import annotations

from workflow_api.mot_3d_preliminary_transition_remote import (
    TransitionDescriptor,
    descriptor_scope,
    main as _shared_main,
)
from workflow_api.mot_3d_refinement_transition import CODE_PATHS, GENERATED_PATHS
from workflow_api.mot_3d_refinement_submission import FILES


DESCRIPTOR = TransitionDescriptor(
    from_stage="refinement",
    to_stage="closure",
    sync_name="refinement_to_closure",
    source_result_count=200,
    transfer_file_count=208,
    source_submission_receipt="refinement_submission.json",
    prior_local_sync_receipt=".mot_ui/sync/preliminary_to_refinement.json",
    generated_paths=GENERATED_PATHS,
    source_identity_paths=FILES,
    code_paths=CODE_PATHS | {"workflow_api/mot_3d_refinement_transition_remote.py"},
    prepared_status="closure_prepared",
    pending_status="closure_pending",
    error_prefix="refinement_transition",
    selection_stage="refinement",
    prior_transition_name="refinement",
    prior_transition_status="refinement_prepared",
    prior_transition_file_count=160,
)


def main(*, trusted_root_override=None):
    with descriptor_scope(DESCRIPTOR):
        return _shared_main(trusted_root_override=trusted_root_override)


if __name__ == "__main__":
    main()
