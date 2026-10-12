"""Executor-authorized lifecycle and durable D3 result publication.

This boundary is deliberately generic across individual-run families.  It does
not launch processes, contact Zeus, or implement physics.  A worker is an
injected callable; E3 tests use only a tiny in-memory fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import fcntl
import math
import os
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol
from contextlib import contextmanager
import stat

from workflow_api.run_discovery import inspect_run
from workflow_api.run_records import (
    RunRecordError,
    RunRecordStore,
    _TRANSITIONS,
    _parsed_timestamp,
    _publish_no_replace_at,
    _read_record_at,
    _read_regular_at,
    _replace_at,
    encode_record,
    record_sha256,
    validate_record,
)
from workflow_api.run_results import (
    _close_descriptors,
    _open_canonical_run,
    _read_record_at as _read_result_record_at,
    _validate_publication_plan_at,
    _verify_canonical_run,
)
from workflow_api.run_specification import INDIVIDUAL_RUN_SPECIFICATION


_SPEC = INDIVIDUAL_RUN_SPECIFICATION
_AUTHORITY_SEAL = object()
_UNSET = object()
_EXECUTOR_TRANSITIONS = {
    (source, target)
    for source, targets in _TRANSITIONS.items()
    for target in targets
    if (source, target) != ("configured", "cancelled") and target != "succeeded"
}


class ExecutionAuthority:
    """Opaque capability kept outside the generic D2 cancellation surface."""

    __slots__ = ("_seal",)

    def __init__(self, seal: object):
        if seal is not _AUTHORITY_SEAL:
            raise PermissionError("Execution authority cannot be constructed directly.")
        self._seal = seal


def issue_execution_authority() -> ExecutionAuthority:
    """Issue one in-process executor capability at the composition root."""

    return ExecutionAuthority(_AUTHORITY_SEAL)


def _require_authority(value: object) -> None:
    if not isinstance(value, ExecutionAuthority) or value._seal is not _AUTHORITY_SEAL:
        raise PermissionError("Execution authority is required.")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain(child) for child in value]
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class WorkerRequest:
    run: Mapping[str, Any]
    configuration: Mapping[str, Any]
    inputs: Mapping[str, Any]


@dataclass(frozen=True)
class WorkerProduct:
    """Finite worker output; publication remains exclusively coordinator-owned."""

    results: Mapping[str, Any]
    receipt: Mapping[str, Any] | None
    artifacts: Mapping[str, bytes]


@dataclass(frozen=True)
class ExecutionLease:
    family: str
    run_id: str
    directory_identities: tuple[tuple[int, int, int], ...]


class WorkerProductError(RunRecordError):
    """Definite worker-contract rejection before durable publication begins."""


def mot_2d_result_provenance(
    run: Mapping[str, Any], configuration: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the exact provenance object required for individual 2D results."""
    resolved = configuration["resolved"]
    sampling = resolved["sampling"]
    source = resolved["input_source"]
    controls = resolved["mot_2d"]
    return {
        "git_revision": run["git_revision"],
        "configuration_sha256": run["configuration_sha256"],
        "inputs_sha256": run["inputs_sha256"],
        "laboratory_spec_sha256": configuration["laboratory_spec"]["sha256"],
        "numerical_policy_sha256": configuration["numerical_policy"]["sha256"],
        "admission_specification_sha256": resolved["admission_specification"]["sha256"],
        "source_id": source["id"],
        "source_fingerprint": source["fingerprint"],
        "selection_algorithm": sampling["algorithm"],
        "selection_version": sampling["version"],
        "selection_seed": sampling["selection_seed"],
        "mot_seed": resolved["simulation"]["mot_seed"],
        "s0": controls["laser"]["s0"],
        "detuning_gamma": controls["laser"]["detuning_gamma"],
        "magnet_radius_m": controls["magnet_radius_m"],
        "solver": resolved["numerical_policy"]["solver"],
        "timestep_s": resolved["numerical_policy"]["dt_s"],
        "capture_criterion_version": controls["capture_criterion_version"],
    }


