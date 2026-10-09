"""Closed SSH execution for audited, repository-owned receiver programs."""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from workflow_api.zeus_snapshot import ZEUS_HOST, ZeusProfile, ZeusSnapshotError


class ReceiverKind(Enum):
    REFINEMENT_TRANSITION = "refinement_transition"
    CONFIRMATION_PREPARATION = "confirmation_preparation"
    REFINEMENT_SUBMISSION = "refinement_submission"
    SCREENING_PREPARATION = "screening_preparation"
    SCREENING_SUBMISSION = "screening_submission"
    SMOKE_SUBMISSION = "smoke_submission"
    SNAPSHOT = "snapshot"


class ReceiverOperation(Enum):
    INSPECT = "inspect"
    PREPARE = "prepare"
    SUBMIT = "submit"


class PinnedSshProcessError(RuntimeError):
    """A process-launch OSError, distinct from receiver file read failures."""


@dataclass(frozen=True)
class _ReceiverDefinition:
    filename: str | None
    compile_name: str
    operations: frozenset[ReceiverOperation]
    wrap_process_oserror: bool
    ssh_arguments: tuple[str, ...] = (
        "-F", "none", "-T",
        "-o", "BatchMode=yes",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ForwardAgent=no",
        "-o", "ClearAllForwardings=yes",
    )
    pinned_environment: bool = False
    explicit_process_safety: bool = False
    payload_before_receiver: bool = False
    embedded_smoke_receiver: bool = False
    embedded_snapshot_receiver: bool = False


_RECEIVERS = {
    ReceiverKind.REFINEMENT_TRANSITION: _ReceiverDefinition(
        "zeus_refinement_remote.py",
        "<refine>",
        frozenset({ReceiverOperation.INSPECT, ReceiverOperation.PREPARE}),
        False,
    ),
    ReceiverKind.CONFIRMATION_PREPARATION: _ReceiverDefinition(
        "zeus_confirmation_remote.py",
        "<confirmation>",
        frozenset({ReceiverOperation.INSPECT, ReceiverOperation.PREPARE}),
        True,
    ),
    ReceiverKind.REFINEMENT_SUBMISSION: _ReceiverDefinition(
        "zeus_refinement_submission_remote.py",
        "<refine-submit>",
        frozenset({ReceiverOperation.INSPECT, ReceiverOperation.SUBMIT}),
        False,
    ),
    ReceiverKind.SCREENING_PREPARATION: _ReceiverDefinition(
        "zeus_screening_remote.py",
        "<zeus-screening>",
        frozenset({ReceiverOperation.INSPECT, ReceiverOperation.PREPARE}),
        False,
        (
            "-F", "none", "-T",
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
        ),
        True,
        True,
        True,
    ),
    ReceiverKind.SCREENING_SUBMISSION: _ReceiverDefinition(
        "zeus_screen_submission_remote.py",
        "<screen-submit>",
        frozenset({ReceiverOperation.INSPECT, ReceiverOperation.SUBMIT}),
        False,
        (
            "-F", "none", "-T",
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
        ),
        True,
        True,
        True,
    ),
    ReceiverKind.SMOKE_SUBMISSION: _ReceiverDefinition(
        None,
        "<smoke-submit>",
        frozenset({ReceiverOperation.INSPECT, ReceiverOperation.SUBMIT}),
        False,
        (
            "-F", "none", "-T",
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
        ),
        True,
        True,
        True,
        True,
    ),
    ReceiverKind.SNAPSHOT: _ReceiverDefinition(
        None,
        "<snapshot>",
        frozenset(),
        False,
        (
            "-F", "none", "-T",
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
        ),
        True,
        True,
        False,
        False,
        True,
    ),
}


