import hashlib
import json
import os
from pathlib import Path

import pytest

from tests.test_mot_3d_final_input_results import (
    LOGICAL,
    PROJECT,
    ROOT,
    _fixture,
    _json,
)
from workflow_api import mot_3d_final_validation_transition_remote as wrapper
from workflow_api import mot_3d_preliminary_transition_remote as core
from workflow_api.mot_3d_linear_submission_remote import scheduler_state
from workflow_api.verified_artifact_bundle import (
    ArtifactBundleError,
    MAX_REVIEWED_FILE_BYTES,
    MAX_REVIEWED_TOTAL_BYTES,
    build_artifact_bundle,
    unpack_artifact_bundle,
)


JOBS = {
    "zeeman": "101[].zeus-master",
    "mot_2d": "102[].zeus-master",
    "freeze": "103.zeus-master",
}


def _qstat(job, *, state="F", exit_status="0", count=20):
    prefix = job.split("[]", 1)[0]
    return "".join(
        f"Job Id: {prefix}[{index}].zeus-master\n    job_state = {state}\n    Exit_status = {exit_status}\n"
        for index in range(count)
    ).encode()


def _repository(tmp_path):
    repository = tmp_path / "repository"
    campaign = repository / LOGICAL
    submissions = campaign / ".mot_ui/submissions"
    submissions.mkdir(parents=True)
    manifest, locked, compatibility, results = _fixture()
    (campaign / "campaign.json").write_bytes(_json(manifest))
    locked_path = campaign / "selection/locked_nominals.json"
    locked_path.parent.mkdir(parents=True)
    locked_path.write_bytes(_json(locked))
    for name, raw in results.items():
        target = campaign / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    pbs_names = (
        "jobs/final_validation_inputs/01_generate_zeeman.pbs",
        "jobs/final_validation_inputs/02_generate_2d_survivors.pbs",
        "jobs/final_validation_inputs/03_freeze_inputs.pbs",
    )
    pbs = {}
    for index, name in enumerate(pbs_names):
        raw = f"pbs-{index}".encode()
        target = campaign / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        pbs[name] = raw
    key, nonce, created, submitted = "6" * 64, "7" * 32, 10, 17
    final = {
        "version": 1,
        "status": "submitted",
        "submission_key": key,
        "nonce": nonce,
        "commit": "a" * 40,
        "jobs": JOBS,
        "created_unix_s": created,
        "submitted_unix_s": submitted,
    }
    (submissions / "final_validation_input_generation.json").write_bytes(_json(final))
    for index, step in enumerate(("zeeman", "mot_2d", "freeze")):
        receipt = {
            "status": "submitted",
            "submission_key": key,
            "nonce": nonce,
            "commit": "a" * 40,
            "step": step,
            "pbs_sha256": hashlib.sha256(pbs[pbs_names[index]]).hexdigest(),
            "depends_on": None if index == 0 else JOBS[("zeeman", "mot_2d")[index - 1]],
            "created_unix_s": 11 + 2 * index,
            "job_id": JOBS[step],
            "completed_unix_s": 12 + 2 * index,
        }
        (submissions / f"final_validation_input_generation_{step}.json").write_bytes(
            _json(receipt)
        )
    compatibility.update(
        {
            "submission_key": key,
            "nonce": nonce,
            "commit": "a" * 40,
            "created_unix_s": created,
            "zeeman_array_job_id": JOBS["zeeman"],
            "mot_array_job_id": JOBS["mot_2d"],
            "freeze_job_id": JOBS["freeze"],
        }
    )
    compatibility_path = campaign / "final_validation_input_generation_submission.json"
    compatibility_path.write_bytes(_json(compatibility))
    # Keep the frozen input manifest cryptographically bound to the exact receipt.
    inputs_path = campaign / "final_validation_inputs/input_manifest.json"
    inputs = json.loads(inputs_path.read_bytes())
    inputs["generation_submission_sha256"] = hashlib.sha256(
        _json(compatibility)
    ).hexdigest()
    inputs["generation_jobs"] = compatibility
    inputs_path.write_bytes(_json(inputs))
    return repository, campaign, key


def test_descriptor_freezes_linear_exact_101_to_107_and_reviewed_caps():
    descriptor = wrapper.DESCRIPTOR
    assert descriptor.submission_evidence == "linear_chain"
    assert descriptor.source_result_count == 101
    assert descriptor.transfer_file_count == 107
    assert descriptor.bundle_max_total_bytes == 128 * 1024 * 1024
    assert descriptor.artifact_max_file_bytes == 8 * 1024 * 1024
    assert descriptor.generated_paths == wrapper.GENERATED_PATHS


