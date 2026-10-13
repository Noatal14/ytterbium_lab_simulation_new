"""Pinned final-input-generation -> final-validation transition receiver."""

from workflow_api.mot_3d_preliminary_transition_remote import (
    TransitionDescriptor,
    descriptor_scope,
    main as _main,
)
from workflow_api.mot_3d_final_input_submission import CODE_FILES, FILES
from workflow_api.verified_artifact_bundle import (
    MAX_REVIEWED_FILE_BYTES,
    MAX_REVIEWED_TOTAL_BYTES,
)

GENERATED_PATHS = frozenset(
    {
        "campaign.json",
        "jobs/final_validation/angled_donut_array.pbs",
        "jobs/final_validation/angled_donut_merge.pbs",
        "jobs/final_validation/single_pass_array.pbs",
        "jobs/final_validation/single_pass_merge.pbs",
    }
)

CODE_PATHS = frozenset(
    set(CODE_FILES)
    | {
        "workflow_api/mot_3d_final_input_results.py",
        "workflow_api/mot_3d_final_validation_transition_remote.py",
    }
)

DESCRIPTOR = TransitionDescriptor(
    from_stage="final_validation_input_generation",
    to_stage="final_validation",
    sync_name="final_validation_inputs_to_final_validation",
    source_result_count=101,
    transfer_file_count=107,
    source_submission_receipt="final_validation_input_generation_submission.json",
    prior_local_sync_receipt=(
        ".mot_ui/sync/finalist_selection_to_final_validation_inputs.json"
    ),
    generated_paths=GENERATED_PATHS,
    source_identity_paths=FILES,
    code_paths=CODE_PATHS,
    prepared_status="final_validation_prepared",
    pending_status="final_validation_pending",
    error_prefix="final_validation_transition",
    selection_stage="finalists",
    prior_transition_name="finalist_selection_to_final_validation_inputs",
    prior_transition_status="final_validation_input_generation_prepared",
    prior_transition_file_count=50,
    bundle_max_total_bytes=MAX_REVIEWED_TOTAL_BYTES,
    submission_evidence="linear_chain",
    artifact_max_file_bytes=MAX_REVIEWED_FILE_BYTES,
)


def main(*, trusted_root_override=None):
    with descriptor_scope(DESCRIPTOR):
        return _main(trusted_root_override=trusted_root_override)


if __name__ == "__main__":
    main()
