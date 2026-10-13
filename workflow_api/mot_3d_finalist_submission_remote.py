"""Thin pinned receiver entry point for 3D finalist-selection submission."""

from workflow_api import mot_3d_selection_submission_remote as core
from workflow_api.mot_3d_finalist_submission import CODE_FILES, FILES
from workflow_api.mot_3d_stage_topology import (
    FAMILIES,
    FINALIST_SELECTION_SCIENTIFIC_DESIGN,
    FINALIST_SELECTION_TOPOLOGY,
)

JOBS = FINALIST_SELECTION_TOPOLOGY.jobs
_policy = FINALIST_SELECTION_SCIENTIFIC_DESIGN
SCIENCE = {
    "classification": "final_candidate_selection_not_unbiased_validation",
    "candidates_per_family": 3,
    "input_ensembles": 20,
    "recoil_seeds": list(_policy.recoil_seeds),
    "dt_s": None,
    "t_max_s": _policy.t_max_s,
    "solver": None,
    "npools": 200,
    "bootstrap_replicates": _policy.bootstrap_replicates,
    "bootstrap_seed": _policy.bootstrap_seed,
}
DESCRIPTOR = core.ReceiverDescriptor(
    stage="finalist_selection",
    input_role=("discovery", "refinement", "preliminary_check"),
    transition_receipt="closure_to_finalist_selection.json",
    jobs=JOBS,
    files=FILES,
    science=SCIENCE,
    code_names=CODE_FILES,
    transition_status="finalist_selection_prepared",
    outcome_error="finalist_selection_submission_outcome_unknown",
    preparation_error="finalist_selection_preparation_invalid",
)

canonical = core.canonical
digest = core.digest
qstat_fields = core.qstat_fields
publish_at = core._publish_at_impl
replace_at = core._replace_at_impl
unlink_at = core._unlink_at_impl
run = core._run_impl


def scheduler(job, kind):
    with core.descriptor_scope(DESCRIPTOR):
        token = core._RUNNER.set(run)
        try:
            return core.scheduler(job, kind)
        finally:
            core._RUNNER.reset(token)


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
