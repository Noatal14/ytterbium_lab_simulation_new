"""Guarded Discovery result synchronization and Preliminary Check preparation.

The remote receiver owns scientific validation and canonical transition rendering.
This coordinator binds an explicit review to that immutable evidence, downloads a
bounded deterministic bundle, and publishes ``campaign.json`` last so the local
manifest never advertises artifacts that are not durable yet.
"""

from __future__ import annotations

from workflow_api import mot_3d_workload as workload

import base64
import errno
from workflow_api.platform_io import locking as fcntl
import gzip
import io
import hashlib
import json
from workflow_api.platform_io import os
import re
import secrets
import stat
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol

from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshProcessError,
    PinnedSshRunner,
    ReceiverOperation,
)
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.zeus_discovery_submission import (
    ZeusMot3DDiscoverySubmissionCoordinator,
    ZeusMot3DDiscoverySubmissionError,
    canonical_digest,
)
from workflow_api.zeus_snapshot import ZeusProfile

TTL = 300
CAPACITY = 32
EXPECTED_TRIALS = 950
EXPECTED_FILES = 961
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_CHUNK_BYTES = 4 * 1024 * 1024
MAX_CHUNKS = 16
HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
JOB = re.compile(r"^\d+\[\]\.zeus-master$")
FAMILIES = ("angled_donut", "single_pass")
TARGETS = {"angled_donut": (117, 117, 116), "single_pass": (200, 200, 200)}


def _expected_bundle_paths(manifest=None) -> frozenset[str]:
    paths: set[str] = {"campaign.json"}
    for family in FAMILIES:
        for worker, target in enumerate(
            TARGETS[family]
            if manifest is None
            else workload.discovery_targets(manifest, family)
        ):
            paths.update(
                f"discovery/{family}/worker_{worker}/trials/trial_{number:04d}.json"
                for number in range(target)
            )
        paths.update(
            {
                f"discovery/{family}/merged/merged_summary.json",
                f"discovery/{family}/merged/ranked_trials.csv",
                f"selection/discovery/{family}.json",
                f"jobs/preliminary_check/{family}_array.pbs",
                f"jobs/preliminary_check/{family}_merge.pbs",
            }
        )
    if manifest is None and len(paths) != EXPECTED_FILES:
        raise RuntimeError("closed Discovery artifact allowlist is inconsistent")
    return frozenset(paths)


EXPECTED_BUNDLE_PATHS = _expected_bundle_paths()


class Mot3DDiscoveryTransitionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RemoteDiscoveryTransitionState:
    lifecycle: str
    branch: str
    chain: Mapping[str, tuple[str, ...]]
    receipt: Mapping[str, Any] | None
    bundle: Mapping[str, Any] | None
    chunk: Mapping[str, Any] | None


class DiscoveryTransitionTransport(Protocol):
    def inspect(self, **payload: object) -> RemoteDiscoveryTransitionState: ...
    def status(self, **payload: object) -> RemoteDiscoveryTransitionState: ...
    def prepare(self, **payload: object) -> RemoteDiscoveryTransitionState: ...
    def retrieve(self, **payload: object) -> RemoteDiscoveryTransitionState: ...


@dataclass(frozen=True)
class _Pending:
    session_id: str
    campaign_id: str
    profile: ZeusProfile
    commit: str
    relative: str
    bootstrap_digest: str
    bootstrap_key: str
    submission_key: str
    chain: Mapping[str, tuple[str, ...]]
    evidence_sha256: str
    transition_key: str
    nonce: str
    expires: float
    result: Mapping[str, object] | None = None
    terminal_error: str | None = None


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _strict_json(data: bytes) -> object:
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    return json.loads(
        data.decode("utf-8", "strict"),
        object_pairs_hook=pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
    )


_DIRECTORY_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


def _open_directory_at(parent_fd: int, name: str, *, create: bool) -> int:
    if name in {"", ".", ".."} or "/" in name:
        raise Mot3DDiscoveryTransitionError("local_sync_conflict")
    try:
        return os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        os.fsync(parent_fd)
        return descriptor


def _open_parent_at(root_fd: int, parts: tuple[str, ...], *, create: bool) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            following = _open_directory_at(current, part, create=create)
            os.close(current)
            current = following
        return current
    except Exception:
        os.close(current)
        raise


