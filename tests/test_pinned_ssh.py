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
from workflow_api.zeus_confirmation import (
    PinnedSshConfirmationTransport,
    ZeusConfirmationError,
)
from workflow_api.zeus_refinement_submission import (
    PinnedSshRefinementSubmissionTransport,
    ZeusRefinementSubmissionError,
)
from workflow_api.zeus_screening import (
    PinnedSshScreeningTransport,
    ZeusScreeningError,
)
from workflow_api.zeus_screen_submission import (
    PinnedSshScreenSubmissionTransport,
    ZeusScreenSubmissionError,
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


def _valid_confirmation_response() -> bytes:
    return json.dumps({
        "lifecycle": "running",
        "rounds": [{}, {}, {}, {}],
        "rows": [],
        "branch": "main",
        "receipt": None,
    }).encode()


def _valid_screening_response() -> bytes:
    return json.dumps({
        "lifecycle": "running",
        "job_id": "123.zeus-master",
        "raw_state": "R",
        "exit_status": None,
        "points": [],
        "artifact_count": 0,
    }).encode()


def _valid_screen_submission_response() -> bytes:
    return json.dumps({
        "status": "eligible",
        "branch": "main",
        "validated_smoke_job_id": "123.zeus-master",
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


@pytest.mark.parametrize("operation", ["inspect", "prepare"])
def test_refinement_process_oserror_remains_raw(tmp_path, monkeypatch, operation):
    def fail(*_args, **_kwargs):
        raise OSError("ssh unavailable")

    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", fail)
    transport = PinnedSshRefinementTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(OSError, match="ssh unavailable"):
        getattr(transport, operation)(example=True)


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


@pytest.mark.parametrize("operation", ["inspect", "prepare"])
def test_confirmation_runner_preserves_exact_legacy_argv_wrapper_bytes_and_kwargs(
    tmp_path, monkeypatch, operation,
):
    observed = {}

    def run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            argv, 0, _valid_confirmation_response(), b"",
        )

    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", run)
    payload = {"campaign": "data/optimization/mot_2d/c", "commit": "a" * 40}
    transport = PinnedSshConfirmationTransport(
        tmp_path,
        Path("/usr/bin/ssh"),
        _profile(),
    )
    state = getattr(transport, operation)(**payload)
    assert state.lifecycle == "running"

    receiver = (Path(__file__).parents[1] / "workflow_api/zeus_confirmation_remote.py").read_bytes()
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).decode()
    script = base64.urlsafe_b64encode(receiver).decode()
    wrapper = (
        "import base64,sys;code=base64.urlsafe_b64decode(sys.argv[1]);"
        "sys.argv=sys.argv[2:];exec(compile(code,'<confirmation>','exec'),"
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
        "timeout": 90,
        "check": False,
    }
    assert "env" not in observed["kwargs"]
    assert "close_fds" not in observed["kwargs"]
    remote_parts = shlex.split(observed["argv"][-1])
    assert base64.urlsafe_b64decode(remote_parts[3]) == receiver
    assert json.loads(base64.urlsafe_b64decode(remote_parts[7])) == payload


@pytest.mark.parametrize("exception", [
    subprocess.TimeoutExpired([], 90),
    OSError("ssh unavailable"),
])
@pytest.mark.parametrize("operation,expected", [
    ("inspect", "zeus_timeout"),
    ("prepare", "transition_outcome_unknown"),
])
def test_confirmation_timeout_and_oserror_translation_is_unchanged(
    tmp_path, monkeypatch, exception, operation, expected,
):
    def fail(*_args, **_kwargs):
        raise exception

    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", fail)
    transport = PinnedSshConfirmationTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusConfirmationError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation", ["inspect", "prepare"])
def test_confirmation_receiver_read_oserror_remains_raw(
    tmp_path, monkeypatch, operation,
):
    process_calls = []
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda *args, **kwargs: process_calls.append((args, kwargs)),
    )
    original_read_bytes = Path.read_bytes

    def fail_confirmation_receiver(path):
        if path.name == "zeus_confirmation_remote.py":
            raise OSError("receiver unreadable")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_confirmation_receiver)
    transport = PinnedSshConfirmationTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(OSError, match="receiver unreadable"):
        getattr(transport, operation)(example=True)
    assert process_calls == []