def test_joined_linear_receipts_and_exact_qstat_40_plus_1(tmp_path):
    _, campaign, key = _repository(tmp_path)
    campaign_fd = os.open(campaign, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with core.descriptor_scope(wrapper.DESCRIPTOR):
            final, jobs = core._exact_stage2(campaign_fd, key, "a" * 40)
    finally:
        os.close(campaign_fd)
    assert final["jobs"] == JOBS and jobs == JOBS
    outputs = {
        JOBS["zeeman"]: _qstat(JOBS["zeeman"]),
        JOBS["mot_2d"]: _qstat(JOBS["mot_2d"]),
        JOBS[
            "freeze"
        ]: b"Job Id: 103.zeus-master\n    job_state = F\n    Exit_status = 0\n",
    }
    assert scheduler_state(JOBS, run=lambda argv, **_: (0, outputs[argv[-1]], b"")) == (
        "completed_success_unvalidated",
        40,
        1,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "step_dependency",
        "step_time",
        "compat_job",
        "missing_child",
        "duplicate_child",
        "junk_qstat",
    ],
)
def test_receipt_and_qstat_mutations_fail_closed(tmp_path, mutation):
    _, campaign, key = _repository(tmp_path)
    if mutation.startswith("step"):
        path = (
            campaign
            / ".mot_ui/submissions/final_validation_input_generation_mot_2d.json"
        )
        row = json.loads(path.read_bytes())
        row["depends_on"] = (
            "999[].zeus-master" if mutation == "step_dependency" else row["depends_on"]
        )
        if mutation == "step_time":
            row["created_unix_s"] = 1
        path.write_bytes(_json(row))
        fd = os.open(campaign, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with core.descriptor_scope(wrapper.DESCRIPTOR), pytest.raises(SystemExit):
                core._exact_stage2(fd, key, "a" * 40)
        finally:
            os.close(fd)
        return
    if mutation == "compat_job":
        path = campaign / "final_validation_input_generation_submission.json"
        row = json.loads(path.read_bytes())
        row["freeze_job_id"] = "999.zeus-master"
        path.write_bytes(_json(row))
        fd = os.open(campaign, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with core.descriptor_scope(wrapper.DESCRIPTOR), pytest.raises(SystemExit):
                core._exact_stage2(fd, key, "a" * 40)
        finally:
            os.close(fd)
        return
    raw = _qstat(JOBS["zeeman"])
    if mutation == "missing_child":
        raw = _qstat(JOBS["zeeman"], count=19)
    elif mutation == "duplicate_child":
        raw += raw.split(b"Job Id: ", 1)[1].join((b"Job Id: ", b""))
    else:
        raw = b"junk\n" + raw
    outputs = {
        JOBS["zeeman"]: raw,
        JOBS["mot_2d"]: _qstat(JOBS["mot_2d"]),
        JOBS[
            "freeze"
        ]: b"Job Id: 103.zeus-master\n    job_state = F\n    Exit_status = 0\n",
    }
    assert (
        scheduler_state(JOBS, run=lambda argv, **_: (0, outputs[argv[-1]], b""))[0]
        == "status_unknown"
    )


def test_real_validator_renderer_and_bundle_form_exact_107_registry():
    manifest, locked, submission, results = _fixture()
    with core.descriptor_scope(wrapper.DESCRIPTOR):
        parsed, validated = core._validate_results(
            _json(manifest),
            {"locked_nominals": _json(locked), "submission": _json(submission)},
            results,
            PROJECT,
            ROOT,
        )
        generated, updated = core._render_transition(
            LOGICAL, parsed, validated, _json(manifest)
        )
    transfer = dict(results)
    transfer["final_validation_input_generation_submission.json"] = _json(submission)
    transfer.update(generated)
    assert len(transfer) == 107 and set(generated) == wrapper.GENERATED_PATHS
    built = build_artifact_bundle(
        transfer,
        campaign="campaign",
        commit="a" * 40,
        from_stage=wrapper.DESCRIPTOR.from_stage,
        to_stage=wrapper.DESCRIPTOR.to_stage,
        expected_paths=frozenset(transfer),
        max_total_bytes=wrapper.DESCRIPTOR.bundle_max_total_bytes,
        max_file_bytes=wrapper.DESCRIPTOR.artifact_max_file_bytes,
    )
    assert built.manifest["file_count"] == 107
    assert (
        unpack_artifact_bundle(
            built.packed,
            built.manifest,
            campaign="campaign",
            commit="a" * 40,
            from_stage=wrapper.DESCRIPTOR.from_stage,
            to_stage=wrapper.DESCRIPTOR.to_stage,
            expected_paths=frozenset(transfer),
            max_total_bytes=MAX_REVIEWED_TOTAL_BYTES,
            max_file_bytes=MAX_REVIEWED_FILE_BYTES,
        )
        == transfer
    )
    assert updated["stage"] == "final_validation"


def test_reviewed_bundle_caps_reject_per_file_total_and_gzip_bomb():
    base = {"a": b"x"}
    with pytest.raises(ArtifactBundleError):
        build_artifact_bundle(
            {"a": b"x" * (MAX_REVIEWED_FILE_BYTES + 1)},
            campaign="campaign",
            commit="a" * 40,
            from_stage="source",
            to_stage="target",
            expected_paths=frozenset({"a"}),
            max_total_bytes=MAX_REVIEWED_TOTAL_BYTES,
            max_file_bytes=MAX_REVIEWED_FILE_BYTES,
        )
    built = build_artifact_bundle(
        base,
        campaign="campaign",
        commit="a" * 40,
        from_stage="source",
        to_stage="target",
        expected_paths=frozenset(base),
        max_total_bytes=MAX_REVIEWED_TOTAL_BYTES,
        max_file_bytes=MAX_REVIEWED_FILE_BYTES,
    )
    bad = dict(built.manifest)
    bad["uncompressed_bytes"] = MAX_REVIEWED_TOTAL_BYTES + 1
    with pytest.raises(ArtifactBundleError):
        unpack_artifact_bundle(
            built.packed,
            bad,
            campaign="campaign",
            commit="a" * 40,
            from_stage="source",
            to_stage="target",
            expected_paths=frozenset(base),
            max_total_bytes=MAX_REVIEWED_TOTAL_BYTES,
            max_file_bytes=MAX_REVIEWED_FILE_BYTES,
        )


def test_locked_terminal_counts_follow_closed_submission_contract():
    # Both modes retain the reviewed twenty-seed generation chain.
    with core.descriptor_scope(wrapper.DESCRIPTOR):
        assert core._terminal_counts() == (40, 1)
    from workflow_api import mot_3d_refinement_transition_remote as family_wrapper
    with core.descriptor_scope(family_wrapper.DESCRIPTOR):
        assert core._terminal_counts() == (6, 2)
