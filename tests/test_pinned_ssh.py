from __future__ import annotations
from workflow_api.platform_io import executable

import base64
import os
import inspect
import io
import json
import shlex
import subprocess
import sys
import threading
from pathlib import Path

import pytest


@pytest.mark.parametrize("factory", ["zeeman_individual", "mot_2d_individual", "mot_3d_individual"])
def test_large_receiver_and_payload_execute_with_short_command_line(tmp_path, monkeypatch, factory):
    # Exercise the actual bootstrap in a new Python process, including argv
    # identity and unread JSON bytes after the receiver framing line.
    receiver = (b"#" + b"x" * 40000 + b"\nimport sys,json\n"
                b"print(json.dumps({'argv':sys.argv[1:],'payload':json.loads(sys.stdin.buffer.read())}))\n")
    original = Path.read_bytes
    def read(path):
        if path.name in {"zeeman_zeus_remote.py", "mot_2d_zeus_remote.py", "mot_3d_zeus_remote.py"}:
            return receiver
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", read)
    observed = {}
    def execute(argv, **kwargs):
        observed['length'] = len(subprocess.list2cmdline(argv))
        parts = shlex.split(argv[-1])
        python_index = parts.index('-c') - 1
        return subprocess.run([sys.executable, *parts[python_index + 1:]],
                              input=kwargs['input'], capture_output=True, check=True)
    monkeypatch.setattr('workflow_api.pinned_ssh._bounded_run', execute)
    policy = getattr(PinnedSshPolicy, factory)(tmp_path, Path(sys.executable), timeout=10)
    payload = {'unicode': '\u05d1\u05d3\u05d9\u05e7\u05d4', 'large': 'p' * 40000}
    profile = _profile()
    result = PinnedSshRunner(policy).run(ReceiverOperation.INSPECT, profile, payload)
    assert observed['length'] < 4000
    assert json.loads(result.stdout) == {'argv': ['inspect', profile.username, profile.project_directory, '-'], 'payload': payload}

def _framed_receiver(observed):
    parts = shlex.split(observed["argv"][-1])
    assert len(parts[parts.index("-c") + 1:]) == 1
    assert len(subprocess.list2cmdline(observed["argv"])) < 4000
    header, remainder = observed["kwargs"]["input"].split(b"\n", 1)
    source, argv = json.loads(header)
    return base64.urlsafe_b64decode(source), argv, remainder

def _expected_windows_ssh_paths():
    if os.name != "nt":
        return {}
    return {name: os.environ[name] for name in
            ("SystemRoot", "WINDIR", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "PROGRAMDATA")
            if name in os.environ}