@pytest.mark.parametrize("operation,returncode,stderr,stdout,expected", [
    ("inspect", 1, b"", b"", "remote_response_invalid"),
    ("prepare", 1, b"", b"", "transition_outcome_unknown"),
    ("inspect", 0, b"warning", _valid_confirmation_response(), "remote_response_invalid"),
    ("prepare", 0, b"warning", _valid_confirmation_response(), "transition_outcome_unknown"),
    ("inspect", 0, b"", b"not-json", "remote_response_invalid"),
    ("prepare", 0, b"", b"not-json", "remote_response_invalid"),
])
def test_confirmation_process_and_decode_error_translation_is_unchanged(
    tmp_path, monkeypatch, operation, returncode, stderr, stdout, expected,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, stdout, stderr,
        ),
    )
    transport = PinnedSshConfirmationTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusConfirmationError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation", ["inspect", "prepare"])
def test_confirmation_remote_error_code_translation_is_unchanged(
    tmp_path, monkeypatch, operation,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, b'{"error":"refinement_not_ready"}', b"",
        ),
    )
    transport = PinnedSshConfirmationTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusConfirmationError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == "refinement_not_ready"


def _valid_refinement_submission_response() -> bytes:
    return json.dumps({
        "status": "eligible",
        "branch": "main",
        "job_ids": [],
        "nonce": None,
        "completed_unix_s": None,
    }).encode()


@pytest.mark.parametrize("operation", ["inspect", "submit"])
def test_refinement_submission_runner_preserves_exact_legacy_invocation(
    tmp_path, monkeypatch, operation,
):
    observed = {}

    def run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            argv, 0, _valid_refinement_submission_response(), b"",
        )

    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", run)
    payload = {"campaign": "data/optimization/mot_2d/c", "chain_key": "a" * 64}
    transport = PinnedSshRefinementSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    state = getattr(transport, operation)(**payload)
    assert state.status == "eligible"

    receiver = (
        Path(__file__).parents[1]
        / "workflow_api/zeus_refinement_submission_remote.py"
    ).read_bytes()
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).decode()
    script = base64.urlsafe_b64encode(receiver).decode()
    wrapper = (
        "import base64,sys;code=base64.urlsafe_b64decode(sys.argv[1]);"
        "sys.argv=sys.argv[2:];exec(compile(code,'<refine-submit>','exec'),"
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
        "timeout": 150,
        "check": False,
    }
    assert "env" not in observed["kwargs"]
    assert "close_fds" not in observed["kwargs"]
    remote_parts = shlex.split(observed["argv"][-1])
    assert base64.urlsafe_b64decode(remote_parts[3]) == receiver
    assert json.loads(base64.urlsafe_b64decode(remote_parts[7])) == payload


@pytest.mark.parametrize("operation", ["inspect", "submit"])
@pytest.mark.parametrize("failure", ["receiver_read", "process_launch"])
def test_refinement_submission_oserror_boundaries_remain_raw(
    tmp_path, monkeypatch, operation, failure,
):
    process_calls = []
    original_read_bytes = Path.read_bytes

    def read_bytes(path):
        if failure == "receiver_read" and path.name == "zeus_refinement_submission_remote.py":
            raise OSError("receiver unreadable")
        return original_read_bytes(path)

    def run(*args, **kwargs):
        process_calls.append((args, kwargs))
        raise OSError("ssh unavailable")

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", run)
    transport = PinnedSshRefinementSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    expected = "receiver unreadable" if failure == "receiver_read" else "ssh unavailable"
    with pytest.raises(OSError, match=expected):
        getattr(transport, operation)(example=True)
    assert len(process_calls) == (0 if failure == "receiver_read" else 1)


@pytest.mark.parametrize("operation,expected", [
    ("inspect", "zeus_timeout"),
    ("submit", "refinement_submission_outcome_unknown"),
])
def test_refinement_submission_timeout_translation_is_unchanged(
    tmp_path, monkeypatch, operation, expected,
):
    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", timeout)
    transport = PinnedSshRefinementSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusRefinementSubmissionError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation,returncode,stderr,stdout,expected", [
    ("inspect", 1, b"", b"", "remote_response_invalid"),
    ("submit", 1, b"", b"", "refinement_submission_outcome_unknown"),
    ("inspect", 0, b"warning", _valid_refinement_submission_response(), "remote_response_invalid"),
    ("submit", 0, b"warning", _valid_refinement_submission_response(), "refinement_submission_outcome_unknown"),
    ("inspect", 0, b"", b"not-json", "remote_response_invalid"),
    ("submit", 0, b"", b"not-json", "refinement_submission_outcome_unknown"),
])
def test_refinement_submission_process_and_decode_mapping_is_unchanged(
    tmp_path, monkeypatch, operation, returncode, stderr, stdout, expected,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, stdout, stderr,
        ),
    )
    transport = PinnedSshRefinementSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusRefinementSubmissionError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation", ["inspect", "submit"])
