"""Closed SSH execution for audited, repository-owned receiver programs."""

from __future__ import annotations

import base64
import json
from workflow_api.platform_io import os
import shlex
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from workflow_api.zeus_snapshot import ZEUS_HOST, ZeusProfile, ZeusSnapshotError


_GENERIC_STDOUT_LIMIT = 8 * 1024 * 1024
_GENERIC_STDERR_LIMIT = 256 * 1024


def _bounded_run(
    argv: list[str], **kwargs: object
) -> subprocess.CompletedProcess[bytes]:
    """Narrow injection seam backed by bounded streaming in production."""
    return PinnedSshRunner._run_bounded(argv, kwargs)


class ReceiverKind(Enum):
    REFINEMENT_TRANSITION = "refinement_transition"
    CONFIRMATION_PREPARATION = "confirmation_preparation"
    CONFIRMATION_SUBMISSION = "confirmation_submission"
    SENSITIVITY_PREPARATION = "sensitivity_preparation"
    SENSITIVITY_SUBMISSION = "sensitivity_submission"
    PRODUCTION_PREPARATION = "production_preparation"
    PRODUCTION_SUBMISSION = "production_submission"
    FINALIZATION = "finalization"
    MOT_3D_DISCOVERY_SUBMISSION = "mot_3d_discovery_submission"
    MOT_3D_DISCOVERY_TRANSITION = "mot_3d_discovery_transition"
    MOT_3D_PRELIMINARY_SUBMISSION = "mot_3d_preliminary_submission"
    MOT_3D_PRELIMINARY_TRANSITION = "mot_3d_preliminary_transition"
    MOT_3D_REFINEMENT_SUBMISSION = "mot_3d_refinement_submission"
    MOT_3D_REFINEMENT_TRANSITION = "mot_3d_refinement_transition"
    MOT_3D_CLOSURE_SUBMISSION = "mot_3d_closure_submission"
    MOT_3D_CLOSURE_TRANSITION = "mot_3d_closure_transition"
    MOT_3D_FINALIST_SUBMISSION = "mot_3d_finalist_submission"
    MOT_3D_FINALIST_TRANSITION = "mot_3d_finalist_transition"
    MOT_3D_FINAL_INPUT_SUBMISSION = "mot_3d_final_input_submission"
    MOT_3D_FINAL_VALIDATION_TRANSITION = "mot_3d_final_validation_transition"
    MOT_3D_FINAL_VALIDATION_SUBMISSION = "mot_3d_final_validation_submission"
    MOT_3D_FINAL_VALIDATION_COMPLETION = "mot_3d_final_validation_completion"
    REFINEMENT_SUBMISSION = "refinement_submission"
    SCREENING_PREPARATION = "screening_preparation"
    SCREENING_SUBMISSION = "screening_submission"
    SMOKE_SUBMISSION = "smoke_submission"
    SNAPSHOT = "snapshot"
    TRANSFER = "transfer"
    ZEEMAN_INDIVIDUAL = "zeeman_individual"
    MOT_2D_INDIVIDUAL = "mot_2d_individual"
    MOT_3D_INDIVIDUAL = "mot_3d_individual"


class ReceiverOperation(Enum):
    INSPECT = "inspect"
    PREPARE = "prepare"
    SUBMIT = "submit"
    STAGE = "stage"
    STATUS = "status"
    RETRIEVE = "retrieve"


class TransferOperation(Enum):
    INSPECT = "inspect"
    INPUTS = "inputs"
    CAMPAIGN = "campaign"


class PinnedSshProcessError(RuntimeError):
    """A process-launch OSError, distinct from receiver file read failures."""


@dataclass(frozen=True)
class _ReceiverDefinition:
    filename: str | None
    compile_name: str
    operations: frozenset[ReceiverOperation]
    wrap_process_oserror: bool
    ssh_arguments: tuple[str, ...] = (
        "-F",
        "none",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ClearAllForwardings=yes",
    )
    pinned_environment: bool = False
    explicit_process_safety: bool = False
    payload_before_receiver: bool = False
    embedded_smoke_receiver: bool = False
    embedded_snapshot_receiver: bool = False
    payload_stdin: bool = False


