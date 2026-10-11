"""Session-bound preview/confirm boundary for one individual Zeeman run.

Preview is pure.  Confirmation publishes only the configured D2 record package;
it never starts a process, contacts Zeus, or advances the run lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Callable, Mapping, Protocol

from workflow_api.preview_registry import PreviewRegistry
from workflow_api.repository_snapshot import RepositorySnapshot
from workflow_api.run_records import RunRecordStore
from workflow_api.zeeman_run_plan import ZeemanRunPlan, build_zeeman_run_plan


_PREVIEW_LIFETIME_SECONDS = 300
_PREVIEW_CAPACITY = 64
_TOKEN_MAXIMUM_BYTES = 512
_SESSION_MAXIMUM_BYTES = 512
_REQUESTS_PER_MINUTE = 12
_RATE_LIMIT_SESSION_CAPACITY = 1_024


class SnapshotProvider(Protocol):
    def capture(self) -> RepositorySnapshot: ...


class RecordStore(Protocol):
    def create(
        self,
        run: Mapping[str, Any],
        configuration: Mapping[str, Any],
        inputs: Mapping[str, Any],
        status: Mapping[str, Any],
    ) -> Path: ...

    def close(self) -> None: ...


@dataclass
class _PendingZeemanRun:
    expires_at: float
    session_digest: str
    request: dict[str, Any]
    run_id: str
    created_utc: str
    snapshot: RepositorySnapshot
    plan_sha256: str
    consumed: bool = False
    result: dict[str, Any] | None = None


def _bounded_digest(value: str, *, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not value.isprintable()
        or len(value.encode("utf-8")) > maximum
    ):
        raise PermissionError(f"{label} is invalid.")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _default_run_id() -> str:
    return f"zeeman-{secrets.token_hex(12)}"


def _default_created_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview_dto(plan: ZeemanRunPlan) -> dict[str, Any]:
    records = plan.storage_records()
    configuration = records["configuration"]
    return {
        "run_id": records["run"]["run_id"],
        "family": "zeeman",
        "execution_mode": plan.review.execution_mode,
        "particle_count": plan.review.particle_count,
        "seed": plan.review.seed,
        "retain_particle_states": plan.review.retain_particle_states,
        "suitability": plan.review.suitability,
        "output_disposition": plan.review.output_disposition,
        "locked_settings": dict(plan.review.locked_settings),
        # The complete E1-resolved scientific/operational configuration is
        # review evidence.  It is detached from the immutable plan records and
        # cryptographically bound by plan_sha256 below.
        "resolved_configuration": configuration["resolved"],
        "lifecycle_state": "configured",
        "laboratory_specification": dict(configuration["laboratory_spec"]),
        "numerical_policy": dict(configuration["numerical_policy"]),
        "plan_sha256": plan.plan_sha256,
        "execution_started": False,
        "submitted_to_zeus": False,
    }


class ZeemanRunCreationService:
    """Create a configured Zeeman run only from fresh reviewed evidence."""

    def __init__(
        self,
        repository_root: Path,
        snapshot_provider: SnapshotProvider,
        *,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] | None = None,
        run_id_factory: Callable[[], str] = _default_run_id,
        created_utc_factory: Callable[[], str] = _default_created_utc,
        store_factory: Callable[[Path], RecordStore] = RunRecordStore,
    ) -> None:
        self.root = repository_root.resolve(strict=True)
        self.snapshots = snapshot_provider
        self.clock = clock
        self.run_id_factory = run_id_factory
        self.created_utc_factory = created_utc_factory
        self.store_factory = store_factory
        self._previews = PreviewRegistry[_PendingZeemanRun](
            clock=clock,
            token_factory=token_factory,
        )
        self._lock = threading.RLock()
        self._rate_lock = threading.Lock()
        self._request_times: dict[str, list[float]] = {}

    def _rate_limit(self, session_digest: str) -> None:
        with self._rate_lock:
            now = self.clock()
            active = {
                key: [stamp for stamp in stamps if now - stamp < 60]
                for key, stamps in self._request_times.items()
            }
            active = {key: stamps for key, stamps in active.items() if stamps}
            recent = active.get(session_digest, [])
            if len(recent) >= _REQUESTS_PER_MINUTE:
                self._request_times = active
                raise BlockingIOError("Too many Zeeman creation requests.")
            if (
                session_digest not in active
                and len(active) >= _RATE_LIMIT_SESSION_CAPACITY
            ):
                self._request_times = active
                raise BlockingIOError("Too many active Zeeman creation sessions.")
            recent.append(now)
            active[session_digest] = recent
            self._request_times = active

    def preview(
        self, request: Mapping[str, Any], session: str
    ) -> dict[str, Any]:
        session_digest = _bounded_digest(
            session, label="Session", maximum=_SESSION_MAXIMUM_BYTES
        )
        self._rate_limit(session_digest)
        # Build from a detached shallow copy.  The E1 validator rejects nested or
        # extra request data, and the supported values are JSON scalars.
        detached_request = dict(request)
        before = self.snapshots.capture()
        run_id = self.run_id_factory()
        created_utc = self.created_utc_factory()
        plan = build_zeeman_run_plan(
            detached_request,
            run_id=run_id,
            git_revision=before.commit,
            created_utc=created_utc,
        )
        after = self.snapshots.capture()
        if before != after:
            raise RuntimeError("Repository changed during preview.")
        expires_at = self.clock() + _PREVIEW_LIFETIME_SECONDS
        with self._lock:
            try:
                token = self._previews.add_factory_keyed(
                    lambda _raw: _PendingZeemanRun(
                        expires_at=expires_at,
                        session_digest=session_digest,
                        request=detached_request,
                        run_id=run_id,
                        created_utc=created_utc,
                        snapshot=before,
                        plan_sha256=plan.plan_sha256,
                    ),
                    key_factory=lambda raw: _bounded_digest(
                        raw, label="Preview token", maximum=_TOKEN_MAXIMUM_BYTES
                    ),
                    expires_at=expires_at,
                    capacity=_PREVIEW_CAPACITY,
                    retain_at_expiry=False,
                )
            except OverflowError as error:
                raise RuntimeError("Too many pending Zeeman previews.") from error
        return {
            "preview_token": token,
            "expires_in_seconds": _PREVIEW_LIFETIME_SECONDS,
            "plan": _preview_dto(plan),
        }

    def confirm(self, token: str, session: str) -> dict[str, Any]:
        token_digest = _bounded_digest(
            token, label="Preview token", maximum=_TOKEN_MAXIMUM_BYTES
        )
        session_digest = _bounded_digest(
            session, label="Session", maximum=_SESSION_MAXIMUM_BYTES
        )
        self._rate_limit(session_digest)
        with self._lock:
            registered = self._previews.get(token_digest)
            pending = registered.value if registered is not None else None
            if (
                pending is None
                or pending.session_digest != session_digest
                or pending.expires_at <= self.clock()
            ):
                raise PermissionError("Preview token is invalid or expired.")
            if pending.consumed:
                if pending.result is not None:
                    return dict(pending.result)
                raise RuntimeError("Preview token can no longer be used.")

            # Consumption happens before any mutation.  An uncertain or failed
            # publication is terminal, so a retry cannot create a second run.
            pending.consumed = True
            snapshot = self.snapshots.capture()
            if snapshot != pending.snapshot:
                raise RuntimeError("Preview is stale; review the run again.")
            refreshed = build_zeeman_run_plan(
                pending.request,
                run_id=pending.run_id,
                git_revision=snapshot.commit,
                created_utc=pending.created_utc,
            )
            if refreshed.plan_sha256 != pending.plan_sha256:
                raise RuntimeError("Preview is stale; review the run again.")
            if self.snapshots.capture() != snapshot:
                raise RuntimeError("Repository changed before run creation.")

            records = refreshed.storage_records()
            store = self.store_factory(self.root)
            try:
                destination = store.create(
                    records["run"],
                    records["configuration"],
                    records["inputs"],
                    records["status"],
                )
            finally:
                store.close()
            expected = self.root / "data/runs/zeeman" / pending.run_id
            if destination != expected:
                raise RuntimeError("Run store returned an unexpected destination.")
            result = {
                "status": "created",
                "run_id": pending.run_id,
                "family": "zeeman",
                "path": expected.relative_to(self.root).as_posix(),
                "lifecycle_state": "configured",
                "execution_started": False,
                "submitted_to_zeus": False,
            }
            pending.result = result
            return dict(result)