def test_refinement_submission_non_dict_response_mapping_is_unchanged(
    tmp_path, monkeypatch, operation,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, b"[]", b"",
        ),
    )
    transport = PinnedSshRefinementSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusRefinementSubmissionError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == "remote_response_invalid"


@pytest.mark.parametrize("operation", ["inspect", "submit"])
def test_refinement_submission_remote_error_code_propagates_unchanged(
    tmp_path, monkeypatch, operation,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, b'{"error":"refinement_submission_busy"}', b"",
        ),
    )
    transport = PinnedSshRefinementSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusRefinementSubmissionError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == "refinement_submission_busy"


@pytest.mark.parametrize("operation", ["inspect", "prepare"])
def test_screening_runner_preserves_exact_hardened_invocation(
    tmp_path, monkeypatch, operation,
):
    observed = {}

    def run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, _valid_screening_response(), b"")

    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/test-agent.sock")
    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", run)
    payload = {"campaign": "data/optimization/mot_2d/c", "commit": "a" * 40}
    state = getattr(PinnedSshScreeningTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(), timeout=37,
    ), operation)(**payload)
    assert state.lifecycle == "running"

    receiver = (
        Path(__file__).parents[1] / "workflow_api/zeus_screening_remote.py"
    ).read_bytes()
    parts = shlex.split(observed["argv"][-1])
    assert base64.urlsafe_b64decode(parts[3]) == receiver
    assert json.loads(base64.urlsafe_b64decode(parts[7])) == payload
    assert "compile(code,'<zeus-screening>','exec')" in parts[2]
    assert parts[4:7] == [
        operation, "tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new",
    ]
    assert observed["argv"][:-2] == [
        "/usr/bin/ssh", "-F", "none", "-T",
        "-o", "BatchMode=yes",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "NumberOfPasswordPrompts=0",
        "-o", "ConnectTimeout=8",
        "-o", "ConnectionAttempts=1",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ForwardAgent=no",
        "-o", "ClearAllForwardings=yes",
        "-o", "PermitLocalCommand=no",
        "-o", "ProxyCommand=none",
        "-o", "ProxyJump=none",
        "-o", "KnownHostsCommand=none",
        "-o", "CanonicalizeHostname=no",
        "-o", "LogLevel=ERROR",
    ]
    assert observed["argv"][-2] == "tal.noa@zeus.technion.ac.il"
    assert observed["kwargs"] == {
        "cwd": tmp_path,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": 37,
        "check": False,
        "env": {
            "PATH": "/usr/bin",
            "HOME": str(Path.home()),
            "LC_ALL": "C",
            "SSH_AUTH_SOCK": "/tmp/test-agent.sock",
        },
        "shell": False,
        "close_fds": True,
    }


def test_screening_runner_omits_absent_ssh_agent_from_pinned_environment(
    tmp_path, monkeypatch,
):
    observed = {}
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)

    def run(argv, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, _valid_screening_response(), b"")

    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", run)
    PinnedSshScreeningTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    ).inspect(example=True)
    assert observed["env"] == {
        "PATH": "/usr/bin", "HOME": str(Path.home()), "LC_ALL": "C",
    }
    assert observed["timeout"] == 45


def test_screening_serializes_payload_before_receiver_read(tmp_path, monkeypatch):
    reads = []
    process_calls = []

    def read_bytes(path):
        reads.append(path)
        raise OSError("receiver unreadable")

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda *args, **kwargs: process_calls.append((args, kwargs)),
    )
    transport = PinnedSshScreeningTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(TypeError):
        transport.inspect(unserializable=object())
    assert reads == []
    assert process_calls == []


@pytest.mark.parametrize("operation", ["inspect", "prepare"])
@pytest.mark.parametrize("failure", ["receiver_read", "process_launch"])
def test_screening_oserror_boundaries_remain_raw(
    tmp_path, monkeypatch, operation, failure,
):
    calls = []
    original = Path.read_bytes

    def read_bytes(path):
        if failure == "receiver_read" and path.name == "zeus_screening_remote.py":
            raise OSError("receiver unreadable")
        return original(path)

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        raise OSError("ssh unavailable")

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", run)
    transport = PinnedSshScreeningTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    expected = "receiver unreadable" if failure == "receiver_read" else "ssh unavailable"
    with pytest.raises(OSError, match=expected):
        getattr(transport, operation)(example=True)
    assert len(calls) == (0 if failure == "receiver_read" else 1)


