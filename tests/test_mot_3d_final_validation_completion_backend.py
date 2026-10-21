from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import sys
from pathlib import Path
import shutil

import numpy as np
import pytest

from workflow_api.mot_3d_final_validation_completion import (
    Mot3DFinalValidationCompletionCoordinator,
    Mot3DFinalValidationCompletionError,
)
from workflow_api.mot_3d_final_validation_completion_remote import DESCRIPTOR
from workflow_api.mot_3d_final_validation_results import (
    FinalValidationResultError,
    expected_paths,
    validate_final_validation_result_bytes,
)
from workflow_api.mot_3d_preliminary_transition import RemotePreliminaryTransitionState
from workflow_api.mot_3d_preliminary_transition import Mot3DPreliminaryTransitionError
from workflow_api.mot_3d_preliminary_transition_remote import (
    _generated_paths_valid,
    _receipt_status_valid,
    descriptor_scope,
)
from workflow_api import mot_3d_preliminary_transition_remote as generic_remote
from workflow_api import mot_3d_preliminary_submission_remote as stage2_remote
from workflow_api import mot_3d_final_validation_completion_remote as completion_remote
from workflow_api.verified_artifact_bundle import build_artifact_bundle
from workflow_api.zeus_discovery_submission import canonical_digest
from workflow_api.zeus_snapshot import ZeusProfile


# Pinned host executables; remote receiver fixtures remain isolated below.
SSH_EXECUTABLE = Path(shutil.which("ssh")).resolve()
GIT_EXECUTABLE = Path(shutil.which("git")).resolve()


def _state(lifecycle="complete", *, receipt=None):
    return RemotePreliminaryTransitionState(
        lifecycle,
        "main",
        {
            "angled_donut": {
                "array": "101[].zeus-master",
                "merge": "102.zeus-master",
            },
            "single_pass": {
                "array": "103[].zeus-master",
                "merge": "104.zeus-master",
            },
        },
        6,
        2,
        "valid",
        None,
        "a" * 64,
        receipt,
        None,
        None,
        None,
    )


def test_completion_descriptor_is_exact_and_outcome_aware():
    assert len(expected_paths()) == 14
    assert DESCRIPTOR.source_result_count == 14
    assert DESCRIPTOR.transfer_file_count == 17
    assert DESCRIPTOR.workflow_kind == "final_validation_completion"
    assert DESCRIPTOR.generated_file_count == 2
    assert DESCRIPTOR.terminal_statuses == {
        "complete",
        "final_validation_extension_required",
    }

    with descriptor_scope(DESCRIPTOR):
        assert _receipt_status_valid("complete")
        assert _receipt_status_valid("final_validation_extension_required")
        assert _generated_paths_valid({"campaign.json", "final_report.json"})
        assert _generated_paths_valid({"campaign.json", "final_validation_status.json"})
        assert not _generated_paths_valid(
            {"campaign.json", "final_report.json", "final_validation_status.json"}
        )


@pytest.mark.parametrize("outcome", ["complete", "final_validation_extension_required"])
def test_terminal_outcome_without_receipt_is_rejected(outcome):
    with pytest.raises(Mot3DPreliminaryTransitionError):
        Mot3DFinalValidationCompletionCoordinator._validate_state(_state(outcome))
    bad = _state("final_validation_completed")
    with pytest.raises(Mot3DFinalValidationCompletionError):
        Mot3DFinalValidationCompletionCoordinator._validate_prepared(bad, (None,) * 10)


@pytest.mark.parametrize(
    ("lifecycle", "validation", "expected_action"),
    [
        ("queued", "not_started", "wait"),
        ("running", "not_started", "wait"),
        ("ready_to_advance", "valid", "review_completion"),
        ("held", "not_started", "inspect_zeus"),
        ("completed_failed", "not_started", "inspect_zeus"),
        ("status_unknown", "not_started", "inspect_zeus"),
        ("outcome_unknown", "valid", "inspect_zeus"),
        (
            "completed_success_unvalidated",
            "scientifically_invalid",
            "inspect_zeus",
        ),
    ],
)
def test_completion_status_uses_conservative_action_matrix(
    tmp_path, lifecycle, validation, expected_action
):
    base = _state(lifecycle)
    state = RemotePreliminaryTransitionState(
        base.lifecycle,
        base.branch,
        base.jobs,
        base.completed_array_tasks,
        base.completed_merge_jobs,
        validation,
        "summary_mismatch" if validation == "scientifically_invalid" else None,
        base.evidence_sha256 if validation == "valid" else None,
        None,
        None,
        None,
        None,
    )
    coordinator = object.__new__(Mot3DFinalValidationCompletionCoordinator)
    plan = (
        "campaign-id",
        None,
        tmp_path,
        {"name": "campaign"},
        None,
        None,
        None,
        None,
        None,
        None,
    )
    coordinator._inspect = lambda _request, _operation: (plan, None, state)
    status = coordinator.status({})
    assert status["next_action"] == expected_action
    assert status["completion"]["detail"] is None


