from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest

from workflow_api.mot_3d_preliminary_submission import (
    Mot3DPreliminarySubmissionCoordinator,
    Mot3DPreliminarySubmissionError,
    RemotePreliminarySubmissionState,
)
from workflow_api import mot_3d_preliminary_submission_remote as receiver
from workflow_api.mot_3d_preliminary_submission_remote import qstat_fields, scheduler
from workflow_api.mot_3d_stage_topology import PRELIMINARY_CHECK_TOPOLOGY


def state(lifecycle, jobs, nonce=None, submitted=None, arrays=0, merges=0):
    return RemotePreliminarySubmissionState(
        lifecycle, "main", jobs, nonce, submitted, arrays, merges
    )


EMPTY = {
    "angled_donut": {"array": None, "merge": None},
    "single_pass": {"array": None, "merge": None},
}


def test_outcome_unknown_accepts_only_exact_global_prefix_and_nonce():
    valid = {
        "angled_donut": {
            "array": "100[].zeus-master",
            "merge": "101.zeus-master",
        },
        "single_pass": {"array": None, "merge": None},
    }
    Mot3DPreliminarySubmissionCoordinator._validate(
        state("outcome_unknown", valid, "a" * 32), "status"
    )
    invalid = {
        "angled_donut": {"array": None, "merge": None},
        "single_pass": {"array": "102[].zeus-master", "merge": None},
    }
    with pytest.raises(Mot3DPreliminarySubmissionError):
        Mot3DPreliminarySubmissionCoordinator._validate(
            state("outcome_unknown", invalid, "a" * 32), "status"
        )


def test_duplicate_numeric_job_ids_fail_closed():
    jobs = {
        "angled_donut": {
            "array": "100[].zeus-master",
            "merge": "100.zeus-master",
        },
        "single_pass": {
            "array": "102[].zeus-master",
            "merge": "103.zeus-master",
        },
    }
    with pytest.raises(Mot3DPreliminarySubmissionError):
        Mot3DPreliminarySubmissionCoordinator._validate(
            state("submitted", jobs, "a" * 32, 1), "status"
        )


def test_qstat_parser_accepts_pbs_continuations():
    parsed = qstat_fields(
        b"Job Id: 100[0].zeus-master\n"
        b"    job_state = F\n"
        b"    comment = first\n"
        b"\tcontinued\n"
        b"    Exit_status = 0\n"
    )
    assert parsed == {
        "100[0].zeus-master": {
            "job_state": "F",
            "comment": "first continued",
            "Exit_status": "0",
        }
    }


def test_array_parent_failure_dominates_successful_children(monkeypatch):
    output = b"Job Id: 100[].zeus-master\n    job_state = F\n    Exit_status = 1\n"
    for index in range(3):
        output += (
            f"Job Id: 100[{index}].zeus-master\n"
            "    job_state = F\n"
            "    Exit_status = 0\n"
        ).encode()
    monkeypatch.setattr(
        "workflow_api.mot_3d_preliminary_submission_remote.run",
        lambda *args, **kwargs: (0, output, b""),
    )
    assert scheduler("100[].zeus-master", "array") == ("completed_failed", 3)


def test_canonical_renderer_matches_reviewed_preliminary_topology(tmp_path):
    from studies.mot_3d_campaign import _selection_stage_jobs

    manifest = {
        "provenance": {"git_commit": "a" * 40},
        "design": {"screening_dt_s": 1e-5},
    }
    selections = {
        family: tmp_path / "selection" / f"{family}.json"
        for family in ("angled_donut", "single_pass")
    }
    workers, merges = _selection_stage_jobs(
        tmp_path,
        manifest,
        "preliminary_check",
        selections,
        "preliminary_check",
        150,
        51001,
        52001,
    )
    topology = PRELIMINARY_CHECK_TOPOLOGY
    assert set(workers) == set(merges) == set(receiver.FAMILIES)
    for family in ("angled_donut", "single_pass"):
        assert (
            workers[family].relative_to(tmp_path).as_posix()
            == receiver.JOBS[family]["array"]
        )
        assert (
            merges[family].relative_to(tmp_path).as_posix()
            == receiver.JOBS[family]["merge"]
        )
        worker = workers[family].read_text()
        merge = merges[family].read_text()
        assert "#PBS -l select=1:ncpus=200:mem=64gb" in worker
        assert f"#PBS -l walltime={topology.array_walltime}" in worker
        assert "--num-workers 3" in worker
        assert "--particles-per-ensemble 150" in worker
        assert "--selection-seed 51001" in worker
        assert "--npools 200" in worker
        assert "--dt 1e-05" in worker
        assert "#PBS -l select=1:ncpus=1:mem=4gb" in merge
        assert f"#PBS -l walltime={topology.merge_walltime}" in merge
        assert "--bootstrap-seed 52001" in merge


