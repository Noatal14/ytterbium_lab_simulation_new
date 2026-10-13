"""Pinned zero-submit final-validation completion receiver."""

from workflow_api.mot_3d_final_validation_submission import CODE_FILES, FILES
from workflow_api.mot_3d_preliminary_transition_remote import (
    TransitionDescriptor,
    descriptor_scope,
    main as _main,
)

GENERATED_PATHS = frozenset(
    {"campaign.json", "final_report.json", "final_validation_status.json"}
)

CODE_PATHS = frozenset(
    set(CODE_FILES)
    | {
        "workflow_api/mot_3d_final_validation_results.py",
        "workflow_api/mot_3d_final_validation_completion_remote.py",
        "workflow_api/mot_3d_preliminary_transition_remote.py",
    }
)

DESCRIPTOR = TransitionDescriptor(
    from_stage="final_validation",
    to_stage="final_validation_completion",
    sync_name="final_validation_completion",
    source_result_count=14,
    transfer_file_count=17,
    source_submission_receipt="final_validation_submission.json",
    prior_local_sync_receipt=(
        ".mot_ui/sync/final_validation_inputs_to_final_validation.json"
    ),
    generated_paths=GENERATED_PATHS,
    source_identity_paths=FILES,
    code_paths=CODE_PATHS,
    prepared_status="final_validation_completed",
    pending_status="final_validation_completion_pending",
    error_prefix="final_validation_completion",
    selection_stage="locked_nominals",
    prior_transition_name="final_validation_inputs_to_final_validation",
    prior_transition_status="final_validation_prepared",
    prior_transition_file_count=107,
    workflow_kind="final_validation_completion",
    terminal_statuses=frozenset({"complete", "final_validation_extension_required"}),
    generated_file_count=2,
)


def main(*, trusted_root_override=None):
    with descriptor_scope(DESCRIPTOR):
        return _main(trusted_root_override=trusted_root_override)


if __name__ == "__main__":
    main()