def test_synchronized_extension_status_restores_closed_completion_detail(tmp_path):
    detail = {
        "outcome": "final_validation_extension_required",
        "families": [
            {
                "family": family,
                "candidate_id": f"{family}_finalist_02",
                "conditional_efficiency": 0.5,
                "bootstrap_95_ci": [0.49, 0.51],
                "ci_half_width": 0.010000000000000009,
                "precision_target_met": False,
            }
            for family in ("angled_donut", "single_pass")
        ],
        "evidence_sha256": "a" * 64,
    }
    base = _state(
        "final_validation_completed",
        receipt={"status": "final_validation_extension_required"},
    )
    state = RemotePreliminaryTransitionState(
        base.lifecycle,
        base.branch,
        base.jobs,
        base.completed_array_tasks,
        base.completed_merge_jobs,
        base.validation,
        base.reason_code,
        base.evidence_sha256,
        base.receipt,
        base.bundle,
        base.chunk,
        detail,
    )
    coordinator = object.__new__(Mot3DFinalValidationCompletionCoordinator)
    plan = (
        "campaign-id",
        None,
        tmp_path,
        {"name": "campaign"},
        None,
        None,
        None,
        None,
        None,
        None,
    )
    coordinator._inspect = lambda _request, _operation: (plan, None, state)
    coordinator._verify_local_snapshot = lambda _campaign, _state: "c" * 64
    status = coordinator.status({})
    assert status["next_action"] == "review_extension_required"
    assert status["completion"] == {
        "status": "final_validation_extension_required",
        "detail": detail,
    }


def test_local_publication_rejects_mutually_exclusive_terminal_artifacts(tmp_path):
    (tmp_path / "final_report.json").write_text("{}", encoding="utf-8")
    (tmp_path / "final_validation_status.json").write_text("{}", encoding="utf-8")
    from workflow_api.platform_io import os as host_os
    campaign_fd = host_os.open(tmp_path, host_os.O_RDONLY | host_os.O_DIRECTORY)
    try:
        coordinator = object.__new__(Mot3DFinalValidationCompletionCoordinator)
        with pytest.raises(
            Mot3DFinalValidationCompletionError, match="local_sync_conflict"
        ):
            coordinator._expected_paths(campaign_fd)
    finally:
        host_os.close(campaign_fd)


