"""Explicit Zeus lifecycle for one reviewed individual Zeeman run.

The coordinator owns policy and durable local lifecycle state.  Its transport
is a deliberately tiny, allowlisted receiver contract; tests inject a fake and
this module never accepts a command, host, PBS option, or result path from a
caller.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import base64
import json
from workflow_api.platform_io import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

from workflow_api.preview_registry import PreviewRegistry
from workflow_api.run_execution import (
    ExecutionAuthority,
    ExecutorLifecycleStore,
    WorkerProduct,
    WorkerProductError,
)
from workflow_api.run_records import (
    RunRecordError,
    encode_record,
    _publish_no_replace_at,
    _read_regular_at,
    _replace_at,
)
from workflow_api.zeeman_run_specification import ZEEMAN_RUN_SPECIFICATION
from workflow_api.zeus_snapshot import ZeusProfile
from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshProcessError,
    PinnedSshRunner,
    ReceiverOperation,
)


_LIFETIME = 300
_CAPACITY = 64
_JOB_ID = re.compile(r"^[1-9][0-9]*\.zeus-master$")
_REMOTE_STATES = frozenset({"queued", "running", "succeeded", "failed"})
_OPERATIONS = frozenset({"inspect", "stage", "submit", "status", "retrieve"})


class ZeemanZeusError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FrozenZeusPackage:
    run_id: str
    commit: str
    records: Mapping[str, bytes]
    package_sha256: str
    pbs: bytes
    pbs_sha256: str
    submission_key: str
    username: str
    project_directory: str


@dataclass(frozen=True)
class RemoteSubmission:
    state: str  # absent, submitted, ambiguous
    nonce: str | None = None
    job_id: str | None = None


@dataclass(frozen=True)
class RemoteJobStatus:
    job_id: str
    state: str
    exit_status: int | None = None


class ZeemanZeusTransport(Protocol):
    """Dedicated allowlist: implementations expose exactly four operations."""

    operations: frozenset[str]

    def inspect(
        self, *, package: FrozenZeusPackage, nonce: str
    ) -> RemoteSubmission: ...
    def stage(self, *, package: FrozenZeusPackage, nonce: str) -> RemoteSubmission: ...
    def submit(self, *, package: FrozenZeusPackage, nonce: str) -> RemoteSubmission: ...
    def status(self, *, job_id: str, submission_key: str) -> RemoteJobStatus: ...
    def retrieve(
        self, *, job_id: str, submission_key: str, package_sha256: str
    ) -> WorkerProduct: ...


def _package_payload(package: FrozenZeusPackage) -> dict[str, Any]:
    return {
        "version": 1,
        "run_id": package.run_id,
        "commit": package.commit,
        "username": package.username,
        "project_directory": package.project_directory,
        "package_sha256": package.package_sha256,
        "pbs_sha256": package.pbs_sha256,
        "submission_key": package.submission_key,
        "records": {
            name: base64.b64encode(content).decode("ascii")
            for name, content in package.records.items()
        },
        "pbs": base64.b64encode(package.pbs).decode("ascii"),
    }


class PinnedSshZeemanTransport:
    """Concrete adapter to the dedicated repository-owned Zeus receiver."""

    operations = _OPERATIONS

    def __init__(
        self,
        repository_root: Path,
        ssh_executable: Path,
        profile: ZeusProfile,
        *,
        timeout: float = 90,
    ) -> None:
        self.profile = profile
        self.runner = PinnedSshRunner(
            PinnedSshPolicy.zeeman_individual(
                repository_root, ssh_executable, timeout=timeout
            )
        )

    def _request(
        self, operation: ReceiverOperation, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        try:
            completed = self.runner.run(operation, self.profile, payload)
        except (PinnedSshProcessError, subprocess.TimeoutExpired):
            raise ZeemanZeusError(
                "submission_outcome_unknown"
                if operation is ReceiverOperation.SUBMIT
                else "zeus_unavailable"
            ) from None
        if len(completed.stdout) > 8 * 1024 * 1024 or len(completed.stderr) > 64 * 1024:
            raise ZeemanZeusError("remote_response_invalid")
        try:
            value = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise ZeemanZeusError(
                "submission_outcome_unknown"
                if operation is ReceiverOperation.SUBMIT
                else "remote_response_invalid"
            ) from None
        if completed.returncode:
            code = value.get("error") if isinstance(value, dict) else None
            allowed = {
                "remote_request_invalid",
                "remote_project_missing",
                "remote_package_invalid",
                "submission_outcome_unknown",
                "submission_busy",
                "job_status_unavailable",
                "result_unavailable",
            }
            if code not in allowed:
                code = (
                    "submission_outcome_unknown"
                    if operation is ReceiverOperation.SUBMIT
                    else "remote_response_invalid"
                )
            raise ZeemanZeusError(str(code))
        if not isinstance(value, dict):
            raise ZeemanZeusError("remote_response_invalid")
        return value

    def inspect(self, *, package: FrozenZeusPackage, nonce: str) -> RemoteSubmission:
        return self._submission("inspect", package, nonce)

    def stage(self, *, package: FrozenZeusPackage, nonce: str) -> RemoteSubmission:
        return self._submission("stage", package, nonce)

    def submit(self, *, package: FrozenZeusPackage, nonce: str) -> RemoteSubmission:
        return self._submission("submit", package, nonce)

    def _submission(
        self, operation: str, package: FrozenZeusPackage, nonce: str
    ) -> RemoteSubmission:
        value = self._request(
            ReceiverOperation(operation),
            {
                "identity": _package_payload(package),
                "nonce": nonce,
            },
        )
        if set(value) != {"state", "nonce", "job_id"}:
            raise ZeemanZeusError("remote_response_invalid")
        return RemoteSubmission(value["state"], value["nonce"], value["job_id"])

    def status(self, *, job_id: str, submission_key: str) -> RemoteJobStatus:
        value = self._request(
            ReceiverOperation.STATUS,
            {
                "job_id": job_id,
                "submission_key": submission_key,
            },
        )
        if set(value) != {"job_id", "state", "exit_status"}:
            raise ZeemanZeusError("remote_response_invalid")
        return RemoteJobStatus(value["job_id"], value["state"], value["exit_status"])

    def retrieve(
        self, *, job_id: str, submission_key: str, package_sha256: str
    ) -> WorkerProduct:
        value = self._request(
            ReceiverOperation.RETRIEVE,
            {
                "job_id": job_id,
                "submission_key": submission_key,
                "package_sha256": package_sha256,
            },
        )
        if set(value) != {"results", "receipt", "artifacts"} or not isinstance(
            value["artifacts"], dict
        ):
            raise ZeemanZeusError("remote_response_invalid")
        try:
            artifacts = {
                path: base64.b64decode(content, validate=True)
                for path, content in value["artifacts"].items()
            }
        except (ValueError, TypeError):
            raise ZeemanZeusError("remote_response_invalid") from None
        if sum(map(len, artifacts.values())) > 4 * 1024 * 1024:
            raise ZeemanZeusError("remote_response_invalid")
        return WorkerProduct(value["results"], value["receipt"], artifacts)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _target_pbs(text: str, project_directory: str | None) -> bytes:
    if project_directory is not None:
        path = Path(project_directory)
        ZeusProfile.parse({"username": path.parent.name, "project_directory": project_directory})
        if path.name == "ytterbium_lab_simulation_ui_test":
            text = text.replace("set -euo pipefail\n", "set -euo pipefail\nexport OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1\n")
            text = text.replace("/ytterbium_lab_simulation_new", "/ytterbium_lab_simulation_ui_test")
            text = text.replace("/venvs/atomsmltr/", "/venvs/atomsmltr-ui-test/")
            if "source " not in text:
                text = text.replace("python -m ", 'module load SPACK/apps\nmodule load gcc/14.1.0\nmodule load python/3.14.2\nsource "${HOME}/venvs/atomsmltr-ui-test/bin/activate"\npython -m ')
    return text.encode("utf-8")


def _render_pbs(run: Mapping[str, Any], package_sha256: str, project_directory: str | None = None) -> bytes:
    workers = ZEEMAN_RUN_SPECIFICATION["worker_policy"]["zeus"]["fixed"]
    # Scalar by construction: no #PBS -J and no user-controlled command text.
    text = f"""#!/bin/bash