@pytest.mark.parametrize("operation,expected", [
    ("inspect", "zeus_timeout"),
    ("prepare", "transition_outcome_unknown"),
])
def test_screening_timeout_mapping_is_unchanged(
    tmp_path, monkeypatch, operation, expected,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda argv, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(argv, kwargs["timeout"])
        ),
    )
    transport = PinnedSshScreeningTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusScreeningError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation,returncode,stderr,stdout,expected", [
    ("inspect", 1, b"", b"", "remote_response_invalid"),
    ("prepare", 1, b"", b"", "transition_outcome_unknown"),
    ("inspect", 0, b"warning", _valid_screening_response(), "remote_response_invalid"),
    ("prepare", 0, b"warning", _valid_screening_response(), "transition_outcome_unknown"),
    ("inspect", 0, b"", b"not-json", "remote_response_invalid"),
    ("prepare", 0, b"", b"not-json", "transition_outcome_unknown"),
])
def test_screening_process_and_decode_mapping_is_unchanged(
    tmp_path, monkeypatch, operation, returncode, stderr, stdout, expected,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, stdout, stderr,
        ),
    )
    transport = PinnedSshScreeningTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusScreeningError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation", ["inspect", "prepare"])
def test_screening_remote_error_code_propagates_unchanged(
    tmp_path, monkeypatch, operation,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, b'{"error":"screening_transition_busy"}', b"",
        ),
    )
    transport = PinnedSshScreeningTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusScreeningError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == "screening_transition_busy"


@pytest.mark.parametrize("operation", ["inspect", "prepare"])
@pytest.mark.parametrize("stderr,expected", [
    (b"Host key verification failed", "zeus_host_key_untrusted"),
    (b"Permission denied (publickey)", "zeus_authentication_required"),
    (b"Could not resolve hostname zeus", "zeus_unreachable"),
    (b"Connection refused", "zeus_unreachable"),
])
def test_screening_hardened_connection_errors_override_operation_ambiguity(
    tmp_path, monkeypatch, operation, stderr, expected,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 255, b"", stderr),
    )
    transport = PinnedSshScreeningTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusScreeningError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation", ["inspect", "submit"])
def test_screen_submission_runner_preserves_exact_hardened_invocation(
    tmp_path, monkeypatch, operation,
):
    observed = {}
    payload = {
        "campaign": "data/optimization/mot_2d/c",
        "commit": "a" * 40,
        "submission_key": "b" * 64,
        "transition_digest": "c" * 64,
        "nonce": "d" * 32,
    }

    def run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        response = _valid_screen_submission_response()
        if operation == "submit":
            response = json.dumps({
                "status": "submitted",
                "version": 1,
                "submission_key": payload["submission_key"],
                "transition_digest": payload["transition_digest"],
                "nonce": payload["nonce"],
                "job_file": f"{payload['campaign']}/jobs/02_screen.pbs",
                "commit": payload["commit"],
                "created_unix_s": 1,
                "job_id": "123[].zeus-master",
                "completed_unix_s": 2,
            }).encode()
        return subprocess.CompletedProcess(argv, 0, response, b"")

    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/test-agent.sock")
    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", run)
    state = getattr(PinnedSshScreenSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    ), operation)(**payload)
    assert state.status == ("eligible" if operation == "inspect" else "submitted")

    receiver = (
        Path(__file__).parents[1] / "workflow_api/zeus_screen_submission_remote.py"
    ).read_bytes()
    parts = shlex.split(observed["argv"][-1])
    assert base64.urlsafe_b64decode(parts[3]) == receiver
    assert json.loads(base64.urlsafe_b64decode(parts[7])) == payload
    assert "compile(code,'<screen-submit>','exec')" in parts[2]
    assert parts[4:7] == [
        operation, "tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new",
    ]
    assert observed["argv"][:-2] == [
        "/usr/bin/ssh", "-F", "none", "-T",
        "-o", "BatchMode=yes",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "NumberOfPasswordPrompts=0",
        "-o", "ConnectTimeout=8",
        "-o", "ConnectionAttempts=1",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ForwardAgent=no",
        "-o", "ClearAllForwardings=yes",
        "-o", "PermitLocalCommand=no",
        "-o", "ProxyCommand=none",
        "-o", "ProxyJump=none",
        "-o", "KnownHostsCommand=none",
        "-o", "CanonicalizeHostname=no",
        "-o", "LogLevel=ERROR",
    ]
    assert observed["argv"][-2] == "tal.noa@zeus.technion.ac.il"
    assert observed["kwargs"] == {
        "cwd": tmp_path,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": 45,
        "check": False,
        "env": {
            "PATH": "/usr/bin",
            "HOME": str(Path.home()),
            "LC_ALL": "C",
            "SSH_AUTH_SOCK": "/tmp/test-agent.sock",
        },
        "shell": False,
        "close_fds": True,
    }