def _json(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode()


def _exact14(
    tmp_path: Path,
    *,
    extension_family: str | tuple[str, ...] | None = None,
    return_values=False,
):
    from test_mot_3d_final_input_results import _fixture as input_fixture
    from studies.mot_3d.final_validation import merge
    from studies.mot_3d_campaign import render_final_validation_transition

    source_manifest, locked, generation_submission, input_files = input_fixture()
    from lab_setup.physical_specification import (
        CANONICAL_ZEEMAN_PROFILE_SHA256,
        LABORATORY_SPEC_SHA256,
        LABORATORY_SPEC_VERSION,
    )
    from config import MOT_2D_SIM_CONFIG

    input_manifest = json.loads(
        input_files["final_validation_inputs/input_manifest.json"]
    )
    for input_row in input_manifest["ensembles"]:
        metadata_name = input_row["metadata_path"].split("campaign/", 1)[1]
        replicate_name = input_row["replicate_path"].split("campaign/", 1)[1]
        zeeman_metadata_name = input_row["zeeman_metadata_path"].split("campaign/", 1)[
            1
        ]
        metadata = json.loads(input_files[metadata_name])
        metadata["design"].update(
            {
                "dt_s": MOT_2D_SIM_CONFIG["dt_s"],
                "laboratory_spec_version": LABORATORY_SPEC_VERSION,
                "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
                "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
            }
        )
        replicate = json.loads(input_files[replicate_name])
        replicate["design"] = json.loads(json.dumps(metadata["design"]))
        zeeman_metadata = json.loads(input_files[zeeman_metadata_name])
        zeeman_metadata.update(
            {
                "laboratory_spec_version": LABORATORY_SPEC_VERSION,
                "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
                "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
            }
        )
        input_files[metadata_name] = _json(metadata)
        input_files[replicate_name] = _json(replicate)
        input_files[zeeman_metadata_name] = _json(zeeman_metadata)
        input_row["metadata_sha256"] = hashlib.sha256(
            input_files[metadata_name]
        ).hexdigest()
        input_row["replicate_sha256"] = hashlib.sha256(
            input_files[replicate_name]
        ).hexdigest()
        input_row["zeeman_metadata_sha256"] = hashlib.sha256(
            input_files[zeeman_metadata_name]
        ).hexdigest()
    rendered, _ = render_final_validation_transition(
        "data/optimization/mot_3d/campaign", source_manifest
    )
    manifest_bytes = rendered["campaign.json"]
    locked_bytes = _json(locked)
    input_manifest["locked_nominals_sha256"] = hashlib.sha256(locked_bytes).hexdigest()
    input_manifest["generation_submission_sha256"] = hashlib.sha256(
        _json(generation_submission)
    ).hexdigest()
    input_manifest["total_survivors"] = sum(
        row["n_survivors"] for row in input_manifest["ensembles"]
    )
    input_files["final_validation_inputs/input_manifest.json"] = _json(input_manifest)
    input_manifest_bytes = input_files["final_validation_inputs/input_manifest.json"]
    jobs = {name: raw for name, raw in rendered.items() if name.endswith(".pbs")}
    submission = {
        "kind": "mot_3d_selection_stage_submission",
        "stage": "final_validation",
        "status": "submitted",
        "dependency": "afterok",
        "families": {
            "angled_donut": {
                "array_job_id": "101[].zeus-master",
                "merge_job_id": "102.zeus-master",
            },
            "single_pass": {
                "array_job_id": "103[].zeus-master",
                "merge_job_id": "104.zeus-master",
            },
        },
        "campaign_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "worker_job_sha256": {
            family: hashlib.sha256(
                jobs[f"jobs/final_validation/{family}_array.pbs"]
            ).hexdigest()
            for family in ("angled_donut", "single_pass")
        },
        "merge_job_sha256": {
            family: hashlib.sha256(
                jobs[f"jobs/final_validation/{family}_merge.pbs"]
            ).hexdigest()
            for family in ("angled_donut", "single_pass")
        },
    }
    results = {}
    extension_families = (
        set(extension_family)
        if isinstance(extension_family, tuple)
        else ({extension_family} if extension_family else set())
    )
    for family in ("angled_donut", "single_pass"):
        family_root = tmp_path / family
        family_root.mkdir(parents=True)
        masks = np.ones(20, dtype=bool)
        if family in extension_families:
            masks = np.asarray([index % 2 == 0 for index in range(20)], dtype=bool)
        ensemble_ids = np.arange(20, dtype=np.int64)
        for seed in (44001, 44002, 44003):
            stream = io.BytesIO()
            np.savez_compressed(
                stream,
                usable_at_end=masks,
                usable_ever=masks,
                ensemble_ids=ensemble_ids,
            )
            archive = stream.getvalue()
            archive_path = family_root / f"seed_{seed}.npz"
            archive_path.write_bytes(archive)
            row = {
                "kind": "mot_3d_sealed_final_validation_seed_result",
                "family": family,
                "candidate_id": locked["families"][family]["candidate_id"],
                "recoil_seed": seed,
                "input_particle_count": 20,
                "usable_at_end_count": int(masks.sum()),
                "usable_ever_count": int(masks.sum()),
                "outcomes_path": str(archive_path),
                "outcomes_sha256": hashlib.sha256(archive).hexdigest(),
                "design": {
                    "campaign_manifest_sha256": hashlib.sha256(
                        manifest_bytes
                    ).hexdigest(),
                    "locked_nominals_sha256": hashlib.sha256(locked_bytes).hexdigest(),
                    "input_manifest_sha256": hashlib.sha256(
                        input_manifest_bytes
                    ).hexdigest(),
                    "family": family,
                    "recoil_seed": seed,
                    "dt_s": 5e-6,
                    "t_max_s": 0.05,
                    "solver": "RK4StHybridCustom",
                    "classification": "sealed_unbiased_final_validation",
                },
            }
            (family_root / f"seed_{seed}.json").write_bytes(_json(row))
            remote_row = json.loads(json.dumps(row))
            remote_row["outcomes_path"] = (
                "/home/test/ytterbium_lab_simulation_new/data/optimization/mot_3d/campaign/"
                f"final_validation/{family}/seed_{seed}.npz"
            )
            results[f"final_validation/{family}/seed_{seed}.json"] = _json(remote_row)
            results[f"final_validation/{family}/seed_{seed}.npz"] = archive
        campaign_path = tmp_path / "campaign.json"
        locked_path = tmp_path / "locked.json"
        input_path = tmp_path / "input.json"
        campaign_path.write_bytes(manifest_bytes)
        locked_path.write_bytes(locked_bytes)
        input_path.write_bytes(input_manifest_bytes)
        summary_path = family_root / "final_validation_summary.json"
        merge(
            argparse.Namespace(
                input_root=str(family_root),
                output=str(summary_path),
                family=family,
                locked_nominals=str(locked_path),
                input_manifest=str(input_path),
                campaign_manifest=str(campaign_path),
                dt=5e-6,
                bootstrap_replicates=20_000,
                bootstrap_seed=92_001,
            )
        )
        results[f"final_validation/{family}/final_validation_summary.json"] = (
            summary_path.read_bytes()
        )
    values = dict(
        manifest_bytes=manifest_bytes,
        locked_nominals_bytes=locked_bytes,
        input_manifest_bytes=input_manifest_bytes,
        generation_submission_bytes=_json(generation_submission),
        submission_bytes=_json(submission),
        job_files=jobs,
        input_files=input_files,
        result_files=results,
        logical_campaign_root="data/optimization/mot_3d/campaign",
        project_directory="/home/test/ytterbium_lab_simulation_new",
        campaign_absolute_path=(
            "/home/test/ytterbium_lab_simulation_new/data/optimization/mot_3d/campaign"
        ),
    )
    if return_values:
        return values
    return validate_final_validation_result_bytes(**values)


