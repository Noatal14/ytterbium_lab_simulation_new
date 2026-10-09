"""Closed SSH execution for audited, repository-owned receiver programs."""

from __future__ import annotations

import base64
import json
import shlex
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from workflow_api.zeus_snapshot import ZEUS_HOST, ZeusProfile


class ReceiverKind(Enum):
    REFINEMENT_TRANSITION = "refinement_transition"


class ReceiverOperation(Enum):
    INSPECT = "inspect"
    PREPARE = "prepare"


@dataclass(frozen=True)
class _ReceiverDefinition:
    filename: str
    compile_name: str
    operations: frozenset[ReceiverOperation]


_RECEIVERS = {
    ReceiverKind.REFINEMENT_TRANSITION: _ReceiverDefinition(
        "zeus_refinement_remote.py",
        "<refine>",
        frozenset({ReceiverOperation.INSPECT, ReceiverOperation.PREPARE}),
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
        receiver = Path(__file__).with_name(definition.filename).read_bytes()
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).decode()
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
            "-F", "none",
            "-T",
            "-o", "BatchMode=yes",
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "ForwardAgent=no",
            "-o", "ClearAllForwardings=yes",
            f"{profile.username}@{ZEUS_HOST}",
            remote,
        ]
        return subprocess.run(
            argv,
            cwd=self._policy.repository_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self._policy.timeout,
            check=False,
        )
