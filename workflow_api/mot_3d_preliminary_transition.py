"""Guarded local synchronization for Preliminary Check -> Refinement.

The remote receiver is the scientific authority.  This module binds an
explicit, session-owned preview to that authority, downloads its closed
160-file bundle, and publishes it locally with the campaign manifest last.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol

from workflow_api.discovery import build_registry
from workflow_api.mot_3d_discovery_transition import (
    _DIRECTORY_FLAGS,
    _atomic_json_at,
    _atomic_replace_at,
    _bounded_read_at,
    _open_directory_at,
    _open_parent_at,
    _publish_no_replace_at,
    _strict_json,
)
from workflow_api.mot_3d_preliminary_results import (
    FAMILIES,
    PRELIMINARY_RESULT_REASON_CODES,
    expected_paths,
)
from workflow_api.mot_3d_discovery_transition import Mot3DDiscoveryTransitionError
from workflow_api.mot_3d_stage_topology import PRELIMINARY_CHECK_TOPOLOGY, public_chain
from workflow_api.mot_3d_preliminary_submission import (
    CODE_FILES as SUBMISSION_CODE_FILES,
)
from workflow_api.mot_3d_preliminary_submission import FILES as SUBMISSION_FILES
from workflow_api.mot_3d_preliminary_submission import (
    Mot3DPreliminarySubmissionCoordinator,
)
from workflow_api.mot_3d_preliminary_transition_remote import (
    PRELIMINARY_CODE_PATHS as CODE_PATHS,
    PRELIMINARY_GENERATED_PATHS as GENERATED_PATHS,
)
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshProcessError,
    PinnedSshRunner,
    ReceiverOperation,
)
from workflow_api.verified_artifact_bundle import (
    MAX_CHUNKS,
    MAX_FILE_BYTES,
    MAX_REVIEWED_FILE_BYTES,
    MAX_TOTAL_BYTES,
    unpack_artifact_bundle,
)
from workflow_api.zeus_discovery_submission import canonical_digest
from workflow_api.zeus_snapshot import ZeusProfile

TTL = 300
CAPACITY = 32
EXPECTED_RESULT_FILES = 152
EXPECTED_TRANSFER_FILES = 160
HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ARRAY = re.compile(r"^\d+\[\]\.zeus-master$")
SCALAR = re.compile(r"^\d+\.zeus-master$")


class Mot3DPreliminaryTransitionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RemotePreliminaryTransitionState:
    lifecycle: str
    branch: str
    jobs: Mapping[str, Mapping[str, str]]
    completed_array_tasks: int
    completed_merge_jobs: int
    validation: str
    reason_code: str | None
    evidence_sha256: str | None
    receipt: Mapping[str, Any] | None
    bundle: Mapping[str, Any] | None
    chunk: Mapping[str, Any] | None
    winner_selection: Mapping[str, Any] | None = None


class PreliminaryTransitionTransport(Protocol):
    def inspect(self, **payload: object) -> RemotePreliminaryTransitionState: ...
    def status(self, **payload: object) -> RemotePreliminaryTransitionState: ...
    def prepare(self, **payload: object) -> RemotePreliminaryTransitionState: ...
    def retrieve(self, **payload: object) -> RemotePreliminaryTransitionState: ...


@dataclass(frozen=True)
class _Pending:
    session_id: str
    campaign_id: str
    profile: ZeusProfile
    relative: str
    commit: str
    submission_key: str
    identity: Mapping[str, Any]
    transition_key: str
    evidence_sha256: str
    nonce: str
    expires: float
    result: Mapping[str, object] | None = None
    terminal_error: str | None = None


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _matches(pattern, value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _read_relative(root_fd: int, relative: str) -> bytes:
    return _read_relative_bound(root_fd, relative, MAX_FILE_BYTES)


def _read_relative_bound(root_fd: int, relative: str, limit: int) -> bytes:
    path = PurePosixPath(relative)
    parent = _open_parent_at(root_fd, path.parts[:-1], create=False)
    try:
        return _bounded_read_at(parent, path.name, limit)
    finally:
        os.close(parent)


class Mot3DPreliminaryTransitionCoordinator:
    topology = PRELIMINARY_CHECK_TOPOLOGY
    sync_name = "preliminary_to_refinement"
    from_stage = "preliminary_check"
    to_stage = "refinement"
    prepared_lifecycle = "refinement_prepared"
    result_reason_codes = PRELIMINARY_RESULT_REASON_CODES
    public_stage_key = "preliminary"
    expected_result_files = EXPECTED_RESULT_FILES
    expected_transfer_files = EXPECTED_TRANSFER_FILES
    open_action = "open_refinement"
    created_selection_files = 2
    created_job_files = 4
    not_ready_error = "preliminary_not_ready"
    effects = {
        "synchronize_preliminary_check": True,
        "prepare_refinement": True,
        "submit_refinement": False,
        "start_simulation": False,
        "overwrite_existing": False,
    }
    bundle_max_total_bytes = MAX_TOTAL_BYTES
    bundle_max_file_bytes = MAX_FILE_BYTES
    expected_array_tasks = 6
    expected_merge_jobs = 2

    @classmethod
    def _public_chain(cls, jobs):
        return public_chain(jobs, topology=cls.topology)

    def __init__(
        self,
        repository_root: Path,
        ssh_executable: Path,
        git_executable: Path,
        *,
        clock=time.time,
        token_factory=None,
        transport_factory=None,
    ):
        self.root = repository_root.resolve(strict=True)
        self.ssh = ssh_executable.resolve(strict=True)
        self.git = git_executable.resolve(strict=True)
        self.clock = clock
        self.transport_factory = transport_factory or (
            lambda profile: PinnedSshMot3DPreliminaryTransitionTransport(
                self.root, self.ssh, profile
            )
        )
        self._previews = PreviewRegistry[_Pending](
            clock=clock, token_factory=token_factory
        )
        self._confirm_lock = threading.Lock()

    def _plan(self, request: Mapping[str, object]):
        try:
            base = Mot3DPreliminarySubmissionCoordinator(
                self.root, self.ssh, self.git, transport_factory=lambda _p: None
            )._plan(request)
        except Exception as exc:
            try:
                return self._recovery_plan(request)
            except Exception:
                raise Mot3DPreliminaryTransitionError(
                    getattr(exc, "code", "preliminary_preparation_invalid")
                ) from exc
        (
            campaign_id,
            profile,
            campaign,
            manifest,
            commit,
            submission_identity,
            submission_key,
            relative,
        ) = base
        campaign_fd = root_fd = -1
        try:
            campaign_fd = os.open(campaign, _DIRECTORY_FLAGS)
            root_fd = os.open(self.root, _DIRECTORY_FLAGS)
            source_files = {
                name: _sha(_read_relative(campaign_fd, name))
                for name in SUBMISSION_FILES
            }
            if set(source_files) != {
                "campaign.json",
                *(f"selection/discovery/{family}.json" for family in FAMILIES),
                *(
                    f"jobs/preliminary_check/{family}_{kind}.pbs"
                    for family in FAMILIES
                    for kind in ("array", "merge")
                ),
            }:
                raise ValueError("source registry mismatch")
            sync = _strict_json(
                _read_relative(
                    campaign_fd, ".mot_ui/sync/discovery_to_preliminary.json"
                )
            )
            identity = {
                "source_files": source_files,
                "code_files": {
                    name: _sha(_read_relative(root_fd, name)) for name in CODE_PATHS
                },
                "stage1_receipt_sha256": sync["remote_receipt_sha256"],
                "stage1_bundle_sha256": sync["bundle_sha256"],
            }
            if any(not _matches(HEX64, v) for v in identity["source_files"].values()):
                raise ValueError
            if any(not _matches(HEX64, v) for v in identity["code_files"].values()):
                raise ValueError
            if not _matches(HEX64, identity["stage1_receipt_sha256"]) or not _matches(
                HEX64, identity["stage1_bundle_sha256"]
            ):
                raise ValueError
        except Exception as exc:
            raise Mot3DPreliminaryTransitionError(
                "preliminary_preparation_invalid"
            ) from exc
        finally:
            if root_fd >= 0:
                os.close(root_fd)
            if campaign_fd >= 0:
                os.close(campaign_fd)
        campaign_fd = os.open(campaign, _DIRECTORY_FLAGS)
        try:
            parsed = {
                family: _strict_json(
                    _read_relative(campaign_fd, f"selection/discovery/{family}.json")
                )
                for family in FAMILIES
            }
            transfer_paths = (
                frozenset(expected_paths(parsed))
                | {"preliminary_check_submission.json"}
                | GENERATED_PATHS
            )
        finally:
            os.close(campaign_fd)
        if len(transfer_paths) != self.expected_transfer_files:
            raise Mot3DPreliminaryTransitionError("preliminary_preparation_invalid")
        transition_key = canonical_digest(
            {
                "campaign": relative,
                "commit": commit,
                "submission_key": submission_key,
                "identity": identity,
            }
        )
        return (
            campaign_id,
            profile,
            campaign,
            manifest,
            commit,
            identity,
            submission_key,
            transition_key,
            relative,
            transfer_paths,
        )

    def _recovery_plan(self, request: Mapping[str, object]):
        """Recover only a previously authenticated local synchronization intent."""
        if (
            not isinstance(request, Mapping)
            or set(request) != {"campaign_id", "username", "project_directory"}
            or not isinstance(request.get("campaign_id"), str)
        ):
            raise ValueError
        profile = ZeusProfile.parse(
            {
                "username": request["username"],
                "project_directory": request["project_directory"],
            }
        )
        entry = build_registry(self.root).get(request["campaign_id"])
        if entry is None or entry.family != "mot_3d":
            raise ValueError
        campaign = entry.manifest.parent
        campaign_fd = mot_fd = sync_fd = -1
        try:
            campaign_fd = os.open(campaign, _DIRECTORY_FLAGS)
            mot_fd = _open_directory_at(campaign_fd, ".mot_ui", create=False)
            sync_fd = _open_directory_at(mot_fd, "sync", create=False)
            try:
                recovery_raw = _bounded_read_at(
                    sync_fd, f"{self.sync_name}.pending.json", 256 * 1024
                )
            except FileNotFoundError:
                recovery_raw = _bounded_read_at(
                    sync_fd, f"{self.sync_name}.identity.json", 256 * 1024
                )
            pending = _strict_json(recovery_raw)
            required = {
                "status",
                "transition_key",
                "remote_receipt_sha256",
                "bundle",
                "campaign_id",
                "relative",
                "commit",
                "submission_key",
                "identity",
                "evidence_sha256",
                "created_unix_s",
            }
            if (
                not isinstance(pending, dict)
                or set(pending) != required
                or pending.get("status") != "synchronizing"
                or pending.get("campaign_id") != request["campaign_id"]
                or pending.get("relative") != campaign.relative_to(self.root).as_posix()
                or type(pending.get("created_unix_s")) is not int
            ):
                raise ValueError
            commit = pending["commit"]
            identity = pending["identity"]
            submission_key = pending["submission_key"]
            transition_key = pending["transition_key"]
            if (
                not _matches(HEX40, commit)
                or not _matches(HEX64, submission_key)
                or not _matches(HEX64, transition_key)
                or transition_key
                != canonical_digest(
                    {
                        "campaign": pending["relative"],
                        "commit": commit,
                        "submission_key": submission_key,
                        "identity": identity,
                    }
                )
            ):
                raise ValueError
            manifest = _strict_json(
                _bounded_read_at(campaign_fd, "campaign.json", MAX_FILE_BYTES)
            )
            transfer = self._expected_paths(campaign_fd)
            if len(transfer) != self.expected_transfer_files:
                raise ValueError
            check = subprocess.run(
                [self.git, "-C", self.root, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            dirty = subprocess.run(
                [
                    self.git,
                    "-C",
                    self.root,
                    "status",
                    "--porcelain",
                    "--untracked-files=no",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if (
                check.returncode
                or check.stderr
                or check.stdout.strip() != commit
                or dirty.returncode
                or dirty.stderr
                or dirty.stdout
            ):
                raise ValueError
            return (
                str(request["campaign_id"]),
                profile,
                campaign,
                manifest,
                commit,
                identity,
                submission_key,
                transition_key,
                pending["relative"],
                transfer,
            )
        finally:
            if sync_fd >= 0:
                os.close(sync_fd)
            if mot_fd >= 0:
                os.close(mot_fd)
            if campaign_fd >= 0:
                os.close(campaign_fd)

    @staticmethod
    def _payload(plan):
        return {
            "campaign": plan[8],
            "commit": plan[4],
            "submission_key": plan[6],
            "transition_key": plan[7],
            "identity": plan[5],
        }

    @classmethod
    def _validate_state(
        cls, state: RemotePreliminaryTransitionState, *, allow_chunk=False
    ) -> None:
        allowed = {
            "queued",
            "running",
            "held",
            "completed_failed",
            "status_unknown",
            "completed_success_unvalidated",
            "ready_to_advance",
            "outcome_unknown",
            cls.prepared_lifecycle,
        }
        if (
            state.lifecycle not in allowed
            or not isinstance(state.branch, str)
            or not state.branch
            or len(state.branch) > 256
            or not state.branch.isprintable()
        ):
            raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        if not isinstance(state.jobs, Mapping) or set(state.jobs) != set(FAMILIES):
            raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        for family in FAMILIES:
            row = state.jobs[family]
            if (
                not isinstance(row, Mapping)
                or set(row) != {"array", "merge"}
                or not _matches(ARRAY, row["array"])
                or not _matches(SCALAR, row["merge"])
            ):
                raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        if (
            type(state.completed_array_tasks) is not int
            or not 0 <= state.completed_array_tasks <= cls.expected_array_tasks
            or type(state.completed_merge_jobs) is not int
            or not 0 <= state.completed_merge_jobs <= cls.expected_merge_jobs
        ):
            raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        if state.validation not in {"not_started", "valid", "scientifically_invalid"}:
            raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        prepared = state.lifecycle == cls.prepared_lifecycle
        if prepared != (state.receipt is not None and state.bundle is not None):
            raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        if not prepared and (
            state.receipt is not None
            or state.bundle is not None
            or state.chunk is not None
        ):
            raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        if state.chunk is not None and (not prepared or not allow_chunk):
            raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        if state.evidence_sha256 is not None and not _matches(
            HEX64, state.evidence_sha256
        ):
            raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        terminal = {
            "completed_success_unvalidated",
            "ready_to_advance",
            "outcome_unknown",
            cls.prepared_lifecycle,
        }
        if state.lifecycle in terminal and (
            state.completed_array_tasks,
            state.completed_merge_jobs,
        ) != (cls.expected_array_tasks, cls.expected_merge_jobs):
            raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        if state.validation == "valid":
            if (
                state.lifecycle
                not in {"ready_to_advance", "outcome_unknown", cls.prepared_lifecycle}
                or state.reason_code is not None
                or not _matches(HEX64, state.evidence_sha256)
            ):
                raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        elif state.validation == "scientifically_invalid":
            if (
                state.lifecycle != "completed_success_unvalidated"
                or state.reason_code not in cls.result_reason_codes
                or state.evidence_sha256 is not None
            ):
                raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        elif (
            state.reason_code is not None
            or state.evidence_sha256 is not None
            or state.lifecycle
            in {"ready_to_advance", "outcome_unknown", cls.prepared_lifecycle}
        ):
            raise Mot3DPreliminaryTransitionError("remote_response_invalid")

    @classmethod
    def _validate_prepared(cls, state, plan):
        bundle, receipt = state.bundle, state.receipt
        if (
            not isinstance(bundle, Mapping)
            or set(bundle)
            != {
                "version",
                "file_count",
                "uncompressed_bytes",
                "bundle_sha256",
                "chunks",
            }
            or bundle.get("version") != 1
            or bundle.get("file_count") != cls.expected_transfer_files
            or type(bundle.get("uncompressed_bytes")) is not int
            or not cls.expected_transfer_files
            <= bundle["uncompressed_bytes"]
            <= cls.bundle_max_total_bytes
            or not _matches(HEX64, bundle.get("bundle_sha256"))
            or not isinstance(bundle.get("chunks"), list)
            or not 1
            <= len(bundle["chunks"])
            <= cls.bundle_max_total_bytes // (4 * 1024 * 1024)
        ):
            raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        for index, row in enumerate(bundle["chunks"]):
            if (
                not isinstance(row, Mapping)
                or set(row) != {"index", "size", "sha256"}
                or type(row["index"]) is not int
                or row["index"] != index
                or type(row["size"]) is not int
                or not 0 < row["size"] <= 4 * 1024 * 1024
                or not _matches(HEX64, row["sha256"])
            ):
                raise Mot3DPreliminaryTransitionError("remote_response_invalid")
        keys = {
            "version",
            "status",
            "nonce",
            "transition_key",
            "commit",
            "submission_key",
            "identity_sha256",
            "old_campaign_sha256",
            "new_campaign_sha256",
            "evidence_sha256",
            "files",
            "bundle",
            "completed_unix_s",
        }
        if (
            not isinstance(receipt, Mapping)
            or set(receipt) != keys
            or receipt.get("version") != 1
            or type(receipt.get("version")) is not int
            or receipt.get("status") != cls.prepared_lifecycle
            or not _matches(HEX32, receipt.get("nonce"))
            or receipt.get("transition_key") != plan[7]
            or receipt.get("commit") != plan[4]
            or receipt.get("submission_key") != plan[6]
            or receipt.get("identity_sha256") != canonical_digest(plan[5])
            or receipt.get("bundle") != bundle
            or receipt.get("evidence_sha256") != state.evidence_sha256
            or receipt.get("old_campaign_sha256")
            != plan[5]["source_files"]["campaign.json"]
            or not isinstance(receipt.get("files"), Mapping)
            or set(receipt["files"]) != plan[9]
            or receipt.get("new_campaign_sha256")
            != receipt["files"].get("campaign.json")
            or any(not _matches(HEX64, v) for v in receipt["files"].values())
            or type(receipt.get("completed_unix_s")) is not int
            or not 0 <= receipt["completed_unix_s"] <= 253402300799
        ):
            raise Mot3DPreliminaryTransitionError("transition_outcome_unknown")

    def _inspect(self, request, operation="inspect"):
        plan = self._plan(request)
        transport = self.transport_factory(plan[1])
        state = getattr(transport, operation)(**self._payload(plan))
        self._validate_state(state)
        if state.lifecycle == self.prepared_lifecycle:
            self._validate_prepared(state, plan)
        return plan, transport, state

    def status(self, request):
        plan, _, state = self._inspect(request, "status")
        receipt_sha = (
            self._verify_local_snapshot(plan[2], state)
            if state.lifecycle == self.prepared_lifecycle
            else None
        )
        synchronized = receipt_sha is not None
        public = self.prepared_lifecycle if synchronized else state.lifecycle
        next_action = (
            self.open_action
            if synchronized
            else (
                "synchronize_results"
                if state.lifecycle == self.prepared_lifecycle
                else (
                    "review_transition"
                    if state.lifecycle
                    in {"ready_to_advance", "completed_success_unvalidated"}
                    and state.validation != "scientifically_invalid"
                    else (
                        "inspect_zeus"
                        if state.lifecycle
                        in {
                            "held",
                            "completed_failed",
                            "status_unknown",
                            "outcome_unknown",
                        }
                        or state.validation == "scientifically_invalid"
                        else "wait"
                    )
                )
            )
        )
        return {
            "source": "zeus",
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "campaign": {
                "id": plan[0],
                "name": plan[3]["name"],
                "stage": self.to_stage if synchronized else self.from_stage,
            },
            self.public_stage_key: {
                "status": public,
                "chain": self._public_chain(state.jobs),
            },
            "scheduler": {
                "completed_array_tasks": state.completed_array_tasks,
                "expected_array_tasks": self.expected_array_tasks,
                "completed_merge_jobs": state.completed_merge_jobs,
                "expected_merge_jobs": self.expected_merge_jobs,
            },
            "validation": {
                "status": state.validation,
                "result_artifacts": (
                    self.expected_result_files if state.validation == "valid" else 0
                ),
                "expected_result_artifacts": self.expected_result_files,
                "reason_code": state.reason_code,
            },
            "transition": {
                "status": (
                    self.prepared_lifecycle
                    if state.lifecycle == self.prepared_lifecycle
                    else "not_prepared"
                )
            },
            "next_action": next_action,
            "local_sync": {
                "status": "synchronized" if synchronized else "not_synchronized",
                "receipt_sha256": receipt_sha,
            },
        }

    def preview(self, request, *, session_id: str):
        plan, _, state = self._inspect(request)
        if (
            state.lifecycle not in {"ready_to_advance", self.prepared_lifecycle}
            or state.validation != "valid"
            or not state.evidence_sha256
        ):
            raise Mot3DPreliminaryTransitionError(self.not_ready_error)
        expires = self.clock() + TTL
        pending = _Pending(
            session_id,
            plan[0],
            plan[1],
            plan[8],
            plan[4],
            plan[6],
            plan[5],
            plan[7],
            state.evidence_sha256,
            state.receipt["nonce"] if state.receipt else secrets.token_hex(16),
            expires,
        )
        try:
            token = self._previews.add(pending, expires_at=expires, capacity=CAPACITY)
        except OverflowError as exc:
            raise Mot3DPreliminaryTransitionError("too_many_pending_previews") from exc
        result = {
            "preview_token": token,
            "expires_in_seconds": TTL,
            "campaign": {"id": plan[0], "name": plan[3]["name"], "git_commit": plan[4]},
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            self.public_stage_key: {
                "result_artifacts": self.expected_result_files,
                "expected_result_artifacts": self.expected_result_files,
                "families": list(FAMILIES),
                "evidence_sha256": state.evidence_sha256,
            },
            "artifacts": {
                "synchronize": {
                    "result_files": self.expected_result_files,
                    "submission_receipts": 1,
                },
                "create": {
                    "selection_files": self.created_selection_files,
                    "job_files": self.created_job_files,
                },
                "update": ["campaign.json"],
                "transfer_files": self.expected_transfer_files,
            },
            "effects": dict(self.effects),
        }
        result.update(self._preview_extension(state))
        return result

    def _preview_extension(self, state: RemotePreliminaryTransitionState):
        return {}

    def confirm(self, request, *, session_id: str):
        if (
            not isinstance(request, Mapping)
            or set(request) != {"preview_token"}
            or not isinstance(request.get("preview_token"), str)
        ):
            raise Mot3DPreliminaryTransitionError("request_invalid")
        token = request["preview_token"]
        with self._confirm_lock:
            record = self._previews.get(token)
            pending = record.value if record else None
            if pending is None or not secrets.compare_digest(
                pending.session_id, session_id
            ):
                raise Mot3DPreliminaryTransitionError("confirmation_invalid")
            if pending.result is not None:
                return dict(pending.result)
            if pending.terminal_error:
                raise Mot3DPreliminaryTransitionError(pending.terminal_error)
            if self.clock() > pending.expires:
                raise Mot3DPreliminaryTransitionError("confirmation_expired")
            again = {
                "campaign_id": pending.campaign_id,
                "username": pending.profile.username,
                "project_directory": pending.profile.project_directory,
            }
            plan, transport, state = self._inspect(again)
            if (
                state.lifecycle not in {"ready_to_advance", self.prepared_lifecycle}
                or state.validation != "valid"
                or (plan[4], plan[6], plan[5], plan[7], state.evidence_sha256)
                != (
                    pending.commit,
                    pending.submission_key,
                    pending.identity,
                    pending.transition_key,
                    pending.evidence_sha256,
                )
            ):
                raise Mot3DPreliminaryTransitionError(
                    "local_or_remote_evidence_changed"
                )
            prepared = state
            if state.lifecycle != self.prepared_lifecycle:
                try:
                    prepared = transport.prepare(
                        **(self._payload(plan) | {"nonce": pending.nonce})
                    )
                except Exception as exc:
                    code = getattr(exc, "code", "transition_outcome_unknown")
                    self._previews.replace(token, replace(pending, terminal_error=code))
                    raise
                self._validate_state(prepared)
                self._validate_prepared(prepared, plan)
            if prepared.receipt["nonce"] != pending.nonce:
                raise Mot3DPreliminaryTransitionError("transition_outcome_unknown")
            try:
                receipt_sha = self._synchronize(plan, transport, prepared)
            except Exception as exc:
                self._previews.replace(
                    token, replace(pending, terminal_error="local_sync_outcome_unknown")
                )
                if isinstance(exc, Mot3DPreliminaryTransitionError):
                    raise
                raise Mot3DPreliminaryTransitionError(
                    "local_sync_outcome_unknown"
                ) from exc
            result = {
                "status": self.prepared_lifecycle,
                "campaign_id": pending.campaign_id,
                "stage": self.to_stage,
                "artifacts": {
                    "synchronized": self.expected_result_files + 1,
                    "created": self.expected_transfer_files
                    - self.expected_result_files
                    - 2,
                    "updated": 1,
                    "bundle_sha256": prepared.bundle["bundle_sha256"],
                },
                "submitted_to_zeus": False,
                "simulation_started": False,
                "local_sync": {"status": "synchronized", "receipt_sha256": receipt_sha},
            }
            self._previews.replace(token, replace(pending, result=result))
            return result

    def _expected_paths(self, campaign_fd: int) -> frozenset[str]:
        selections = {
            family: _strict_json(
                _read_relative(campaign_fd, f"selection/discovery/{family}.json")
            )
            for family in FAMILIES
        }
        return (
            frozenset(expected_paths(selections))
            | {"preliminary_check_submission.json"}
            | GENERATED_PATHS
        )

    def _bundle_to_stage(self, state: RemotePreliminaryTransitionState) -> str:
        return self.to_stage

    def _synchronize(self, plan, transport, state) -> str:
        campaign_fd = mot_fd = sync_fd = lock_fd = -1
        receipt_digest = canonical_digest(state.receipt)
        identity = {
            "status": "synchronizing",
            "transition_key": plan[7],
            "remote_receipt_sha256": receipt_digest,
            "bundle": state.bundle,
            "campaign_id": plan[0],
            "relative": plan[8],
            "commit": plan[4],
            "submission_key": plan[6],
            "identity": plan[5],
            "evidence_sha256": state.evidence_sha256,
        }
        try:
            campaign_fd = os.open(plan[2], _DIRECTORY_FLAGS)
            expected = plan[9]
            if len(expected) != self.expected_transfer_files:
                raise Mot3DPreliminaryTransitionError("local_sync_conflict")
            mot_fd = _open_directory_at(campaign_fd, ".mot_ui", create=True)
            sync_fd = _open_directory_at(mot_fd, "sync", create=True)
            lock_fd = os.open(
                f"{self.sync_name}.lock",
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=sync_fd,
            )
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                final_raw = _bounded_read_at(
                    sync_fd, f"{self.sync_name}.json", 256 * 1024
                )
            except FileNotFoundError:
                final_raw = None
            if final_raw is not None:
                if not self._verify_local_at(campaign_fd, state, final_raw, expected):
                    raise Mot3DPreliminaryTransitionError("local_sync_conflict")
                try:
                    pending_raw = _bounded_read_at(
                        sync_fd,
                        f"{self.sync_name}.pending.json",
                        256 * 1024,
                    )
                except FileNotFoundError:
                    pending_raw = None
                if pending_raw is not None:
                    current = _strict_json(pending_raw)
                    if (
                        not isinstance(current, dict)
                        or set(current) != {*identity, "created_unix_s"}
                        or {key: current.get(key) for key in identity} != identity
                        or type(current.get("created_unix_s")) is not int
                    ):
                        raise Mot3DPreliminaryTransitionError("local_sync_conflict")
                    os.unlink(
                        f"{self.sync_name}.pending.json",
                        dir_fd=sync_fd,
                    )
                    os.fsync(sync_fd)
                return _sha(final_raw)
            intent = {**identity, "created_unix_s": int(self.clock())}
            try:
                pending_raw = _bounded_read_at(
                    sync_fd, f"{self.sync_name}.pending.json", 256 * 1024
                )
            except FileNotFoundError:
                _atomic_json_at(
                    sync_fd,
                    f"{self.sync_name}.pending.json",
                    intent,
                    replace=False,
                )
            else:
                current = _strict_json(pending_raw)
                if (
                    not isinstance(current, dict)
                    or {k: current.get(k) for k in identity} != identity
                    or type(current.get("created_unix_s")) is not int
                ):
                    raise Mot3DPreliminaryTransitionError("local_sync_conflict")
            # Preserve the authenticated pre-transition identity across process
            # restart even after the transient intent is removed.
            _atomic_json_at(
                sync_fd,
                f"{self.sync_name}.identity.json",
                intent,
                replace=False,
            )
            chunks = []
            for row in state.bundle["chunks"]:
                remote = transport.retrieve(
                    **(
                        self._payload(plan)
                        | {
                            "bundle_sha256": state.bundle["bundle_sha256"],
                            "chunk_index": row["index"],
                        }
                    )
                )
                self._validate_state(remote, allow_chunk=True)
                chunk = remote.chunk
                if (
                    not isinstance(chunk, Mapping)
                    or set(chunk) != {"index", "sha256", "content"}
                    or chunk.get("index") != row["index"]
                    or chunk.get("sha256") != row["sha256"]
                ):
                    raise Mot3DPreliminaryTransitionError("remote_response_invalid")
                try:
                    raw = base64.b64decode(chunk["content"], validate=True)
                except Exception as exc:
                    raise Mot3DPreliminaryTransitionError(
                        "remote_response_invalid"
                    ) from exc
                if len(raw) != row["size"] or _sha(raw) != row["sha256"]:
                    raise Mot3DPreliminaryTransitionError("remote_response_invalid")
                chunks.append(raw)
            packed = b"".join(chunks)
            try:
                files = unpack_artifact_bundle(
                    packed,
                    state.bundle,
                    campaign=plan[2].name,
                    commit=plan[4],
                    from_stage=self.from_stage,
                    to_stage=self._bundle_to_stage(state),
                    expected_paths=expected,
                    max_total_bytes=self.bundle_max_total_bytes,
                    max_file_bytes=self.bundle_max_file_bytes,
                )
            except Exception as exc:
                raise Mot3DPreliminaryTransitionError(
                    "remote_response_invalid"
                ) from exc
            manifest = files.pop("campaign.json")
            current = _bounded_read_at(campaign_fd, "campaign.json", MAX_FILE_BYTES)
            old_hash = plan[5]["source_files"]["campaign.json"]
            new_hash = _sha(manifest)
            if _sha(current) == old_hash:
                for name, data in files.items():
                    path = PurePosixPath(name)
                    parent = _open_parent_at(campaign_fd, path.parts[:-1], create=True)
                    try:
                        _publish_no_replace_at(parent, path.name, data)
                    finally:
                        os.close(parent)
                if (
                    _bounded_read_at(campaign_fd, "campaign.json", MAX_FILE_BYTES)
                    != current
                ):
                    raise Mot3DPreliminaryTransitionError("local_sync_conflict")
                _atomic_replace_at(campaign_fd, "campaign.json", manifest)
            elif _sha(current) == new_hash:
                for name, data in files.items():
                    path = PurePosixPath(name)
                    parent = _open_parent_at(campaign_fd, path.parts[:-1], create=False)
                    try:
                        if (
                            _bounded_read_at(
                                parent, path.name, self.bundle_max_file_bytes
                            )
                            != data
                        ):
                            raise Mot3DPreliminaryTransitionError("local_sync_conflict")
                    finally:
                        os.close(parent)
            else:
                raise Mot3DPreliminaryTransitionError("local_sync_conflict")
            hashes = {
                name: _sha(data)
                for name, data in {**files, "campaign.json": manifest}.items()
            }
            complete = {
                "status": "synchronized",
                "transition_key": plan[7],
                "remote_receipt_sha256": receipt_digest,
                "bundle_sha256": state.bundle["bundle_sha256"],
                "files": hashes,
                "completed_unix_s": int(self.clock()),
            }
            raw = (
                json.dumps(
                    complete,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode()
                + b"\n"
            )
            if not self._verify_local_at(campaign_fd, state, raw, expected):
                raise Mot3DPreliminaryTransitionError("local_sync_conflict")
            _atomic_json_at(sync_fd, f"{self.sync_name}.json", complete, replace=False)
            os.unlink(f"{self.sync_name}.pending.json", dir_fd=sync_fd)
            os.fsync(sync_fd)
            final = _bounded_read_at(sync_fd, f"{self.sync_name}.json", 256 * 1024)
            if not self._verify_local_at(campaign_fd, state, final, expected):
                raise Mot3DPreliminaryTransitionError("local_sync_conflict")
            return _sha(final)
        except Mot3DDiscoveryTransitionError as exc:
            raise Mot3DPreliminaryTransitionError(exc.code) from exc
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise Mot3DPreliminaryTransitionError("local_sync_conflict") from exc
        finally:
            if lock_fd >= 0:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)
            if sync_fd >= 0:
                os.close(sync_fd)
            if mot_fd >= 0:
                os.close(mot_fd)
            if campaign_fd >= 0:
                os.close(campaign_fd)

    def _verify_local_snapshot(self, campaign: Path, state) -> str | None:
        fd = -1
        try:
            fd = os.open(campaign, _DIRECTORY_FLAGS)
            expected = self._expected_paths(fd)
            mot = _open_directory_at(fd, ".mot_ui", create=False)
            sync = _open_directory_at(mot, "sync", create=False)
            try:
                raw = _bounded_read_at(sync, f"{self.sync_name}.json", 256 * 1024)
            finally:
                os.close(sync)
                os.close(mot)
            return (
                _sha(raw) if self._verify_local_at(fd, state, raw, expected) else None
            )
        except Exception:
            return None
        finally:
            if fd >= 0:
                os.close(fd)

    @classmethod
    def _verify_local_at(
        cls, campaign_fd: int, state, raw: bytes, expected: frozenset[str]
    ) -> bool:
        try:
            receipt = _strict_json(raw)
            if (
                not isinstance(receipt, dict)
                or set(receipt)
                != {
                    "status",
                    "transition_key",
                    "remote_receipt_sha256",
                    "bundle_sha256",
                    "files",
                    "completed_unix_s",
                }
                or receipt.get("status") != "synchronized"
                or receipt.get("transition_key") != state.receipt.get("transition_key")
                or receipt.get("remote_receipt_sha256")
                != canonical_digest(state.receipt)
                or receipt.get("bundle_sha256") != state.bundle.get("bundle_sha256")
                or type(receipt.get("completed_unix_s")) is not int
                or not 0 <= receipt["completed_unix_s"] <= 253402300799
                or not isinstance(receipt.get("files"), dict)
                or set(receipt["files"]) != expected
            ):
                return False
            for name, digest in receipt["files"].items():
                if (
                    not _matches(HEX64, digest)
                    or _sha(
                        _read_relative_bound(
                            campaign_fd, name, cls.bundle_max_file_bytes
                        )
                    )
                    != digest
                ):
                    return False
            return True
        except Exception:
            return False


class PinnedSshMot3DPreliminaryTransitionTransport:
    """Strict adapter around the repository-pinned Stage-3 receiver."""

    policy_factory = staticmethod(PinnedSshPolicy.mot_3d_preliminary_transition)
    error_type = Mot3DPreliminaryTransitionError
    error_prefix = "preliminary_transition"

    def __init__(self, root: Path, ssh: Path, profile: ZeusProfile, *, timeout=90):
        self.runner = PinnedSshRunner(self.policy_factory(root, ssh, timeout=timeout))
        self.profile = profile

    def _call(self, operation: str, payload: Mapping[str, object]):
        selected = {
            "inspect": ReceiverOperation.INSPECT,
            "status": ReceiverOperation.STATUS,
            "prepare": ReceiverOperation.PREPARE,
            "retrieve": ReceiverOperation.RETRIEVE,
        }.get(operation)
        if selected is None:
            raise self.error_type("remote_response_invalid")
        try:
            result = self.runner.run(selected, self.profile, payload)
        except subprocess.TimeoutExpired:
            raise self.error_type(
                "transition_outcome_unknown"
                if operation == "prepare"
                else "zeus_timeout"
            ) from None
        except PinnedSshProcessError as exc:
            raise self.error_type("zeus_unavailable") from exc
        if result.returncode or result.stderr:
            raise self.error_type(
                "transition_outcome_unknown"
                if operation == "prepare"
                else "remote_response_invalid"
            )
        try:
            value = json.loads(result.stdout)
        except Exception as exc:
            raise self.error_type("remote_response_invalid") from exc
        if isinstance(value, dict) and set(value) == {"error"}:
            code = value["error"]
            allowed = {
                "invalid_request",
                "remote_checkout_mismatch",
                f"{self.error_prefix}_conflict",
                f"{self.error_prefix}_busy",
                f"{self.error_prefix}_outcome_unknown",
                f"{self.error_prefix}_not_prepared",
            }
            raise self.error_type(
                code
                if isinstance(code, str) and code in allowed
                else "remote_response_invalid"
            )
        keys = {
            "lifecycle",
            "branch",
            "jobs",
            "completed_array_tasks",
            "completed_merge_jobs",
            "validation",
            "reason_code",
            "evidence_sha256",
            "receipt",
            "bundle",
            "chunk",
            "winner_selection",
        }
        if not isinstance(value, dict) or set(value) != keys:
            raise self.error_type("remote_response_invalid")
        return RemotePreliminaryTransitionState(
            value["lifecycle"],
            value["branch"],
            value["jobs"],
            value["completed_array_tasks"],
            value["completed_merge_jobs"],
            value["validation"],
            value["reason_code"],
            value["evidence_sha256"],
            value["receipt"],
            value["bundle"],
            value["chunk"],
            value["winner_selection"],
        )

    def inspect(self, **payload):
        return self._call("inspect", payload)

    def status(self, **payload):
        return self._call("status", payload)

    def prepare(self, **payload):
        return self._call("prepare", payload)

    def retrieve(self, **payload):
        return self._call("retrieve", payload)
