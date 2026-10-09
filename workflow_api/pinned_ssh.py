"""Closed SSH execution for audited, repository-owned receiver programs."""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from workflow_api.zeus_snapshot import ZEUS_HOST, ZeusProfile


class ReceiverKind(Enum):
    REFINEMENT_TRANSITION = "refinement_transition"
    CONFIRMATION_PREPARATION = "confirmation_preparation"
    REFINEMENT_SUBMISSION = "refinement_submission"
    SCREENING_PREPARATION = "screening_preparation"


class ReceiverOperation(Enum):
    INSPECT = "inspect"
    PREPARE = "prepare"
    SUBMIT = "submit"


class PinnedSshProcessError(RuntimeError):
    """A process-launch OSError, distinct from receiver file read failures."""


@dataclass(frozen=True)
class _ReceiverDefinition:
    filename: str
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

        if definition.payload_before_receiver:
            encoded = encode_payload()
            receiver = Path(__file__).with_name(definition.filename).read_bytes()
        else:
            receiver = Path(__file__).with_name(definition.filename).read_bytes()
            encoded = encode_payload()
        script = base64.urlsafe_b64encode(receiver).decode()
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