def _bounded_read_at(parent_fd: int, name: str, limit: int) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(name, _READ_FLAGS, dir_fd=parent_fd)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= limit:
            raise OSError(errno.EINVAL, "invalid bounded file")
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(descriptor)
        identity = lambda row: (
            row.st_dev,
            row.st_ino,
            row.st_mode,
            row.st_nlink,
            row.st_uid,
            row.st_gid,
            row.st_size,
            row.st_mtime_ns,
            row.st_ctime_ns,
        )
        if len(data) != before.st_size or identity(before) != identity(after):
            raise OSError(errno.EIO, "file changed during read")
        return bytes(data)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _publish_no_replace_at(parent_fd: int, name: str, data: bytes) -> None:
    temporary = f".{name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=parent_fd,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(
                temporary,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            if _bounded_read_at(parent_fd, name, max(len(data), 1)) != data:
                raise Mot3DDiscoveryTransitionError("local_sync_conflict")
        os.fsync(parent_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def _atomic_replace_at(parent_fd: int, name: str, data: bytes) -> None:
    temporary = f".{name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=parent_fd,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def _atomic_json_at(
    parent_fd: int, name: str, value: Mapping[str, object], *, replace: bool
) -> None:
    data = _json_bytes(value) + b"\n"
    if replace:
        _atomic_replace_at(parent_fd, name, data)
    else:
        _publish_no_replace_at(parent_fd, name, data)


def _safe_relative(name: object) -> PurePosixPath:
    if not isinstance(name, str):
        raise Mot3DDiscoveryTransitionError("remote_response_invalid")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise Mot3DDiscoveryTransitionError("remote_response_invalid")
    return path