def test_receiver_inspect_is_zero_write_and_rejects_symlinked_receipt_root(
    tmp_path, monkeypatch, capsys
):
    root, campaign, payload, _ = _receiver_repository(tmp_path)

    def git_only(argv, input_data=None, limit=None):
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "rev-parse"]:
            return 0, b"a" * 40 + b"\n", b""
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "branch"]:
            return 0, b"main\n", b""
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "status"]:
            return 0, b"", b""
        raise AssertionError(argv)

    before = sorted(path.relative_to(campaign) for path in campaign.rglob("*"))
    _invoke_receiver(monkeypatch, root, "inspect", payload, git_only)
    assert json.loads(capsys.readouterr().out)["lifecycle"] == "eligible"
    assert sorted(path.relative_to(campaign) for path in campaign.rglob("*")) == before

    outside = tmp_path / "outside"
    outside.mkdir()
    (campaign / ".mot_ui/submissions").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SystemExit):
        _invoke_receiver(monkeypatch, root, "inspect", payload, git_only)
    assert not list(outside.iterdir())


def _receiver_repository(tmp_path: Path):
    root = tmp_path / "remote"
    campaign = root / "data/optimization/mot_3d/campaign"
    campaign.mkdir(parents=True)
    (campaign / ".mot_ui/transitions").mkdir(parents=True)
    design = {
        "screening_dt_s": 1e-5,
        "solver": "RK4StHybridCustom",
        "timestep_evidence": {"policy_sha256": "4" * 64},
    }
    manifest = {
        "name": "campaign",
        "stage": "preliminary_check",
        "provenance": {"git_commit": "a" * 40, "physical_model_sha256": "1" * 64},
        "upstream_2d_campaign": {
            "campaign_sha256": "2" * 64,
            "final_report_sha256": "3" * 64,
        },
        "design": design,
        "stages": {
            "preliminary_check": {
                "classification": "candidate_selection_not_final_validation",
                "input_role": "preliminary_check",
            }
        },
    }
    files = {"campaign.json": json.dumps(manifest, sort_keys=True).encode()}
    for family in receiver.FAMILIES:
        files[f"selection/discovery/{family}.json"] = b"{}\n"
        files[receiver.JOBS[family]["array"]] = f"array-{family}\n".encode()
        files[receiver.JOBS[family]["merge"]] = f"merge-{family}\n".encode()
    for name, raw in files.items():
        target = campaign / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    transition = {
        "status": "preliminary_check_prepared",
        "transition_key": "5" * 64,
        "bundle": {"bundle_sha256": "6" * 64},
    }
    transition_raw = receiver.canonical(transition) + b"\n"
    (campaign / ".mot_ui/transitions/preliminary_check.json").write_bytes(
        transition_raw
    )
    code_files = {}
    for name in {
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
    }:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(name.encode())
        code_files[name] = hashlib.sha256(name.encode()).hexdigest()
    identity = {
        "campaign_sha256": hashlib.sha256(files["campaign.json"]).hexdigest(),
        "local_transition_receipt_sha256": "7" * 64,
        "transition_key": "5" * 64,
        "remote_transition_receipt_sha256": hashlib.sha256(
            receiver.canonical(transition)
        ).hexdigest(),
        "bundle_sha256": "6" * 64,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
        "science": {
            "classification": "candidate_selection_not_final_validation",
            "candidates_per_family": 12,
            "input_ensembles": 4,
            "particles_per_ensemble": 150,
            "total_particles": 600,
            "recoil_seeds": [41001, 41002, 41003],
            "dt_s": 1e-5,
            "t_max_s": 0.1,
            "solver": "RK4StHybridCustom",
            "selection_seed": 51001,
            "bootstrap_replicates": 10000,
            "bootstrap_seed": 52001,
        },
        "physical_model_sha256": "1" * 64,
        "upstream_campaign_sha256": "2" * 64,
        "upstream_final_report_sha256": "3" * 64,
        "timestep_policy_sha256": "4" * 64,
        "code_files": code_files,
    }
    payload = {
        "campaign": "data/optimization/mot_3d/campaign",
        "commit": "a" * 40,
        "identity": identity,
    }
    payload["submission_key"] = receiver.digest(
        {"campaign": payload["campaign"], "commit": payload["commit"], **identity}
    )
    return root, campaign, payload, files


def _invoke_receiver(monkeypatch, root, operation, payload, fake_run):
    encoded = base64.urlsafe_b64encode(receiver.canonical(payload)).decode()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "receiver",
            operation,
            "tal.noa",
            "/home/tal.noa/ytterbium_lab_simulation_new",
            encoded,
        ],
    )
    monkeypatch.setattr(receiver, "run", fake_run)
    receiver.main(trusted_root_override=root)