_RECEIVERS = {
    ReceiverKind.MOT_3D_FINAL_INPUT_SUBMISSION: _ReceiverDefinition(
        "mot_3d_final_input_submission_remote.py",
        "<mot-3d-final-input-submission>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.SUBMIT,
                ReceiverOperation.STATUS,
            }
        ),
        True,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
        ),
    ),
    ReceiverKind.MOT_3D_FINALIST_TRANSITION: _ReceiverDefinition(
        "mot_3d_finalist_transition_remote.py",
        "<mot-3d-finalist-transition>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.PREPARE,
                ReceiverOperation.STATUS,
                ReceiverOperation.RETRIEVE,
            }
        ),
        True,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
        ),
    ),
    ReceiverKind.MOT_3D_FINAL_VALIDATION_TRANSITION: _ReceiverDefinition(
        "mot_3d_final_validation_transition_remote.py",
        "<mot-3d-final-validation-transition>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.PREPARE,
                ReceiverOperation.STATUS,
                ReceiverOperation.RETRIEVE,
            }
        ),
        True,
        (
            "-F", "none", "-T", "-o", "BatchMode=yes", "-o",
            "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
            "-o", "StrictHostKeyChecking=yes", "-o", "ForwardAgent=no", "-o",
            "ClearAllForwardings=yes",
        ),
    ),
    ReceiverKind.MOT_3D_FINAL_VALIDATION_COMPLETION: _ReceiverDefinition(
        "mot_3d_final_validation_completion_remote.py",
        "<mot-3d-final-validation-completion>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.PREPARE,
                ReceiverOperation.STATUS,
                ReceiverOperation.RETRIEVE,
            }
        ),
        True,
        (
            "-F", "none", "-T", "-o", "BatchMode=yes", "-o",
            "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
            "-o", "StrictHostKeyChecking=yes", "-o", "ForwardAgent=no", "-o",
            "ClearAllForwardings=yes",
        ),
    ),
    ReceiverKind.MOT_3D_CLOSURE_TRANSITION: _ReceiverDefinition(
        "mot_3d_closure_transition_remote.py",
        "<mot-3d-closure-transition>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.PREPARE,
                ReceiverOperation.STATUS,
                ReceiverOperation.RETRIEVE,
            }
        ),
        True,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
        ),
        pinned_environment=True,
        explicit_process_safety=True,
        payload_before_receiver=True,
        payload_stdin=True,
    ),
    ReceiverKind.MOT_3D_REFINEMENT_TRANSITION: _ReceiverDefinition(
        "mot_3d_refinement_transition_remote.py",
        "<mot-3d-refinement-transition>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.PREPARE,
                ReceiverOperation.STATUS,
                ReceiverOperation.RETRIEVE,
            }
        ),
        True,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
        ),
        True,
        True,
        True,
        False,
        False,
        True,
    ),
    ReceiverKind.MOT_3D_PRELIMINARY_TRANSITION: _ReceiverDefinition(
        "mot_3d_preliminary_transition_remote.py",
        "<mot-3d-preliminary-transition>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.PREPARE,
                ReceiverOperation.STATUS,
                ReceiverOperation.RETRIEVE,
            }
        ),
        True,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
        ),
        True,
        True,
        True,
        False,
        False,
        True,
    ),
    ReceiverKind.MOT_3D_PRELIMINARY_SUBMISSION: _ReceiverDefinition(
        "mot_3d_preliminary_submission_remote.py",
        "<mot-3d-preliminary-submission>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.SUBMIT,
                ReceiverOperation.STATUS,
            }
        ),
        True,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
        ),
        True,
        True,
        True,
        False,
        False,
        True,
    ),
    ReceiverKind.MOT_3D_REFINEMENT_SUBMISSION: _ReceiverDefinition(
        "mot_3d_refinement_submission_remote.py",
        "<mot-3d-refinement-submission>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.SUBMIT,
                ReceiverOperation.STATUS,
            }
        ),
        True,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
        ),
        True,
        True,
        True,
        False,
        False,
        True,
    ),
    ReceiverKind.MOT_3D_CLOSURE_SUBMISSION: _ReceiverDefinition(
        "mot_3d_closure_submission_remote.py",
        "<mot-3d-closure-submission>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.SUBMIT,
                ReceiverOperation.STATUS,
            }
        ),
        True,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
        ),
        True,
        True,
        True,
        False,
        False,
        True,
    ),
    ReceiverKind.MOT_3D_FINALIST_SUBMISSION: _ReceiverDefinition(
        "mot_3d_finalist_submission_remote.py",
        "<mot-3d-finalist-submission>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.SUBMIT,
                ReceiverOperation.STATUS,
            }
        ),
        True,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
        ),
        True,
        True,
        True,
        False,
        False,
        True,
    ),
    ReceiverKind.MOT_3D_FINAL_VALIDATION_SUBMISSION: _ReceiverDefinition(
        "mot_3d_final_validation_submission_remote.py",
        "<mot-3d-final-validation-submission>",
        frozenset(
            {ReceiverOperation.INSPECT, ReceiverOperation.SUBMIT, ReceiverOperation.STATUS}
        ),
        True,
        (
            "-F", "none", "-T", "-o", "BatchMode=yes", "-o",
            "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
            "-o", "NumberOfPasswordPrompts=0", "-o", "ConnectTimeout=8", "-o",
            "ConnectionAttempts=1", "-o", "StrictHostKeyChecking=yes", "-o",
            "ForwardAgent=no", "-o", "ClearAllForwardings=yes", "-o",
            "PermitLocalCommand=no", "-o", "ProxyCommand=none", "-o",
            "ProxyJump=none", "-o", "KnownHostsCommand=none", "-o",
            "CanonicalizeHostname=no", "-o", "LogLevel=ERROR",
        ),
        True, True, True, False, False, True,
    ),
    ReceiverKind.MOT_3D_DISCOVERY_TRANSITION: _ReceiverDefinition(
        "mot_3d_discovery_transition_remote.py",
        "<mot-3d-discovery-transition>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.PREPARE,
                ReceiverOperation.STATUS,
                ReceiverOperation.RETRIEVE,
            }
        ),
        True,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
        ),
        True,
        True,
        True,
        False,
        False,
        True,
    ),
    ReceiverKind.MOT_3D_INDIVIDUAL: _ReceiverDefinition(
        "mot_3d_zeus_remote.py",
        "<mot-3d-individual>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.STAGE,
                ReceiverOperation.SUBMIT,
                ReceiverOperation.STATUS,
                ReceiverOperation.RETRIEVE,
            }
        ),
        True,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
        ),
        True,
        True,
        True,
        False,
        False,
        True,
    ),
    ReceiverKind.MOT_2D_INDIVIDUAL: _ReceiverDefinition(
        "mot_2d_zeus_remote.py",
        "<mot-2d-individual>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.STAGE,
                ReceiverOperation.SUBMIT,
                ReceiverOperation.STATUS,
                ReceiverOperation.RETRIEVE,
            }
        ),
        True,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
        ),
        True,
        True,
        True,
        False,
        False,
        True,
    ),
    ReceiverKind.ZEEMAN_INDIVIDUAL: _ReceiverDefinition(
        "zeeman_zeus_remote.py",
        "<zeeman-individual>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.STAGE,
                ReceiverOperation.SUBMIT,
                ReceiverOperation.STATUS,
                ReceiverOperation.RETRIEVE,
            }
        ),
        True,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
        ),
        True,
        True,
        True,
    ),
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
    ReceiverKind.CONFIRMATION_SUBMISSION: _ReceiverDefinition(
        "zeus_confirmation_submission_remote.py",
        "<confirmation-submit>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.SUBMIT,
                ReceiverOperation.STATUS,
            }
        ),
        True,
    ),
    ReceiverKind.SENSITIVITY_PREPARATION: _ReceiverDefinition(
        "zeus_sensitivity_remote.py",
        "<sensitivity>",
        frozenset({ReceiverOperation.INSPECT, ReceiverOperation.PREPARE}),
        True,
    ),
    ReceiverKind.SENSITIVITY_SUBMISSION: _ReceiverDefinition(
        "zeus_sensitivity_submission_remote.py",
        "<sensitivity-submit>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.SUBMIT,
                ReceiverOperation.STATUS,
            }
        ),
        True,
    ),
    ReceiverKind.PRODUCTION_SUBMISSION: _ReceiverDefinition(
        "zeus_production_submission_remote.py",
        "<production-submit>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.SUBMIT,
                ReceiverOperation.STATUS,
            }
        ),
        True,
    ),
    ReceiverKind.PRODUCTION_PREPARATION: _ReceiverDefinition(
        "zeus_production_remote.py",
        "<production>",
        frozenset({ReceiverOperation.INSPECT, ReceiverOperation.PREPARE}),
        True,
    ),
    ReceiverKind.FINALIZATION: _ReceiverDefinition(
        "zeus_finalization_remote.py",
        "<finalization>",
        frozenset({ReceiverOperation.INSPECT, ReceiverOperation.PREPARE}),
        True,
    ),
    ReceiverKind.MOT_3D_DISCOVERY_SUBMISSION: _ReceiverDefinition(
        "zeus_discovery_submission_remote.py",
        "<mot-3d-discovery-submit>",
        frozenset(
            {
                ReceiverOperation.INSPECT,
                ReceiverOperation.SUBMIT,
                ReceiverOperation.STATUS,
            }
        ),
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
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
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
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
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
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
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
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
        ),
        True,
        True,
        False,
        False,
        True,
    ),
    ReceiverKind.TRANSFER: _ReceiverDefinition(
        None,
        "<transfer>",
        frozenset(),
        False,
        (
            "-F",
            "none",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "KnownHostsCommand=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "LogLevel=ERROR",
        ),
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
    def confirmation_submission(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.CONFIRMATION_SUBMISSION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def sensitivity_preparation(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.SENSITIVITY_PREPARATION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def sensitivity_submission(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.SENSITIVITY_SUBMISSION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def production_submission(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.PRODUCTION_SUBMISSION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def production_preparation(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.PRODUCTION_PREPARATION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def finalization(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.FINALIZATION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def mot_3d_discovery_submission(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_DISCOVERY_SUBMISSION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def mot_3d_discovery_transition(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_DISCOVERY_TRANSITION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def mot_3d_preliminary_submission(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_PRELIMINARY_SUBMISSION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def mot_3d_preliminary_transition(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_PRELIMINARY_TRANSITION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def mot_3d_refinement_submission(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_REFINEMENT_SUBMISSION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def mot_3d_refinement_transition(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_REFINEMENT_TRANSITION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def mot_3d_closure_submission(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_CLOSURE_SUBMISSION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def mot_3d_closure_transition(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_CLOSURE_TRANSITION, repository_root, executable, timeout
        )

    @classmethod
    def mot_3d_finalist_submission(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_FINALIST_SUBMISSION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def mot_3d_final_validation_submission(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_FINAL_VALIDATION_SUBMISSION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def mot_3d_finalist_transition(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_FINALIST_TRANSITION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def mot_3d_final_input_submission(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_FINAL_INPUT_SUBMISSION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def mot_3d_final_validation_transition(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_FINAL_VALIDATION_TRANSITION,
            repository_root,
            executable,
            timeout,
        )

    @classmethod
    def mot_3d_final_validation_completion(
        cls, repository_root: Path, executable: Path, *, timeout: float
    ) -> "PinnedSshPolicy":
        return cls(
            ReceiverKind.MOT_3D_FINAL_VALIDATION_COMPLETION,
            repository_root,
            executable,
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

    @classmethod
    def transfer(
        cls,
        repository_root: Path,
        ssh_executable: Path,
        *,
        timeout: float,
    ) -> PinnedSshPolicy:
        return cls(
            ReceiverKind.TRANSFER,
            repository_root,
            ssh_executable,
            timeout,
        )

    @classmethod
    def zeeman_individual(
        cls, repository_root: Path, ssh_executable: Path, *, timeout: float
    ) -> PinnedSshPolicy:
        return cls(
            ReceiverKind.ZEEMAN_INDIVIDUAL,
            repository_root,
            ssh_executable,
            timeout,
        )

    @classmethod
    def mot_2d_individual(
        cls, repository_root: Path, executable: Path, *, timeout: float = 90
    ) -> "PinnedSshPolicy":
        return cls(ReceiverKind.MOT_2D_INDIVIDUAL, repository_root, executable, timeout)

    @classmethod
    def mot_3d_individual(
        cls, repository_root: Path, executable: Path, *, timeout: float = 90
    ) -> "PinnedSshPolicy":
        return cls(ReceiverKind.MOT_3D_INDIVIDUAL, repository_root, executable, timeout)


class PinnedSshRunner:
    """Run one closed receiver without accepting commands or SSH options."""

    def __init__(self, policy: PinnedSshPolicy):
        if (
            type(policy.receiver) is not ReceiverKind
            or policy.receiver not in _RECEIVERS
        ):
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
            validated_profile = ZeusProfile.parse(
                {
                    "username": profile.username,
                    "project_directory": profile.project_directory,
                }
            )
        except ValueError as error:
            raise ValueError("Invalid pinned SSH profile.") from error
        if validated_profile != profile:
            raise ValueError("Invalid pinned SSH profile.")
        definition = _RECEIVERS[self._policy.receiver]
        if (
            type(operation) is not ReceiverOperation
            or operation not in definition.operations
        ):
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

        if definition.payload_stdin:
            receiver = read_receiver()
            encoded = ""
        elif definition.payload_before_receiver:
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
            # Individual receivers parse four arguments after argv[0]. Keep the
            # encoded receiver as argv[0] when entering their Python bootstrap.
            argument_start = 1 if self._policy.receiver in {
                ReceiverKind.ZEEMAN_INDIVIDUAL,
                ReceiverKind.MOT_2D_INDIVIDUAL,
                ReceiverKind.MOT_3D_INDIVIDUAL,
            } else 2
            wrapper = (
                "import base64,sys;code=base64.urlsafe_b64decode(sys.argv[1]);"
                f"sys.argv=sys.argv[{argument_start}:];exec(compile(code,'"
                + definition.compile_name
                + "','exec'),{'__name__':'__main__'})"
            )
        interpreter = "python3"
        prefix = ""
        if self._policy.receiver in {ReceiverKind.MOT_2D_INDIVIDUAL, ReceiverKind.MOT_3D_INDIVIDUAL}:
            expected_project = profile.project_directory
            environment = "atomsmltr-ui-test" if expected_project.endswith("/ytterbium_lab_simulation_ui_test") else "atomsmltr"
            interpreter = f"/home/{profile.username}/venvs/{environment}/bin/python"
            prefix = f"cd -- {shlex.quote(expected_project)} && exec "
        remote = prefix + shlex.join(
            (
                interpreter,
                "-c",
                wrapper,
                script,
                operation.value,
                profile.username,
                profile.project_directory,
                "-" if definition.payload_stdin else encoded,
            )
        )
        argv = [
            str(self._policy.ssh_executable),
            *definition.ssh_arguments,
            f"{profile.username}@{ZEUS_HOST}",
            remote,
        ]
        kwargs: dict[str, object] = {
            "cwd": self._policy.repository_root,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "timeout": self._policy.timeout,
            "check": False,
        }
        if definition.payload_stdin:
            kwargs["input"] = json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode()
        else:
            kwargs["stdin"] = subprocess.DEVNULL
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
            return _bounded_run(argv, **kwargs)
        except OSError as error:
            if definition.wrap_process_oserror:
                raise PinnedSshProcessError from error
            raise

    @staticmethod
    def _run_bounded(
        argv: list[str], kwargs: Mapping[str, object]
    ) -> subprocess.CompletedProcess[bytes]:
        """Run SSH while retaining at most the reviewed response bounds."""
        input_bytes = kwargs.get("input")
        if input_bytes is not None and type(input_bytes) is not bytes:
            raise TypeError("Pinned SSH input must be bytes.")
        process = subprocess.Popen(
            argv,
            cwd=kwargs.get("cwd"),
            env=kwargs.get("env"),
            shell=bool(kwargs.get("shell", False)),
            close_fds=bool(kwargs.get("close_fds", True)),
            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        output = bytearray()
        errors = bytearray()
        exceeded = threading.Event()

        def terminate() -> None:
            try:
                process.kill()
            except OSError:
                pass

        def drain(stream: Any, limit: int, destination: bytearray) -> None:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    return
                remaining = limit + 1 - len(destination)
                if remaining > 0:
                    destination.extend(chunk[:remaining])
                if len(destination) > limit or len(chunk) > remaining:
                    exceeded.set()
                    terminate()
                    return

        def feed() -> None:
            if input_bytes is None:
                return
            try:
                process.stdin.write(input_bytes)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                return

        readers = (
            threading.Thread(
                target=drain,
                args=(process.stdout, _GENERIC_STDOUT_LIMIT, output),
                daemon=True,
            ),
            threading.Thread(
                target=drain,
                args=(process.stderr, _GENERIC_STDERR_LIMIT, errors),
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()
        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        timeout = float(kwargs["timeout"])
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate()
            process.wait()
            feeder.join(timeout=1)
            for reader in readers:
                reader.join(timeout=1)
            raise subprocess.TimeoutExpired(
                argv, timeout, output=bytes(output), stderr=bytes(errors)
            ) from None
        feeder.join(timeout=1)
        for reader in readers:
            reader.join(timeout=1)
        if (
            exceeded.is_set()
            or feeder.is_alive()
            or any(reader.is_alive() for reader in readers)
        ):
            terminate()
            process.wait()
            raise PinnedSshProcessError("Pinned SSH response exceeded its bound.")
        return subprocess.CompletedProcess(
            argv, returncode, bytes(output), bytes(errors)
        )

    def snapshot(self, profile: ZeusProfile) -> tuple[int, bytes, bytes]:
        """Run the one fixed bounded snapshot receiver."""
        if self._policy.receiver is not ReceiverKind.SNAPSHOT:
            raise ValueError("Unsupported pinned SSH snapshot receiver.")
        if type(profile) is not ZeusProfile:
            raise ValueError("Invalid pinned SSH profile.")
        try:
            validated_profile = ZeusProfile.parse(
                {
                    "username": profile.username,
                    "project_directory": profile.project_directory,
                }
            )
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

    def transfer(
        self,
        operation: TransferOperation,
        profile: ZeusProfile,
        paths: tuple[str, ...],
        expected_commit: str,
        payload: bytes,
    ) -> tuple[int, bytes, bytes]:
        """Run one fixed streaming transfer receiver operation."""
        if self._policy.receiver is not ReceiverKind.TRANSFER:
            raise ValueError("Unsupported pinned SSH transfer receiver.")
        if type(operation) is not TransferOperation:
            raise ValueError("Unsupported pinned SSH transfer operation.")
        if type(profile) is not ZeusProfile:
            raise ValueError("Invalid pinned SSH profile.")
        try:
            validated_profile = ZeusProfile.parse(
                {
                    "username": profile.username,
                    "project_directory": profile.project_directory,
                }
            )
        except ValueError as error:
            raise ValueError("Invalid pinned SSH profile.") from error
        if validated_profile != profile:
            raise ValueError("Invalid pinned SSH profile.")

        from workflow_api.zeus_transfer import (
            MAX_REMOTE_OUTPUT,
            MAX_TRANSFER_BYTES,
            _REMOTE_TRANSFER_SCRIPT,
            ZeusPreparationError,
        )

        if type(payload) is not bytes:
            raise ValueError("Invalid pinned SSH transfer payload.")
        if len(payload) > MAX_TRANSFER_BYTES:
            raise ZeusPreparationError("transfer_too_large")

        definition = _RECEIVERS[ReceiverKind.TRANSFER]
        encoded = base64.urlsafe_b64encode(
            json.dumps(paths, separators=(",", ":")).encode()
        ).decode("ascii")
        script = base64.urlsafe_b64encode(_REMOTE_TRANSFER_SCRIPT.encode()).decode(
            "ascii"
        )
        wrapper = (
            "import base64,sys;payload=sys.argv[1];sys.argv=sys.argv[1:];"
            "exec(base64.urlsafe_b64decode(payload).decode('utf-8'))"
        )
        command = shlex.join(
            (
                "python3",
                "-c",
                wrapper,
                script,
                operation.value,
                profile.username,
                profile.project_directory,
                encoded,
                expected_commit,
            )
        )
        arguments = [
            str(self._policy.ssh_executable),
            *definition.ssh_arguments,
            f"{profile.username}@{ZEUS_HOST}",
            command,
        ]
        environment = {
            "PATH": str(self._policy.ssh_executable.parent),
            "HOME": str(Path.home()),
            "LC_ALL": "C",
        }
        if os.environ.get("SSH_AUTH_SOCK"):
            environment["SSH_AUTH_SOCK"] = os.environ["SSH_AUTH_SOCK"]
        process = subprocess.Popen(
            arguments,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self._policy.repository_root,
            env=environment,
            shell=False,
            close_fds=True,
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

        def feed() -> None:
            try:
                if payload:
                    process.stdin.write(payload)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                return

        readers = [
            threading.Thread(
                target=drain,
                args=(process.stdout, MAX_REMOTE_OUTPUT, output),
                daemon=True,
            ),
            threading.Thread(
                target=drain,
                args=(process.stderr, 65536, errors),
                daemon=True,
            ),
        ]
        writer = threading.Thread(target=feed, daemon=True)
        for thread in readers:
            thread.start()
        writer.start()
        try:
            returncode = process.wait(timeout=self._policy.timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise ZeusPreparationError("zeus_timeout") from None
        writer.join(timeout=1)
        for reader in readers:
            reader.join(timeout=1)
        if (
            exceeded.is_set()
            or writer.is_alive()
            or any(reader.is_alive() for reader in readers)
        ):
            process.kill()
            raise ZeusPreparationError("remote_response_invalid")
        return returncode, bytes(output), bytes(errors)