@pytest.mark.parametrize(
    ("extension_family", "outcome", "terminal"),
    [
        (None, "complete", "final_report.json"),
        (
            "single_pass",
            "final_validation_extension_required",
            "final_validation_status.json",
        ),
    ],
)
def test_realistic_off_zeus_exact14_is_portable_and_outcome_truthful(
    tmp_path, extension_family, outcome, terminal
):
    validated = _exact14(tmp_path, extension_family=extension_family)
    assert validated.outcome == outcome
    assert validated.terminal_name == terminal
    assert b"/private/" not in validated.campaign_bytes
    assert b"/private/" not in validated.terminal_bytes
    assert validated.summaries["single_pass"]["precision_target_met"] is (
        extension_family != "single_pass"
    )


@pytest.mark.parametrize(
    ("extension_families", "outcome"),
    [
        ((), "complete"),
        (("angled_donut",), "final_validation_extension_required"),
        (("single_pass",), "final_validation_extension_required"),
        (
            ("angled_donut", "single_pass"),
            "final_validation_extension_required",
        ),
    ],
)
def test_all_four_family_precision_outcome_combinations(
    tmp_path, extension_families, outcome
):
    assert _exact14(tmp_path, extension_family=extension_families).outcome == outcome


@pytest.mark.parametrize("extension_family", [None, "single_pass"])
@pytest.mark.parametrize(
    ("boundary", "phase"),
    [
        (boundary, phase)
        for boundary in ("pending", "terminal", "bundle", "campaign", "final", "unlink")
        for phase in ("before", "after")
    ]
    + [("busy_lock", "before"), ("aba", "before"), ("symlink", "before")],
)
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_real_receiver_main_prepares_and_retrieves_exact17_for_both_outcomes(
    tmp_path, monkeypatch, capsys, extension_family, boundary, phase
):
    values = _exact14(
        tmp_path / "science",
        extension_family=extension_family,
        return_values=True,
    )
    root = tmp_path / "repository"
    campaign = root / "data/optimization/mot_3d/campaign"
    (campaign / ".mot_ui/transitions").mkdir(parents=True)
    writes = {
        "campaign.json": values["manifest_bytes"],
        "selection/locked_nominals.json": values["locked_nominals_bytes"],
        "final_validation_inputs/input_manifest.json": values["input_manifest_bytes"],
        "final_validation_input_generation_submission.json": values[
            "generation_submission_bytes"
        ],
        "final_validation_submission.json": values["submission_bytes"],
        **values["job_files"],
        **values["input_files"],
        **values["result_files"],
    }
    for name, raw in writes.items():
        path = campaign / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    identity = {
        "source_files": {"campaign.json": hashlib.sha256(values["manifest_bytes"]).hexdigest()},
        "code_files": {},
        "stage1_receipt_sha256": "b" * 64,
        "stage1_bundle_sha256": "c" * 64,
    }
    submission_key = "d" * 64
    payload = {
        "campaign": "data/optimization/mot_3d/campaign",
        "commit": "a" * 40,
        "submission_key": submission_key,
        "identity": identity,
    }
    payload["transition_key"] = generic_remote.digest(payload)
    jobs = {
        "angled_donut": {
            "array": "101[].zeus-master",
            "merge": "102.zeus-master",
        },
        "single_pass": {
            "array": "103[].zeus-master",
            "merge": "104.zeus-master",
        },
    }
    commands = []
    monkeypatch.setattr(
        generic_remote,
        "_identity",
        lambda *_, **__: (identity, {"campaign.json": values["manifest_bytes"]}),
    )
    monkeypatch.setattr(generic_remote, "_exact_stage2", lambda *_: ({}, jobs))
    def fake_run(argv, input_data=None, limit=0):
        commands.append(tuple(argv))
        if argv and Path(argv[0]).name == "qsub":
            raise AssertionError("completion transition must never submit a job")
        if "rev-parse" in argv:
            return 0, b"a" * 40 + b"\n", b""
        if "branch" in argv:
            return 0, b"main\n", b""
        if "status" in argv:
            return 0, b"", b""
        job = argv[-1]
        if "[]" in job:
            prefix = job.split("[]", 1)[0]
            output = "".join(
                f"Job Id: {prefix}[{index}].zeus-master\n"
                "    job_state = F\n    Exit_status = 0\n"
                for index in range(3)
            )
        else:
            output = f"Job Id: {job}\n    job_state = F\n    Exit_status = 0\n"
        return 0, output.encode(), b""

    monkeypatch.setattr(generic_remote, "run", fake_run)
    monkeypatch.setattr(stage2_remote, "run", fake_run)

    def invoke(operation, request):
        encoded = base64.urlsafe_b64encode(_json(request)).decode()
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "receiver",
                operation,
                "test",
                "/home/test/ytterbium_lab_simulation_new",
                encoded,
            ],
        )
        completion_remote.main(trusted_root_override=root)
        return json.loads(capsys.readouterr().out.splitlines()[-1])

    before = {
        path.relative_to(campaign): path.read_bytes()
        for path in campaign.rglob("*")
        if path.is_file()
    }
    inspected = invoke("inspect", payload)
    assert inspected["lifecycle"] == "ready_to_advance"
    assert {
        path.relative_to(campaign): path.read_bytes()
        for path in campaign.rglob("*")
        if path.is_file()
    } == before
    status = invoke("status", payload)
    assert status["lifecycle"] == "ready_to_advance"
    assert status["completed_array_tasks"] == 6
    assert status["completed_merge_jobs"] == 2
    assert {
        path.relative_to(campaign): path.read_bytes()
        for path in campaign.rglob("*")
        if path.is_file()
    } == before
    publish_bytes = generic_remote._publish_bytes
    publish_relative = generic_remote._publish_relative
    replace_campaign = generic_remote._replace_campaign
    unlink_at = generic_remote.unlink_at
    flock = generic_remote.fcntl.flock
    crashed = False
    aba_path = campaign / "campaign.json"
    aba_raw = aba_path.read_bytes()
    symlink_path = campaign / (
        "final_report.json"
        if extension_family is None
        else "final_validation_status.json"
    )
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"outside")
    if boundary == "symlink":
        symlink_path.symlink_to(outside)

    def crash_once():
        nonlocal crashed
        if not crashed:
            crashed = True
            raise SystemExit(93)

    def maybe_crash(matches, action):
        if matches and phase == "before":
            crash_once()
        result = action()
        if matches and phase == "after":
            crash_once()
        return result

    def wrapped_publish_bytes(parent, name, raw, *, identical_ok):
        matches = (
            (boundary == "pending" and name == DESCRIPTOR.pending_name)
            or (boundary == "bundle" and name == DESCRIPTOR.bundle_name)
            or (boundary == "final" and name == DESCRIPTOR.final_name)
        )
        return maybe_crash(
            matches,
            lambda: publish_bytes(parent, name, raw, identical_ok=identical_ok),
        )

    def wrapped_publish_relative(parent, name, raw):
        expected_terminal = (
            "final_report.json"
            if extension_family is None
            else "final_validation_status.json"
        )
        return maybe_crash(
            boundary == "terminal" and name == expected_terminal,
            lambda: publish_relative(parent, name, raw),
        )

    def wrapped_replace(parent, old, new):
        return maybe_crash(
            boundary == "campaign", lambda: replace_campaign(parent, old, new)
        )

    def wrapped_unlink(parent, name):
        return maybe_crash(
            boundary == "unlink" and name == DESCRIPTOR.pending_name,
            lambda: unlink_at(parent, name),
        )

    def wrapped_flock(fd, operation):
        if boundary == "busy_lock" and operation & generic_remote.fcntl.LOCK_EX:
            raise BlockingIOError
        result = flock(fd, operation)
        if boundary == "aba" and operation & generic_remote.fcntl.LOCK_EX:
            # Mutate a previously captured source only after the receiver owns
            # its operation lock.  Its production frozen-byte re-attestation,
            # rather than a test-side exception, must detect this change.
            aba_path.write_bytes(aba_raw + b" ")
        return result

    monkeypatch.setattr(generic_remote, "_publish_bytes", wrapped_publish_bytes)
    monkeypatch.setattr(generic_remote, "_publish_relative", wrapped_publish_relative)
    monkeypatch.setattr(generic_remote, "_replace_campaign", wrapped_replace)
    monkeypatch.setattr(generic_remote, "unlink_at", wrapped_unlink)
    monkeypatch.setattr(generic_remote.fcntl, "flock", wrapped_flock)
    with pytest.raises(SystemExit) as crash:
        invoke("prepare", {**payload, "nonce": "1" * 32})
    assert crash.value.code == (
        93 if boundary not in {"busy_lock", "aba", "symlink"} else 20
    )
    if boundary == "aba":
        aba_path.write_bytes(aba_raw)
    if boundary == "symlink":
        symlink_path.unlink()
        assert outside.read_bytes() == b"outside"
    monkeypatch.setattr(generic_remote, "_publish_bytes", publish_bytes)
    monkeypatch.setattr(generic_remote, "_publish_relative", publish_relative)
    monkeypatch.setattr(generic_remote, "_replace_campaign", replace_campaign)
    monkeypatch.setattr(generic_remote, "unlink_at", unlink_at)
    monkeypatch.setattr(generic_remote.fcntl, "flock", flock)
    prepared = invoke("prepare", {**payload, "nonce": "1" * 32})
    expected = (
        "complete"
        if extension_family is None
        else "final_validation_extension_required"
    )
    assert prepared["lifecycle"] == expected
    assert prepared["bundle"]["file_count"] == 17
    retrieved = invoke(
        "retrieve",
        {
            **payload,
            "bundle_sha256": prepared["bundle"]["bundle_sha256"],
            "chunk_index": 0,
        },
    )
    chunk = base64.b64decode(retrieved["chunk"]["content"], validate=True)
    assert hashlib.sha256(chunk).hexdigest() == retrieved["chunk"]["sha256"]
    restarted = invoke("prepare", {**payload, "nonce": "1" * 32})
    assert restarted["lifecycle"] == expected
    assert not any(Path(argv[0]).name == "qsub" for argv in commands if argv)