class Mot3DDiscoveryTransitionCoordinator:
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
            lambda profile: PinnedSshMot3DDiscoveryTransitionTransport(
                self.root, self.ssh, profile
            )
        )
        self._previews = PreviewRegistry[_Pending](
            clock=clock, token_factory=token_factory
        )
        self._confirm = threading.Lock()

    def _base(self, request: Mapping[str, object]):
        try:
            submit = ZeusMot3DDiscoverySubmissionCoordinator(
                self.root, self.ssh, self.git
            )
            plan = submit._plan(request)
        except ZeusMot3DDiscoverySubmissionError as exc:
            raise Mot3DDiscoveryTransitionError(exc.code) from exc
        return plan

    def _payload(self, plan: tuple[Any, ...]) -> dict[str, object]:
        return {
            "campaign": plan[2].relative_to(self.root).as_posix(),
            "commit": plan[4],
            "bootstrap_digest": plan[7],
            "bootstrap_key": plan[8],
            "submission_key": plan[9],
        }

    @staticmethod
    def _validate_chain(chain: Mapping[str, tuple[str, ...]]) -> None:
        if (
            not isinstance(chain, Mapping)
            or set(chain) != set(FAMILIES)
            or len(chain["angled_donut"]) != 2
            or len(chain["single_pass"]) != 3
            or any(
                not isinstance(job, str) or not JOB.fullmatch(job)
                for family in FAMILIES
                for job in chain[family]
            )
        ):
            raise Mot3DDiscoveryTransitionError("remote_response_invalid")

    @classmethod
    def _validate_state(cls, state: RemoteDiscoveryTransitionState) -> None:
        allowed = {
            "queued",
            "running",
            "held",
            "completed_failed",
            "status_unknown",
            "completed_success_unvalidated",
            "outputs_invalid",
            "ready_to_advance",
            "preliminary_check_prepared",
        }
        if (
            state.lifecycle not in allowed
            or not isinstance(state.branch, str)
            or not state.branch
            or len(state.branch) > 256
            or not state.branch.isprintable()
        ):
            raise Mot3DDiscoveryTransitionError("remote_response_invalid")
        cls._validate_chain(state.chain)
        prepared = state.lifecycle == "preliminary_check_prepared"
        if prepared != (state.receipt is not None and state.bundle is not None):
            raise Mot3DDiscoveryTransitionError("remote_response_invalid")
        if not prepared and (
            state.receipt is not None
            or state.bundle is not None
            or state.chunk is not None
        ):
            raise Mot3DDiscoveryTransitionError("remote_response_invalid")

    def _transition_key(
        self, plan: tuple[Any, ...], chain: Mapping[str, tuple[str, ...]]
    ) -> str:
        return canonical_digest(
            {
                "campaign": plan[2].relative_to(self.root).as_posix(),
                "commit": plan[4],
                "bootstrap_digest": plan[7],
                "submission_key": plan[9],
                "chain": {family: list(chain[family]) for family in FAMILIES},
            }
        )

    def _inspect(self, request: Mapping[str, object], *, status: bool = False):
        plan = self._base(request)
        transport = self.transport_factory(plan[1])
        payload = self._payload(plan)
        state = transport.status(**payload) if status else transport.inspect(**payload)
        self._validate_state(state)
        transition_key = self._transition_key(plan, state.chain)
        if state.lifecycle == "preliminary_check_prepared":
            self._validate_prepared(state, plan, transition_key)
        return plan, transport, state, transition_key

    @staticmethod
    def _validate_bundle(bundle: Mapping[str, Any], expected_files=None) -> None:
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
            or bundle.get("file_count")
            not in (
                {expected_files} if expected_files is not None else {EXPECTED_FILES, 35}
            )
            or not isinstance(bundle.get("uncompressed_bytes"), int)
            or isinstance(bundle.get("uncompressed_bytes"), bool)
            or not 0 <= bundle["uncompressed_bytes"] <= MAX_TOTAL_BYTES
            or not HEX64.fullmatch(str(bundle.get("bundle_sha256", "")))
            or not isinstance(bundle.get("chunks"), list)
            or not 1 <= len(bundle["chunks"]) <= MAX_CHUNKS
        ):
            raise Mot3DDiscoveryTransitionError("remote_response_invalid")
        for index, row in enumerate(bundle["chunks"]):
            if (
                not isinstance(row, dict)
                or set(row) != {"index", "size", "sha256"}
                or row["index"] != index
                or not isinstance(row["size"], int)
                or isinstance(row["size"], bool)
                or not 0 < row["size"] <= MAX_CHUNK_BYTES
                or not HEX64.fullmatch(str(row["sha256"]))
            ):
                raise Mot3DDiscoveryTransitionError("remote_response_invalid")

    @classmethod
    def _validate_prepared(cls, state, plan, transition_key):
        cls._validate_bundle(state.bundle, len(_expected_bundle_paths(plan[3])))
        receipt = state.receipt
        exact = {
            "status",
            "nonce",
            "transition_key",
            "commit",
            "bootstrap_digest",
            "submission_key",
            "chain",
            "bundle",
            "completed_unix_s",
        }
        if (
            not isinstance(receipt, Mapping)
            or set(receipt) != exact
            or receipt.get("status") != "preliminary_check_prepared"
            or not HEX32.fullmatch(str(receipt.get("nonce", "")))
            or receipt.get("transition_key") != transition_key
            or receipt.get("commit") != plan[4]
            or receipt.get("bootstrap_digest") != plan[7]
            or receipt.get("submission_key") != plan[9]
            or receipt.get("chain")
            != {family: list(state.chain[family]) for family in FAMILIES}
            or receipt.get("bundle") != state.bundle
            or not isinstance(receipt.get("completed_unix_s"), int)
            or isinstance(receipt.get("completed_unix_s"), bool)
            or not 0 <= receipt["completed_unix_s"] <= 253402300799
        ):
            raise Mot3DDiscoveryTransitionError("transition_outcome_unknown")

    def status(self, request):
        plan, _, state, _ = self._inspect(request, status=True)
        local_receipt = plan[2] / ".mot_ui/sync/discovery_to_preliminary.json"
        synchronized = (
            state.lifecycle == "preliminary_check_prepared"
            and self._verify_local_receipt(
                plan[2], state, local_receipt, raise_on_error=False
            )
        )
        invalid = state.lifecycle in {"held", "completed_failed", "outputs_invalid"}
        valid = state.lifecycle in {"ready_to_advance", "preliminary_check_prepared"}
        return {
            "source": "zeus",
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "campaign": {
                "id": plan[0],
                "name": plan[3]["name"],
                "stage": "preliminary_check" if synchronized else "discovery",
            },
            "discovery": {
                "status": (
                    "preliminary_check_prepared" if synchronized else state.lifecycle
                ),
                "chain": {family: list(state.chain[family]) for family in FAMILIES},
            },
            "validation": {
                "status": "valid" if valid else "invalid" if invalid else "not_ready",
                "completed_trials": (
                    len(_expected_bundle_paths(plan[3])) - 11 if valid else 0
                ),
                "expected_trials": len(_expected_bundle_paths(plan[3])) - 11,
            },
            "next_action": (
                "none"
                if synchronized
                else (
                    "review_transition"
                    if state.lifecycle
                    in {"ready_to_advance", "preliminary_check_prepared"}
                    else (
                        "inspect_zeus"
                        if invalid or state.lifecycle == "status_unknown"
                        else "wait"
                    )
                )
            ),
            "local_sync": {
                "status": "synchronized" if synchronized else "not_synchronized",
                "receipt_sha256": (
                    hashlib.sha256(local_receipt.read_bytes()).hexdigest()
                    if synchronized
                    else None
                ),
            },
        }

    def preview(self, request, *, session_id: str):
        plan, _, state, transition_key = self._inspect(request)
        if state.lifecycle not in {"ready_to_advance", "preliminary_check_prepared"}:
            raise Mot3DDiscoveryTransitionError("discovery_not_complete")
        expires = self.clock() + TTL
        evidence = canonical_digest(
            {
                "commit": plan[4],
                "bootstrap_digest": plan[7],
                "submission_key": plan[9],
                "chain": {family: list(state.chain[family]) for family in FAMILIES},
            }
        )
        pending = _Pending(
            session_id,
            plan[0],
            plan[1],
            plan[4],
            plan[2].relative_to(self.root).as_posix(),
            plan[7],
            plan[8],
            plan[9],
            dict(state.chain),
            evidence,
            transition_key,
            (
                state.receipt["nonce"]
                if state.receipt is not None
                else secrets.token_hex(16)
            ),
            expires,
        )
        try:
            token = self._previews.add(pending, expires_at=expires, capacity=CAPACITY)
        except OverflowError as exc:
            raise Mot3DDiscoveryTransitionError("too_many_pending_previews") from exc
        return {
            "preview_token": token,
            "expires_in_seconds": TTL,
            "campaign": {"id": plan[0], "name": plan[3]["name"], "git_commit": plan[4]},
            "from_stage": "discovery",
            "to_stage": "preliminary_check",
            "discovery": {
                "completed_trials": len(_expected_bundle_paths(plan[3])) - 11,
                "expected_trials": len(_expected_bundle_paths(plan[3])) - 11,
                "families": list(FAMILIES),
                "evidence_sha256": evidence,
            },
            "artifacts": {
                "synchronize": {
                    "trial_registries": len(_expected_bundle_paths(plan[3])) - 11,
                    "merged_files": 4,
                },
                "create": {"selection_files": 2, "job_files": 4},
                "update": ["campaign.json"],
            },
            "effects": {
                "synchronize_discovery": True,
                "prepare_preliminary_check": True,
                "submit_preliminary_check": False,
                "start_simulation": False,
                "overwrite_existing": False,
            },
        }

    def confirm(self, request, *, session_id: str):
        if (
            not isinstance(request, Mapping)
            or set(request) != {"preview_token"}
            or not isinstance(request.get("preview_token"), str)
        ):
            raise Mot3DDiscoveryTransitionError("request_invalid")
        token = request["preview_token"]
        with self._confirm:
            record = self._previews.get(token)
            pending = record.value if record else None
            if pending is None or not secrets.compare_digest(
                pending.session_id, session_id
            ):
                raise Mot3DDiscoveryTransitionError("confirmation_invalid")
            if pending.result is not None:
                return dict(pending.result)
            if pending.terminal_error:
                raise Mot3DDiscoveryTransitionError(pending.terminal_error)
            if self.clock() > pending.expires:
                raise Mot3DDiscoveryTransitionError("confirmation_expired")
            request_again = {
                "campaign_id": pending.campaign_id,
                "username": pending.profile.username,
                "project_directory": pending.profile.project_directory,
            }
            plan, transport, state, transition_key = self._inspect(request_again)
            identity = (
                plan[4],
                plan[2].relative_to(self.root).as_posix(),
                plan[7],
                plan[8],
                plan[9],
                dict(state.chain),
                transition_key,
            )
            expected = (
                pending.commit,
                pending.relative,
                pending.bootstrap_digest,
                pending.bootstrap_key,
                pending.submission_key,
                pending.chain,
                pending.transition_key,
            )
            if (
                state.lifecycle
                not in {"ready_to_advance", "preliminary_check_prepared"}
                or identity != expected
            ):
                raise Mot3DDiscoveryTransitionError("local_or_remote_evidence_changed")
            if state.lifecycle == "preliminary_check_prepared":
                prepared = state
            else:
                payload = self._payload(plan) | {"nonce": pending.nonce}
                try:
                    prepared = transport.prepare(**payload)
                except Mot3DDiscoveryTransitionError as exc:
                    if exc.code in {
                        "transition_outcome_unknown",
                        "remote_response_invalid",
                    }:
                        self._previews.replace(
                            token, replace(pending, terminal_error=exc.code)
                        )
                    raise
                self._validate_state(prepared)
                self._validate_prepared(prepared, plan, transition_key)
            if prepared.receipt["nonce"] != pending.nonce:
                raise Mot3DDiscoveryTransitionError("transition_outcome_unknown")
            try:
                receipt_sha = self._synchronize(plan, transport, prepared)
            except Exception as exc:
                self._previews.replace(
                    token, replace(pending, terminal_error="local_sync_outcome_unknown")
                )
                if isinstance(exc, Mot3DDiscoveryTransitionError):
                    raise
                raise Mot3DDiscoveryTransitionError(
                    "local_sync_outcome_unknown"
                ) from exc
            result = {
                "status": "preliminary_check_prepared",
                "campaign_id": pending.campaign_id,
                "stage": "preliminary_check",
                "artifacts": {
                    "synchronized": len(_expected_bundle_paths(plan[3])) - 7,
                    "created": 6,
                    "updated": 1,
                    "bundle_sha256": prepared.bundle["bundle_sha256"],
                },
                "submitted_to_zeus": False,
                "simulation_started": False,
                "local_sync": {"status": "synchronized", "receipt_sha256": receipt_sha},
            }
            self._previews.replace(token, replace(pending, result=result))
            return result

    def _synchronize(self, plan, transport, state) -> str:
        campaign = plan[2]
        campaign_fd = os.open(campaign, _DIRECTORY_FLAGS)
        mot_fd = sync_fd = lock_fd = -1
        receipt_digest = canonical_digest(state.receipt)
        intent_identity = {
            "status": "synchronizing",
            "transition_key": state.receipt["transition_key"],
            "remote_receipt_sha256": receipt_digest,
            "bundle": state.bundle,
        }
        intent = {**intent_identity, "created_unix_s": int(self.clock())}
        try:
            mot_fd = _open_directory_at(campaign_fd, ".mot_ui", create=True)
            sync_fd = _open_directory_at(mot_fd, "sync", create=True)
            lock_fd = os.open(
                "discovery_to_preliminary.lock",
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=sync_fd,
            )
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                final_raw = _bounded_read_at(
                    sync_fd, "discovery_to_preliminary.json", 256 * 1024
                )
            except FileNotFoundError:
                final_raw = None
            if final_raw is not None:
                if self._verify_local_receipt_at(
                    campaign_fd, state, final_raw, raise_on_error=False
                ):
                    return hashlib.sha256(final_raw).hexdigest()
                raise Mot3DDiscoveryTransitionError("local_sync_conflict")
            try:
                pending_raw = _bounded_read_at(
                    sync_fd, "discovery_to_preliminary.pending.json", 256 * 1024
                )
            except FileNotFoundError:
                _atomic_json_at(
                    sync_fd,
                    "discovery_to_preliminary.pending.json",
                    intent,
                    replace=False,
                )
            else:
                existing = _strict_json(pending_raw)
                if (
                    not isinstance(existing, dict)
                    or {key: existing.get(key) for key in intent_identity}
                    != intent_identity
                    or not isinstance(existing.get("created_unix_s"), int)
                ):
                    raise Mot3DDiscoveryTransitionError("local_sync_conflict")
            chunks = []
            for row in state.bundle["chunks"]:
                remote = transport.retrieve(
                    **(
                        self._payload(plan)
                        | {
                            "transition_key": state.receipt["transition_key"],
                            "bundle_sha256": state.bundle["bundle_sha256"],
                            "chunk_index": row["index"],
                        }
                    )
                )
                self._validate_state(remote)
                chunk = remote.chunk
                if (
                    not isinstance(chunk, Mapping)
                    or set(chunk) != {"index", "sha256", "content"}
                    or chunk.get("index") != row["index"]
                    or chunk.get("sha256") != row["sha256"]
                ):
                    raise Mot3DDiscoveryTransitionError("remote_response_invalid")
                try:
                    raw = base64.b64decode(chunk["content"], validate=True)
                except Exception as exc:
                    raise Mot3DDiscoveryTransitionError(
                        "remote_response_invalid"
                    ) from exc
                if (
                    len(raw) != row["size"]
                    or hashlib.sha256(raw).hexdigest() != row["sha256"]
                ):
                    raise Mot3DDiscoveryTransitionError("remote_response_invalid")
                chunks.append(raw)
            packed = b"".join(chunks)
            if hashlib.sha256(packed).hexdigest() != state.bundle["bundle_sha256"]:
                raise Mot3DDiscoveryTransitionError("remote_response_invalid")
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(packed), mode="rb") as stream:
                    unpacked = stream.read(MAX_TOTAL_BYTES * 2 + 1)
                if len(unpacked) > MAX_TOTAL_BYTES * 2:
                    raise ValueError("expanded bundle exceeds bound")
            except Exception as exc:
                raise Mot3DDiscoveryTransitionError("remote_response_invalid") from exc
            files = self._validate_bundle_payload(
                _strict_json(unpacked), plan, state.bundle
            )
            manifest_data = files.pop("campaign.json")
            current_manifest_data = _bounded_read_at(
                campaign_fd, "campaign.json", MAX_FILE_BYTES
            )
            current_manifest_hash = hashlib.sha256(current_manifest_data).hexdigest()
            old_manifest_hash = plan[5]["campaign.json"]
            new_manifest_hash = hashlib.sha256(manifest_data).hexdigest()
            if current_manifest_hash == old_manifest_hash:
                for name, data in files.items():
                    path = PurePosixPath(name)
                    parent_fd = _open_parent_at(
                        campaign_fd, path.parts[:-1], create=True
                    )
                    try:
                        _publish_no_replace_at(parent_fd, path.name, data)
                    finally:
                        os.close(parent_fd)
                if (
                    _bounded_read_at(campaign_fd, "campaign.json", MAX_FILE_BYTES)
                    != current_manifest_data
                ):
                    raise Mot3DDiscoveryTransitionError("local_sync_conflict")
                _atomic_replace_at(campaign_fd, "campaign.json", manifest_data)
            elif current_manifest_hash == new_manifest_hash:
                for name, data in files.items():
                    path = PurePosixPath(name)
                    parent_fd = _open_parent_at(
                        campaign_fd, path.parts[:-1], create=False
                    )
                    try:
                        if (
                            _bounded_read_at(parent_fd, path.name, MAX_FILE_BYTES)
                            != data
                        ):
                            raise Mot3DDiscoveryTransitionError("local_sync_conflict")
                    finally:
                        os.close(parent_fd)
            else:
                raise Mot3DDiscoveryTransitionError("local_sync_conflict")
            file_hashes = {
                name: hashlib.sha256(data).hexdigest()
                for name, data in {**files, "campaign.json": manifest_data}.items()
            }
            complete = {
                "status": "synchronized",
                "transition_key": state.receipt["transition_key"],
                "remote_receipt_sha256": receipt_digest,
                "bundle_sha256": state.bundle["bundle_sha256"],
                "files": file_hashes,
                "completed_unix_s": int(self.clock()),
            }
            complete_raw = _json_bytes(complete) + b"\n"
            if not self._verify_local_receipt_at(
                campaign_fd, state, complete_raw, raise_on_error=False
            ):
                raise Mot3DDiscoveryTransitionError("local_sync_conflict")
            _atomic_json_at(
                sync_fd, "discovery_to_preliminary.json", complete, replace=False
            )
            os.unlink("discovery_to_preliminary.pending.json", dir_fd=sync_fd)
            os.fsync(sync_fd)
            final_raw = _bounded_read_at(
                sync_fd, "discovery_to_preliminary.json", 256 * 1024
            )
            if not self._verify_local_receipt_at(
                campaign_fd, state, final_raw, raise_on_error=False
            ):
                raise Mot3DDiscoveryTransitionError("local_sync_conflict")
            return hashlib.sha256(final_raw).hexdigest()
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise Mot3DDiscoveryTransitionError("local_sync_conflict") from exc
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
            os.close(campaign_fd)

    @staticmethod
    def _verify_local_receipt(
        campaign: Path,
        state: RemoteDiscoveryTransitionState,
        receipt_path: Path,
        *,
        raise_on_error: bool,
    ) -> bool:
        campaign_fd = mot_fd = sync_fd = -1
        try:
            if receipt_path.name != "discovery_to_preliminary.json":
                raise ValueError("unexpected receipt path")
            campaign_fd = os.open(campaign, _DIRECTORY_FLAGS)
            mot_fd = _open_directory_at(campaign_fd, ".mot_ui", create=False)
            sync_fd = _open_directory_at(mot_fd, "sync", create=False)
            raw_receipt = _bounded_read_at(sync_fd, receipt_path.name, 256 * 1024)
            return Mot3DDiscoveryTransitionCoordinator._verify_local_receipt_at(
                campaign_fd, state, raw_receipt, raise_on_error=raise_on_error
            )
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
            if raise_on_error:
                raise Mot3DDiscoveryTransitionError("local_sync_conflict") from None
            return False
        finally:
            if sync_fd >= 0:
                os.close(sync_fd)
            if mot_fd >= 0:
                os.close(mot_fd)
            if campaign_fd >= 0:
                os.close(campaign_fd)

    @staticmethod
    def _verify_local_receipt_at(
        campaign_fd: int,
        state: RemoteDiscoveryTransitionState,
        raw_receipt: bytes,
        *,
        raise_on_error: bool,
    ) -> bool:
        try:
            receipt = _strict_json(raw_receipt)
            exact = {
                "status",
                "transition_key",
                "remote_receipt_sha256",
                "bundle_sha256",
                "files",
                "completed_unix_s",
            }
            if (
                not isinstance(receipt, dict)
                or set(receipt) != exact
                or receipt.get("status") != "synchronized"
                or state.receipt is None
                or state.bundle is None
                or receipt.get("transition_key") != state.receipt.get("transition_key")
                or receipt.get("remote_receipt_sha256")
                != canonical_digest(state.receipt)
                or receipt.get("bundle_sha256") != state.bundle.get("bundle_sha256")
                or not isinstance(receipt.get("completed_unix_s"), int)
                or isinstance(receipt.get("completed_unix_s"), bool)
                or not 0 <= receipt["completed_unix_s"] <= 253402300799
                or not isinstance(receipt.get("files"), dict)
                or set(receipt["files"])
                != _expected_bundle_paths(
                    _strict_json(
                        _bounded_read_at(campaign_fd, "campaign.json", MAX_FILE_BYTES)
                    )
                )
                or any(
                    not HEX64.fullmatch(str(value))
                    for value in receipt["files"].values()
                )
            ):
                raise ValueError("receipt schema or identity mismatch")
            for name, expected in receipt["files"].items():
                path = PurePosixPath(name)
                parent_fd = _open_parent_at(campaign_fd, path.parts[:-1], create=False)
                try:
                    actual = hashlib.sha256(
                        _bounded_read_at(parent_fd, path.name, MAX_FILE_BYTES)
                    ).hexdigest()
                finally:
                    os.close(parent_fd)
                if actual != expected:
                    raise ValueError("published artifact mismatch")
            return True
        except (
            OSError,
            ValueError,
            UnicodeError,
            json.JSONDecodeError,
            Mot3DDiscoveryTransitionError,
        ):
            if raise_on_error:
                raise Mot3DDiscoveryTransitionError("local_sync_conflict") from None
            return False

    @staticmethod
    def _validate_bundle_payload(value, plan, manifest):
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "version",
                "campaign",
                "commit",
                "from_stage",
                "to_stage",
                "files",
                "uncompressed_bytes",
            }
            or value.get("version") != 1
            or value.get("campaign") != plan[2].name
            or value.get("commit") != plan[4]
            or value.get("from_stage") != "discovery"
            or value.get("to_stage") != "preliminary_check"
            or value.get("uncompressed_bytes") != manifest["uncompressed_bytes"]
            or not isinstance(value.get("files"), list)
            or len(value["files"]) != len(_expected_bundle_paths(plan[3]))
        ):
            raise Mot3DDiscoveryTransitionError("remote_response_invalid")
        result = {}
        prior = ""
        total = 0
        for row in value["files"]:
            if not isinstance(row, dict) or set(row) != {
                "path",
                "size",
                "sha256",
                "content",
            }:
                raise Mot3DDiscoveryTransitionError("remote_response_invalid")
            path = _safe_relative(row["path"])
            name = path.as_posix()
            if (
                name <= prior
                or not isinstance(row["size"], int)
                or isinstance(row["size"], bool)
                or not 0 <= row["size"] <= MAX_FILE_BYTES
                or not HEX64.fullmatch(str(row["sha256"]))
            ):
                raise Mot3DDiscoveryTransitionError("remote_response_invalid")
            try:
                data = base64.b64decode(row["content"], validate=True)
            except Exception as exc:
                raise Mot3DDiscoveryTransitionError("remote_response_invalid") from exc
            if (
                len(data) != row["size"]
                or hashlib.sha256(data).hexdigest() != row["sha256"]
            ):
                raise Mot3DDiscoveryTransitionError("remote_response_invalid")
            result[name] = data
            prior = name
            total += len(data)
        if total != manifest["uncompressed_bytes"] or set(
            result
        ) != _expected_bundle_paths(plan[3]):
            raise Mot3DDiscoveryTransitionError("remote_response_invalid")
        return result