def test_receiver_submits_exact_chain_and_restart_does_not_resubmit(
    tmp_path, monkeypatch, capsys
):
    root, campaign, payload, frozen = _receiver_repository(tmp_path)
    payload = {**payload, "nonce": "8" * 32}
    calls = []
    job_ids = iter(
        [
            b"510[].zeus-master\n",
            b"511.zeus-master\n",
            b"512[].zeus-master\n",
            b"513.zeus-master\n",
        ]
    )

    def fake_run(argv, input_data=None, limit=None):
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "rev-parse"]:
            return 0, b"a" * 40 + b"\n", b""
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "branch"]:
            return 0, b"main\n", b""
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "status"]:
            return 0, b"", b""
        if argv[0] == "/usr/local/bin/qsub":
            calls.append((argv, input_data))
            return 0, next(job_ids), b""
        raise AssertionError(argv)

    _invoke_receiver(monkeypatch, root, "submit", payload, fake_run)
    result = json.loads(capsys.readouterr().out)
    assert result["lifecycle"] == "submitted"
    assert [call[0][1:] for call in calls] == [
        ["-J", "0-2:1"],
        ["-W", "depend=afterok:510[].zeus-master"],
        ["-J", "0-2:1"],
        ["-W", "depend=afterok:512[].zeus-master"],
    ]
    assert [call[1] for call in calls] == [
        frozen[receiver.JOBS["angled_donut"]["array"]],
        frozen[receiver.JOBS["angled_donut"]["merge"]],
        frozen[receiver.JOBS["single_pass"]["array"]],
        frozen[receiver.JOBS["single_pass"]["merge"]],
    ]

    inspect_payload = {key: value for key, value in payload.items() if key != "nonce"}
    before = sorted(path.relative_to(campaign) for path in campaign.rglob("*"))
    _invoke_receiver(monkeypatch, root, "inspect", inspect_payload, fake_run)
    assert json.loads(capsys.readouterr().out)["lifecycle"] == "submitted"
    assert len(calls) == 4
    assert sorted(path.relative_to(campaign) for path in campaign.rglob("*")) == before


def test_receiver_recovers_crash_after_final_receipt_without_resubmitting(
    tmp_path, monkeypatch, capsys
):
    root, campaign, payload, _ = _receiver_repository(tmp_path)
    submit_payload = {**payload, "nonce": "8" * 32}
    job_ids = iter(
        [
            b"510[].zeus-master\n",
            b"511.zeus-master\n",
            b"512[].zeus-master\n",
            b"513.zeus-master\n",
        ]
    )
    qsub_count = 0

    def fake_run(argv, input_data=None, limit=None):
        nonlocal qsub_count
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "rev-parse"]:
            return 0, b"a" * 40 + b"\n", b""
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "branch"]:
            return 0, b"main\n", b""
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "status"]:
            return 0, b"", b""
        if argv[0] == "/usr/local/bin/qsub":
            qsub_count += 1
            return 0, next(job_ids), b""
        if argv[0] == "/usr/local/bin/qstat":
            job = argv[-1]
            if "[]" in job:
                prefix = job.split("[]", 1)[0]
                rows = b"".join(
                    (
                        f"Job Id: {prefix}[{index}].zeus-master\n"
                        "    job_state = F\n    Exit_status = 0\n"
                    ).encode()
                    for index in range(3)
                )
            else:
                rows = (
                    f"Job Id: {job}\n    job_state = F\n    Exit_status = 0\n"
                ).encode()
            return 0, rows, b""
        raise AssertionError(argv)

    original_replace = receiver.replace_at
    replacements = 0

    def crash_before_final_compat(*args, **kwargs):
        nonlocal replacements
        replacements += 1
        if replacements == 5:
            raise SystemExit(99)
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(receiver, "replace_at", crash_before_final_compat)
    with pytest.raises(SystemExit, match="99"):
        _invoke_receiver(monkeypatch, root, "submit", submit_payload, fake_run)
    capsys.readouterr()
    assert qsub_count == 4
    assert (
        campaign / ".mot_ui/submissions/preliminary_check.json"
    ).is_file(), "the durable aggregate receipt must precede compatibility publication"

    monkeypatch.setattr(receiver, "replace_at", original_replace)
    status_payload = {key: value for key, value in payload.items() if key != "nonce"}
    _invoke_receiver(monkeypatch, root, "status", status_payload, fake_run)
    result = json.loads(capsys.readouterr().out)
    assert result["lifecycle"] == "completed_success"
    assert result["completed_array_tasks"] == 6
    assert result["completed_merge_jobs"] == 2
    assert qsub_count == 4
    submissions = campaign / ".mot_ui/submissions"
    assert not (submissions / "preliminary_check.pending.json").exists()
    assert not list(submissions.glob("*.pending.json"))


def test_receiver_ambiguous_qsub_is_durable_and_never_retried(
    tmp_path, monkeypatch, capsys
):
    root, _, payload, _ = _receiver_repository(tmp_path)
    submit_payload = {**payload, "nonce": "8" * 32}
    qsub_count = 0

    def fake_run(argv, input_data=None, limit=None):
        nonlocal qsub_count
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "rev-parse"]:
            return 0, b"a" * 40 + b"\n", b""
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "branch"]:
            return 0, b"main\n", b""
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "status"]:
            return 0, b"", b""
        if argv[0] == "/usr/local/bin/qsub":
            qsub_count += 1
            return 1, b"", b"connection lost"
        raise AssertionError(argv)

    _invoke_receiver(monkeypatch, root, "submit", submit_payload, fake_run)
    assert json.loads(capsys.readouterr().out)["lifecycle"] == "outcome_unknown"
    assert qsub_count == 1
    status_payload = {key: value for key, value in payload.items() if key != "nonce"}
    _invoke_receiver(monkeypatch, root, "status", status_payload, fake_run)
    result = json.loads(capsys.readouterr().out)
    assert result["lifecycle"] == "outcome_unknown"
    assert qsub_count == 1


@pytest.mark.parametrize("completed_steps", [1, 2, 3])
@pytest.mark.parametrize("boundary", ["before_pending_unlink", "before_compat_replace"])
def test_receiver_reconciles_every_intermediate_done_receipt_without_resubmit(
    tmp_path, monkeypatch, capsys, completed_steps, boundary
):
    root, campaign, payload, _ = _receiver_repository(tmp_path)
    submit_payload = {**payload, "nonce": "8" * 32}
    ids = [
        b"510[].zeus-master\n",
        b"511.zeus-master\n",
        b"512[].zeus-master\n",
        b"513.zeus-master\n",
    ]
    qsub_count = 0

    def fake_run(argv, input_data=None, limit=None):
        nonlocal qsub_count
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "rev-parse"]:
            return 0, b"a" * 40 + b"\n", b""
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "branch"]:
            return 0, b"main\n", b""
        if argv[:4] == ["/usr/bin/git", "-C", str(root), "status"]:
            return 0, b"", b""
        if argv[0] == "/usr/local/bin/qsub":
            result = ids[qsub_count]
            qsub_count += 1
            return 0, result, b""
        raise AssertionError(argv)

    original_unlink = receiver.unlink_at
    original_replace = receiver.replace_at
    replacements = 0

    def maybe_crash_unlink(parent, name):
        if (
            boundary == "before_pending_unlink"
            and qsub_count == completed_steps
            and name.endswith(".pending.json")
            and name != "preliminary_check.pending.json"
        ):
            raise SystemExit(91)
        return original_unlink(parent, name)

    def maybe_crash_replace(*args, **kwargs):
        nonlocal replacements
        replacements += 1
        if boundary == "before_compat_replace" and replacements == completed_steps:
            raise SystemExit(92)
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(receiver, "unlink_at", maybe_crash_unlink)
    monkeypatch.setattr(receiver, "replace_at", maybe_crash_replace)
    with pytest.raises(SystemExit):
        _invoke_receiver(monkeypatch, root, "submit", submit_payload, fake_run)
    capsys.readouterr()
    assert qsub_count == completed_steps

    monkeypatch.setattr(receiver, "unlink_at", original_unlink)
    monkeypatch.setattr(receiver, "replace_at", original_replace)
    status_payload = {key: value for key, value in payload.items() if key != "nonce"}
    _invoke_receiver(monkeypatch, root, "status", status_payload, fake_run)
    result = json.loads(capsys.readouterr().out)
    assert result["lifecycle"] == "partial"
    assert qsub_count == completed_steps
    known = [
        job
        for family in receiver.FAMILIES
        for job in result["jobs"][family].values()
        if job is not None
    ]
    assert len(known) == completed_steps
    compat = json.loads((campaign / "preliminary_check_submission.json").read_text())
    compat_known = [
        job
        for family in receiver.FAMILIES
        for job in compat["families"][family].values()
        if job is not None
    ]
    assert compat["status"] == "submitting"
    assert compat_known == known
    remaining = {
        path.name for path in (campaign / ".mot_ui/submissions").glob("*.pending.json")
    }
    assert remaining == {"preliminary_check.pending.json"}


@pytest.mark.parametrize(
    "raw",
    [
        b"garbage\nJob Id: 100.zeus-master\n    job_state = Q\n",
        b"Job Id: 100.zeus-master\n    job_state = Q\ntrailing\n",
        b"Job Id: 100.zeus-master\nnot a field\n",
        b"Job Id: 100.zeus-master\n    job_state = Q\n    job_state = R\n",
    ],
)
def test_qstat_parser_rejects_noncanonical_output(raw):
    assert qstat_fields(raw) is None