@pytest.mark.parametrize(
    "mutation",
    [
        "metadata_authority",
        "replicate_design",
        "zeeman_authority",
        "manifest_hash",
        "manifest_path",
        "locked_nominals_hash",
        "generation_submission_hash",
        "total_survivors",
        "seed_input_hash",
        "seed_outcome_path",
    ],
)
def test_original_captured_science_is_rejected_before_private_adaptation(
    tmp_path, mutation
):
    values = _exact14(tmp_path, return_values=True)
    inputs = dict(values["input_files"])
    results = dict(values["result_files"])
    manifest = json.loads(values["input_manifest_bytes"])
    row = manifest["ensembles"][0]
    if mutation in {"metadata_authority", "replicate_design", "zeeman_authority"}:
        key = {
            "metadata_authority": "metadata_path",
            "replicate_design": "replicate_path",
            "zeeman_authority": "zeeman_metadata_path",
        }[mutation]
        relative = row[key].split("campaign/", 1)[1]
        decoded = json.loads(inputs[relative])
        if mutation == "metadata_authority":
            decoded["design"]["dt_s"] = 1e-5
            digest_key = "metadata_sha256"
        elif mutation == "replicate_design":
            decoded["design"]["npools"] = 1
            digest_key = "replicate_sha256"
        else:
            decoded["laboratory_spec_sha256"] = "0" * 64
            digest_key = "zeeman_metadata_sha256"
        inputs[relative] = _json(decoded)
        row[digest_key] = hashlib.sha256(inputs[relative]).hexdigest()
    elif mutation == "manifest_hash":
        row["metadata_sha256"] = "0" * 64
    elif mutation == "manifest_path":
        row["metadata_path"] = row["metadata_path"].replace(
            "/campaign/", "/campaign/../outside/"
        )
    elif mutation in {
        "locked_nominals_hash",
        "generation_submission_hash",
        "total_survivors",
    }:
        if mutation == "locked_nominals_hash":
            manifest["locked_nominals_sha256"] = "0" * 64
        elif mutation == "generation_submission_hash":
            manifest["generation_submission_sha256"] = "0" * 64
        else:
            manifest["total_survivors"] += 1
    else:
        name = "final_validation/angled_donut/seed_44001.json"
        decoded = json.loads(results[name])
        if mutation == "seed_input_hash":
            decoded["design"]["input_manifest_sha256"] = "0" * 64
        else:
            decoded["outcomes_path"] = decoded["outcomes_path"].replace(
                "/campaign/", "/campaign/../outside/"
            )
        results[name] = _json(decoded)
    values["input_files"] = inputs
    values["result_files"] = results
    values["input_manifest_bytes"] = _json(manifest)
    with pytest.raises(FinalValidationResultError):
        validate_final_validation_result_bytes(**values)