class PinnedSshMot3DDiscoveryTransitionTransport:
    def __init__(self, root: Path, ssh: Path, profile: ZeusProfile, *, timeout=240):
        self.profile = profile
        self.runner = PinnedSshRunner(
            PinnedSshPolicy.mot_3d_discovery_transition(root, ssh, timeout=timeout)
        )

    def _call(self, operation: str, payload: Mapping[str, object]):
        pin = {
            "inspect": ReceiverOperation.INSPECT,
            "status": ReceiverOperation.STATUS,
            "prepare": ReceiverOperation.PREPARE,
            "retrieve": ReceiverOperation.RETRIEVE,
        }[operation]
        try:
            result = self.runner.run(pin, self.profile, payload)
        except (subprocess.TimeoutExpired, PinnedSshProcessError):
            raise Mot3DDiscoveryTransitionError(
                "transition_outcome_unknown"
                if operation == "prepare"
                else "zeus_timeout"
            ) from None
        if result.returncode or result.stderr:
            raise Mot3DDiscoveryTransitionError("remote_response_invalid")
        try:
            data = _strict_json(result.stdout)
        except Exception:
            raise Mot3DDiscoveryTransitionError("remote_response_invalid") from None
        if not isinstance(data, dict) or set(data) != {
            "lifecycle",
            "branch",
            "chain",
            "receipt",
            "bundle",
            "chunk",
        }:
            raise Mot3DDiscoveryTransitionError("remote_response_invalid")
        chain = data["chain"]
        if not isinstance(chain, dict):
            raise Mot3DDiscoveryTransitionError("remote_response_invalid")
        return RemoteDiscoveryTransitionState(
            data["lifecycle"],
            data["branch"],
            {
                key: tuple(value) if isinstance(value, list) else value
                for key, value in chain.items()
            },
            data["receipt"],
            data["bundle"],
            data["chunk"],
        )

    def inspect(self, **payload):
        return self._call("inspect", payload)

    def status(self, **payload):
        return self._call("status", payload)

    def prepare(self, **payload):
        return self._call("prepare", payload)

    def retrieve(self, **payload):
        return self._call("retrieve", payload)
