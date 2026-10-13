"""Thin pinned receiver for the sealed final-validation submission."""

from workflow_api import mot_3d_selection_submission_remote as core
from workflow_api.mot_3d_final_validation_submission import CODE_FILES, FILES
from workflow_api.mot_3d_stage_topology import (
    FINAL_VALIDATION_SCIENTIFIC_DESIGN,
    FINAL_VALIDATION_TOPOLOGY,
)

JOBS = FINAL_VALIDATION_TOPOLOGY.jobs
_policy = FINAL_VALIDATION_SCIENTIFIC_DESIGN
SCIENCE = {
    "classification": "sealed_unbiased_final_validation",
    "candidates_per_family": 1,
    "input_ensembles": _policy.input_ensembles,
    "recoil_seeds": list(_policy.recoil_seeds),
    "dt_s": None,
    "t_max_s": _policy.t_max_s,
    "solver": None,
    "npools": _policy.npools,
    "bootstrap_replicates": _policy.bootstrap_replicates,
    "bootstrap_seed": _policy.bootstrap_seed,
}
DESCRIPTOR = core.ReceiverDescriptor(
    stage="final_validation",
    input_role=None,
    transition_receipt="final_validation_inputs_to_final_validation.json",
    jobs=JOBS,
    files=FILES,
    science=SCIENCE,
    code_names=CODE_FILES,
    transition_status="final_validation_prepared",
    outcome_error="final_validation_submission_outcome_unknown",
    preparation_error="final_validation_preparation_invalid",
    non_job_files=frozenset(
        {
            "campaign.json",
            "selection/locked_nominals.json",
            "final_validation_inputs/input_manifest.json",
        }
    ),
    science_keys=frozenset(SCIENCE),
    dt_design_key="production_dt_s",
)

canonical = core.canonical
digest = core.digest
qstat_fields = core.qstat_fields
publish_at = core._publish_at_impl
replace_at = core._replace_at_impl
unlink_at = core._unlink_at_impl
run = core._run_impl


def main(*, trusted_root_override=None):
    return core.serve(
        DESCRIPTOR,
        trusted_root_override=trusted_root_override,
        run_override=run,
        publish_override=publish_at,
        replace_override=replace_at,
        unlink_override=unlink_at,
    )


if __name__ == "__main__":
    main()