def test_screen_submission_serializes_before_receiver_read(tmp_path, monkeypatch):
    reads = []
    process_calls = []
    monkeypatch.setattr(Path, "read_bytes", lambda path: reads.append(path))
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda *args, **kwargs: process_calls.append((args, kwargs)),
    )
    transport = PinnedSshScreenSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(TypeError):
        transport.inspect(unserializable=object())
    assert reads == []
    assert process_calls == []


@pytest.mark.parametrize("operation", ["inspect", "submit"])
@pytest.mark.parametrize("failure", ["receiver_read", "process_launch"])
def test_screen_submission_oserror_boundaries_remain_raw(
    tmp_path, monkeypatch, operation, failure,
):
    calls = []
    original = Path.read_bytes

    def read_bytes(path):
        if failure == "receiver_read" and path.name == "zeus_screen_submission_remote.py":
            raise OSError("receiver unreadable")
        return original(path)

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        raise OSError("ssh unavailable")

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", run)
    transport = PinnedSshScreenSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    expected = "receiver unreadable" if failure == "receiver_read" else "ssh unavailable"
    with pytest.raises(OSError, match=expected):
        getattr(transport, operation)(example=True)
    assert len(calls) == (0 if failure == "receiver_read" else 1)


@pytest.mark.parametrize("operation,expected", [
    ("inspect", "zeus_timeout"),
    ("submit", "screening_submission_outcome_unknown"),
])
def test_screen_submission_timeout_mapping_is_unchanged(
    tmp_path, monkeypatch, operation, expected,
):
    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.run", timeout)
    transport = PinnedSshScreenSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusScreenSubmissionError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation,returncode,stderr,stdout,expected", [
    ("inspect", 1, b"", b"", "remote_response_invalid"),
    ("submit", 1, b"", b"", "screening_submission_outcome_unknown"),
    ("inspect", 0, b"warning", _valid_screen_submission_response(), "remote_response_invalid"),
    ("submit", 0, b"warning", _valid_screen_submission_response(), "screening_submission_outcome_unknown"),
    ("inspect", 0, b"", b"not-json", "remote_response_invalid"),
    ("submit", 0, b"", b"not-json", "screening_submission_outcome_unknown"),
    ("inspect", 0, b"", b"[]", "remote_response_invalid"),
    ("submit", 0, b"", b"[]", "remote_response_invalid"),
])
def test_screen_submission_process_and_decode_mapping_is_unchanged(
    tmp_path, monkeypatch, operation, returncode, stderr, stdout, expected,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, stdout, stderr,
        ),
    )
    transport = PinnedSshScreenSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusScreenSubmissionError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation", ["inspect", "submit"])
@pytest.mark.parametrize("stderr,expected", [
    (b"Host key verification failed", "zeus_host_key_untrusted"),
    (b"Permission denied (publickey)", "zeus_authentication_required"),
    (b"Could not resolve hostname zeus", "zeus_unreachable"),
    (b"Connection refused", "zeus_unreachable"),
])
def test_screen_submission_hardened_connection_errors_are_unchanged(
    tmp_path, monkeypatch, operation, stderr, expected,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 255, b"", stderr),
    )
    transport = PinnedSshScreenSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusScreenSubmissionError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation", ["inspect", "submit"])
def test_screen_submission_remote_error_propagates_unchanged(
    tmp_path, monkeypatch, operation,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, b'{"error":"screening_submission_busy"}', b"",
        ),
    )
    transport = PinnedSshScreenSubmissionTransport(
        tmp_path, Path("/usr/bin/ssh"), _profile(),
    )
    with pytest.raises(ZeusScreenSubmissionError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == "screening_submission_busy"
