import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from workflow_api.zeus_discovery_submission_remote import canonical_digest


FILES = {
    "campaign.json",
    "jobs/01_smoke_angled_donut.pbs",
    "jobs/01_smoke_single_pass.pbs",
    "jobs/02_submit_discovery_chain.sh",
    "jobs/angled_donut/round_01.pbs",
    "jobs/angled_donut/round_02.pbs",
    "jobs/single_pass/round_01.pbs",
    "jobs/single_pass/round_02.pbs",
    "jobs/single_pass/round_03.pbs",
}


def _receiver_fixture(tmp_path, monkeypatch):
    source = (
        Path(__file__).parents[1] / "workflow_api/zeus_discovery_submission_remote.py"
    ).read_text()
    source = source.replace(
        '        or project != f"/home/{username}/ytterbium_lab_simulation_new"\n',
        "",
    )
    namespace = {"__name__": "discovery_receiver_test"}
    exec(compile(source, "<receiver>", "exec"), namespace)
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_3d/campaign"
    transition = campaign / ".mot_ui/transitions"
    transition.mkdir(parents=True)
    commit = "a" * 40
    manifest = {
        "kind": "mot_3d_campaign_v2",
        "name": "campaign",
        "stage": "discovery",
        "provenance": {"git_commit": commit, "physical_model_sha256": "b" * 64},
        "input_directory": "data/particle_states/after_2d_mot/source",
        "upstream_2d_campaign": {},
        "input_roles": {},
        "design": {},
        "jobs": {},
    }
    for index, name in enumerate(sorted(FILES)):
        path = campaign / name
        path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            (json.dumps(manifest) + "\n").encode()
            if name == "campaign.json"
            else f"artifact-{index}\n".encode()
        )
        path.write_bytes(content)
    files = {
        name: hashlib.sha256((campaign / name).read_bytes()).hexdigest()
        for name in FILES
    }
    nonce = "c" * 32
    receipt = {
        "status": "discovery_prepared",
        "nonce": nonce,
        "bootstrap_key": "",
        "commit": commit,
        "physical_model_sha256": "b" * 64,
        "source_2d_campaign_sha256": "d" * 64,
        "source_2d_final_report_sha256": "e" * 64,
        "input_registry_sha256": "f" * 64,
        "timestep_policy_sha256": "1" * 64,
        "files": files,
        "completed_unix_s": 1,
    }
    receipt["bootstrap_key"] = canonical_digest(
        {
            "campaign_name": "campaign",
            "commit": commit,
            "physical_model_sha256": receipt["physical_model_sha256"],
            "source_2d_campaign_sha256": receipt["source_2d_campaign_sha256"],
            "source_2d_final_report_sha256": receipt["source_2d_final_report_sha256"],
            "input_registry_sha256": receipt["input_registry_sha256"],
            "timestep_policy_sha256": receipt["timestep_policy_sha256"],
            "files": files,
            "nonce": nonce,
        }
    )
    receipt_path = transition / "discovery_bootstrap.json"
    receipt_path.write_text(json.dumps(receipt))
    bootstrap_digest = canonical_digest(receipt)
    base = {
        "campaign": "data/optimization/mot_3d/campaign",
        "commit": commit,
        "bootstrap_digest": bootstrap_digest,
        "bootstrap_key": receipt["bootstrap_key"],
        "bootstrap_nonce": nonce,
        "files": files,
    }
    base["submission_key"] = canonical_digest(base)
    calls = []

    def run(argv, **kwargs):
        calls.append((list(argv), kwargs.get("input")))
        stdout = kwargs["stdout"]
        if argv[-2:] == ["rev-parse", "HEAD"]:
            stdout.write((commit + "\n").encode())
        elif argv[-2:] == ["branch", "--show-current"]:
            stdout.write(b"main\n")
        elif argv[0] == "/usr/local/bin/qsub":
            count = sum(call[0][0] == "/usr/local/bin/qsub" for call in calls)
            stdout.write(f"{100 + count}[].zeus-master\n".encode())
        elif argv[0] == "/usr/local/bin/qstat":
            job = argv[-1]
            prefix = job.split("[]", 1)[0]
            stdout.write(
                "".join(
                    f"Job Id: {prefix}[{index}].zeus-master\n"
                    "    job_state = F\n"
                    "    Exit_status = 0\n"
                    for index in range(3)
                ).encode()
            )
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(namespace["subprocess"], "run", run)
    return namespace, root, base, calls


def _invoke(namespace, root, payload, operation, monkeypatch, capsys):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    monkeypatch.setattr(
        sys, "argv", ["receiver", operation, "tal.noa", str(root), encoded]
    )
    namespace["main"]()
    return json.loads(capsys.readouterr().out)