def mot_3d_result_provenance(
    run: Mapping[str, Any], configuration: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the exact provenance object required for individual 3D results."""
    resolved = configuration["resolved"]
    return {
        "git_revision": run["git_revision"],
        "configuration_sha256": run["configuration_sha256"],
        "inputs_sha256": run["inputs_sha256"],
        "laboratory_spec_sha256": configuration["laboratory_spec"]["sha256"],
        "numerical_policy_sha256": configuration["numerical_policy"]["sha256"],
        "admission_specification_sha256": resolved["admission_specification"]["sha256"],
        "source_id": resolved["input_source"]["id"],
        "source_fingerprint": resolved["input_source"]["fingerprint"],
        "selection_algorithm": resolved["sampling"]["algorithm"],
        "selection_version": resolved["sampling"]["version"],
        "selection_seed": resolved["sampling"]["selection_seed"],
        "simulation_seed": resolved["simulation"]["simulation_seed"],
        "geometry_family": resolved["mot_3d"]["geometry_family"],
        "solver": resolved["numerical_policy"]["solver"],
        "timestep_s": resolved["numerical_policy"]["dt_s"],
        "t_max_s": resolved["numerical_policy"]["t_max_s"],
        "convergence_claim": resolved["numerical_policy"]["convergence_claim"],
    }


def _validate_family_metrics(
    family: str,
    run: Mapping[str, Any],
    results: Mapping[str, Any],
    configuration: Mapping[str, Any] | None = None,
) -> None:
    """Enforce family-specific scientific relationships before publication."""
    if family == "mot_3d":
        if configuration is None:
            raise WorkerProductError("3D-MOT result validation requires configuration evidence.")
        metrics = results["metrics"]
        expected = {
            "n_input", "usable_at_end_count", "usable_at_end_fraction",
            "residence_qualified_captured_count",
            "residence_qualified_captured_fraction", "elapsed_s",
            "selection_sha256", "provenance",
        }
        resolved = configuration["resolved"]
        n_input = metrics.get("n_input")
        usable = metrics.get("usable_at_end_count")
        captured = metrics.get("residence_qualified_captured_count")
        elapsed = metrics.get("elapsed_s")
        if (
            set(metrics) != expected
            or isinstance(n_input, bool) or not isinstance(n_input, int)
            or n_input != run["particle_count"]
            or n_input != resolved["sampling"]["selected_count"]
            or isinstance(usable, bool) or not isinstance(usable, int)
            or isinstance(captured, bool) or not isinstance(captured, int)
            or not 0 <= captured <= usable <= n_input
            or metrics.get("usable_at_end_fraction") != usable / n_input
            or metrics.get("residence_qualified_captured_fraction") != captured / n_input
            or isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
            or not math.isfinite(float(elapsed)) or elapsed < 0
            or metrics.get("selection_sha256") != resolved["sampling"]["selected_identities_sha256"]
            or metrics.get("provenance") != mot_3d_result_provenance(run, configuration)
        ):
            raise WorkerProductError("3D-MOT result metrics are scientifically inconsistent.")
        return
    if family == "mot_2d":
        if configuration is None:
            raise WorkerProductError("2D-MOT result validation requires configuration evidence.")
        metrics = results["metrics"]
        expected = {
            "n_input", "n_survivors", "conditional_efficiency", "elapsed_s",
            "selection_sha256", "provenance",
        }
        resolved = configuration["resolved"]
        sampling = resolved["sampling"]
        expected_provenance = mot_2d_result_provenance(run, configuration)
        n_input = metrics.get("n_input")
        n_survivors = metrics.get("n_survivors")
        efficiency = metrics.get("conditional_efficiency")
        elapsed = metrics.get("elapsed_s")
        if (
            set(metrics) != expected
            or isinstance(n_input, bool)
            or not isinstance(n_input, int)
            or n_input != run["particle_count"]
            or n_input != sampling["selected_count"]
            or isinstance(n_survivors, bool)
            or not isinstance(n_survivors, int)
            or not 0 <= n_survivors <= n_input
            or isinstance(efficiency, bool)
            or not isinstance(efficiency, (int, float))
            or not math.isfinite(float(efficiency))
            or float(efficiency) != n_survivors / n_input
            or isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(float(elapsed))
            or elapsed < 0
            or metrics.get("selection_sha256")
            != sampling["selected_identities_sha256"]
            or metrics.get("provenance") != expected_provenance
        ):
            raise WorkerProductError("2D-MOT result metrics are scientifically inconsistent.")
        return
    if family != "zeeman":
        return
    metrics = results["metrics"]
    expected = {
        "n_initial",
        "n_survivors",
        "captured",
        "survival_fraction",
        "elapsed_s",
    }
    if set(metrics) != expected:
        raise WorkerProductError("Zeeman result metrics are incomplete or unexpected.")
    n_initial = metrics["n_initial"]
    n_survivors = metrics["n_survivors"]
    captured = metrics["captured"]
    elapsed = metrics["elapsed_s"]
    fraction = metrics["survival_fraction"]
    if (
        isinstance(n_initial, bool)
        or not isinstance(n_initial, int)
        or n_initial != run["particle_count"]
        or isinstance(n_survivors, bool)
        or not isinstance(n_survivors, int)
        or not 0 <= n_survivors <= n_initial
        or captured != n_survivors
        or isinstance(fraction, bool)
        or not isinstance(fraction, (int, float))
        or not math.isfinite(float(fraction))
        or float(fraction) != n_survivors / n_initial
        or isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(float(elapsed))
        or elapsed < 0
    ):
        raise WorkerProductError("Zeeman result metrics are scientifically inconsistent.")


class IndividualRunWorker(Protocol):
    def run(self, request: WorkerRequest) -> WorkerProduct: ...


class WorkerFailed(Exception):
    """A worker reported a definite, safely classifiable failure."""


class WorkerOutcomeUnknown(Exception):
    """A worker may have acted, but no trustworthy outcome is available."""


class ExecutorLifecycleStore(RunRecordStore):
    """CAS lifecycle writer unavailable from the generic D2 store API."""

    @contextmanager
    def _execution_locked_at(self, parent: int):
        """Lock one held run while preserving protected-body exceptions."""
        descriptor: int | None = None
        try:
            descriptor = os.open(
                ".records.lock",
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent,
            )
            opened = os.fstat(descriptor)
            current = os.stat(
                ".records.lock", dir_fd=parent, follow_symlinks=False
            )
            if not stat.S_ISREG(opened.st_mode) or (
                current.st_dev,
                current.st_ino,
            ) != (opened.st_dev, opened.st_ino):
                raise OSError("untrusted lock")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = os.stat(
                ".records.lock", dir_fd=parent, follow_symlinks=False
            )
            if (locked.st_dev, locked.st_ino) != (opened.st_dev, opened.st_ino):
                raise OSError("changed lock")
        except OSError as error:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise RunRecordError("Run lock is unavailable or untrusted.") from error
        try:
            yield
        except BaseException:
            # Never rewrite a publication/crash exception as a validation
            # failure. Its type is part of outcome-uncertainty handling.
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        else:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
            except OSError as error:
                raise RunRecordError("Run lock could not be released safely.") from error

    @contextmanager
    def _held_canonical_run(
        self,
        family: str,
        run_id: str,
        lease: ExecutionLease | None = None,
        *,
        allow_run_metadata_change: bool = False,
    ):
        # Reuse D2's identifier checks before entering D3's descriptor chain.
        self._run_directory(family, run_id, require=False)
        (
            root_descriptor,
            root_identity,
            directory_descriptors,
            directory_links,
            run_descriptor,
            run_identity,
        ) = _open_canonical_run(self.repository_root, family, run_id)
        try:
            identities = tuple(
                (metadata.st_dev, metadata.st_ino, metadata.st_ctime_ns)
                for metadata in map(os.fstat, directory_descriptors)
            )
            if lease is not None:
                same_directories = (
                    lease.directory_identities == identities
                    if not allow_run_metadata_change
                    else (
                        lease.directory_identities[:-1] == identities[:-1]
                        and lease.directory_identities[-1][:2] == identities[-1][:2]
                    )
                )
                if (
                    lease.family != family
                    or lease.run_id != run_id
                    or not same_directories
                ):
                    raise RunRecordError(
                        "Execution lease no longer names the canonical run."
                    )
            pinned = os.fstat(self._repository_descriptor)
            if (pinned.st_dev, pinned.st_ino) != (
                root_identity.st_dev,
                root_identity.st_ino,
            ):
                raise RunRecordError("Repository root changed before execution mutation.")

            def verify(*, allow_run_metadata_change: bool = False) -> None:
                current_pinned = os.fstat(self._repository_descriptor)
                if (current_pinned.st_dev, current_pinned.st_ino) != (
                    root_identity.st_dev,
                    root_identity.st_ino,
                ):
                    raise RunRecordError("Repository root changed during execution mutation.")
                if lease is not None:
                    current_identities = tuple(
                        (metadata.st_dev, metadata.st_ino, metadata.st_ctime_ns)
                        for metadata in map(os.fstat, directory_descriptors)
                    )
                    stable_count = len(identities) - (
                        1 if allow_run_metadata_change else 0
                    )
                    if current_identities[:stable_count] != identities[:stable_count]:
                        raise RunRecordError(
                            "Execution lease changed during execution mutation."
                        )
                    if (
                        allow_run_metadata_change
                        and current_identities[-1][:2] != identities[-1][:2]
                    ):
                        raise RunRecordError(
                            "Canonical run identity changed during execution mutation."
                        )
                _verify_canonical_run(
                    self.repository_root,
                    root_descriptor,
                    root_identity,
                    directory_links,
                    run_descriptor,
                    run_identity,
                )

            verify()
            yield run_descriptor, verify, ExecutionLease(family, run_id, identities)
        finally:
            _close_descriptors(directory_descriptors)
            os.close(root_descriptor)

    def evidence_snapshot(
        self,
        authority: ExecutionAuthority,
        family: str,
        run_id: str,
        *,
        prior_lease: ExecutionLease | None = None,
        allow_run_metadata_change: bool = False,
    ) -> tuple[dict[str, dict[str, Any]], ExecutionLease]:
        """Read one digest-bound evidence snapshot from a pinned canonical run."""
        _require_authority(authority)
        with self._held_canonical_run(
            family,
            run_id,
            prior_lease,
            allow_run_metadata_change=allow_run_metadata_change,
        ) as (directory, verify, lease):
            with self._execution_locked_at(directory):
                records = {
                    kind: _read_record_at(directory, f"{kind}.json", kind)
                    for kind in ("run", "configuration", "inputs", "status")
                }
                run = records["run"]
                if (
                    run["configuration_sha256"]
                    != record_sha256("configuration", records["configuration"])
                    or run["inputs_sha256"]
                    != record_sha256("inputs", records["inputs"])
                ):
                    raise RunRecordError("Execution evidence digests do not match.")
                if any(
                    record["run_id"] != run_id
                    for record in records.values()
                ):
                    raise RunRecordError("Execution evidence identities do not match.")
                if (
                    records["configuration"]["family"] != family
                    or records["inputs"]["family"] != family
                    or run["family"] != family
                ):
                    raise RunRecordError("Execution evidence families do not match.")
                if any(
                    _read_record_at(directory, f"{kind}.json", kind) != record
                    for kind, record in records.items()
                ):
                    raise RunRecordError("Execution evidence changed during snapshot.")
                verify()
                run_metadata = os.fstat(directory)
                refreshed_lease = ExecutionLease(
                    family=lease.family,
                    run_id=lease.run_id,
                    directory_identities=(
                        *lease.directory_identities[:-1],
                        (
                            run_metadata.st_dev,
                            run_metadata.st_ino,
                            run_metadata.st_ctime_ns,
                        ),
                    ),
                )
                return records, refreshed_lease

    def transition(
        self,
        authority: ExecutionAuthority,
        family: str,
        run_id: str,
        *,
        expected_revision: int,
        target_state: str,
        updated_utc: str,
        local_pid: int | None | object = _UNSET,
        zeus_job_id: str | None | object = _UNSET,
        error: Mapping[str, str] | None = None,
        lease: ExecutionLease | None = None,
    ) -> dict[str, Any]:
        _require_authority(authority)
        with self._held_canonical_run(family, run_id, lease) as (directory, verify, _):
            with self._execution_locked_at(directory):
                current = _read_record_at(directory, "status.json", "status")
                if current["revision"] != expected_revision:
                    raise RunRecordError("Status transition lost its revision race.")
                if (current["state"], target_state) not in _EXECUTOR_TRANSITIONS:
                    raise RunRecordError("Executor status transition is invalid.")
                current_pid = current["execution"]["local_pid"]
                current_job = current["execution"]["zeus_job_id"]
                next_pid = current_pid if local_pid is _UNSET else local_pid
                next_job = current_job if zeus_job_id is _UNSET else zeus_job_id
                if (
                    current_pid is not None and next_pid != current_pid
                    or current_job is not None and next_job != current_job
                ):
                    raise RunRecordError("Execution evidence cannot be rebound.")
                proposed = {
                    "schema_version": _SPEC["record_versions"]["status"],
                    "run_id": run_id,
                    "revision": expected_revision + 1,
                    "state": target_state,
                    "updated_utc": updated_utc,
                    "execution": {
                        "mode": current["execution"]["mode"],
                        "local_pid": next_pid,
                        "zeus_job_id": next_job,
                    },
                    "error": dict(error) if error is not None else None,
                }
                validate_record("status", proposed)
                if _parsed_timestamp(updated_utc) < _parsed_timestamp(
                    current["updated_utc"]
                ):
                    raise RunRecordError("Status timestamp moved backwards.")
                run = _read_record_at(directory, "run.json", "run")
                if proposed["execution"]["mode"] != run["execution_mode"]:
                    raise RunRecordError("Status execution mode changed.")
                if (
                    _read_record_at(directory, "status.json", "status") != current
                    or _read_record_at(directory, "run.json", "run") != run
                ):
                    raise RunRecordError("Lifecycle evidence changed during transition.")
                verify()
                _replace_at(directory, "status.json", encode_record("status", proposed))
                verify(allow_run_metadata_change=True)
                return proposed

    def execution_lease(
        self,
        authority: ExecutionAuthority,
        family: str,
        run_id: str,
        *,
        expected_revision: int,
    ) -> ExecutionLease:
        _require_authority(authority)
        with self._held_canonical_run(family, run_id) as (directory, verify, lease):
            current = _read_record_at(directory, "status.json", "status")
            if current["state"] != "running" or current["revision"] != expected_revision:
                raise RunRecordError("Execution lease requires the reviewed running revision.")
            verify()
            return lease

    @staticmethod
    def _publish_or_verify(parent: int, name: str, content: bytes) -> None:
        try:
            _publish_no_replace_at(parent, name, content)
        except RunRecordError:
            if _read_regular_at(parent, name) != content:
                raise RunRecordError("Published result conflicts with durable evidence.")

    def publish_worker_artifacts(
        self,
        authority: ExecutionAuthority,
        family: str,
        run_id: str,
        *,
        expected_revision: int,
        product: WorkerProduct,
        lease: ExecutionLease,
    ) -> None:
        _require_authority(authority)
        results = validate_record("results", dict(product.results))
        if results["run_id"] != run_id:
            raise WorkerProductError("Worker results belong to another run.")
        artifacts = dict(product.artifacts)
        if any(not isinstance(path, str) or not isinstance(data, bytes) for path, data in artifacts.items()):
            raise WorkerProductError("Worker artifacts are invalid.")
        realized = {row["path"]: row for row in results["artifacts"]}
        expected_worker_paths = {
            path
            for path, row in realized.items()
            if row["kind"] != "retention_receipt"
        }
        if set(artifacts) != expected_worker_paths:
            raise WorkerProductError("Worker artifacts do not match the result registry.")
        for path, content in artifacts.items():
            row = realized[path]
            if (
                len(content) != row["size_bytes"]
                or hashlib.sha256(content).hexdigest() != row["sha256"]
            ):
                raise WorkerProductError("Worker artifact digest does not match.")
        with self._held_canonical_run(family, run_id, lease) as (directory, verify, _):
            with self._execution_locked_at(directory):
                current = _read_record_at(directory, "status.json", "status")
                if current["revision"] != expected_revision or current["state"] != "running":
                    raise RunRecordError("Worker publication lost its lifecycle race.")
                run = _read_record_at(directory, "run.json", "run")
                declared = {
                    row["path"]: row
                    for row in run["outputs"]
                    if row["path"] != _SPEC["layout"]["result_registry"]
                }
                if any(
                    path not in declared
                    or declared[path]["kind"] != realized[path]["kind"]
                    for path in artifacts
                ):
                    raise WorkerProductError("Worker artifact was not reviewed in the run plan.")
                if bool(results["states_retained"]) is not bool(
                    run["retention"]["particle_states"]
                ):
                    raise WorkerProductError("Worker output contradicts retention policy.")
                configuration = _read_record_at(
                    directory, "configuration.json", "configuration"
                )
                _validate_family_metrics(family, run, results, configuration)
                children: dict[str, int] = {}
                try:
                    for path, content in sorted(artifacts.items()):
                        pure = PurePosixPath(path)
                        if len(pure.parts) != 2 or pure.parts[0] not in {"results", "logs"}:
                            raise RunRecordError("Worker artifact path is not publishable.")
                        parent = children.get(pure.parts[0])
                        if parent is None:
                            parent = os.open(
                                pure.parts[0],
                                os.O_RDONLY
                                | getattr(os, "O_DIRECTORY", 0)
                                | getattr(os, "O_NOFOLLOW", 0),
                                dir_fd=directory,
                            )
                            children[pure.parts[0]] = parent
                        self._publish_or_verify(parent, pure.parts[1], content)
                    verify()
                finally:
                    for child in children.values():
                        os.close(child)
                if (
                    _read_record_at(directory, "status.json", "status") != current
                    or _read_record_at(directory, "run.json", "run") != run
                ):
                    raise RunRecordError("Run evidence changed during artifact publication.")

    def publish_success(
        self,
        authority: ExecutionAuthority,
        family: str,
        run_id: str,
        *,
        product: WorkerProduct,
        updated_utc: str,
        lease: ExecutionLease,
    ) -> dict[str, Any]:
        _require_authority(authority)
        with self._held_canonical_run(family, run_id, lease) as (directory, verify, _):
            with self._execution_locked_at(directory):
                current = _read_record_at(directory, "status.json", "status")
                if current["state"] != "running":
                    raise RunRecordError("Success publication lost its lifecycle race.")
                run = _read_record_at(directory, "run.json", "run")
                configuration = _read_record_at(
                    directory, "configuration.json", "configuration"
                )
                inputs = _read_record_at(directory, "inputs.json", "inputs")
                plan = _validate_publication_plan_at(
                    directory,
                    run,
                    configuration,
                    inputs,
                    current,
                    product.results,
                    product.receipt,
                )
                _validate_family_metrics(family, run, product.results, configuration)
                if current["revision"] != plan.expected_status_revision:
                    raise RunRecordError("Success publication lost its lifecycle race.")
                verify()
                results_directory = os.open(
                    "results",
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory,
                )
                try:
                    if plan.receipt_bytes is not None:
                        self._publish_or_verify(
                            results_directory,
                            "state_retention_receipt.json",
                            plan.receipt_bytes,
                        )
                    self._publish_or_verify(
                        results_directory, "summary.json", plan.results_bytes
                    )
                finally:
                    os.close(results_directory)

                durable_results = _read_result_record_at(
                    directory, "results/summary.json", "results"
                )
                durable_receipt = (
                    _read_result_record_at(
                        directory,
                        "results/state_retention_receipt.json",
                        "retention_receipt",
                    )
                    if plan.receipt_bytes is not None
                    else None
                )
                durable_plan = _validate_publication_plan_at(
                    directory,
                    run,
                    configuration,
                    inputs,
                    current,
                    durable_results,
                    durable_receipt,
                )
                if durable_plan != plan:
                    raise RunRecordError("D3 did not admit the durable publication.")
                if (
                    _read_record_at(directory, "run.json", "run") != run
                    or _read_record_at(
                        directory, "configuration.json", "configuration"
                    )
                    != configuration
                    or _read_record_at(directory, "inputs.json", "inputs") != inputs
                    or _read_record_at(directory, "status.json", "status") != current
                ):
                    raise RunRecordError("Run evidence changed during publication.")
                verify()
                proposed = self._succeeded_status(current, product.results, updated_utc)
                _replace_at(directory, "status.json", encode_record("status", proposed))
                verify(allow_run_metadata_change=True)
                return proposed

    def finalize_existing_success(
        self,
        authority: ExecutionAuthority,
        family: str,
        run_id: str,
        *,
        updated_utc: str,
        lease: ExecutionLease,
    ) -> dict[str, Any]:
        _require_authority(authority)
        with self._held_canonical_run(family, run_id, lease) as (directory, verify, _):
            with self._execution_locked_at(directory):
                run = _read_record_at(directory, "run.json", "run")
                configuration = _read_record_at(
                    directory, "configuration.json", "configuration"
                )
                inputs = _read_record_at(directory, "inputs.json", "inputs")
                current = _read_record_at(directory, "status.json", "status")
                if current["state"] != "running":
                    raise RunRecordError("Run is not awaiting success finalization.")
                results = _read_result_record_at(
                    directory, "results/summary.json", "results"
                )
                receipt = (
                    _read_result_record_at(
                        directory,
                        "results/state_retention_receipt.json",
                        "retention_receipt",
                    )
                    if not results["states_retained"]
                    else None
                )
                plan = _validate_publication_plan_at(
                    directory,
                    run,
                    configuration,
                    inputs,
                    current,
                    results,
                    receipt,
                )
                _validate_family_metrics(family, run, results, configuration)
                if plan.results_sha256 != hashlib.sha256(
                    encode_record("results", results)
                ).hexdigest():
                    raise RunRecordError("No D3-validated publication is recoverable.")
                if (
                    _read_record_at(directory, "run.json", "run") != run
                    or _read_record_at(
                        directory, "configuration.json", "configuration"
                    )
                    != configuration
                    or _read_record_at(directory, "inputs.json", "inputs") != inputs
                    or _read_record_at(directory, "status.json", "status") != current
                    or _read_result_record_at(
                        directory, "results/summary.json", "results"
                    )
                    != results
                ):
                    raise RunRecordError("Run evidence changed during recovery.")
                verify()
                proposed = self._succeeded_status(current, results, updated_utc)
                _replace_at(directory, "status.json", encode_record("status", proposed))
                verify(allow_run_metadata_change=True)
                return proposed

    @staticmethod
    def _succeeded_status(
        current: Mapping[str, Any], results: Mapping[str, Any], updated_utc: str
    ) -> dict[str, Any]:
        proposed = {
            "schema_version": _SPEC["record_versions"]["status"],
            "run_id": current["run_id"],
            "revision": current["revision"] + 1,
            "state": "succeeded",
            "updated_utc": updated_utc,
            "execution": _plain(current["execution"]),
            "error": None,
        }
        validate_record("status", proposed)
        if (
            _parsed_timestamp(updated_utc) < _parsed_timestamp(current["updated_utc"])
            or _parsed_timestamp(updated_utc)
            < _parsed_timestamp(str(results["completed_utc"]))
        ):
            raise RunRecordError("Success timestamp predates durable results.")
        return proposed


class IndividualRunExecutionCoordinator:
    """Coordinate one injected worker without owning any execution mechanism."""

    def __init__(
        self,
        repository_root: Path,
        worker: IndividualRunWorker,
        authority: ExecutionAuthority,
        *,
        clock: Callable[[], str] = _utc_now,
        store_factory: Callable[[Path], ExecutorLifecycleStore] = ExecutorLifecycleStore,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        _require_authority(authority)
        self.root = repository_root.resolve(strict=True)
        self.worker = worker
        self.authority = authority
        self.clock = clock
        self.store_factory = store_factory
        self.progress_callback = progress_callback

    def execute(self, family: str, run_id: str) -> dict[str, Any]:
        store = self.store_factory(self.root)
        try:
            inspected = inspect_run(self.root, family, run_id)
            evidence, lease = store.evidence_snapshot(
                self.authority, family, run_id
            )
            inspected_records = {
                "run": _plain(inspected.run),
                "configuration": _plain(inspected.configuration),
                "inputs": _plain(inspected.inputs),
                "status": _plain(inspected.status),
            }
            if evidence != inspected_records:
                raise RunRecordError(
                    "Canonical execution evidence changed after inspection."
                )
            if evidence["status"]["state"] == "succeeded":
                return {"state": "succeeded", "recovered": True, "worker_started": False}
            if evidence["status"]["state"] == "running":
                if inspected.integrity == "incomplete_publication":
                    status = store.finalize_existing_success(
                        self.authority,
                        family,
                        run_id,
                        updated_utc=self.clock(),
                        lease=lease,
                    )
                    return {"state": status["state"], "recovered": True, "worker_started": False}
                status = store.transition(
                    self.authority,
                    family,
                    run_id,
                    expected_revision=evidence["status"]["revision"],
                    target_state="outcome_unknown",
                    updated_utc=self.clock(),
                    error={
                        "code": "interrupted_execution",
                        "message": "Execution was interrupted before durable publication.",
                    },
                    lease=lease,
                )
                return {"state": status["state"], "recovered": True, "worker_started": False}
            if evidence["status"]["state"] in _SPEC["lifecycle"]["terminal"]:
                return {
                    "state": evidence["status"]["state"],
                    "recovered": True,
                    "worker_started": False,
                }

            current = evidence["status"]
            for target in ("validated", "reviewed", "running"):
                if current["state"] == target:
                    continue
                if target not in _TRANSITIONS[current["state"]]:
                    continue
                current = store.transition(
                    self.authority,
                    family,
                    run_id,
                    expected_revision=current["revision"],
                    target_state=target,
                    updated_utc=self.clock(),
                    lease=lease,
                )
                refreshed, lease = store.evidence_snapshot(
                    self.authority,
                    family,
                    run_id,
                    prior_lease=lease,
                    allow_run_metadata_change=True,
                )
                if (
                    refreshed["run"] != evidence["run"]
                    or refreshed["configuration"] != evidence["configuration"]
                    or refreshed["inputs"] != evidence["inputs"]
                    or refreshed["status"] != current
                ):
                    raise RunRecordError(
                        "Canonical execution evidence changed during admission."
                    )
                evidence = refreshed
            if current["state"] != "running":
                raise RunRecordError("Run could not enter the running state.")

            request = WorkerRequest(
                run=_freeze(_plain(evidence["run"])),
                configuration=_freeze(_plain(evidence["configuration"])),
                inputs=_freeze(_plain(evidence["inputs"])),
            )
            try:
                setter = getattr(self.worker, "set_progress_callback", None)
                if setter is not None:
                    setter(self.progress_callback)
                product = self.worker.run(request)
            except WorkerFailed:
                status = store.transition(
                    self.authority, family, run_id,
                    expected_revision=current["revision"], target_state="failed",
                    updated_utc=self.clock(),
                    error={"code": "worker_failed", "message": "The worker reported a failure."},
                    lease=lease,
                )
                return {"state": status["state"], "recovered": False, "worker_started": True}
            except Exception:
                status = store.transition(
                    self.authority, family, run_id,
                    expected_revision=current["revision"], target_state="outcome_unknown",
                    updated_utc=self.clock(),
                    error={"code": "worker_outcome_unknown", "message": "The worker outcome is unknown."},
                    lease=lease,
                )
                return {"state": status["state"], "recovered": False, "worker_started": True}
            if not isinstance(product, WorkerProduct):
                product_error = WorkerProductError("Worker returned an invalid product.")
            else:
                product_error = None
            try:
                if product_error is not None:
                    raise product_error
                store.publish_worker_artifacts(
                    self.authority, family, run_id,
                    expected_revision=current["revision"], product=product, lease=lease,
                )
                status = store.publish_success(
                    self.authority, family, run_id,
                    product=product, updated_utc=self.clock(), lease=lease,
                )
            except WorkerProductError:
                status = store.transition(
                    self.authority, family, run_id,
                    expected_revision=current["revision"], target_state="failed",
                    updated_utc=self.clock(),
                    error={"code": "invalid_worker_output", "message": "Worker output failed validation."},
                    lease=lease,
                )
            return {"state": status["state"], "recovered": False, "worker_started": True}
        finally:
            store.close()