from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshRunner,
    ReceiverOperation,
    TransferOperation,
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
from workflow_api.zeus_snapshot import _REMOTE_SCRIPT as SNAPSHOT_REMOTE_SCRIPT
from workflow_api.zeus_snapshot import MAX_STDERR as SNAPSHOT_MAX_STDERR
from workflow_api.zeus_snapshot import MAX_STDOUT as SNAPSHOT_MAX_STDOUT
from workflow_api.zeus_snapshot import ZeusSnapshotError
from workflow_api.zeus_submission import (
    MAX_REMOTE_OUTPUT,
    PinnedSshSmokeSubmissionTransport,
    ZeusSubmissionError,
    _REMOTE_SCRIPT,
)
from workflow_api.zeus_transfer import (
    MAX_TRANSFER_BYTES,
    PinnedSshZeusPreparationTransport,
    ZeusPreparationError,
    _REMOTE_TRANSFER_SCRIPT,
)


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

    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", run)
    payload = {"campaign": "data/optimization/mot_2d/c", "commit": "a" * 40}
    transport = PinnedSshRefinementTransport(
        tmp_path,
        executable("ssh"),
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
    remote = observed["argv"][-1]
    assert _framed_receiver(observed) == (receiver, ["<refine>", operation, "tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new", encoded], b"")
    assert observed["argv"] == [
        str(executable("ssh")), "-F", "none", "-T",
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
        "input": observed["kwargs"]["input"],
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": 37,
        "check": False,
    }
    # Legacy inherited the parent environment and Python's close_fds default.
    assert "env" not in observed["kwargs"]
    assert "close_fds" not in observed["kwargs"]
    remote_parts = shlex.split(observed["argv"][-1])
    assert _framed_receiver(observed)[0] == receiver
    assert json.loads(base64.urlsafe_b64decode(_framed_receiver(observed)[1][4])) == payload


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
        "workflow_api.pinned_ssh._bounded_run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    runner = PinnedSshRunner(PinnedSshPolicy.refinement_transition(
        tmp_path, executable("ssh"), timeout=60,
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
        "workflow_api.pinned_ssh._bounded_run",
        lambda *args, **kwargs: process_calls.append((args, kwargs)),
    )
    original_read_bytes = Path.read_bytes

    def read_bytes(path):
        receiver_reads.append(path)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    runner = PinnedSshRunner(PinnedSshPolicy.refinement_transition(
        tmp_path, executable("ssh"), timeout=60,
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

    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", timeout)
    transport = PinnedSshRefinementTransport(tmp_path, executable("ssh"), _profile())
    with pytest.raises(ZeusRefinementError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation", ["inspect", "prepare"])
def test_refinement_process_oserror_remains_raw(tmp_path, monkeypatch, operation):
    def fail(*_args, **_kwargs):
        raise OSError("ssh unavailable")

    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", fail)
    transport = PinnedSshRefinementTransport(
        tmp_path, executable("ssh"), _profile(),
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
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, stdout, stderr,
        ),
    )
    transport = PinnedSshRefinementTransport(tmp_path, executable("ssh"), _profile())
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

    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", run)
    payload = {"campaign": "data/optimization/mot_2d/c", "commit": "a" * 40}
    transport = PinnedSshConfirmationTransport(
        tmp_path,
        executable("ssh"),
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
    remote = observed["argv"][-1]
    assert _framed_receiver(observed) == (receiver, ["<confirmation>", operation, "tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new", encoded], b"")
    assert observed["argv"] == [
        str(executable("ssh")), "-F", "none", "-T",
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
        "input": observed["kwargs"]["input"],
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": 90,
        "check": False,
    }
    assert "env" not in observed["kwargs"]
    assert "close_fds" not in observed["kwargs"]
    remote_parts = shlex.split(observed["argv"][-1])
    assert _framed_receiver(observed)[0] == receiver
    assert json.loads(base64.urlsafe_b64decode(_framed_receiver(observed)[1][4])) == payload


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

    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", fail)
    transport = PinnedSshConfirmationTransport(
        tmp_path, executable("ssh"), _profile(),
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
        "workflow_api.pinned_ssh._bounded_run",
        lambda *args, **kwargs: process_calls.append((args, kwargs)),
    )
    original_read_bytes = Path.read_bytes

    def fail_confirmation_receiver(path):
        if path.name == "zeus_confirmation_remote.py":
            raise OSError("receiver unreadable")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_confirmation_receiver)
    transport = PinnedSshConfirmationTransport(
        tmp_path, executable("ssh"), _profile(),
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
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, stdout, stderr,
        ),
    )
    transport = PinnedSshConfirmationTransport(
        tmp_path, executable("ssh"), _profile(),
    )
    with pytest.raises(ZeusConfirmationError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation", ["inspect", "prepare"])
def test_confirmation_remote_error_code_translation_is_unchanged(
    tmp_path, monkeypatch, operation,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, b'{"error":"refinement_not_ready"}', b"",
        ),
    )
    transport = PinnedSshConfirmationTransport(
        tmp_path, executable("ssh"), _profile(),
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

    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", run)
    payload = {"campaign": "data/optimization/mot_2d/c", "chain_key": "a" * 64}
    transport = PinnedSshRefinementSubmissionTransport(
        tmp_path, executable("ssh"), _profile(),
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
    remote = observed["argv"][-1]
    assert _framed_receiver(observed) == (receiver, ["<refine-submit>", operation, "tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new", encoded], b"")
    assert observed["argv"] == [
        str(executable("ssh")), "-F", "none", "-T",
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
        "input": observed["kwargs"]["input"],
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": 150,
        "check": False,
    }
    assert "env" not in observed["kwargs"]
    assert "close_fds" not in observed["kwargs"]
    remote_parts = shlex.split(observed["argv"][-1])
    assert _framed_receiver(observed)[0] == receiver
    assert json.loads(base64.urlsafe_b64decode(_framed_receiver(observed)[1][4])) == payload


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
    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", run)
    transport = PinnedSshRefinementSubmissionTransport(
        tmp_path, executable("ssh"), _profile(),
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

    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", timeout)
    transport = PinnedSshRefinementSubmissionTransport(
        tmp_path, executable("ssh"), _profile(),
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
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, stdout, stderr,
        ),
    )
    transport = PinnedSshRefinementSubmissionTransport(
        tmp_path, executable("ssh"), _profile(),
    )
    with pytest.raises(ZeusRefinementSubmissionError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation", ["inspect", "submit"])
def test_refinement_submission_non_dict_response_mapping_is_unchanged(
    tmp_path, monkeypatch, operation,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, b"[]", b"",
        ),
    )
    transport = PinnedSshRefinementSubmissionTransport(
        tmp_path, executable("ssh"), _profile(),
    )
    with pytest.raises(ZeusRefinementSubmissionError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == "remote_response_invalid"


@pytest.mark.parametrize("operation", ["inspect", "submit"])
def test_refinement_submission_remote_error_code_propagates_unchanged(
    tmp_path, monkeypatch, operation,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, b'{"error":"refinement_submission_busy"}', b"",
        ),
    )
    transport = PinnedSshRefinementSubmissionTransport(
        tmp_path, executable("ssh"), _profile(),
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
    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", run)
    payload = {"campaign": "data/optimization/mot_2d/c", "commit": "a" * 40}
    state = getattr(PinnedSshScreeningTransport(
        tmp_path, executable("ssh"), _profile(), timeout=37,
    ), operation)(**payload)
    assert state.lifecycle == "running"

    receiver = (
        Path(__file__).parents[1] / "workflow_api/zeus_screening_remote.py"
    ).read_bytes()
    parts = shlex.split(observed["argv"][-1])
    assert _framed_receiver(observed)[0] == receiver
    assert json.loads(base64.urlsafe_b64decode(_framed_receiver(observed)[1][4])) == payload
    assert "<zeus-screening>" in parts[parts.index("-c") + 1]
    assert _framed_receiver(observed)[1][1:4] == [
        operation, "tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new",
    ]
    assert observed["argv"][:-2] == [
        str(executable("ssh")), "-F", "none", "-T",
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
        "input": observed["kwargs"]["input"],
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": 37,
        "check": False,
        "env": {
            "PATH": str(executable("ssh").parent),
            "HOME": str(Path.home()),
            "LC_ALL": "C", **_expected_windows_ssh_paths(),
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

    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", run)
    PinnedSshScreeningTransport(
        tmp_path, executable("ssh"), _profile(),
    ).inspect(example=True)
    assert observed["env"] == {
        "PATH": str(executable("ssh").parent), "HOME": str(Path.home()), "LC_ALL": "C", **_expected_windows_ssh_paths(),
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
        "workflow_api.pinned_ssh._bounded_run",
        lambda *args, **kwargs: process_calls.append((args, kwargs)),
    )
    transport = PinnedSshScreeningTransport(
        tmp_path, executable("ssh"), _profile(),
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
    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", run)
    transport = PinnedSshScreeningTransport(
        tmp_path, executable("ssh"), _profile(),
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
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(argv, kwargs["timeout"])
        ),
    )
    transport = PinnedSshScreeningTransport(
        tmp_path, executable("ssh"), _profile(),
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
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, stdout, stderr,
        ),
    )
    transport = PinnedSshScreeningTransport(
        tmp_path, executable("ssh"), _profile(),
    )
    with pytest.raises(ZeusScreeningError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation", ["inspect", "prepare"])
def test_screening_remote_error_code_propagates_unchanged(
    tmp_path, monkeypatch, operation,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, b'{"error":"screening_transition_busy"}', b"",
        ),
    )
    transport = PinnedSshScreeningTransport(
        tmp_path, executable("ssh"), _profile(),
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
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 255, b"", stderr),
    )
    transport = PinnedSshScreeningTransport(
        tmp_path, executable("ssh"), _profile(),
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
    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", run)
    state = getattr(PinnedSshScreenSubmissionTransport(
        tmp_path, executable("ssh"), _profile(),
    ), operation)(**payload)
    assert state.status == ("eligible" if operation == "inspect" else "submitted")

    receiver = (
        Path(__file__).parents[1] / "workflow_api/zeus_screen_submission_remote.py"
    ).read_bytes()
    parts = shlex.split(observed["argv"][-1])
    assert _framed_receiver(observed)[0] == receiver
    assert json.loads(base64.urlsafe_b64decode(_framed_receiver(observed)[1][4])) == payload
    assert "<screen-submit>" in parts[parts.index("-c") + 1]
    assert _framed_receiver(observed)[1][1:4] == [
        operation, "tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new",
    ]
    assert observed["argv"][:-2] == [
        str(executable("ssh")), "-F", "none", "-T",
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
        "input": observed["kwargs"]["input"],
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": 45,
        "check": False,
        "env": {
            "PATH": str(executable("ssh").parent),
            "HOME": str(Path.home()),
            "LC_ALL": "C", **_expected_windows_ssh_paths(),
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
        "workflow_api.pinned_ssh._bounded_run",
        lambda *args, **kwargs: process_calls.append((args, kwargs)),
    )
    transport = PinnedSshScreenSubmissionTransport(
        tmp_path, executable("ssh"), _profile(),
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
    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", run)
    transport = PinnedSshScreenSubmissionTransport(
        tmp_path, executable("ssh"), _profile(),
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

    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", timeout)
    transport = PinnedSshScreenSubmissionTransport(
        tmp_path, executable("ssh"), _profile(),
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
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, stdout, stderr,
        ),
    )
    transport = PinnedSshScreenSubmissionTransport(
        tmp_path, executable("ssh"), _profile(),
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
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 255, b"", stderr),
    )
    transport = PinnedSshScreenSubmissionTransport(
        tmp_path, executable("ssh"), _profile(),
    )
    with pytest.raises(ZeusScreenSubmissionError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation", ["inspect", "submit"])
def test_screen_submission_remote_error_propagates_unchanged(
    tmp_path, monkeypatch, operation,
):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, b'{"error":"screening_submission_busy"}', b"",
        ),
    )
    transport = PinnedSshScreenSubmissionTransport(
        tmp_path, executable("ssh"), _profile(),
    )
    with pytest.raises(ZeusScreenSubmissionError) as caught:
        getattr(transport, operation)(example=True)
    assert caught.value.code == "screening_submission_busy"


def _smoke_payload() -> dict[str, object]:
    return {
        "files": {f"data/f{i}": "a" * 64 for i in range(72)},
        "campaign": "data/optimization/mot_2d/c",
        "job_file": "data/optimization/mot_2d/c/jobs/01_smoke.pbs",
        "commit": "b" * 40,
        "submission_key": "c" * 64,
    }


@pytest.mark.parametrize("operation", ["inspect", "submit"])
def test_smoke_submission_runner_preserves_exact_embedded_invocation(
    tmp_path, monkeypatch, operation,
):
    root = tmp_path / "repo"
    root.mkdir()
    observed = {}
    payload = _smoke_payload()
    if operation == "submit":
        payload["nonce"] = "d" * 32

    def run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        response = {"status": "eligible", "branch": "main"}
        if operation == "submit":
            response = {
                "status": "submitted",
                "job_id": "123.zeus-master",
                "nonce": payload["nonce"],
                "submitted_unix_s": 1,
            }
        return subprocess.CompletedProcess(argv, 0, json.dumps(response).encode(), b"")

    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/test-agent.sock")
    monkeypatch.setattr("workflow_api.pinned_ssh._bounded_run", run)
    transport = PinnedSshSmokeSubmissionTransport(
        root, executable("ssh"), _profile(),
    )
    state = getattr(transport, operation)(**payload)
    assert state.status == ("eligible" if operation == "inspect" else "submitted")

    parts = shlex.split(observed["argv"][-1])
    assert _framed_receiver(observed)[0].decode() == _REMOTE_SCRIPT
    expected_payload = dict(payload)
    if operation == "inspect":
        expected_payload["nonce"] = None
    assert json.loads(base64.urlsafe_b64decode(_framed_receiver(observed)[1][4])) == expected_payload
    assert "exec(compile(" in parts[parts.index("-c") + 1]
    assert _framed_receiver(observed)[1][1:4] == [
        operation, "tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new",
    ]
    assert observed["argv"][:-2] == [
        str(executable("ssh")), "-F", "none", "-T",
        "-o", "BatchMode=yes", "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "NumberOfPasswordPrompts=0", "-o", "ConnectTimeout=8",
        "-o", "ConnectionAttempts=1", "-o", "StrictHostKeyChecking=yes",
        "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes",
        "-o", "PermitLocalCommand=no", "-o", "ProxyCommand=none",
        "-o", "ProxyJump=none", "-o", "KnownHostsCommand=none",
        "-o", "CanonicalizeHostname=no", "-o", "LogLevel=ERROR",
    ]
    assert observed["argv"][-2] == "tal.noa@zeus.technion.ac.il"
    assert observed["kwargs"] == {
        "cwd": root,
        "input": observed["kwargs"]["input"],
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": 45,
        "check": False,
        "env": {
            "PATH": str(executable("ssh").parent), "HOME": str(Path.home()), "LC_ALL": "C", **_expected_windows_ssh_paths(),
            "SSH_AUTH_SOCK": "/tmp/test-agent.sock",
        },
        "shell": False,
        "close_fds": True,
    }


def test_smoke_submission_serializes_before_embedded_receiver(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    calls = []
    monkeypatch.setattr(
        "workflow_api.pinned_ssh._bounded_run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    transport = PinnedSshSmokeSubmissionTransport(
        root, executable("ssh"), _profile(),
    )
    with pytest.raises(TypeError):
        transport.inspect(unserializable=object())
    assert calls == []


@pytest.mark.parametrize("operation", ["inspect", "submit"])
def test_smoke_submission_process_oserror_remains_raw(
    tmp_path, monkeypatch, operation,
):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(
        "workflow_api.pinned_ssh._bounded_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("ssh unavailable")),
    )
    transport = PinnedSshSmokeSubmissionTransport(
        root, executable("ssh"), _profile(),
    )
    payload = _smoke_payload()
    if operation == "submit":
        payload["nonce"] = "d" * 32
    with pytest.raises(OSError, match="ssh unavailable"):
        getattr(transport, operation)(**payload)


@pytest.mark.parametrize("operation", ["inspect", "submit"])
def test_smoke_submission_stdout_cap_allows_exact_boundary(
    tmp_path, monkeypatch, operation,
):
    root = tmp_path / "repo"
    root.mkdir()
    payload = _smoke_payload()
    response = {"status": "eligible", "branch": "main"}
    if operation == "submit":
        payload["nonce"] = "d" * 32
        response = {
            "status": "submitted", "job_id": "123.zeus-master",
            "nonce": payload["nonce"], "submitted_unix_s": 1,
        }
    encoded = json.dumps(response).encode()
    stdout = encoded + b" " * (MAX_REMOTE_OUTPUT - len(encoded))
    monkeypatch.setattr(
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, stdout, b""),
    )
    transport = PinnedSshSmokeSubmissionTransport(
        root, executable("ssh"), _profile(),
    )
    assert getattr(transport, operation)(**payload).status == response["status"]


@pytest.mark.parametrize("operation,expected", [
    ("inspect", "remote_response_invalid"),
    ("submit", "submission_outcome_unknown"),
])
def test_smoke_submission_stdout_cap_rejects_one_byte_over(
    tmp_path, monkeypatch, operation, expected,
):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, b" " * (MAX_REMOTE_OUTPUT + 1), b"",
        ),
    )
    transport = PinnedSshSmokeSubmissionTransport(
        root, executable("ssh"), _profile(),
    )
    payload = _smoke_payload()
    if operation == "submit":
        payload["nonce"] = "d" * 32
    with pytest.raises(ZeusSubmissionError) as caught:
        getattr(transport, operation)(**payload)
    assert caught.value.code == expected


@pytest.mark.parametrize("operation,overflow,expected", [
    ("inspect", False, "zeus_authentication_required"),
    ("submit", False, "zeus_authentication_required"),
    ("inspect", True, "remote_response_invalid"),
    ("submit", True, "submission_outcome_unknown"),
])
def test_smoke_submission_stderr_cap_precedes_authentication_mapping(
    tmp_path, monkeypatch, operation, overflow, expected,
):
    root = tmp_path / "repo"
    root.mkdir()
    prefix = b"Permission denied"
    size = MAX_REMOTE_OUTPUT + int(overflow)
    stderr = prefix + b" " * (size - len(prefix))
    monkeypatch.setattr(
        "workflow_api.pinned_ssh._bounded_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 255, b"", stderr),
    )
    transport = PinnedSshSmokeSubmissionTransport(
        root, executable("ssh"), _profile(),
    )
    payload = _smoke_payload()
    if operation == "submit":
        payload["nonce"] = "d" * 32
    with pytest.raises(ZeusSubmissionError) as caught:
        getattr(transport, operation)(**payload)
    assert caught.value.code == expected


def test_snapshot_runner_preserves_exact_bounded_popen_contract(
    tmp_path, monkeypatch,
):
    observed = {}

    class Process:
        stdout = io.BytesIO(b"snapshot-output")
        stderr = io.BytesIO(b"snapshot-errors")

        def wait(self, timeout):
            observed.setdefault("waits", []).append(timeout)
            return 7

        def kill(self):
            raise AssertionError("successful snapshot must not be killed")

    def popen(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return Process()

    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/test-agent.sock")
    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.Popen", popen)
    runner = PinnedSshRunner(PinnedSshPolicy.snapshot(
        tmp_path, executable("ssh"), timeout=25,
    ))
    assert runner.snapshot(_profile()) == (7, b"snapshot-output", b"snapshot-errors")
    remote = shlex.split(observed["argv"][-1])
    assert remote[:3] == [
        "python3", "-c",
        "import base64,sys;payload=sys.argv[1];sys.argv=sys.argv[1:];"
        "exec(base64.urlsafe_b64decode(payload).decode('utf-8'))",
    ]
    assert base64.urlsafe_b64decode(remote[3]).decode() == SNAPSHOT_REMOTE_SCRIPT
    assert remote[4:] == [
        "tal.noa", "/home/tal.noa/ytterbium_lab_simulation_new",
    ]
    assert observed["argv"][:-2] == [
        str(executable("ssh")), "-F", "none", "-T",
        "-o", "BatchMode=yes", "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "NumberOfPasswordPrompts=0", "-o", "ConnectTimeout=8",
        "-o", "ConnectionAttempts=1", "-o", "StrictHostKeyChecking=yes",
        "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes",
        "-o", "PermitLocalCommand=no", "-o", "ProxyCommand=none",
        "-o", "ProxyJump=none", "-o", "KnownHostsCommand=none",
        "-o", "CanonicalizeHostname=no", "-o", "LogLevel=ERROR",
    ]
    assert observed["argv"][-2] == "tal.noa@zeus.technion.ac.il"
    assert observed["kwargs"] == {
        "cwd": tmp_path,
        "env": {
            "PATH": str(executable("ssh").parent), "HOME": str(Path.home()), "LC_ALL": "C", **_expected_windows_ssh_paths(),
            "SSH_AUTH_SOCK": "/tmp/test-agent.sock",
        },
        "shell": False,
        "close_fds": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    assert observed["waits"] == [25]


def test_snapshot_runner_rejects_hostile_profile_before_popen(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    runner = PinnedSshRunner(PinnedSshPolicy.snapshot(
        tmp_path, executable("ssh"), timeout=25,
    ))
    with pytest.raises(ValueError, match="Invalid pinned SSH profile"):
        runner.snapshot(ZeusProfile(
            "-oProxyCommand=bad",
            "/home/-oProxyCommand=bad/ytterbium_lab_simulation_new",
        ))
    assert calls == []


def test_snapshot_runner_preserves_raw_popen_oserror(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("ssh unavailable")),
    )
    runner = PinnedSshRunner(PinnedSshPolicy.snapshot(
        tmp_path, executable("ssh"), timeout=25,
    ))
    with pytest.raises(OSError, match="ssh unavailable"):
        runner.snapshot(_profile())


@pytest.mark.parametrize("stream,limit", [
    ("stdout", SNAPSHOT_MAX_STDOUT),
    ("stderr", SNAPSHOT_MAX_STDERR),
])
@pytest.mark.parametrize("overflow", [False, True])
def test_snapshot_runner_preserves_exact_stream_cap_boundary(
    tmp_path, monkeypatch, stream, limit, overflow,
):
    content = b"x" * (limit + int(overflow))

    class Process:
        stdout = io.BytesIO(content if stream == "stdout" else b"")
        stderr = io.BytesIO(content if stream == "stderr" else b"")

        def __init__(self):
            self.kills = 0

        def wait(self, timeout):
            return 0

        def kill(self):
            self.kills += 1

    process = Process()
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    runner = PinnedSshRunner(PinnedSshPolicy.snapshot(
        tmp_path, executable("ssh"), timeout=25,
    ))
    if overflow:
        with pytest.raises(ZeusSnapshotError, match="malformed_remote_response"):
            runner.snapshot(_profile())
        assert process.kills >= 1
    else:
        _, stdout, stderr = runner.snapshot(_profile())
        assert (stdout if stream == "stdout" else stderr) == content
        assert process.kills == 0


def test_snapshot_runner_timeout_kills_then_waits_again(tmp_path, monkeypatch):
    events = []

    class Process:
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(b"")

        def wait(self, timeout=None):
            events.append(("wait", timeout))
            if timeout is not None:
                raise subprocess.TimeoutExpired("ssh", timeout)
            return -9

        def kill(self):
            events.append(("kill", None))

    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: Process(),
    )
    runner = PinnedSshRunner(PinnedSshPolicy.snapshot(
        tmp_path, executable("ssh"), timeout=25,
    ))
    with pytest.raises(ZeusSnapshotError, match="zeus_timeout"):
        runner.snapshot(_profile())
    assert events == [("wait", 25), ("kill", None), ("wait", None)]


@pytest.mark.parametrize("failure", ["kill", "second_wait"])
def test_snapshot_timeout_preserves_raw_cleanup_oserror(
    tmp_path, monkeypatch, failure,
):
    class Process:
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(b"")

        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("ssh", timeout)
            if failure == "second_wait":
                raise OSError("wait failed")
            return -9

        def kill(self):
            if failure == "kill":
                raise OSError("kill failed")

    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: Process(),
    )
    runner = PinnedSshRunner(PinnedSshPolicy.snapshot(
        tmp_path, executable("ssh"), timeout=25,
    ))
    expected = "kill failed" if failure == "kill" else "wait failed"
    with pytest.raises(OSError, match=expected):
        runner.snapshot(_profile())


def test_snapshot_overflow_drain_kill_oserror_is_swallowed(tmp_path, monkeypatch):
    class Process:
        stdout = io.BytesIO(b"x" * (SNAPSHOT_MAX_STDOUT + 1))
        stderr = io.BytesIO(b"")

        def __init__(self):
            self.kills = 0

        def wait(self, timeout):
            return 0

        def kill(self):
            self.kills += 1
            if self.kills == 1:
                raise OSError("first kill failed")

    process = Process()
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    runner = PinnedSshRunner(PinnedSshPolicy.snapshot(
        tmp_path, executable("ssh"), timeout=25,
    ))
    with pytest.raises(ZeusSnapshotError, match="malformed_remote_response"):
        runner.snapshot(_profile())
    assert process.kills == 2


def test_snapshot_alive_reader_is_killed_and_rejected(tmp_path, monkeypatch):
    release = threading.Event()

    class BlockingStream:
        def read(self, _size):
            release.wait(timeout=3)
            return b""

    class Process:
        stdout = BlockingStream()
        stderr = io.BytesIO(b"")

        def wait(self, timeout):
            return 0

        def kill(self):
            release.set()

    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: Process(),
    )
    runner = PinnedSshRunner(PinnedSshPolicy.snapshot(
        tmp_path, executable("ssh"), timeout=25,
    ))
    with pytest.raises(ZeusSnapshotError, match="malformed_remote_response"):
        runner.snapshot(_profile())
    assert release.is_set()


def test_snapshot_runner_omits_absent_agent_socket(tmp_path, monkeypatch):
    observed = {}

    class Process:
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(b"")

        def wait(self, timeout):
            return 0

        def kill(self):
            raise AssertionError("must not kill")

    def popen(*args, **kwargs):
        observed.update(kwargs)
        return Process()

    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.Popen", popen)
    PinnedSshRunner(PinnedSshPolicy.snapshot(
        tmp_path, executable("ssh"), timeout=25,
    )).snapshot(_profile())
    assert observed["env"] == {
        "PATH": str(executable("ssh").parent), "HOME": str(Path.home()), "LC_ALL": "C", **_expected_windows_ssh_paths(),
    }


@pytest.mark.parametrize("operation", list(TransferOperation))
def test_transfer_runner_preserves_exact_closed_streaming_contract(
    tmp_path, monkeypatch, operation,
):
    observed = {}

    class Sink:
        def __init__(self):
            self.value = bytearray()
            self.closed = False

        def write(self, value):
            self.value.extend(value)

        def close(self):
            self.closed = True

    class Process:
        def __init__(self):
            self.stdin = Sink()
            self.stdout = io.BytesIO(b'{"ok":true}')
            self.stderr = io.BytesIO(b"")

        def wait(self, timeout):
            observed["wait"] = timeout
            return 0

        def kill(self):
            raise AssertionError("successful transfer must not be killed")

    process = Process()

    def popen(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return process

    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/test-agent.sock")
    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.Popen", popen)
    runner = PinnedSshRunner(PinnedSshPolicy.transfer(
        tmp_path, executable("ssh"), timeout=120,
    ))
    paths = ("data/particle_states/after_zeeman/p/a.npy",)
    payload = b"payload" if operation is not TransferOperation.INSPECT else b""
    assert runner.transfer(
        operation, _profile(), paths, "a" * 40, payload,
    ) == (0, b'{"ok":true}', b"")
    remote = shlex.split(observed["argv"][-1])
    assert remote[:2] == ["python3", "-c"]
    assert len(remote) == 3
    assert "sys.stdin.buffer.readline(262145)" in remote[2]
    header_line, remaining = bytes(process.stdin.value).split(b"\n", 1)
    source, receiver_argv = json.loads(header_line)
    assert base64.urlsafe_b64decode(source).decode() == _REMOTE_TRANSFER_SCRIPT
    assert receiver_argv[:4] == ["<transfer-receiver>", operation.value, "tal.noa",
                                "/home/tal.noa/ytterbium_lab_simulation_new"]
    assert json.loads(base64.urlsafe_b64decode(receiver_argv[4])) == list(paths)
    assert receiver_argv[5] == "a" * 40
    assert remaining == payload
    assert observed["argv"][-2] == "tal.noa@zeus.technion.ac.il"
    assert observed["kwargs"] == {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": tmp_path,
        "env": {
            "PATH": str(executable("ssh").parent), "HOME": str(Path.home()), "LC_ALL": "C", **_expected_windows_ssh_paths(),
            "SSH_AUTH_SOCK": "/tmp/test-agent.sock",
        },
        "shell": False,
        "close_fds": True,
    }
    assert observed["wait"] == 120
    assert process.stdin.closed


def test_transfer_runner_enforces_input_cap_before_popen(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    runner = PinnedSshRunner(PinnedSshPolicy.transfer(
        tmp_path, executable("ssh"), timeout=120,
    ))
    with pytest.raises(Exception) as caught:
        runner.transfer(
            TransferOperation.INPUTS, _profile(), (), "a" * 40,
            b"x" * (MAX_TRANSFER_BYTES + 1),
        )
    assert getattr(caught.value, "code", None) == "transfer_too_large"
    assert calls == []


def test_transfer_runner_rejects_non_bytes_before_popen(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    runner = PinnedSshRunner(PinnedSshPolicy.transfer(
        tmp_path, executable("ssh"), timeout=120,
    ))
    with pytest.raises(ValueError, match="Invalid pinned SSH transfer payload"):
        runner.transfer(
            TransferOperation.INPUTS, _profile(), (), "a" * 40,
            bytearray(),  # type: ignore[arg-type]
        )
    assert calls == []


@pytest.mark.parametrize("stream,limit", [
    ("stdout", 2 * 1024 * 1024),
    ("stderr", 65536),
])
@pytest.mark.parametrize("overflow", [False, True])
def test_transfer_runner_preserves_exact_output_boundaries(
    tmp_path, monkeypatch, stream, limit, overflow,
):
    content = b"x" * (limit + int(overflow))

    class Process:
        stdin = io.BytesIO()
        stdout = io.BytesIO(content if stream == "stdout" else b"")
        stderr = io.BytesIO(content if stream == "stderr" else b"")

        def __init__(self):
            self.kills = 0

        def wait(self, timeout):
            return 0

        def kill(self):
            self.kills += 1

    process = Process()
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    runner = PinnedSshRunner(PinnedSshPolicy.transfer(
        tmp_path, executable("ssh"), timeout=120,
    ))
    if overflow:
        with pytest.raises(Exception) as caught:
            runner.transfer(
                TransferOperation.INSPECT, _profile(), (), "a" * 40, b"",
            )
        assert getattr(caught.value, "code", None) == "remote_response_invalid"
        assert process.kills >= 1
    else:
        _, stdout, stderr = runner.transfer(
            TransferOperation.INSPECT, _profile(), (), "a" * 40, b"",
        )
        assert (stdout if stream == "stdout" else stderr) == content
        assert process.kills == 0


def test_transfer_runner_writes_exact_max_payload_and_closes(
    tmp_path, monkeypatch,
):
    class Sink:
        def __init__(self):
            self.header = None
            self.length = 0
            self.digest = __import__("hashlib").sha256()
            self.closed = False

        def write(self, value):
            if self.header is None:
                self.header = json.loads(value)
                return
            self.length += len(value)
            self.digest.update(value)

        def close(self):
            self.closed = True

    class Process:
        stdin = Sink()
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(b"")

        def wait(self, timeout):
            return 0

        def kill(self):
            raise AssertionError("must not kill")

    process = Process()
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    payload = b"x" * MAX_TRANSFER_BYTES
    PinnedSshRunner(PinnedSshPolicy.transfer(
        tmp_path, executable("ssh"), timeout=120,
    )).transfer(TransferOperation.INPUTS, _profile(), (), "a" * 40, payload)
    assert process.stdin.length == MAX_TRANSFER_BYTES
    assert process.stdin.digest.hexdigest() == __import__("hashlib").sha256(payload).hexdigest()
    assert process.stdin.closed


@pytest.mark.parametrize("failure", ["timeout", "kill", "second_wait", "popen"])
def test_transfer_runner_preserves_timeout_and_oserror_lifecycle(
    tmp_path, monkeypatch, failure,
):
    events = []

    class Process:
        stdin = io.BytesIO()
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(b"")

        def wait(self, timeout=None):
            events.append(("wait", timeout))
            if timeout is not None:
                raise subprocess.TimeoutExpired("ssh", timeout)
            if failure == "second_wait":
                raise OSError("wait failed")
            return -9

        def kill(self):
            events.append(("kill", None))
            if failure == "kill":
                raise OSError("kill failed")

    def popen(*args, **kwargs):
        if failure == "popen":
            raise OSError("popen failed")
        return Process()

    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.Popen", popen)
    runner = PinnedSshRunner(PinnedSshPolicy.transfer(
        tmp_path, executable("ssh"), timeout=120,
    ))
    if failure == "timeout":
        with pytest.raises(Exception) as caught:
            runner.transfer(
                TransferOperation.INSPECT, _profile(), (), "a" * 40, b"",
            )
        assert getattr(caught.value, "code", None) == "zeus_timeout"
        assert events == [("wait", 120), ("kill", None), ("wait", None)]
    else:
        expected = {
            "kill": "kill failed", "second_wait": "wait failed",
            "popen": "popen failed",
        }[failure]
        with pytest.raises(OSError, match=expected):
            runner.transfer(
                TransferOperation.INSPECT, _profile(), (), "a" * 40, b"",
            )


@pytest.mark.parametrize("failure", [BrokenPipeError, OSError])
def test_transfer_writer_errors_are_swallowed_with_legacy_close_order(
    tmp_path, monkeypatch, failure,
):
    class Sink:
        def __init__(self):
            self.close_attempted = False

        def write(self, _value):
            raise failure("write failed")

        def close(self):
            self.close_attempted = True
            raise failure("close failed")

    class Process:
        stdin = Sink()
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(b"")

        def wait(self, timeout):
            return 0

        def kill(self):
            raise AssertionError("must not kill")

    process = Process()
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    PinnedSshRunner(PinnedSshPolicy.transfer(
        tmp_path, executable("ssh"), timeout=120,
    )).transfer(TransferOperation.INPUTS, _profile(), (), "a" * 40, b"x")
    assert not process.stdin.close_attempted


@pytest.mark.parametrize("failure", [BrokenPipeError, OSError])
def test_transfer_empty_payload_still_attempts_and_swallows_close(
    tmp_path, monkeypatch, failure,
):
    class Sink:
        def __init__(self):
            self.close_attempted = False

        def write(self, value):
            # Empty binary payloads still carry the transport-owned header.
            assert value.endswith(b"\n")
            assert json.loads(value)[1][1] == "inspect"

        def close(self):
            self.close_attempted = True
            raise failure("close failed")

    class Process:
        stdin = Sink()
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(b"")

        def wait(self, timeout):
            return 0

        def kill(self):
            raise AssertionError("must not kill")

    process = Process()
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    PinnedSshRunner(PinnedSshPolicy.transfer(
        tmp_path, executable("ssh"), timeout=120,
    )).transfer(TransferOperation.INSPECT, _profile(), (), "a" * 40, b"")
    assert process.stdin.close_attempted


@pytest.mark.parametrize("blocked", ["writer", "stdout", "stderr"])
def test_transfer_stuck_thread_is_killed_and_rejected(
    tmp_path, monkeypatch, blocked,
):
    release = threading.Event()

    class BlockingStream:
        def read(self, _size):
            release.wait(timeout=3)
            return b""

    class Sink:
        def write(self, _value):
            if blocked == "writer":
                release.wait(timeout=3)

        def close(self):
            pass

    class Process:
        stdin = Sink()
        stdout = BlockingStream() if blocked == "stdout" else io.BytesIO(b"")
        stderr = BlockingStream() if blocked == "stderr" else io.BytesIO(b"")

        def wait(self, timeout):
            return 0

        def kill(self):
            release.set()

    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: Process(),
    )
    runner = PinnedSshRunner(PinnedSshPolicy.transfer(
        tmp_path, executable("ssh"), timeout=120,
    ))
    with pytest.raises(Exception) as caught:
        runner.transfer(
            TransferOperation.INPUTS, _profile(), (), "a" * 40, b"x",
        )
    assert getattr(caught.value, "code", None) == "remote_response_invalid"
    assert release.is_set()


def test_transfer_overflow_drain_kill_oserror_is_swallowed(tmp_path, monkeypatch):
    class Process:
        stdin = io.BytesIO()
        stdout = io.BytesIO(b"x" * (2 * 1024 * 1024 + 1))
        stderr = io.BytesIO(b"")

        def __init__(self):
            self.kills = 0

        def wait(self, timeout):
            return 0

        def kill(self):
            self.kills += 1
            if self.kills == 1:
                raise OSError("first kill failed")

    process = Process()
    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    runner = PinnedSshRunner(PinnedSshPolicy.transfer(
        tmp_path, executable("ssh"), timeout=120,
    ))
    with pytest.raises(ZeusPreparationError, match="remote_response_invalid"):
        runner.transfer(
            TransferOperation.INSPECT, _profile(), (), "a" * 40, b"",
        )
    assert process.kills == 2


@pytest.mark.parametrize("stderr,expected", [
    (b"Host key verification failed", "zeus_host_key_untrusted"),
    (b"Remote host identification has changed", "zeus_host_key_untrusted"),
    (b"Permission denied", "zeus_authentication_required"),
    (b"Authentication failed", "zeus_authentication_required"),
    (b"Connection timed out", "zeus_timeout"),
    (b"Could not resolve hostname", "zeus_unreachable"),
    (b"Connection refused", "zeus_unreachable"),
    (b"No route to host", "zeus_unreachable"),
])
def test_transfer_transport_connection_mapping_is_unchanged(
    tmp_path, monkeypatch, stderr, expected,
):
    root = tmp_path / "repo"
    root.mkdir()

    class Process:
        def __init__(self):
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO(b"")
            self.stderr = io.BytesIO(stderr)

        def wait(self, timeout):
            return 255

        def kill(self):
            raise AssertionError("must not kill")

    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: Process(),
    )
    transport = PinnedSshZeusPreparationTransport(
        root, executable("ssh"), _profile(), "a" * 40,
    )
    with pytest.raises(ZeusPreparationError) as caught:
        transport.inspect(())
    assert caught.value.code == expected


def test_transfer_unknown_remote_error_falls_back_unchanged(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()

    class Process:
        stdin = io.BytesIO()
        stdout = io.BytesIO(b'{"error":"hostile_internal_code"}')
        stderr = io.BytesIO(b"")

        def wait(self, timeout):
            return 1

        def kill(self):
            raise AssertionError("must not kill")

    monkeypatch.setattr(
        "workflow_api.pinned_ssh.subprocess.Popen",
        lambda *args, **kwargs: Process(),
    )
    transport = PinnedSshZeusPreparationTransport(
        root, executable("ssh"), _profile(), "a" * 40,
    )
    with pytest.raises(ZeusPreparationError) as caught:
        transport.inspect(())
    assert caught.value.code == "zeus_transfer_failed"


@pytest.mark.parametrize("operation", list(TransferOperation))
@pytest.mark.parametrize("acceptance", [False, True])
def test_transfer_maximum_valid_paths_use_short_command_and_preserve_binary_stream(
    tmp_path, monkeypatch, operation, acceptance
):
    """Execute the real framing bootstrap, never SSH or a campaign operation."""
    import hashlib
    from workflow_api import zeus_transfer
    namespace = "n" * 128
    prefix = f"data/particle_states/after_zeeman/{'ui_acceptance/' if acceptance else ''}{namespace}/{'d' * 128}/"
    paths = tuple(prefix + "f" * (512 - len(prefix) - 8) + f"{index:04}.npy" for index in range(72))
    assert len(set(paths)) == 72
    assert all(len(value.encode()) == 512 for value in paths)
    encoded_paths = base64.urlsafe_b64encode(json.dumps(paths, separators=(",", ":")).encode()).decode()
    # Demonstrate the old command exceeded Windows' maximum with valid inputs.
    old_remote = shlex.join(("python3", "-c", "fixed-wrapper", base64.urlsafe_b64encode(zeus_transfer._REMOTE_TRANSFER_SCRIPT.encode()).decode(), operation.value, "tal.noa", "/home/tal.noa/ytterbium_lab_simulation_ui_acceptance", encoded_paths, "a" * 40))
    old_length = len(subprocess.list2cmdline([str(executable("ssh")), "tal.noa@zeus.technion.ac.il", old_remote]))
    assert old_length > 32767
    receiver = "#" + "x" * 40000 + "\nimport sys,json,hashlib\ndata=sys.stdin.buffer.read()\nprint(json.dumps({'argv':sys.argv[1:],'length':len(data),'sha256':hashlib.sha256(data).hexdigest()}))\n"
    monkeypatch.setattr(zeus_transfer, "_REMOTE_TRANSFER_SCRIPT", receiver)
    original_popen = subprocess.Popen
    observed = {}
    def execute_bootstrap(argv, **kwargs):
        observed["length"] = len(subprocess.list2cmdline(argv))
        observed["remote"] = shlex.split(argv[-1])
        parts = observed["remote"]
        wrapper = parts[parts.index("-c") + 1]
        # The observer receiver is test-only; the bootstrap and stdin stream are real.
        return original_popen([sys.executable, "-c", wrapper], **kwargs)
    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.Popen", execute_bootstrap)
    profile = ZeusProfile.parse({"username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_" + ("ui_acceptance" if acceptance else "new")})
    payload = (b'\n["untrusted-payload-header",["campaign","attacker"]]\n' + b"\x00\n\xffBINARY\r\n" * 1000) if operation is not TransferOperation.INSPECT else b""
    runner = PinnedSshRunner(PinnedSshPolicy.transfer(tmp_path, executable("ssh"), timeout=10))
    status, raw, stderr = runner.transfer(operation, profile, paths, "a" * 40, payload)
    assert status == 0, stderr.decode(errors="replace")
    result = json.loads(raw)
    assert result == {"argv": [operation.value, profile.username, profile.project_directory, encoded_paths, "a" * 40], "length": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    assert observed["length"] < 4000
    parts = observed["remote"]
    assert parts[parts.index("-c") - 1] == ("/home/tal.noa/venvs/atomsmltr-ui-test/bin/python" if acceptance else "python3")
    if acceptance:
        assert parts[:4] == ["cd", "--", profile.project_directory, "&&"]
    else:
        assert parts[:2] == ["python3", "-c"]


def test_transfer_rejects_oversized_framing_before_process_creation(tmp_path, monkeypatch):
    from workflow_api import zeus_transfer
    monkeypatch.setattr(zeus_transfer, "_REMOTE_TRANSFER_SCRIPT", "#" * (256 * 1024))
    calls = []
    monkeypatch.setattr("workflow_api.pinned_ssh.subprocess.Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    runner = PinnedSshRunner(PinnedSshPolicy.transfer(tmp_path, executable("ssh"), timeout=10))
    with pytest.raises(ValueError, match="framing exceeds its bound"):
        runner.transfer(TransferOperation.INSPECT, _profile(), (), "a" * 40, b"")
    assert calls == []


@pytest.mark.parametrize('kind,operation,profile_mode', [
    (kind, operation, profile_mode)
    for kind, definition in __import__('workflow_api.pinned_ssh', fromlist=['_RECEIVERS'])._RECEIVERS.items()
    if definition.filename is not None or definition.embedded_smoke_receiver
    for operation in definition.operations
    for profile_mode in (['canonical'] if kind.value.endswith('_individual') else ['canonical','acceptance'])
])
def test_every_file_receiver_bootstrap_preserves_real_child_argument_contract(tmp_path, monkeypatch, kind, operation, profile_mode):
    from workflow_api import pinned_ssh
    definition = pinned_ssh._RECEIVERS[kind]
    operation_only = kind in {
        pinned_ssh.ReceiverKind.SENSITIVITY_PREPARATION,
        pinned_ssh.ReceiverKind.PRODUCTION_PREPARATION,
        pinned_ssh.ReceiverKind.FINALIZATION,
    }
    stdin_payload = definition.payload_stdin or operation_only
    observer = b"#" + b"x" * 40000 + b"\nimport sys,json,base64\nprint(json.dumps({'argv':sys.argv[1:],'payload':json.loads(sys.stdin.buffer.read()) if " + str(stdin_payload).encode() + b" else json.loads(base64.urlsafe_b64decode(sys.argv[4]))}))\n"
    if definition.embedded_smoke_receiver:
        monkeypatch.setattr('workflow_api.zeus_submission._REMOTE_SCRIPT', observer.decode())
    original = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda path: observer if path.name == definition.filename else original(path))
    observed = {}
    def execute(argv, **kwargs):
        parts = shlex.split(argv[-1])
        observed['remote'] = parts
        assert len(subprocess.list2cmdline(argv)) < 4000
        offset = parts.index('-c')
        return subprocess.run([sys.executable, *parts[offset:]],
                              input=kwargs.get('input'), capture_output=True, check=False)
    monkeypatch.setattr(pinned_ssh, '_bounded_run', execute)
    profile = _profile() if profile_mode == 'canonical' else ZeusProfile.parse({'username':'tal.noa','project_directory':'/home/tal.noa/ytterbium_lab_simulation_ui_acceptance'})
    payload = {'unicode': 'בדיקה', 'receiver': kind.value, 'operation': operation.value, 'paths': ['data/' + 'p' * 503 + str(i).zfill(4) for i in range(72)]}
    policy = PinnedSshPolicy(kind, tmp_path, Path(sys.executable), 10)
    result = PinnedSshRunner(policy).run(operation, profile, payload)
    assert result.returncode == 0, result.stderr.decode()
    expected = [operation.value] if operation_only else [operation.value, profile.username, profile.project_directory, '-' if stdin_payload else base64.urlsafe_b64encode(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).decode()]
    assert json.loads(result.stdout) == {'argv': expected, 'payload': payload}
    if not kind.value.endswith('_individual'):
        remote = observed['remote']
        assert remote[remote.index('-c') - 1] == '/home/tal.noa/venvs/' + ('atomsmltr' if profile_mode == 'canonical' else 'atomsmltr-ui-test') + '/bin/python'
        assert observed['remote'][:4] == ['cd', '--', profile.project_directory, '&&']


def test_run_rejects_oversized_transport_header_before_process_launch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr('workflow_api.pinned_ssh._bounded_run', lambda *a, **k: calls.append((a,k)))
    runner = PinnedSshRunner(PinnedSshPolicy.screening_preparation(tmp_path, Path(sys.executable), timeout=10))
    with pytest.raises(ValueError, match='receiver framing exceeds its bound'):
        runner.run(ReceiverOperation.INSPECT, _profile(), {'oversized': 'x' * (2 * 1024 * 1024)})
    assert calls == []