def test_inspect_is_zero_write_and_submit_runs_exact_five_round_arrays(
    tmp_path, monkeypatch, capsys
):
    namespace, root, base, calls = _receiver_fixture(tmp_path, monkeypatch)
    inspected = _invoke(namespace, root, base, "inspect", monkeypatch, capsys)
    assert inspected["lifecycle"] == "eligible"
    assert not (root / "data/optimization/mot_3d/campaign/.mot_ui/submissions").exists()
    assert not any(call[0][0] == "/usr/local/bin/qsub" for call in calls)

    submitted = _invoke(
        namespace,
        root,
        {**base, "nonce": "2" * 32},
        "submit",
        monkeypatch,
        capsys,
    )
    qsub = [call for call in calls if call[0][0] == "/usr/local/bin/qsub"]
    assert len(qsub) == 5
    assert all(call[0][1:3] == ["-J", "0-2:1"] for call in qsub)
    assert "-W" not in qsub[0][0] and "-W" in qsub[1][0]
    assert "-W" not in qsub[2][0] and "-W" in qsub[3][0] and "-W" in qsub[4][0]
    assert all(data is not None for _, data in qsub)
    assert submitted["lifecycle"] == "submitted"
    assert [
        len(submitted["chain"][family]) for family in ("angled_donut", "single_pass")
    ] == [2, 3]
    before_status = len(calls)
    status = _invoke(namespace, root, base, "status", monkeypatch, capsys)
    qstat = [
        call for call in calls[before_status:] if call[0][0] == "/usr/local/bin/qstat"
    ]
    assert len(qstat) == 5
    assert all(call[0][1:4] == ["-x", "-t", "-f"] for call in qstat)
    assert status["lifecycle"] == "completed_success"


def test_pending_state_blocks_retry_without_qsub(tmp_path, monkeypatch, capsys):
    namespace, root, base, calls = _receiver_fixture(tmp_path, monkeypatch)
    submissions = root / "data/optimization/mot_3d/campaign/.mot_ui/submissions"
    submissions.mkdir(parents=True)
    (submissions / "discovery.pending.json").write_text("{}")
    result = _invoke(namespace, root, base, "inspect", monkeypatch, capsys)
    assert result["lifecycle"] == "outcome_unknown"
    assert not any(call[0][0] == "/usr/local/bin/qsub" for call in calls)


def test_receiver_rejects_tampered_bootstrap_key(tmp_path, monkeypatch, capsys):
    namespace, root, base, calls = _receiver_fixture(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        _invoke(
            namespace,
            root,
            {**base, "bootstrap_key": "0" * 64},
            "inspect",
            monkeypatch,
            capsys,
        )
    assert not any(call[0][0] == "/usr/local/bin/qsub" for call in calls)


def test_receiver_rejects_symlinked_bootstrap_receipt(tmp_path, monkeypatch, capsys):
    namespace, root, base, calls = _receiver_fixture(tmp_path, monkeypatch)
    receipt = root / (
        "data/optimization/mot_3d/campaign/"
        ".mot_ui/transitions/discovery_bootstrap.json"
    )
    target = tmp_path / "outside-receipt.json"
    receipt.rename(target)
    receipt.symlink_to(target)
    with pytest.raises(SystemExit):
        _invoke(namespace, root, base, "inspect", monkeypatch, capsys)
    assert not any(call[0][0] == "/usr/local/bin/qsub" for call in calls)


def test_scheduler_parser_rejects_garbage_and_missing_children():
    from workflow_api.zeus_discovery_submission_remote import scheduler_state

    job = "101[].zeus-master"
    assert scheduler_state(b"garbage\n", job) == "status_unknown"
    assert (
        scheduler_state(
            b"Job Id: 101[0].zeus-master\n"
            b"    job_state = F\n"
            b"    Exit_status = 0\n",
            job,
        )
        == "status_unknown"
    )


def test_receiver_source_never_executes_smoke_or_wrapper():
    source = (
        Path(__file__).parents[1] / "workflow_api/zeus_discovery_submission_remote.py"
    ).read_text()
    assert '"jobs/01_smoke_angled_donut.pbs"' in source
    assert '"jobs/01_smoke_single_pass.pbs"' in source
    assert "for family, job_files in JOBS.items()" in source
    assert "shell=True" not in source


def test_receiver_cross_process_lock_prevents_duplicate_qsub(
    tmp_path, monkeypatch, capsys
):
    namespace, root, base, calls = _receiver_fixture(tmp_path, monkeypatch)
    submissions = root / "data/optimization/mot_3d/campaign/.mot_ui/submissions"
    submissions.mkdir(parents=True)
    lock = submissions / "discovery.lock"
    ready = tmp_path / "lock-ready"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import fcntl,pathlib,time;"
                f"p=pathlib.Path({str(lock)!r});"
                "f=p.open('a+b');fcntl.flock(f,fcntl.LOCK_EX);"
                f"pathlib.Path({str(ready)!r}).write_text('ready');"
                "time.sleep(10)"
            ),
        ]
    )
    try:
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(0.01)
        assert ready.exists()
        with pytest.raises(SystemExit):
            _invoke(
                namespace,
                root,
                {**base, "nonce": "2" * 32},
                "submit",
                monkeypatch,
                capsys,
            )
        assert not any(call[0][0] == "/usr/local/bin/qsub" for call in calls)
    finally:
        holder.terminate()
        holder.wait(timeout=5)
