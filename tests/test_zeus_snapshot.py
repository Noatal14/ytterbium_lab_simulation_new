import base64
import json
import os
import shlex
import subprocess
import threading
from pathlib import Path

import pytest

from workflow_api.zeus_snapshot import (
    ZEUS_HOST,
    ZeusProfile,
    ZeusSnapshotError,
    ZeusSnapshotProvider,
    ZeusSnapshotService,
    _REMOTE_SCRIPT,
    _parse_qstat,
)
import workflow_api.zeus_snapshot as zeus_snapshot


def test_zeus_host_is_pinned_to_the_official_endpoint():
    assert ZEUS_HOST == "zeus.technion.ac.il"


def test_remote_wrapper_passes_username_and_project_at_expected_argv_positions(monkeypatch):
    probe = "import json,sys;print(json.dumps({'username': sys.argv[1], 'project': sys.argv[2]}))"
    monkeypatch.setattr(zeus_snapshot, "_REMOTE_SCRIPT", probe)
    profile = ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new")
    completed = subprocess.run(
        shlex.split(zeus_snapshot._remote_command(profile)),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert json.loads(completed.stdout) == {
        "username": "tal.noa",
        "project": "/home/tal.noa/ytterbium_lab_simulation_new",
    }


def _run_remote_script_with_fake_scheduler(tmp_path, *, selected="", select_code=0, qstat_code=0):
    home_root = tmp_path / "home"
    project = home_root / "tal.noa" / "ytterbium_lab_simulation_new"
    project.mkdir(parents=True)
    commands = tmp_path / "bin"; commands.mkdir()
    log = tmp_path / "commands.log"
    git = commands / "git"
    git.write_text("#!/bin/sh\nprintf 'git %s\\n' \"$*\" >> " + shlex.quote(str(log)) + "\ncase \"$1\" in rev-parse) echo " + "a" * 40 + ";; branch) echo main;; esac\n")
    qselect = commands / "qselect"
    qselect.write_text("#!/bin/sh\nprintf 'qselect %s\\n' \"$*\" >> " + shlex.quote(str(log)) + "\nprintf '%s' " + shlex.quote(selected) + "\nexit " + str(select_code) + "\n")
    qstat = commands / "qstat"
    qstat.write_text("#!/bin/sh\nprintf 'qstat %s\\n' \"$*\" >> " + shlex.quote(str(log)) + "\nprintf 'Job Id: 10.zeus-master\\n    Job_Name = active\\n    job_state = R\\n'\nexit " + str(qstat_code) + "\n")
    for command in (git, qselect, qstat): command.chmod(0o755)
    script = _REMOTE_SCRIPT.replace(
        'home = pathlib.Path("/home") / username',
        f'home = pathlib.Path({str(home_root)!r}) / username',
    ).replace(
        '"PATH": "/opt/pbs/bin:/usr/local/bin:/usr/bin:/bin"',
        f'"PATH": {str(commands)!r}',
    )
    encoded = base64.urlsafe_b64encode(script.encode()).decode()
    wrapper = "import base64,sys;payload=sys.argv[1];sys.argv=sys.argv[1:];exec(base64.urlsafe_b64decode(payload).decode('utf-8'))"
    completed = subprocess.run(
        ["python3", "-c", wrapper, encoded, "tal.noa", str(project)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return completed, calls


def test_remote_scheduler_stops_after_qselect_failure(tmp_path):
    completed, calls = _run_remote_script_with_fake_scheduler(tmp_path, selected="10.zeus-master\n", select_code=1)
    assert completed.returncode == 22
    assert json.loads(completed.stdout) == {"error": "scheduler_unavailable"}
    assert not any(call.startswith("qstat ") for call in calls)


def test_remote_scheduler_skips_qstat_for_empty_selection(tmp_path):
    completed, calls = _run_remote_script_with_fake_scheduler(tmp_path)
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["qstat"] == ""
    assert not any(call.startswith("qstat ") for call in calls)


def test_remote_scheduler_passes_valid_ids_as_separate_qstat_arguments(tmp_path):
    completed, calls = _run_remote_script_with_fake_scheduler(tmp_path, selected="10.zeus-master\n11[].zeus-master\n")
    assert completed.returncode == 0
    assert "qstat -f 10.zeus-master 11[].zeus-master" in calls


@pytest.mark.parametrize("selected", [
    "invalid;id\n",
    "10.zeus-master\n10.zeus-master\n",
    "".join(f"{index}.zeus-master\n" for index in range(501)),
])
def test_remote_scheduler_rejects_invalid_duplicate_or_excessive_ids(tmp_path, selected):
    completed, calls = _run_remote_script_with_fake_scheduler(tmp_path, selected=selected)
    assert completed.returncode == 21
    assert json.loads(completed.stdout) == {"error": "remote_check_failed"}
    assert not any(call.startswith("qstat ") for call in calls)


def test_remote_scheduler_reports_qstat_failure(tmp_path):
    completed, calls = _run_remote_script_with_fake_scheduler(tmp_path, selected="10.zeus-master\n", qstat_code=1)
    assert completed.returncode == 22
    assert json.loads(completed.stdout) == {"error": "scheduler_unavailable"}
    assert "qstat -f 10.zeus-master" in calls


def _fake_ssh(tmp_path: Path, *, stdout: str = "", stderr: str = "", code: int = 0):
    executable = tmp_path / "ssh"
    arguments = tmp_path / "arguments.json"
    executable.write_text(
        "#!/usr/bin/python3\n"
        "import json, os, sys\n"
        "assert 'AWS_SECRET_ACCESS_KEY' not in os.environ\n"
        f"open({str(arguments)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        f"sys.stdout.write({stdout!r})\n"
        f"sys.stderr.write({stderr!r})\n"
        f"raise SystemExit({code})\n"
    )
    executable.chmod(0o700)
    return executable, arguments


def _remote_payload(project: str, qstat: str = "") -> str:
    return json.dumps({
        "project_directory": project,
        "git_commit": "a" * 40,
        "branch": "main",
        "dirty": False,
        "qstat": qstat,
    })


def test_profile_is_strictly_confined_to_matching_home():
    canonical = "/home/tal.noa/ytterbium_lab_simulation_new"
    assert ZeusProfile.parse({"username": "tal.noa", "project_directory": canonical}).username == "tal.noa"
    for payload in (
        {"username": "tal.noa; qsub x", "project_directory": canonical},
        {"username": "tal.noa", "project_directory": "/tmp/project"},
        {"username": "tal.noa", "project_directory": "/home/tal.noa/../other"},
        {"username": "tal.noa", "project_directory": canonical, "password": "never"},
    ):
        with pytest.raises(ValueError): ZeusProfile.parse(payload)


def test_qstat_parser_preserves_raw_state_and_requires_exit_evidence():
    text = """Job Id: 10.zeus-master
    Job_Name = queued
    job_state = Q
Job Id: 11.zeus-master
    Job_Name = running
    job_state = R
Job Id: 12.zeus-master
    Job_Name = dependency
    job_state = H
    depend = afterok:10.zeus-master@zeus-master
Job Id: 13.zeus-master
    Job_Name = held
    job_state = H
Job Id: 14.zeus-master
    Job_Name = success
    job_state = X
    Exit_status = 0
Job Id: 15.zeus-master
    Job_Name = failed
    job_state = F
    Exit_status = -29
Job Id: 16.zeus-master
    Job_Name = not-proven
    job_state = F
"""
    jobs = _parse_qstat(text)
    assert [job["state"] for job in jobs] == [
        "queued", "running", "held_attention", "held_attention",
        "completed_success", "completed_failed", "unknown",
    ]
    assert jobs[2]["dependencies"] == ["10.zeus-master"]
    assert jobs[2]["state"] == "held_attention"
    assert jobs[4]["raw_state"] == "X" and jobs[4]["exit_status"] == 0


def test_hold_with_dependency_and_additional_hold_evidence_requires_attention():
    jobs = _parse_qstat("""Job Id: 20.zeus-master
    Job_Name = ambiguous-hold
    job_state = H
    depend = afterok:19.zeus-master@zeus-master
    comment = Dependency recorded; job also held by an operator
""")
    assert jobs[0]["dependencies"] == ["19.zeus-master"]
    assert jobs[0]["state"] == "held_attention"


@pytest.mark.parametrize("text", [
    "unexpected scheduler prose",
    "Job Id: 1.zeus-master\n    job_state = Q\nJob Id: 1.zeus-master\n    job_state = R\n",
    "Job Id: 1.zeus-master\n    job_state = Q\n    job_state = R\n",
    "Job Id: invalid;id\n    job_state = Q\n",
    "Job Id: 1.zeus-master\n    job_state = Q\x1b[31m\n",
    "Job Id: 1.zeus-master\n    job_state = F\n    Exit_status = 999999999999\n",
])
def test_qstat_parser_fails_closed_on_ambiguous_or_hostile_output(text):
    with pytest.raises(ZeusSnapshotError, match="malformed_remote_response"):
        _parse_qstat(text)


def test_provider_uses_only_pinned_read_only_ssh_contract(tmp_path, monkeypatch):
    project = "/home/tal.noa/ytterbium_lab_simulation_new"
    executable, recorded = _fake_ssh(tmp_path, stdout=_remote_payload(project))
    repository = tmp_path / "repo"; repository.mkdir()
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/test-agent.sock")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-reach-ssh")
    provider = ZeusSnapshotProvider(repository, executable)
    snapshot = provider.snapshot(ZeusProfile("tal.noa", project))
    assert snapshot["connection_status"] == "connected"
    assert snapshot["profile"] == {
        "host": ZEUS_HOST, "username": "tal.noa", "project_directory": project,
        "authentication": "ssh-key-or-agent",
    }
    argv = json.loads(recorded.read_text())
    assert "-F" in argv and "none" in argv
    assert "BatchMode=yes" in argv and "PasswordAuthentication=no" in argv
    assert "StrictHostKeyChecking=yes" in argv and "ProxyCommand=none" in argv and "ProxyJump=none" in argv
    assert f"tal.noa@{ZEUS_HOST}" in argv
    assert not any(token in {"qsub", "qdel", "qalter"} for token in argv)
    remote = shlex.split(argv[-1])
    assert remote[:2] == ["python3", "-c"]
    decoded = base64.urlsafe_b64decode(remote[3]).decode()
    assert decoded == _REMOTE_SCRIPT
    assert '["qselect", "-u", username]' in decoded
    assert '["qstat", "-f"] + job_ids' in decoded
    assert 'qstat", "-x", "-f", "-u"' not in decoded
    assert all(forbidden not in decoded for forbidden in ("qsub", "qdel", "qalter"))


@pytest.mark.parametrize(("stderr", "code"), [
    ("Permission denied (publickey).", "zeus_authentication_required"),
    ("Host key verification failed.", "zeus_host_key_untrusted"),
    ("ssh: Could not resolve hostname", "zeus_unreachable"),
])
def test_provider_sanitizes_common_ssh_failures(tmp_path, stderr, code):
    executable, _ = _fake_ssh(tmp_path, stderr=stderr, code=255)
    repository = tmp_path / "repo"; repository.mkdir()
    provider = ZeusSnapshotProvider(repository, executable)
    with pytest.raises(ZeusSnapshotError, match=code):
        provider.snapshot(ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new"))


def test_provider_rejects_oversized_and_malformed_output(tmp_path):
    executable, _ = _fake_ssh(tmp_path, stdout="x" * (2 * 1024 * 1024 + 65536))
    repository = tmp_path / "repo"; repository.mkdir()
    provider = ZeusSnapshotProvider(repository, executable)
    with pytest.raises(ZeusSnapshotError, match="malformed_remote_response"):
        provider.snapshot(ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new"))
    executable, _ = _fake_ssh(tmp_path, stdout="not-json")
    provider = ZeusSnapshotProvider(repository, executable)
    with pytest.raises(ZeusSnapshotError, match="malformed_remote_response"):
        provider.snapshot(ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new"))


def test_provider_kills_a_timed_out_fake_ssh(tmp_path):
    executable = tmp_path / "ssh"
    executable.write_text("#!/usr/bin/python3\nimport time\ntime.sleep(30)\n")
    executable.chmod(0o700)
    repository = tmp_path / "repo"; repository.mkdir()
    provider = ZeusSnapshotProvider(repository, executable, timeout=0.05)
    with pytest.raises(ZeusSnapshotError, match="zeus_timeout"):
        provider.snapshot(ZeusProfile("tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new"))

def test_service_is_single_flight_and_rate_limited():
    class Provider:
        def snapshot(self, profile): return {"profile": profile.username}
    service = ZeusSnapshotService(Provider())
    assert service.snapshot({"username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"}) == {"profile": "tal.noa"}
    with pytest.raises(ZeusSnapshotError, match="rate_limited"):
        service.snapshot({"username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"})


def test_service_rejects_a_concurrent_refresh():
    entered = threading.Event(); release = threading.Event()
    class Provider:
        def snapshot(self, profile):
            entered.set(); release.wait(timeout=2); return {"profile": profile.username}
    service = ZeusSnapshotService(Provider())
    result = []
    worker = threading.Thread(target=lambda: result.append(service.snapshot({"username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"})))
    worker.start(); assert entered.wait(timeout=1)
    with pytest.raises(ZeusSnapshotError, match="rate_limited"):
        service.snapshot({"username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"})
    release.set(); worker.join(timeout=2)
    assert result == [{"profile": "tal.noa"}]


def test_import_and_profile_parsing_do_not_execute_ssh(monkeypatch):
    def forbidden(*_args, **_kwargs): raise AssertionError("SSH must not run")
    monkeypatch.setattr("subprocess.Popen", forbidden)
    ZeusProfile.parse({"username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"})