def test_real_coordinator_preview_confirm_session_and_local_synchronization(
    tmp_path, monkeypatch
):
    campaign = tmp_path / "data/optimization/mot_3d/campaign"
    campaign.mkdir(parents=True)
    old = b'{"name":"campaign","stage":"final_validation"}\n'
    new = b'{"name":"campaign","stage":"complete"}\n'
    (campaign / "campaign.json").write_bytes(old)
    paths = frozenset(
        set(expected_paths())
        | {"final_validation_submission.json", "campaign.json", "final_report.json"}
    )
    files = {
        name: (new if name == "campaign.json" else b'{"kind":"fixture"}\n')
        for name in paths
    }
    built = build_artifact_bundle(
        files,
        campaign="campaign",
        commit="a" * 40,
        from_stage="final_validation",
        to_stage="complete",
        expected_paths=paths,
    )
    identity = {
        "source_files": {"campaign.json": hashlib.sha256(old).hexdigest()},
        "code_files": {},
        "stage3_local_sync_receipt_sha256": "b" * 64,
        "stage3_remote_receipt_sha256": "c" * 64,
        "stage3_bundle_sha256": "d" * 64,
    }
    transition_key = "e" * 64
    receipt = {
        "version": 1,
        "status": "complete",
        "nonce": "f" * 32,
        "transition_key": transition_key,
        "commit": "a" * 40,
        "submission_key": "1" * 64,
        "identity_sha256": canonical_digest(identity),
        "old_campaign_sha256": hashlib.sha256(old).hexdigest(),
        "new_campaign_sha256": hashlib.sha256(new).hexdigest(),
        "evidence_sha256": "2" * 64,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
        "bundle": built.manifest,
        "completed_unix_s": 1_800_000_000,
    }
    jobs = {
        "angled_donut": {"array": "101[].zeus-master", "merge": "102.zeus-master"},
        "single_pass": {"array": "103[].zeus-master", "merge": "104.zeus-master"},
    }
    detail = {
        "outcome": "complete",
        "families": [
            {
                "family": family,
                "candidate_id": f"{family}_finalist_02",
                "conditional_efficiency": 0.5,
                "bootstrap_95_ci": [0.495, 0.505],
                "ci_half_width": 0.0050000000000000044,
                "precision_target_met": True,
            }
            for family in ("angled_donut", "single_pass")
        ],
        "evidence_sha256": "2" * 64,
    }
    ready = RemotePreliminaryTransitionState(
        "ready_to_advance",
        "main",
        jobs,
        6,
        2,
        "valid",
        None,
        "2" * 64,
        None,
        None,
        None,
        detail,
    )
    prepared = RemotePreliminaryTransitionState(
        "complete",
        "main",
        jobs,
        6,
        2,
        "valid",
        None,
        "2" * 64,
        receipt,
        built.manifest,
        None,
        detail,
    )
    profile = ZeusProfile.parse(
        {
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
    )
    plan = (
        "mot_3d-campaign",
        profile,
        campaign,
        {"name": "campaign"},
        "a" * 40,
        identity,
        "1" * 64,
        transition_key,
        "data/optimization/mot_3d/campaign",
        paths,
    )

    class Transport:
        def __init__(self):
            self.nonce = receipt["nonce"]

        def status(self, **_payload):
            return ready

        inspect = status

        def prepare(self, **payload):
            self.nonce = payload["nonce"]
            return RemotePreliminaryTransitionState(
                prepared.lifecycle,
                prepared.branch,
                prepared.jobs,
                prepared.completed_array_tasks,
                prepared.completed_merge_jobs,
                prepared.validation,
                prepared.reason_code,
                prepared.evidence_sha256,
                {**receipt, "nonce": self.nonce},
                prepared.bundle,
                prepared.chunk,
                prepared.winner_selection,
            )

        def retrieve(self, **payload):
            row = built.manifest["chunks"][payload["chunk_index"]]
            return RemotePreliminaryTransitionState(
                "complete",
                "main",
                jobs,
                6,
                2,
                "valid",
                None,
                "2" * 64,
                {**receipt, "nonce": self.nonce},
                built.manifest,
                {
                    "index": row["index"],
                    "sha256": row["sha256"],
                    "content": base64.b64encode(
                        built.chunks[payload["chunk_index"]]
                    ).decode(),
                },
                detail,
            )

    coordinator = Mot3DFinalValidationCompletionCoordinator(
        tmp_path,
        SSH_EXECUTABLE,
        GIT_EXECUTABLE,
        clock=lambda: 1_800_000_000,
        token_factory=lambda: "preview-token",
        transport_factory=lambda _profile: Transport(),
    )
    monkeypatch.setattr(coordinator, "_plan", lambda _request: plan)
    request = {
        "campaign_id": "mot_3d-campaign",
        "username": profile.username,
        "project_directory": profile.project_directory,
    }
    before_status = {
        path.relative_to(campaign): path.read_bytes()
        for path in campaign.rglob("*")
        if path.is_file()
    }
    status = coordinator.status(request)
    assert status["next_action"] == "review_completion"
    assert {
        path.relative_to(campaign): path.read_bytes()
        for path in campaign.rglob("*")
        if path.is_file()
    } == before_status
    from test_workflow_api_server import (
        _session_headers,
        request_json,
        running_server,
    )

    with running_server(
        request_count=7,
        repository_root=tmp_path,
        mot_3d_final_validation_completion_service=coordinator,
    ) as base:
        session_status, headers_a, session_a = request_json(
            f"{base}/api/v1/session",
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        assert session_status == 200, session_a
        trusted_a = _session_headers(
            base,
            headers_a["Set-Cookie"].split(";", 1)[0],
            session_a["data"]["csrf_token"],
        )
        body = json.dumps(request)
        http_status, _, public_status = request_json(
            f"{base}/api/v1/zeus/mot-3d/final-validation-completion/status",
            method="POST",
            headers=trusted_a,
            body=body,
        )
        assert http_status == 200
        assert public_status["data"]["next_action"] == "review_completion"
        http_status, _, preview_response = request_json(
            f"{base}/api/v1/zeus/mot-3d/final-validation-completion/preview",
            method="POST",
            headers=trusted_a,
            body=body,
        )
        assert http_status == 200
        assert preview_response["data"]["completion"] == detail
        token = preview_response["data"]["preview_token"]
        _, headers_b, session_b = request_json(
            f"{base}/api/v1/session",
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        trusted_b = _session_headers(
            base,
            headers_b["Set-Cookie"].split(";", 1)[0],
            session_b["data"]["csrf_token"],
        )
        confirm_body = json.dumps({"preview_token": token})
        wrong_status, _, wrong = request_json(
            f"{base}/api/v1/zeus/mot-3d/final-validation-completion/confirm",
            method="POST",
            headers=trusted_b,
            body=confirm_body,
        )
        assert wrong_status == 412
        assert wrong["error"]["code"] == "confirmation_invalid"
        http_status, _, confirmed_response = request_json(
            f"{base}/api/v1/zeus/mot-3d/final-validation-completion/confirm",
            method="POST",
            headers=trusted_a,
            body=confirm_body,
        )
        assert http_status == 201
        confirmed = confirmed_response["data"]
        repeat_status, _, repeated = request_json(
            f"{base}/api/v1/zeus/mot-3d/final-validation-completion/confirm",
            method="POST",
            headers=trusted_a,
            body=confirm_body,
        )
        assert repeat_status == 201
        assert repeated["data"] == confirmed
    assert confirmed["status"] == "complete"
    assert (campaign / "final_report.json").is_file()


@pytest.mark.parametrize(
    ("interval", "stored", "accepted"),
    [
        ([0.4925, 0.5075], True, True),
        ([0.4924, 0.5076], False, True),
        ([0.4925, 0.5075], False, False),
    ],
)
def test_precision_boundary_is_exact(interval, stored, accepted):
    from studies.mot_3d_campaign import _validate_precision_decision

    half_width = (interval[1] - interval[0]) / 2
    if accepted:
        _, decision = _validate_precision_decision(interval, half_width, stored)
        assert decision is stored
    else:
        with pytest.raises(ValueError):
            _validate_precision_decision(interval, half_width, stored)