#PBS -N iz_{run['run_id'][:24]}
#PBS -q zeus_combined_q
#PBS -l select=1:ncpus={workers}:mem=64gb
#PBS -l walltime=08:00:00
set -euo pipefail
cd /home/${{USER}}/ytterbium_lab_simulation_new
test "$(git rev-parse HEAD)" = "{run['git_revision']}"
python -m workflow_api.zeeman_zeus_worker --package ".workflow/individual-zeeman/{package_sha256}/package.json" --package-sha256 "{package_sha256}"
"""
    return _target_pbs(text, project_directory)


def build_frozen_package(
    records: Mapping[str, Mapping[str, Any]],
    profile: ZeusProfile,
    *,
    require_configured: bool = True,
) -> FrozenZeusPackage:
    if set(records) != {"run", "configuration", "inputs", "status"}:
        raise ZeemanZeusError("run_evidence_invalid")
    run = records["run"]
    status = records["status"]
    if (
        run["family"] != "zeeman"
        or run["execution_mode"] != "zeus"
        or (require_configured and status["state"] != "configured")
        or (require_configured and status["execution"]["zeus_job_id"] is not None)
    ):
        raise ZeemanZeusError("run_not_submittable")
    # The submitted package always contains the reviewed revision-zero status.
    # This makes its identity reconstructable from immutable run evidence after
    # the local lifecycle advances and binds every later query to that package.
    initial_status = {
        "schema_version": status["schema_version"],
        "run_id": run["run_id"],
        "revision": 0,
        "state": "configured",
        "updated_utc": run["created_utc"],
        "execution": {"mode": "zeus", "local_pid": None, "zeus_job_id": None},
        "error": None,
    }
    encoded = {
        name: encode_record(
            name, dict(initial_status if name == "status" else records[name])
        )
        for name in ("run", "configuration", "inputs", "status")
    }
    manifest = {
        "version": 1,
        "run_id": run["run_id"],
        "commit": run["git_revision"],
        "username": profile.username,
        "project_directory": profile.project_directory,
        "records": {
            key: hashlib.sha256(value).hexdigest() for key, value in encoded.items()
        },
    }
    package_hash = hashlib.sha256(_canonical(manifest)).hexdigest()
    pbs = _render_pbs(run, package_hash, profile.project_directory)
    pbs_hash = hashlib.sha256(pbs).hexdigest()
    key = hashlib.sha256(
        _canonical(
            {
                "package_sha256": package_hash,
                "pbs_sha256": pbs_hash,
                "run_id": run["run_id"],
                "commit": run["git_revision"],
                "username": profile.username,
                "project_directory": profile.project_directory,
            }
        )
    ).hexdigest()
    return FrozenZeusPackage(
        run_id=run["run_id"],
        commit=run["git_revision"],
        records=MappingProxyType(encoded),
        package_sha256=package_hash,
        pbs=pbs,
        pbs_sha256=pbs_hash,
        submission_key=key,
        username=profile.username,
        project_directory=profile.project_directory,
    )


@dataclass(frozen=True)
class _Pending:
    session_digest: str
    profile: ZeusProfile
    package: FrozenZeusPackage
    nonce: str
    expires_at: float
    result: Mapping[str, Any] | None = None
    terminal_error: str | None = None
    remote_job_id: str | None = None


class ZeusBindingStore(ExecutorLifecycleStore):
    """Descriptor-bound durable identity written before any possible qsub."""

    _NAME = ".zeus-execution.json"

    @staticmethod
    def _binding(package: FrozenZeusPackage, nonce: str, job_id: str | None = None):
        return {
            "version": 1,
            "run_id": package.run_id,
            "username": package.username,
            "project_directory": package.project_directory,
            "package_sha256": package.package_sha256,
            "pbs_sha256": package.pbs_sha256,
            "submission_key": package.submission_key,
            "nonce": nonce,
            "job_id": job_id,
        }

    def bind(self, authority, package: FrozenZeusPackage, nonce: str, lease):
        proposed = self._binding(package, nonce)
        encoded = _canonical(proposed)
        family = getattr(package, "family", "zeeman")
        with self._held_canonical_run(family, package.run_id, lease) as (
            directory,
            verify,
            _,
        ):
            with self._execution_locked_at(directory):
                try:
                    _publish_no_replace_at(directory, self._NAME, encoded)
                except RunRecordError:
                    if _read_regular_at(directory, self._NAME) != encoded:
                        raise RunRecordError("Zeus execution identity conflicts.")
                verify(allow_run_metadata_change=True)
        return proposed

    def read_binding(self, authority, run_id: str, lease, *, family: str = "zeeman"):
        with self._held_canonical_run(family, run_id, lease) as (directory, verify, _):
            try:
                os.stat(self._NAME, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                return None
            except OSError as error:
                raise RunRecordError("Invalid Zeus execution identity.") from error
            raw = _read_regular_at(directory, self._NAME)
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as error:
                raise RunRecordError("Invalid Zeus execution identity.") from error
            expected = {
                "version",
                "run_id",
                "username",
                "project_directory",
                "package_sha256",
                "pbs_sha256",
                "submission_key",
                "nonce",
                "job_id",
            }
            if (
                not isinstance(value, dict)
                or set(value) != expected
                or type(value["version"]) is not int
                or value["version"] != 1
                or value["run_id"] != run_id
                or any(
                    not isinstance(value[name], str)
                    for name in (
                        "run_id",
                        "username",
                        "project_directory",
                        "package_sha256",
                        "pbs_sha256",
                        "submission_key",
                        "nonce",
                    )
                )
                or any(
                    re.fullmatch(r"[0-9a-f]{64}", value[name]) is None
                    for name in ("package_sha256", "pbs_sha256", "submission_key")
                )
                or re.fullmatch(r"[0-9a-f]{32}", value["nonce"]) is None
                or (
                    value["job_id"] is not None
                    and (
                        not isinstance(value["job_id"], str)
                        or _JOB_ID.fullmatch(value["job_id"]) is None
                    )
                )
            ):
                raise RunRecordError("Invalid Zeus execution identity.")
            verify()
            return value

    def bind_job(
        self, authority, package: FrozenZeusPackage, nonce: str, job_id: str, lease
    ):
        family = getattr(package, "family", "zeeman")
        with self._held_canonical_run(family, package.run_id, lease) as (
            directory,
            verify,
            _,
        ):
            with self._execution_locked_at(directory):
                current = json.loads(_read_regular_at(directory, self._NAME))
                expected = self._binding(package, nonce)
                if current not in (expected, self._binding(package, nonce, job_id)):
                    raise RunRecordError("Zeus execution identity changed.")
                proposed = self._binding(package, nonce, job_id)
                _replace_at(directory, self._NAME, _canonical(proposed))
                verify(allow_run_metadata_change=True)
                return proposed


class IndividualZeemanZeusCoordinator:
    """Preview, explicitly submit, then poll/retrieve one frozen scalar job."""

    def __init__(
        self,
        repository_root: Path,
        authority: ExecutionAuthority,
        transport_factory: Callable[[ZeusProfile], ZeemanZeusTransport],
        *,
        clock: Callable[[], float] = time.monotonic,
        utc_clock: Callable[[], str] = _utc_now,
        token_factory: Callable[[], str] | None = None,
        nonce_factory: Callable[[], str] = lambda: secrets.token_hex(16),
        store_factory: Callable[[Path], ExecutorLifecycleStore] = ZeusBindingStore,
    ) -> None:
        self.root = repository_root.resolve(strict=True)
        self.authority = authority
        self.transport_factory = transport_factory
        self.clock = clock
        self.utc_clock = utc_clock
        self.nonce_factory = nonce_factory
        self.store_factory = store_factory
        self._previews = PreviewRegistry[_Pending](
            clock=clock, token_factory=token_factory
        )
        self._lock = threading.RLock()

    @staticmethod
    def _session(value: str) -> str:
        if not isinstance(value, str) or not value or len(value.encode()) > 512:
            raise ZeemanZeusError("confirmation_invalid")
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _transport(value: ZeemanZeusTransport) -> ZeemanZeusTransport:
        if getattr(value, "operations", None) != _OPERATIONS:
            raise ZeemanZeusError("transport_not_allowlisted")
        return value

    def _evidence(self, run_id: str):
        store = self.store_factory(self.root)
        try:
            return store.evidence_snapshot(self.authority, self.family, run_id)
        finally:
            store.close()

    def preview(
        self, *, run_id: str, profile: ZeusProfile, session: str
    ) -> dict[str, Any]:
        session_digest = self._session(session)
        if type(profile) is not ZeusProfile:
            raise ZeemanZeusError("profile_invalid")
        try:
            if (
                ZeusProfile.parse(
                    {
                        "username": profile.username,
                        "project_directory": profile.project_directory,
                    }
                )
                != profile
            ):
                raise ValueError
        except ValueError as error:
            raise ZeemanZeusError("profile_invalid") from error
        evidence, _lease = self._evidence(run_id)
        binding_store = self.store_factory(self.root)
        try:
            binding = (
                binding_store.read_binding(
                    self.authority, run_id, _lease, family=self.family
                )
                if isinstance(binding_store, ZeusBindingStore)
                else None
            )
        finally:
            binding_store.close()
        package = self._build_package(
            evidence, profile, require_configured=binding is None
        )
        if binding is not None:
            expected_identity = ZeusBindingStore._binding(
                package, binding["nonce"], binding["job_id"]
            )
            if binding != expected_identity:
                raise ZeemanZeusError("profile_or_submission_identity_mismatch")
            nonce = binding["nonce"]
        else:
            nonce = self.nonce_factory()
        if not re.fullmatch(r"[0-9a-f]{32}", nonce):
            raise ZeemanZeusError("nonce_invalid")
        transport = self._transport(self.transport_factory(profile))
        try:
            remote = transport.inspect(package=package, nonce=nonce)
        except ZeemanZeusError as error:
            if binding is not None and error.code == "submission_outcome_unknown":
                self._mark_unknown(evidence, _lease, error.code)
            raise
        if remote.state == "ambiguous":
            if binding is not None:
                self._mark_unknown(evidence, _lease, "submission_outcome_unknown")
            raise ZeemanZeusError("submission_outcome_unknown")
        if remote.state == "submitted":
            if (
                binding is None
                or remote.nonce != nonce
                or remote.job_id is None
                or not _JOB_ID.fullmatch(remote.job_id)
            ):
                raise ZeemanZeusError("submission_outcome_unknown")
        elif remote.state != "absent" or remote.job_id is not None:
            raise ZeemanZeusError("remote_response_invalid")
        expires = self.clock() + _LIFETIME
        pending = _Pending(
            session_digest,
            profile,
            package,
            nonce,
            expires,
            remote_job_id=remote.job_id,
        )
        try:
            token = self._previews.add(pending, expires_at=expires, capacity=_CAPACITY)
        except OverflowError as error:
            raise ZeemanZeusError("too_many_pending_previews") from error
        return {
            "preview_token": token,
            "expires_in_seconds": _LIFETIME,
            "run_id": run_id,
            "job": {"kind": "scalar", "array": False, "pbs_sha256": package.pbs_sha256},
            "package_sha256": package.package_sha256,
            "submission_key": package.submission_key,
            "effects": {
                "submit_one_job": remote.job_id is None,
                "reconcile_existing_job": remote.job_id is not None,
                "cancel_job": False,
            },
        }

    def confirm(self, *, preview_token: str, session: str) -> dict[str, Any]:
        digest = self._session(session)
        if (
            not isinstance(preview_token, str)
            or not preview_token
            or len(preview_token.encode()) > 512
        ):
            raise ZeemanZeusError("confirmation_invalid")
        with self._lock:
            record = self._previews.get(preview_token)
            pending = record.value if record is not None else None
            if pending is None or not secrets.compare_digest(
                pending.session_digest, digest
            ):
                raise ZeemanZeusError("confirmation_invalid")
            if pending.result is not None:
                return dict(pending.result)
            if pending.terminal_error is not None:
                raise ZeemanZeusError(pending.terminal_error)
            if self.clock() > pending.expires_at:
                self._previews.pop(preview_token)
                raise ZeemanZeusError("confirmation_expired")
            evidence, lease = self._evidence(pending.package.run_id)
            if (
                self._build_package(
                    evidence,
                    pending.profile,
                    require_configured=pending.remote_job_id is None,
                )
                != pending.package
            ):
                raise ZeemanZeusError("run_evidence_changed")
            transport = self._transport(self.transport_factory(pending.profile))
            if pending.remote_job_id is None:
                binding_store = self.store_factory(self.root)
                try:
                    if not isinstance(binding_store, ZeusBindingStore):
                        raise ZeemanZeusError("submission_identity_unavailable")
                    binding_store.bind(
                        self.authority, pending.package, pending.nonce, lease
                    )
                    evidence, lease = binding_store.evidence_snapshot(
                        self.authority,
                        self.family,
                        pending.package.run_id,
                        prior_lease=lease,
                        allow_run_metadata_change=True,
                    )
                finally:
                    binding_store.close()
                try:
                    staged = transport.stage(
                        package=pending.package, nonce=pending.nonce
                    )
                    if staged.state != "absent" or staged.nonce != pending.nonce:
                        raise ZeemanZeusError("remote_stage_invalid")
                    remote = transport.submit(
                        package=pending.package, nonce=pending.nonce
                    )
                except Exception:
                    self._previews.replace(
                        preview_token,
                        replace(pending, terminal_error="submission_outcome_unknown"),
                    )
                    self._mark_unknown(evidence, lease, "submission_outcome_unknown")
                    raise ZeemanZeusError("submission_outcome_unknown") from None
            else:
                remote = RemoteSubmission(
                    "submitted", pending.nonce, pending.remote_job_id
                )
            if (
                remote.state != "submitted"
                or remote.nonce != pending.nonce
                or remote.job_id is None
                or not _JOB_ID.fullmatch(remote.job_id)
            ):
                self._previews.replace(
                    preview_token,
                    replace(pending, terminal_error="submission_outcome_unknown"),
                )
                self._mark_unknown(evidence, lease, "submission_outcome_unknown")
                raise ZeemanZeusError("submission_outcome_unknown")
            binding_store = self.store_factory(self.root)
            try:
                if not isinstance(binding_store, ZeusBindingStore):
                    raise ZeemanZeusError("submission_identity_unavailable")
                binding_store.bind_job(
                    self.authority,
                    pending.package,
                    pending.nonce,
                    remote.job_id,
                    lease,
                )
                evidence, lease = binding_store.evidence_snapshot(
                    self.authority,
                    self.family,
                    pending.package.run_id,
                    prior_lease=lease,
                    allow_run_metadata_change=True,
                )
            finally:
                binding_store.close()
            store = self.store_factory(self.root)
            try:
                try:
                    current = evidence["status"]
                    for state in ("validated", "reviewed"):
                        if current["state"] == state:
                            continue
                        current = store.transition(
                            self.authority,
                            self.family,
                            pending.package.run_id,
                            expected_revision=current["revision"],
                            target_state=state,
                            updated_utc=self.utc_clock(),
                            lease=lease,
                        )
                        evidence, lease = store.evidence_snapshot(
                            self.authority,
                            self.family,
                            pending.package.run_id,
                            prior_lease=lease,
                            allow_run_metadata_change=True,
                        )
                    current = store.transition(
                        self.authority,
                        self.family,
                        pending.package.run_id,
                        expected_revision=current["revision"],
                        target_state="queued",
                        updated_utc=self.utc_clock(),
                        zeus_job_id=remote.job_id,
                        lease=lease,
                    )
                except Exception:
                    # qsub has already returned a job id.  Any inability to bind
                    # it durably is terminal for this nonce; never submit again.
                    self._previews.replace(
                        preview_token,
                        replace(pending, terminal_error="submission_outcome_unknown"),
                    )
                    raise ZeemanZeusError("submission_outcome_unknown") from None
            finally:
                store.close()
            result = {
                "status": "submitted",
                "run_id": pending.package.run_id,
                "job_id": remote.job_id,
                "submission_key": pending.package.submission_key,
            }
            self._previews.replace(preview_token, replace(pending, result=result))
            return result

    def _mark_unknown(self, evidence, lease, code: str) -> None:
        store = self.store_factory(self.root)
        try:
            current = evidence["status"]
            for state in ("validated", "reviewed", "queued", "outcome_unknown"):
                current = store.transition(
                    self.authority,
                    self.family,
                    evidence["run"]["run_id"],
                    expected_revision=current["revision"],
                    target_state=state,
                    updated_utc=self.utc_clock(),
                    lease=lease,
                    error=(
                        {"code": code, "message": "Zeus submission outcome is unknown."}
                        if state == "outcome_unknown"
                        else None
                    ),
                )
                if state != "outcome_unknown":
                    evidence, lease = store.evidence_snapshot(
                        self.authority,
                        self.family,
                        evidence["run"]["run_id"],
                        prior_lease=lease,
                        allow_run_metadata_change=True,
                    )
        finally:
            store.close()

    def refresh(self, *, run_id: str, profile: ZeusProfile) -> dict[str, Any]:
        try:
            evidence, lease = self._evidence(run_id)
        except (OSError, RunRecordError, KeyError, TypeError, ValueError) as error:
            raise ZeemanZeusError("profile_or_submission_identity_mismatch") from error
        status = evidence["status"]
        binding_store = self.store_factory(self.root)
        try:
            binding = (
                binding_store.read_binding(
                    self.authority, run_id, lease, family=self.family
                )
                if isinstance(binding_store, ZeusBindingStore)
                else None
            )
        finally:
            binding_store.close()
        if (
            binding is None
            or type(profile) is not ZeusProfile
            or binding["username"] != profile.username
            or binding["project_directory"] != profile.project_directory
        ):
            raise ZeemanZeusError("profile_or_submission_identity_mismatch")
        if status["state"] in {"succeeded", "failed", "outcome_unknown", "cancelled"}:
            return {
                "state": status["state"],
                "job_id": status["execution"]["zeus_job_id"],
            }
        job_id = status["execution"]["zeus_job_id"]
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise ZeemanZeusError("job_id_unavailable")
        package = self._build_package(evidence, profile, require_configured=False)
        expected_binding = ZeusBindingStore._binding(
            package, binding["nonce"], binding["job_id"]
        )
        if binding != expected_binding or binding["job_id"] != job_id:
            raise ZeemanZeusError("profile_or_submission_identity_mismatch")
        transport = self._transport(self.transport_factory(profile))
        remote = transport.status(job_id=job_id, submission_key=package.submission_key)
        if remote.job_id != job_id or remote.state not in _REMOTE_STATES:
            raise ZeemanZeusError("remote_status_invalid")
        store = self.store_factory(self.root)
        try:
            current = status
            if remote.state == "queued":
                return {"state": "queued", "job_id": job_id}
            if current["state"] == "queued":
                current = store.transition(
                    self.authority,
                    self.family,
                    run_id,
                    expected_revision=current["revision"],
                    target_state="running",
                    updated_utc=self.utc_clock(),
                    lease=lease,
                )
                evidence, lease = store.evidence_snapshot(
                    self.authority,
                    self.family,
                    run_id,
                    prior_lease=lease,
                    allow_run_metadata_change=True,
                )
            if remote.state == "running":
                return {"state": "running", "job_id": job_id}
            if remote.state == "failed" or remote.exit_status not in (None, 0):
                current = store.transition(
                    self.authority,
                    self.family,
                    run_id,
                    expected_revision=current["revision"],
                    target_state="failed",
                    updated_utc=self.utc_clock(),
                    lease=lease,
                    error={
                        "code": "zeus_job_failed",
                        "message": "The Zeus job failed.",
                    },
                )
                return {"state": current["state"], "job_id": job_id}
            try:
                product = transport.retrieve(
                    job_id=job_id,
                    submission_key=package.submission_key,
                    package_sha256=package.package_sha256,
                )
                if not isinstance(product, WorkerProduct):
                    raise TypeError
                store.publish_worker_artifacts(
                    self.authority,
                    self.family,
                    run_id,
                    expected_revision=current["revision"],
                    product=product,
                    lease=lease,
                )
                final = store.publish_success(
                    self.authority,
                    self.family,
                    run_id,
                    product=product,
                    updated_utc=self.utc_clock(),
                    lease=lease,
                )
            except ZeemanZeusError:
                # A read-only transport failure happened before artifact
                # publication. Keep the bound job retryable; never resubmit it.
                raise
            except WorkerProductError:
                final = store.transition(
                    self.authority,
                    self.family,
                    run_id,
                    expected_revision=current["revision"],
                    target_state="failed",
                    updated_utc=self.utc_clock(),
                    lease=lease,
                    error={
                        "code": "invalid_worker_output",
                        "message": "Zeus output failed D3 validation.",
                    },
                )
            except RunRecordError:
                raise
            except Exception:
                final = store.transition(
                    self.authority,
                    self.family,
                    run_id,
                    expected_revision=current["revision"],
                    target_state="outcome_unknown",
                    updated_utc=self.utc_clock(),
                    lease=lease,
                    error={
                        "code": "retrieval_outcome_unknown",
                        "message": "Zeus result retrieval is uncertain.",
                    },
                )
            return {"state": final["state"], "job_id": job_id}
        finally:
            store.close()

    def recover(
        self,
        *,
        run_id: str,
        profile: ZeusProfile,
        session: str,
    ) -> dict[str, Any]:
        """Verify one durable Zeus binding without changing local or remote state."""
        self._session(session)
        if not isinstance(run_id, str) or type(profile) is not ZeusProfile:
            raise ZeemanZeusError("recovery_request_invalid")
        try:
            if (
                ZeusProfile.parse(
                    {
                        "username": profile.username,
                        "project_directory": profile.project_directory,
                    }
                )
                != profile
            ):
                raise ValueError
        except ValueError as error:
            raise ZeemanZeusError("profile_invalid") from error

        try:
            evidence, lease = self._evidence(run_id)
        except (OSError, RunRecordError, KeyError, TypeError, ValueError) as error:
            raise ZeemanZeusError("profile_or_submission_identity_mismatch") from error
        binding_store = self.store_factory(self.root)
        try:
            binding = (
                binding_store.read_binding(
                    self.authority, run_id, lease, family=self.family
                )
                if isinstance(binding_store, ZeusBindingStore)
                else None
            )
        except RunRecordError as error:
            raise ZeemanZeusError("submission_identity_invalid") from error
        finally:
            binding_store.close()
        status = evidence["status"]
        expected_job_id = binding["job_id"] if binding is not None else None
        submission_key = binding["submission_key"] if binding is not None else None
        if (
            binding is None
            or binding["username"] != profile.username
            or binding["project_directory"] != profile.project_directory
            or not isinstance(expected_job_id, str)
            or _JOB_ID.fullmatch(expected_job_id) is None
            or not isinstance(submission_key, str)
            or re.fullmatch(r"[0-9a-f]{64}", submission_key) is None
            or status["execution"]
            != {"mode": "zeus", "local_pid": None, "zeus_job_id": expected_job_id}
        ):
            raise ZeemanZeusError("profile_or_submission_identity_mismatch")
        package = self._build_package(evidence, profile, require_configured=False)
        if (
            binding
            != ZeusBindingStore._binding(package, binding["nonce"], expected_job_id)
            or package.submission_key != submission_key
        ):
            raise ZeemanZeusError("profile_or_submission_identity_mismatch")
        transport = self._transport(self.transport_factory(profile))
        remote = transport.status(job_id=expected_job_id, submission_key=submission_key)
        if (
            remote.job_id != expected_job_id
            or remote.state not in _REMOTE_STATES
            or (remote.exit_status is not None and type(remote.exit_status) is not int)
        ):
            raise ZeemanZeusError("remote_status_invalid")
        return {
            "run_id": run_id,
            "family": self.family,
            "job_id": expected_job_id,
            "scheduler_state": remote.state,
            "exit_status": remote.exit_status,
            "local_state": status["state"],
            "read_only": True,
        }

    family = "zeeman"

    def _build_package(self, evidence, profile, *, require_configured=True):
        return build_frozen_package(
            evidence, profile, require_configured=require_configured
        )
