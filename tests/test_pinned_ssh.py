from __future__ import annotations

import base64
import inspect
import json
import shlex
import subprocess
from pathlib import Path

import pytest

from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshRunner,
    ReceiverOperation,
)
from workflow_api.zeus_refinement import (
    PinnedSshRefinementTransport,
    ZeusRefinementError,
)
from workflow_api.zeus_snapshot import ZeusProfile


def _profile() -> ZeusProfile:
    return ZeusProfile.parse({
        "username": "tal.noa",
        "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
    })


def _valid_response() -> bytes:
    return json.dumps({
        "lifecycle": "screen_running",
        "job_id": "123[].zeus-master",
        "raw_state": "R",
        "exit_status": None,
        "task_count": 3,
        "counts": {"queued": 0, "running": 3, "held": 0, "succeeded": 0, "failed": 0},
        "rows": [],
        "branch": "main",
    }).encode()


@pytest.mark.parametrize("operation", ["inspect", "prepare"])
def test_refinement_runner_preserves_exact_legacy_argv_wrapper_bytes_and_kwargs(
    tmp_path, monkeypatch, operation,
):
    observed = {}

    def run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, _valid_response(), b"")

    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", run)
    payload = {"campaign": "data/optimization/mot_2d/c", "commit": "a" * 40}
    transport = PinnedSshRefinementTransport(
        tmp_path,
        Path("/usr/bin/ssh"),
        _profile(),
        timeout=37,
    )
    state = getattr(transport, operation)(**payload)
    assert state.lifecycle == "screen_running"

    receiver = (Path(__file__).parents[1] / "workflow_api/zeus_refinement_remote.py").read_bytes()
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).decode()
    script = base64.urlsafe_b64encode(receiver).decode()
    wrapper = (
        "import base64,sys;code=base64.urlsafe_b64decode(sys.argv[1]);"
        "sys.argv=sys.argv[2:];exec(compile(code,'<refine>','exec'),"
        "{'__name__':'__main__'})"
    )
    remote = shlex.join((
        "python3", "-c", wrapper, script, operation, "tal.noa",
        "/home/tal.noa/ytterbium_lab_simulation_new", encoded,
    ))
    assert observed["argv"] == [
        "/usr/bin/ssh", "-F", "none", "-T",
        "-o", "BatchMode=yes",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ForwardAgent=no",
        "-o", "ClearAllForwardings=yes",
        "tal.noa@zeus.technion.ac.il", remote,
    ]
    assert observed["kwargs"] == {
        "cwd": tmp_path,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": 37,
        "check": False,
    }
    # Legacy inherited the parent environment and Python's close_fds default.
    assert "env" not in observed["kwargs"]
    assert "close_fds" not in observed["kwargs"]
    remote_parts = shlex.split(observed["argv"][-1])
    assert base64.urlsafe_b64decode(remote_parts[3]) == receiver
    assert json.loads(base64.urlsafe_b64decode(remote_parts[7])) == payload


def test_runner_call_surface_has_no_command_host_receiver_or_ssh_controls():
    parameters = set(inspect.signature(PinnedSshRunner.run).parameters)
    assert parameters == {"self", "operation", "profile", "payload"}
    forbidden = {
        "executable", "ssh", "host", "receiver", "path", "source",
        "command", "argv", "options", "shell", "timeout", "cwd", "env",
    }
    assert parameters.isdisjoint(forbidden)
    policy_parameters = set(inspect.signature(PinnedSshPolicy).parameters)
    assert policy_parameters == {
        "receiver", "repository_root", "ssh_executable", "timeout",
    }
    assert policy_parameters.isdisjoint({
        "filename", "receiver_path", "receiver_source", "host", "options",
        "command", "argv", "shell", "wrapper",
    })


def test_runner_rejects_raw_or_unsupported_operation_before_process_creation(
    tmp_path, monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    runner = PinnedSshRunner(PinnedSshPolicy.refinement_transition(
        tmp_path, Path("/usr/bin/ssh"), timeout=60,
    ))
    with pytest.raises(ValueError, match="operation"):
        runner.run("inspect", _profile(), {})  # type: ignore[arg-type]
    assert calls == []


@pytest.mark.parametrize("profile", [
    ZeusProfile("-oProxyCommand=evil", "/home/-oProxyCommand=evil/ytterbium_lab_simulation_new"),
    ZeusProfile("tal.noa", "/tmp/attacker-controlled"),
    type("DuckProfile", (), {
        "username": "tal.noa",
        "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
    })(),
])
def test_runner_revalidates_exact_profile_before_receiver_read_or_process(
    tmp_path, monkeypatch, profile,
):
    process_calls = []
    receiver_reads = []
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda *args, **kwargs: process_calls.append((args, kwargs)),
    )
    original_read_bytes = Path.read_bytes

    def read_bytes(path):
        receiver_reads.append(path)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    runner = PinnedSshRunner(PinnedSshPolicy.refinement_transition(
        tmp_path, Path("/usr/bin/ssh"), timeout=60,
    ))
    with pytest.raises(ValueError, match="profile"):
        runner.run(ReceiverOperation.INSPECT, profile, {})
    assert receiver_reads == []
    assert process_calls == []


@pytest.mark.parametrize("operation,expected", [
    ("inspect", "zeus_timeout"),
    ("prepare", "transition_outcome_unknown"),
])
def test_refinement_timeout_translation_is_unchanged(
    tmp_path, monkeypatch, operation, expected,
):
    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", timeout)
    transport = PinnedSshRefinementTransport(tmp_path, Path("/usr/bin/ssh"), _profile())
    with pytest.raises(ZeusRefinementError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation,returncode,stderr,stdout,expected", [
    ("inspect", 1, b"", b"", "remote_response_invalid"),
    ("prepare", 1, b"", b"", "transition_outcome_unknown"),
    ("inspect", 0, b"warning", _valid_response(), "remote_response_invalid"),
    ("prepare", 0, b"warning", _valid_response(), "transition_outcome_unknown"),
    ("inspect", 0, b"", b"not-json", "remote_response_invalid"),
    ("prepare", 0, b"", b"not-json", "remote_response_invalid"),
])
def test_refinement_process_and_decode_error_translation_is_unchanged(
    tmp_path, monkeypatch, operation, returncode, stderr, stdout, expected,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, stdout, stderr,
        ),
    )
    transport = PinnedSshRefinementTransport(tmp_path, Path("/usr/bin/ssh"), _profile())
    with pytest.raises(ZeusRefinementError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected
