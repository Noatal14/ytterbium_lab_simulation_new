"""Thin pinned receiver entry point for the canonical 3D Refinement chain."""

from workflow_api import mot_3d_selection_submission_remote as core

FAMILIES = core.FAMILIES
JOBS = {
    family: {
        "array": f"jobs/refinement/{family}_array.pbs",
        "merge": f"jobs/refinement/{family}_merge.pbs",
    }
    for family in FAMILIES
}
FILES = frozenset(
    {
        "campaign.json",
        *(f"selection/refinement/{family}.json" for family in FAMILIES),
        *(path for family in FAMILIES for path in JOBS[family].values()),
    }
)
SCIENCE = {
    "classification": "candidate_selection_not_final_validation",
    "candidates_per_family": 16,
    "input_ensembles": 4,
    "particles_per_ensemble": 750,
    "total_particles": 3000,
    "recoil_seeds": [42001, 42002, 42003],
    "dt_s": None,
    "t_max_s": 0.1,
    "solver": None,
    "selection_seed": 61001,
    "bootstrap_replicates": 10000,
    "bootstrap_seed": 62001,
}
CODE_NAMES = frozenset(
    {
        "config.py",
        "simulations/mot_3d.py",
        "studies/mot_3d_campaign.py",
        "studies/mot_3d/integrity.py",
        "studies/mot_3d/refinement/run.py",
        "studies/mot_3d/refinement/merge.py",
        "workflow_api/mot_3d_stage_topology.py",
        "workflow_api/mot_3d_selection_submission.py",
        "workflow_api/mot_3d_refinement_submission.py",
        "workflow_api/mot_3d_selection_submission_remote.py",
        "workflow_api/mot_3d_refinement_submission_remote.py",
        "lab_setup/specifications/laboratory_physical_v1.json",
        "lab_setup/specifications/mot_3d_timestep_policy_v1.json",
    }
)
DESCRIPTOR = core.ReceiverDescriptor(
    stage="refinement",
    input_role="refinement",
    transition_receipt="refinement.json",
    jobs=JOBS,
    files=FILES,
    science=SCIENCE,
    code_names=CODE_NAMES,
    transition_status="refinement_prepared",
    outcome_error="refinement_submission_outcome_unknown",
    preparation_error="refinement_preparation_invalid",
)

# Pure helpers remain available for direct receiver characterization.
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
