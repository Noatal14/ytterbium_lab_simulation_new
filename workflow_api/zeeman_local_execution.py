"""Bounded local execution adapter for reviewed individual Zeeman runs.

This module is deliberately below the HTTP boundary.  It accepts only the
immutable E3 ``WorkerRequest`` and calls the existing Zeeman engine exactly
once.  The background pool owns concurrency; callers cannot provide a module,
callable, command, working directory, environment, or argument vector.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import math
from pathlib import Path
import threading
import time
from typing import Any, Callable, Mapping, Protocol

import numpy as np

from config import (
    FORCE_SCALE_N,
    MOT_2D_LASER_CONFIG,
    MOT_2D_MAGNET_RADIUS_M,
    ZEEMAN_LASER_CONFIG,
    ZEEMAN_SIM_CONFIG,
)
from lab_setup.mag_field_Zeeman import resolved_zeeman_field_construction
from lab_setup.physical_specification import LABORATORY_PHYSICAL_SPECIFICATION
from lab_setup.zeeman_laser_setup import resolved_zeeman_laser_parameters
from workflow_api.run_execution import (
    ExecutionAuthority,
    IndividualRunExecutionCoordinator,
    WorkerProduct,
    WorkerProductError,
    WorkerRequest,
)
from workflow_api.run_records import RunRecordError, RunRecordStore, encode_record
from workflow_api.run_specification import INDIVIDUAL_RUN_SPECIFICATION
from workflow_api.run_progress import IndividualRunProgressRegistry
from workflow_api.zeeman_run_specification import (
    ZEEMAN_RUN_SPECIFICATION,
    local_worker_maximum,
)


class ZeemanEngine(Protocol):
    def __call__(self, **kwargs: Any) -> tuple[Any, Any, Any]: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trusted_engine(**kwargs: Any):
    # Lazy import keeps server startup and non-execution tests free of the
    # heavyweight physics runtime while fixing the production module/function.
    from simulations.zeeman import zeeman_simulation

    return zeeman_simulation(**kwargs)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain(child) for child in value]
    return value


class ZeemanLocalWorker:
    """Translate one reviewed local plan into one trusted engine invocation."""

    def __init__(
        self,
        *,
        engine: ZeemanEngine = _trusted_engine,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._engine = engine
        self._monotonic = monotonic
        self._clock = clock
        self._progress_callback: Callable[[int, int], None] | None = None

    def set_progress_callback(self, callback: Callable[[int, int], None] | None) -> None:
        self._progress_callback = callback

    def run(self, request: WorkerRequest) -> WorkerProduct:
        run = request.run
        resolved = request.configuration["resolved"]
        simulation = resolved["simulation"]
        execution = resolved["execution"]
        numerical = resolved["numerical_policy"]
        source = resolved["source"]
        mode = run["execution_mode"]
        if run["family"] != "zeeman" or mode not in {"local", "zeus"}:
            raise WorkerProductError("Local Zeeman worker received the wrong run family or mode.")
        worker_policy = ZEEMAN_RUN_SPECIFICATION["worker_policy"]
        workers_valid = (
            worker_policy["local"]["minimum"]
            <= execution["workers"]
            <= local_worker_maximum(simulation["particle_count"])
            if mode == "local"
            else execution["workers"] == worker_policy["zeus"]["fixed"]
        )
        if execution["mode"] != mode or not workers_valid:
            raise WorkerProductError("Local worker count is not the server-owned policy value.")
        if simulation["particle_count"] != run["particle_count"]:
            raise WorkerProductError("Reviewed particle count is inconsistent.")
        field = _plain(resolved["zeeman"]["field"])
        laser = _plain(resolved["zeeman"]["laser"])
        downstream = _plain(resolved["downstream_boundary"])
        from workflow_api.zeeman_run_plan import validate_zeeman_laser_controls
        try:
            s0, detuning = validate_zeeman_laser_controls(laser["s0"], laser["detuning_gamma"])
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            raise WorkerProductError("Reviewed Zeeman laser controls are invalid.") from exc
        expected_laser = resolved_zeeman_laser_parameters(**{**ZEEMAN_LASER_CONFIG, "s0": s0, "detuning_gamma": detuning})
        expected_field = resolved_zeeman_field_construction(
            radii_m=field["radii_m"],
            positions_m=field["positions_m"],
            tilt_angles_deg=field["tilt_angles_deg"],
            angle_deg=LABORATORY_PHYSICAL_SPECIFICATION["apparatus"][
                "zeeman_arm_angle_deg"
            ],
            start_distance_m=LABORATORY_PHYSICAL_SPECIFICATION["apparatus"][
                "zeeman_start_distance_m"
            ],
        )
        if (
            laser != expected_laser
            or field != expected_field
            or downstream["mot_2d_laser"].get("swap_polarization") is not False
            or numerical["solver"] != "RK4StCustom"
            or numerical["dt_s"] != ZEEMAN_SIM_CONFIG["dt_s"]
            or numerical["t_max_s"] != ZEEMAN_SIM_CONFIG["t_max_s"]
            or simulation["start_distance_m"] != ZEEMAN_SIM_CONFIG["start_distance_m"]
            or simulation["cutoff_distance_m"] != ZEEMAN_SIM_CONFIG["cutoff_distance_m"]
            or simulation["force_scale_N"] != FORCE_SCALE_N
        ):
            raise WorkerProductError(
                "Reviewed Zeeman construction differs from the trusted runtime."
            )

        started = self._monotonic()
        outcome = self._engine(
            N_particles=simulation["particle_count"],
            _2d_mot_config=downstream["mot_2d_laser"],
            zeeman_config={
                "s0": laser["s0"],
                "detuning_gamma": laser["detuning_gamma"],
                "polarization": laser["polarization"],
            },
            zeeman_field_config=field,
            magnet_radius=downstream["mot_2d_magnet_radius_m"],
            gravity_enabled=simulation["gravity_enabled"],
            npools=execution["workers"],
            stochastic=simulation["stochastic"],
            dt=numerical["dt_s"],
            collimation_angle_deg=source["collimation_angle_deg"],
            angular_broadening_factor=source["angular_broadening_factor"],
            seed=simulation["seed"],
            t_max_s=numerical["t_max_s"],
            start_distance_m=simulation["start_distance_m"],
            cutoff_distance_m=simulation["cutoff_distance_m"],
            **({"progress_callback": self._progress_callback} if self._progress_callback is not None else {}),
        )
        elapsed = self._monotonic() - started
        if (
            not isinstance(outcome, tuple)
            or len(outcome) != 3
            or isinstance(elapsed, bool)
            or not math.isfinite(elapsed)
            or elapsed < 0
        ):
            raise WorkerProductError("Zeeman engine returned an invalid outcome.")
        _trajectories, survivor_value, survivor_indices = outcome
        survivors = np.asarray(survivor_value)
        if (
            survivors.dtype != np.dtype(np.float64)
            or survivors.ndim != 2
            or survivors.shape[1] != 6
            or not np.all(np.isfinite(survivors))
        ):
            raise WorkerProductError("Zeeman survivor states must be finite float64 N x 6.")
        count = int(survivors.shape[0])
        initial = int(run["particle_count"])
        indices = np.asarray(survivor_indices)
        if (
            indices.ndim != 1
            or len(indices) != count
            or not np.issubdtype(indices.dtype, np.integer)
            or (count and (int(indices.min()) < 0 or int(indices.max()) >= initial))
            or len(np.unique(indices)) != count
        ):
            raise WorkerProductError("Zeeman survivor indices are inconsistent.")

        completed = self._clock()
        retained = bool(run["retention"]["particle_states"])
        artifacts: dict[str, bytes] = {}
        receipt: dict[str, Any] | None = None
        registry: list[dict[str, Any]] = []
        if retained:
            stream = BytesIO()
            np.save(stream, np.ascontiguousarray(survivors), allow_pickle=False)
            states = stream.getvalue()
            artifacts["results/states.npy"] = states
            registry.append(
                {
                    "kind": "particle_states",
                    "path": "results/states.npy",
                    "sha256": hashlib.sha256(states).hexdigest(),
                    "size_bytes": len(states),
                }
            )
        else:
            receipt = {
                "schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"][
                    "retention_receipt"
                ],
                "run_id": run["run_id"],
                "created_utc": completed,
                "reason": "particle_states_not_retained",
            }
            receipt_bytes = encode_record("retention_receipt", receipt)
            registry.append(
                {
                    "kind": "retention_receipt",
                    "path": "results/state_retention_receipt.json",
                    "sha256": hashlib.sha256(receipt_bytes).hexdigest(),
                    "size_bytes": len(receipt_bytes),
                }
            )
        metrics = {
            "n_initial": initial,
            "n_survivors": count,
            "captured": count,
            "survival_fraction": count / initial,
            "elapsed_s": float(elapsed),
        }
        return WorkerProduct(
            results={
                "schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"][
                    "results"
                ],
                "run_id": run["run_id"],
                "completed_utc": completed,
                "states_retained": retained,
                "suitability": "individual_only",
                "metrics": metrics,
                "artifacts": registry,
            },
            receipt=receipt,
            artifacts=artifacts,
        )


@dataclass(frozen=True)
class LocalExecutionHandle:
    family: str
    run_id: str
    future: Future[dict[str, Any]]


class BoundedLocalExecutionPool:
    """Server-owned bounded background pool with conservative cancellation."""

    def __init__(
        self,
        repository_root: Path,
        authority: ExecutionAuthority,
        *,
        max_concurrent: int = 1,
        max_pending: int = 8,
        worker_factory: Callable[[], ZeemanLocalWorker] = ZeemanLocalWorker,
        coordinator_factory: Callable[..., IndividualRunExecutionCoordinator] = (
            IndividualRunExecutionCoordinator
        ),
        allowed_family: str = "zeeman",
        thread_name_prefix: str = "zeeman-local",
        progress_registry: IndividualRunProgressRegistry | None = None,
    ) -> None:
        if (
            isinstance(max_concurrent, bool)
            or not isinstance(max_concurrent, int)
            or not 1 <= max_concurrent <= 4
            or isinstance(max_pending, bool)
            or not isinstance(max_pending, int)
            or not max_concurrent <= max_pending <= 32
        ):
            raise ValueError("Local execution bounds are invalid.")
        self._root = repository_root.resolve(strict=True)
        self._authority = authority
        self._worker_factory = worker_factory
        self._coordinator_factory = coordinator_factory
        self._allowed_family = allowed_family
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent, thread_name_prefix=thread_name_prefix
        )
        self._slots = threading.BoundedSemaphore(max_pending)
        self._lock = threading.RLock()
        self._handles: dict[tuple[str, str], LocalExecutionHandle] = {}
        self._cancelling: set[tuple[str, str]] = set()
        self._closed = False
        self._failures: dict[tuple[str, str], str] = {}
        self._failure_limit = max_pending
        self._progress_registry = progress_registry

    def submit(self, family: str, run_id: str) -> LocalExecutionHandle:
        if family != self._allowed_family:
            raise ValueError("This pool received the wrong individual-run family.")
        with self._lock:
            if self._closed:
                raise RuntimeError("Local execution pool is closed.")
            key = (family, run_id)
            if key in self._failures:
                raise RuntimeError("Local execution failed; explicit recovery is required.")
            if key in self._cancelling:
                raise RuntimeError("This run is already scheduled locally.")
            existing = self._handles.get(key)
            if existing is not None:
                raise RuntimeError("This run is already scheduled locally.")
            if not self._slots.acquire(blocking=False):
                raise RuntimeError("Local execution queue is full.")
            observed = False
            try:
                if self._progress_registry is not None:
                    self._progress_registry.schedule(family, run_id)
                    observed = True
                future = self._executor.submit(self._execute, family, run_id)
            except BaseException:
                if observed:
                    self._progress_registry.finish(family, run_id)
                self._slots.release()
                raise
            handle = LocalExecutionHandle(family, run_id, future)
            self._handles[key] = handle
            future.add_done_callback(lambda completed: self._release(key, completed))
            return handle

    def _execute(self, family: str, run_id: str) -> dict[str, Any]:
        callback = None
        if self._progress_registry is not None:
            store = RunRecordStore(self._root)
            try:
                total = int(store.read(family, run_id, "run")["particle_count"])
            finally:
                store.close()
            self._progress_registry.start(family, run_id, total)
            callback = lambda completed, observed_total: self._progress_registry.update(
                family, run_id, completed, observed_total
            )
        coordinator = self._coordinator_factory(
            self._root, self._worker_factory(), self._authority,
            **({"progress_callback": callback} if callback is not None else {}),
        )
        return coordinator.execute(family, run_id)

    def _release(self, key: tuple[str, str], future: Future[dict[str, Any]]) -> None:
        with self._lock:
            current = self._handles.get(key)
            if current is None or current.future is not future:
                return
            self._handles.pop(key, None)
            self._slots.release()
            if self._progress_registry is not None:
                self._progress_registry.finish(*key)
            if key not in self._cancelling and not future.cancelled():
                error = future.exception()
                if error is not None:
                    # Keep bounded, traceback-free diagnostics after removing
                    # the Future, and never silently resubmit this failed key.
                    self._failures[key] = type(error).__name__[:128]
                    if self._progress_registry is not None:
                        self._progress_registry.fail(*key, "background_execution_failed")
                    if len(self._failures) >= self._failure_limit:
                        self._closed = True

    def failure(self, family: str, run_id: str) -> str | None:
        """Return non-authoritative background failure diagnostics."""
        with self._lock:
            return self._failures.get((family, run_id))

    def cancel_queued(self, family: str, run_id: str, *, updated_utc: str) -> bool:
        """Cancel only work proven not to have started; never guess about running work."""
        key = (family, run_id)
        with self._lock:
            handle = self._handles.get(key)
            if handle is None:
                return False
            self._cancelling.add(key)
            if not handle.future.cancel():
                self._cancelling.discard(key)
                return False
        store = RunRecordStore(self._root)
        try:
            current = store.read(family, run_id, "status")
            if current["state"] != "configured":
                raise RunRecordError("Queued cancellation lost its lifecycle race.")
            cancelled = {
                **current,
                "revision": current["revision"] + 1,
                "state": "cancelled",
                "updated_utc": updated_utc,
            }
            store.update_status(family, run_id, cancelled)
        finally:
            store.close()
            with self._lock:
                self._handles.pop(key, None)
                self._cancelling.discard(key)
        return True

    def close(self, *, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=False)