@dataclass(frozen=True)
class PinnedSshPolicy:
    """Trusted local execution facts, separate from per-call request data."""

    receiver: ReceiverKind
    repository_root: Path
    ssh_executable: Path
    timeout: float

    @classmethod
    def refinement_transition(
        cls,
        repository_root: Path,
        ssh_executable: Path,
        *,
        timeout: float,
    ) -> PinnedSshPolicy:
        return cls(
            ReceiverKind.REFINEMENT_TRANSITION,
            repository_root,
            ssh_executable,
            timeout,
        )

    @classmethod
    def confirmation_preparation(
        cls,
        repository_root: Path,
        ssh_executable: Path,
        *,
        timeout: float,
    ) -> PinnedSshPolicy:
        return cls(
            ReceiverKind.CONFIRMATION_PREPARATION,
            repository_root,
            ssh_executable,
            timeout,
        )

    @classmethod
    def refinement_submission(
        cls,
        repository_root: Path,
        ssh_executable: Path,
        *,
        timeout: float,
    ) -> PinnedSshPolicy:
        return cls(
            ReceiverKind.REFINEMENT_SUBMISSION,
            repository_root,
            ssh_executable,
            timeout,
        )

    @classmethod
    def screening_preparation(
        cls,
        repository_root: Path,
        ssh_executable: Path,
        *,
        timeout: float,
    ) -> PinnedSshPolicy:
        return cls(
            ReceiverKind.SCREENING_PREPARATION,
            repository_root,
            ssh_executable,
            timeout,
        )

    @classmethod
    def screening_submission(
        cls,
        repository_root: Path,
        ssh_executable: Path,
        *,
        timeout: float,
    ) -> PinnedSshPolicy:
        return cls(
            ReceiverKind.SCREENING_SUBMISSION,
            repository_root,
            ssh_executable,
            timeout,
        )

    @classmethod
    def smoke_submission(
        cls,
        repository_root: Path,
        ssh_executable: Path,
        *,
        timeout: float,
    ) -> PinnedSshPolicy:
        return cls(
            ReceiverKind.SMOKE_SUBMISSION,
            repository_root,
            ssh_executable,
            timeout,
        )

    @classmethod
    def snapshot(
        cls,
        repository_root: Path,
        ssh_executable: Path,
        *,
        timeout: float,
    ) -> PinnedSshPolicy:
        return cls(
            ReceiverKind.SNAPSHOT,
            repository_root,
            ssh_executable,
            timeout,
        )


