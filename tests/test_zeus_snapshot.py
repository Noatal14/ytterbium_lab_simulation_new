import base64
import json
import os
import shlex
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


def test_zeus_host_is_pinned_to_the_official_endpoint():
    assert ZEUS_HOST == "zeus.technion.ac.il"


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
    assert "qstat" in decoded
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
