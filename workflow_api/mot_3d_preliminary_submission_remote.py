"""Thin pinned receiver entry point for the 3D preliminary-check chain."""

from workflow_api import mot_3d_selection_submission_remote as core

FAMILIES = core.FAMILIES
JOBS = {
    family: {
        "array": f"jobs/preliminary_check/{family}_array.pbs",
        "merge": f"jobs/preliminary_check/{family}_merge.pbs",
    }
    for family in FAMILIES
}
FILES = frozenset(
    {
        "campaign.json",
        *(f"selection/discovery/{family}.json" for family in FAMILIES),
        *(path for family in FAMILIES for path in JOBS[family].values()),
    }
)
SCIENCE = {
    "classification": "candidate_selection_not_final_validation",
    "candidates_per_family": 12,
    "input_ensembles": 4,
    "particles_per_ensemble": 150,
    "total_particles": 600,
    "recoil_seeds": [41001, 41002, 41003],
    "dt_s": None,
    "t_max_s": 0.1,
    "solver": None,
    "selection_seed": 51001,
    "bootstrap_replicates": 10000,
    "bootstrap_seed": 52001,
}
CODE_NAMES = frozenset(
    {
        "config.py",
        "simulations/mot_3d.py",
        "studies/mot_3d_campaign.py",
        "studies/mot_3d/integrity.py",
        "studies/mot_3d/analysis/retention.py",
        "studies/mot_3d/preliminary/run.py",
        "studies/mot_3d/preliminary/merge.py",
        "workflow_api/mot_3d_selection_submission_remote.py",
        "workflow_api/mot_3d_preliminary_submission_remote.py",
        "lab_setup/specifications/laboratory_physical_v1.json",
        "lab_setup/specifications/mot_3d_timestep_policy_v1.json",
    }
)
DESCRIPTOR = core.ReceiverDescriptor(
    stage="preliminary_check",
    jobs=JOBS,
    files=FILES,
    science=SCIENCE,
    code_names=CODE_NAMES,
    transition_status="preliminary_check_prepared",
    outcome_error="preliminary_submission_outcome_unknown",
    preparation_error="preliminary_preparation_invalid",
)

canonical = core.canonical
digest = core.digest
qstat_fields = core.qstat_fields
ARRAY = core.ARRAY
SCALAR = core.SCALAR
DIR_FLAGS = core.DIR_FLAGS
bounded_at = core.bounded_at
json_bytes = core.json_bytes
open_dir_at = core.open_dir_at
read_relative_at = core.read_relative_at
regular_exists_at = core.regular_exists_at
stamp = core.stamp
strict_json_at = core.strict_json_at
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