class PinnedSshRunner:
    """Run one closed receiver without accepting commands or SSH options."""

    def __init__(self, policy: PinnedSshPolicy):
        if type(policy.receiver) is not ReceiverKind or policy.receiver not in _RECEIVERS:
            raise ValueError("Unsupported pinned SSH receiver.")
        self._policy = policy

    def run(
        self,
        operation: ReceiverOperation,
        profile: ZeusProfile,
        payload: Mapping[str, object],
    ) -> subprocess.CompletedProcess[bytes]:
        if type(profile) is not ZeusProfile:
            raise ValueError("Invalid pinned SSH profile.")
        try:
            validated_profile = ZeusProfile.parse({
                "username": profile.username,
                "project_directory": profile.project_directory,
            })
        except ValueError as error:
            raise ValueError("Invalid pinned SSH profile.") from error
        if validated_profile != profile:
            raise ValueError("Invalid pinned SSH profile.")
        definition = _RECEIVERS[self._policy.receiver]
        if type(operation) is not ReceiverOperation or operation not in definition.operations:
            raise ValueError("Unsupported pinned SSH operation.")
        def encode_payload() -> str:
            return base64.urlsafe_b64encode(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).decode()

        def read_receiver() -> bytes:
            if definition.embedded_smoke_receiver:
                from workflow_api.zeus_submission import _REMOTE_SCRIPT

                return _REMOTE_SCRIPT.encode()
            if definition.filename is None:
                raise RuntimeError("Pinned SSH receiver is unavailable.")
            return Path(__file__).with_name(definition.filename).read_bytes()

        if definition.payload_before_receiver:
            encoded = encode_payload()
            receiver = read_receiver()
        else:
            receiver = read_receiver()
            encoded = encode_payload()
        script = base64.urlsafe_b64encode(receiver).decode()
        if definition.embedded_smoke_receiver:
            wrapper = (
                "import base64,sys;payload=sys.argv[1];sys.argv=sys.argv[1:];"
                "exec(base64.urlsafe_b64decode(payload).decode('utf-8'))"
            )
        else:
            wrapper = (
                "import base64,sys;code=base64.urlsafe_b64decode(sys.argv[1]);"
                "sys.argv=sys.argv[2:];exec(compile(code,'"
                + definition.compile_name
                + "','exec'),{'__name__':'__main__'})"
            )
        remote = shlex.join((
            "python3",
            "-c",
            wrapper,
            script,
            operation.value,
            profile.username,
            profile.project_directory,
            encoded,
        ))
        argv = [
            str(self._policy.ssh_executable),
            *definition.ssh_arguments,
            f"{profile.username}@{ZEUS_HOST}",
            remote,
        ]
        kwargs: dict[str, object] = {
            "cwd": self._policy.repository_root,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "timeout": self._policy.timeout,
            "check": False,
        }
        if definition.pinned_environment:
            environment = {
                "PATH": str(self._policy.ssh_executable.parent),
                "HOME": str(Path.home()),
                "LC_ALL": "C",
            }
            if os.environ.get("SSH_AUTH_SOCK"):
                environment["SSH_AUTH_SOCK"] = os.environ["SSH_AUTH_SOCK"]
            kwargs["env"] = environment
        if definition.explicit_process_safety:
            kwargs["shell"] = False
            kwargs["close_fds"] = True
        try:
            return subprocess.run(argv, **kwargs)
        except OSError as error:
            if definition.wrap_process_oserror:
                raise PinnedSshProcessError from error
            raise

    def snapshot(self, profile: ZeusProfile) -> tuple[int, bytes, bytes]:
        """Run the one fixed bounded snapshot receiver."""
        if self._policy.receiver is not ReceiverKind.SNAPSHOT:
            raise ValueError("Unsupported pinned SSH snapshot receiver.")
        if type(profile) is not ZeusProfile:
            raise ValueError("Invalid pinned SSH profile.")
        try:
            validated_profile = ZeusProfile.parse({
                "username": profile.username,
                "project_directory": profile.project_directory,
            })
        except ValueError as error:
            raise ValueError("Invalid pinned SSH profile.") from error
        if validated_profile != profile:
            raise ValueError("Invalid pinned SSH profile.")

        from workflow_api.zeus_snapshot import (
            MAX_STDERR,
            MAX_STDOUT,
            _REMOTE_SCRIPT,
            _remote_command,
        )

        definition = _RECEIVERS[ReceiverKind.SNAPSHOT]
        arguments = [
            str(self._policy.ssh_executable),
            *definition.ssh_arguments,
            f"{profile.username}@{ZEUS_HOST}",
            _remote_command(profile),
        ]
        environment = {
            "PATH": str(self._policy.ssh_executable.parent),
            "HOME": str(Path.home()),
            "LC_ALL": "C",
        }
        agent_socket = os.environ.get("SSH_AUTH_SOCK")
        if agent_socket:
            environment["SSH_AUTH_SOCK"] = agent_socket
        process = subprocess.Popen(
            arguments,
            cwd=self._policy.repository_root,
            env=environment,
            shell=False,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        output = bytearray()
        errors = bytearray()
        exceeded = threading.Event()

        def drain(stream: Any, limit: int, destination: bytearray) -> None:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    return
                if len(destination) + len(chunk) > limit:
                    exceeded.set()
                    try:
                        process.kill()
                    except OSError:
                        pass
                    return
                destination.extend(chunk)

        readers = [
            threading.Thread(
                target=drain,
                args=(process.stdout, MAX_STDOUT, output),
                daemon=True,
            ),
            threading.Thread(
                target=drain,
                args=(process.stderr, MAX_STDERR, errors),
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()
        try:
            returncode = process.wait(timeout=self._policy.timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise ZeusSnapshotError("zeus_timeout") from None
        for reader in readers:
            reader.join(timeout=1)
        if exceeded.is_set() or any(reader.is_alive() for reader in readers):
            process.kill()
            raise ZeusSnapshotError("malformed_remote_response")
        return returncode, bytes(output), bytes(errors)
