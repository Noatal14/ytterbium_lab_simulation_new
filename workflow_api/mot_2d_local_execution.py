"""Bounded local execution of one reviewed individual 2D-MOT run."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
import math
from workflow_api.platform_io import os
from pathlib import Path, PurePosixPath
import stat
import time
from typing import Any, Callable, Mapping, Protocol

import numpy as np

from lab_setup.mag_field_Zeeman import resolved_zeeman_field_construction
from lab_setup.physical_specification import LABORATORY_PHYSICAL_SPECIFICATION
from lab_setup.zeeman_laser_setup import resolved_zeeman_laser_parameters
from workflow_api.mot_2d_run_specification import MOT_2D_RUN_SPECIFICATION
from workflow_api.mot_2d_individual_sources import individual_mot_2d_source_scan_limits
from workflow_api.run_execution import (
    ExecutionAuthority,
    IndividualRunExecutionCoordinator,
    WorkerProduct,
    WorkerProductError,
    WorkerFailed,
    WorkerRequest,
    mot_2d_result_provenance,
)
from workflow_api.run_records import encode_record
from workflow_api.run_results import (
    _close_descriptors,
    _open_parent,
    _open_repository_root,
    _verify_directory_chain,
)
from workflow_api.run_specification import INDIVIDUAL_RUN_SPECIFICATION, require_local_worker_budget
from workflow_api.zeeman_local_execution import BoundedLocalExecutionPool
from utils.RK4StHybridCustom import RK4StHybridCustom


_MAX_SELECTED_BYTES = max(MOT_2D_RUN_SPECIFICATION["particle_count"]["maximum_by_execution_mode"].values()) * 6 * 8


class Mot2DEngine(Protocol):
    def __call__(self, survivor_states: np.ndarray, **kwargs: Any) -> tuple[Any, Any, Any]: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trusted_engine(survivor_states: np.ndarray, **kwargs: Any):
    from simulations.mot_2d import mot_simulation

    return mot_simulation(survivor_states, **kwargs)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain(child) for child in value]
    return value


def _hash_descriptor(descriptor: int, expected_size: int) -> str:
    digest = hashlib.sha256()
    observed = 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        chunk = os.read(descriptor, min(1024 * 1024, expected_size + 1 - observed))
        if not chunk:
            break
        observed += len(chunk)
        if observed > expected_size:
            raise WorkerProductError("Frozen 2D-MOT input exceeded its attested size.")
        digest.update(chunk)
    if observed != expected_size:
        raise WorkerProductError("Frozen 2D-MOT input size changed while reading.")
    return digest.hexdigest()


def _read_selected_rows(
    descriptor: int,
    expected_size: int,
    rows: tuple[int, ...],
    expected_shape: tuple[int, int],
) -> dict[int, np.ndarray]:
    if not rows:
        return {}
    # A duplicated descriptor shares the underlying file offset.  Rewind the
    # held descriptor after the streaming digest before parsing the header.
    os.lseek(descriptor, 0, os.SEEK_SET)
    with os.fdopen(os.dup(descriptor), "rb", closefd=True) as stream:
        version = np.lib.format.read_magic(stream)
        if version == (1, 0):
            shape, fortran_order, dtype = np.lib.format.read_array_header_1_0(stream)
        elif version == (2, 0):
            shape, fortran_order, dtype = np.lib.format.read_array_header_2_0(stream)
        else:
            raise WorkerProductError("Frozen particle-state format version is unsupported.")
        offset = stream.tell()
    if (
        dtype != np.dtype(np.float64)
        or tuple(shape) != expected_shape
        or expected_shape[1] != 6
        or offset + expected_shape[0] * 6 * 8 != expected_size
    ):
        raise WorkerProductError("Frozen particle-state header is inconsistent.")
    selected: dict[int, np.ndarray] = {}
    for row in rows:
        if not 0 <= row < expected_shape[0]:
            raise WorkerProductError("Frozen 2D-MOT selection is out of range.")
        if fortran_order:
            values = [
                np.frombuffer(
                    os.pread(descriptor, 8, offset + (column * expected_shape[0] + row) * 8),
                    dtype=np.float64,
                    count=1,
                )[0]
                for column in range(6)
            ]
            value = np.asarray(values, dtype=np.float64)
        else:
            raw = os.pread(descriptor, 48, offset + row * 48)
            if len(raw) != 48:
                raise WorkerProductError("Frozen particle-state row is incomplete.")
            value = np.frombuffer(raw, dtype=np.float64, count=6).copy()
        if not np.all(np.isfinite(value)):
            raise WorkerProductError("Selected particle state is non-finite.")
        selected[row] = value
    return selected


def _attest_artifact(
    repository_root: Path,
    artifact: Mapping[str, Any],
    *,
    selected_rows: tuple[int, ...] = (),
    expected_shape: tuple[int, int] | None = None,
) -> dict[int, np.ndarray]:
    """Stream-attest one input and materialize only explicitly selected rows."""
    relative = artifact["path"]
    expected_size = artifact["size_bytes"]
    if (
        not isinstance(relative, str)
        or PurePosixPath(relative).is_absolute()
        or any(part in {"", ".", ".."} for part in PurePosixPath(relative).parts)
        or isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or not 0 <= expected_size <= individual_mot_2d_source_scan_limits().maximum_file_bytes
    ):
        raise WorkerProductError("Frozen 2D-MOT input evidence is invalid.")
    root_descriptor, root_identity = _open_repository_root(repository_root)
    descriptors: list[int] = []
    file_descriptor: int | None = None
    try:
        parent, name, descriptors, links = _open_parent(root_descriptor, relative)
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size != expected_size
        ):
            raise WorkerProductError("Frozen 2D-MOT input is not a trusted regular file.")
        file_descriptor = os.open(
            name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent
        )
        opened = os.fstat(file_descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise WorkerProductError("Frozen 2D-MOT input changed while opening.")
        if _hash_descriptor(file_descriptor, expected_size) != artifact["sha256"]:
            raise WorkerProductError("Frozen 2D-MOT input digest no longer matches.")
        selected = (
            _read_selected_rows(
                file_descriptor, expected_size, selected_rows, expected_shape
            )
            if expected_shape is not None
            else {}
        )
        # Selected bytes must be bound to the same full-file digest that was
        # admitted; a second streaming pass closes an in-place mutation gap.
        if selected and _hash_descriptor(file_descriptor, expected_size) != artifact["sha256"]:
            raise WorkerProductError("Frozen 2D-MOT input changed while selecting rows.")
        after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        current_root = repository_root.lstat()
        if (
            (after.st_dev, after.st_ino, after.st_size)
            != (opened.st_dev, opened.st_ino, expected_size)
            or (current_root.st_dev, current_root.st_ino)
            != (root_identity.st_dev, root_identity.st_ino)
        ):
            raise WorkerProductError("Frozen 2D-MOT input no longer matches its attestation.")
        _verify_directory_chain(links)
        return selected
    except WorkerProductError:
        raise
    except (OSError, ValueError) as error:
        raise WorkerProductError("Frozen 2D-MOT input could not be re-attested.") from error
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if descriptors:
            _close_descriptors(descriptors)
        os.close(root_descriptor)


def _validated_selection(
    sampling: Mapping[str, Any], records: list[Mapping[str, Any]], count: int
) -> tuple[tuple[int, int], ...]:
    policy = MOT_2D_RUN_SPECIFICATION["sampling"]
    identities = sampling.get("selected_identities")
    if (
        sampling.get("algorithm") != policy["algorithm"]
        or sampling.get("version") != policy["version"]
        or sampling.get("canonical_order") != policy["canonical_order"]
        or isinstance(sampling.get("selected_count"), bool)
        or sampling.get("selected_count") != count
        or not isinstance(identities, (list, tuple))
        or len(identities) != count
        or count * 6 * 8 > _MAX_SELECTED_BYTES
    ):
        raise WorkerProductError("Frozen 2D-MOT selection policy is inconsistent.")
    normalized: list[tuple[int, int]] = []
    for identity in identities:
        if (
            not isinstance(identity, (list, tuple))
            or len(identity) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in identity)
        ):
            raise WorkerProductError("Frozen 2D-MOT selection identity is invalid.")
        record_index, row_index = identity
        if (
            not 0 <= record_index < len(records)
            or not 0 <= row_index < records[record_index]["survivor_count"]
        ):
            raise WorkerProductError("Frozen 2D-MOT selection is out of range.")
        normalized.append((record_index, row_index))
    frozen = tuple(normalized)
    if len(set(frozen)) != len(frozen) or tuple(sorted(frozen)) != frozen:
        raise WorkerProductError("Frozen 2D-MOT selection is duplicated or non-canonical.")
    encoded = json.dumps([list(item) for item in frozen], separators=(",", ":")).encode()
    if hashlib.sha256(encoded).hexdigest() != sampling.get("selected_identities_sha256"):
        raise WorkerProductError("Frozen 2D-MOT selection digest is inconsistent.")
    return frozen


def materialize_frozen_selection(
    repository_root: Path, request: WorkerRequest
) -> tuple[np.ndarray, tuple[tuple[int, int], ...]]:
    """Re-attest a frozen pool and read only its already-selected rows."""

    run = request.run
    resolved = request.configuration["resolved"]
    source = resolved["input_source"]
    records = list(source["records"])
    identities = _validated_selection(
        resolved["sampling"], records, run["particle_count"]
    )
    expected_artifacts: dict[tuple[int, str], Mapping[str, Any]] = {}
    total_state_bytes = 0
    for artifact in request.inputs["artifacts"]:
        provenance = artifact["provenance"]
        index = provenance["source_record_index"]
        role = artifact["role"]
        kind = (
            "states" if role == "zeeman_states"
            else "metadata" if role == "zeeman_metadata" else None
        )
        if (
            kind is None
            or provenance["source_id"] != source["id"]
            or provenance["source_fingerprint"] != source["fingerprint"]
        ):
            raise WorkerProductError("Frozen 2D-MOT input provenance is inconsistent.")
        key = (index, kind)
        if key in expected_artifacts:
            raise WorkerProductError("Frozen 2D-MOT inputs contain duplicates.")
        expected_artifacts[key] = artifact
        if kind == "states":
            total_state_bytes += artifact["size_bytes"]
    if total_state_bytes > individual_mot_2d_source_scan_limits().maximum_total_bytes:
        raise WorkerProductError("Frozen 2D-MOT source exceeds the admitted byte limit.")
    expected_keys = {
        (index, kind) for index in range(len(records))
        for kind in (("states", "metadata") if "metadata_path" in records[index] else ("states",))
    }
    if set(expected_artifacts) != expected_keys:
        raise WorkerProductError("Frozen 2D-MOT input registry is incomplete.")
    requested_rows: dict[int, list[int]] = {}
    for record_index, row_index in identities:
        requested_rows.setdefault(record_index, []).append(row_index)
    selected_rows: dict[tuple[int, int], np.ndarray] = {}
    for index, record in enumerate(records):
        state_artifact = expected_artifacts[(index, "states")]
        if (
            state_artifact["path"] != record["path"]
            or state_artifact["sha256"] != record["sha256"]
            or state_artifact["size_bytes"] != record["size_bytes"]
            or tuple(record["shape"]) != (record["survivor_count"], 6)
            or record["dtype"] != "float64"
        ):
            raise WorkerProductError("Frozen state evidence is inconsistent.")
        rows = _attest_artifact(
            repository_root, state_artifact,
            selected_rows=tuple(requested_rows.get(index, ())),
            expected_shape=tuple(record["shape"]),
        )
        selected_rows.update({(index, row): value for row, value in rows.items()})
        if "metadata_path" in record:
            metadata = expected_artifacts[(index, "metadata")]
            if (
                metadata["path"] != record["metadata_path"]
                or metadata["sha256"] != record["metadata_sha256"]
                or metadata["size_bytes"] != record["metadata_size_bytes"]
            ):
                raise WorkerProductError("Frozen metadata evidence is inconsistent.")
            _attest_artifact(repository_root, metadata)
    try:
        selected = np.ascontiguousarray(
            np.stack([selected_rows[identity] for identity in identities]),
            dtype=np.float64,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise WorkerProductError("Frozen 2D-MOT selection is out of range.") from error
    return selected, identities


class Mot2DLocalWorker:
    """Materialize the frozen selection and call the fixed 2D engine once."""

    def __init__(
        self,
        repository_root: Path,
        *,
        engine: Mot2DEngine = _trusted_engine,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self.root = repository_root.resolve(strict=True)
        self._engine = engine
        self._monotonic = monotonic
        self._clock = clock
        self._progress_callback: Callable[[int, int], None] | None = None

    def set_progress_callback(self, callback: Callable[[int, int], None] | None) -> None:
        self._progress_callback = callback

    def run(self, request: WorkerRequest) -> WorkerProduct:
        return self._run(request, selected_states=None)

    def run_materialized(
        self, request: WorkerRequest, selected_states: np.ndarray
    ) -> WorkerProduct:
        """Run an immutable selected-row payload staged by the Zeus boundary."""

        return self._run(request, selected_states=selected_states)

    def _run(
        self, request: WorkerRequest, *, selected_states: np.ndarray | None
    ) -> WorkerProduct:
        run = request.run
        configuration = request.configuration
        resolved = configuration["resolved"]
        if run["family"] != "mot_2d" or run["execution_mode"] not in {"local", "zeus"}:
            raise WorkerProductError("2D-MOT worker received the wrong run family or mode.")
        simulation = resolved["simulation"]
        execution = resolved["execution"]
        numerical = resolved["numerical_policy"]
        controls = resolved["mot_2d"]
        sampling = resolved["sampling"]
        source = resolved["input_source"]
        records = list(source["records"])
        identities = _validated_selection(sampling, records, run["particle_count"])
        fixed = MOT_2D_RUN_SPECIFICATION["fixed_classification"]
        mode = run["execution_mode"]
        expected_workers = execution.get("workers")
        worker_policy = MOT_2D_RUN_SPECIFICATION["local_worker_count"]
        if (
            execution.get("mode") != mode
            or set(execution) != {"mode", "workers"}
            or isinstance(expected_workers, bool)
            or not isinstance(expected_workers, int)
            or (
                mode == "local"
                and not worker_policy["minimum"] <= expected_workers <= worker_policy["maximum"]
            )
            or (
                mode == "zeus"
                and expected_workers != MOT_2D_RUN_SPECIFICATION["workers_by_execution_mode"]["zeus"]
            )
            or run["particle_count"] > MOT_2D_RUN_SPECIFICATION["particle_count"]["maximum_by_execution_mode"][mode]
            or simulation["particle_count"] != run["particle_count"]
            or sampling["selected_count"] != run["particle_count"]
            or numerical != {"solver": fixed["solver"], "dt_s": fixed["timestep_s"], "t_max_s": fixed["t_max_s"]}
            or simulation["start_distance_m"] != fixed["start_distance_m"]
            or simulation["force_scale_N"] != fixed["force_scale_N"]
            or controls["capture_criterion_version"] != fixed["capture_criterion_version"]
            or simulation["gravity_enabled"] is not True
            or simulation["stochastic"] is not True
        ):
            raise WorkerProductError("Reviewed 2D-MOT settings differ from the trusted runtime.")

        field = _plain(resolved["upstream_zeeman_boundary"]["field"])
        laser = _plain(resolved["upstream_zeeman_boundary"]["laser"])
        physical = LABORATORY_PHYSICAL_SPECIFICATION
        expected_field = resolved_zeeman_field_construction(
            radii_m=field["radii_m"],
            positions_m=field["positions_m"],
            tilt_angles_deg=field["tilt_angles_deg"],
            angle_deg=physical["apparatus"]["zeeman_arm_angle_deg"],
            start_distance_m=physical["apparatus"]["zeeman_start_distance_m"],
        )
        expected_laser = resolved_zeeman_laser_parameters(
            s0=laser["s0"], detuning_gamma=laser["detuning_gamma"],
            polarization=laser["polarization"],
        )
        if field != expected_field or laser != expected_laser:
            raise WorkerProductError("Reviewed upstream boundary differs from the trusted runtime.")

        if selected_states is None:
            if mode != "local":
                raise WorkerProductError("Zeus execution requires a frozen selected-row payload.")
            selected, identities = materialize_frozen_selection(self.root, request)
        else:
            identities = _validated_selection(sampling, records, run["particle_count"])
            selected = np.asarray(selected_states)
            if (
                mode != "zeus"
                or selected.dtype != np.dtype(np.float64)
                or selected.shape != (run["particle_count"], 6)
                or not selected.flags.c_contiguous
                or not np.all(np.isfinite(selected))
            ):
                raise WorkerProductError("Frozen selected-row payload is invalid.")

        try:
            require_local_worker_budget(mode, run["particle_count"], expected_workers)
        except ValueError as error:
            raise WorkerFailed(str(error)) from error
        started = self._monotonic()
        outcome = self._engine(
            selected,
            _2d_mot_config={
                "s0": controls["laser"]["s0"],
                "detuning_gamma": controls["laser"]["detuning_gamma"],
                "swap_polarization": controls["laser"]["swap_polarization"],
            },
            zeeman_config={
                "s0": laser["s0"], "detuning_gamma": laser["detuning_gamma"],
                "polarization": laser["polarization"],
            },
            zeeman_field_config=field,
            magnet_radius=controls["magnet_radius_m"],
            gravity_enabled=True,
            npools=expected_workers,
            stochastic=True,
            dt=numerical["dt_s"],
            t_max_s=numerical["t_max_s"],
            seed=simulation["mot_seed"],
            stochastic_sim_function=RK4StHybridCustom,
            **({"progress_callback": self._progress_callback} if self._progress_callback is not None else {}),
        )
        elapsed = self._monotonic() - started
        if not isinstance(outcome, tuple) or len(outcome) != 3 or not math.isfinite(elapsed) or elapsed < 0:
            raise WorkerProductError("2D-MOT engine returned an invalid outcome.")
        _trajectories, count_value, survivor_value = outcome
        survivors = np.asarray(survivor_value)
        if (
            isinstance(count_value, bool) or not isinstance(count_value, (int, np.integer))
            or int(count_value) != len(survivors)
            or survivors.dtype != np.dtype(np.float64)
            or survivors.ndim != 2 or survivors.shape[1] != 6
            or len(survivors) > len(selected) or not np.all(np.isfinite(survivors))
        ):
            raise WorkerProductError("2D-MOT survivor states or count are inconsistent.")

        count = int(count_value); completed = self._clock()
        retained = bool(run["retention"]["particle_states"])
        output_artifacts: dict[str, bytes] = {}; receipt = None; registry = []
        if retained:
            stream = BytesIO(); np.save(stream, np.ascontiguousarray(survivors), allow_pickle=False)
            states_bytes = stream.getvalue(); output_artifacts["results/states.npy"] = states_bytes
            registry.append({"kind": "particle_states", "path": "results/states.npy", "sha256": hashlib.sha256(states_bytes).hexdigest(), "size_bytes": len(states_bytes)})
        else:
            receipt = {"schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["retention_receipt"], "run_id": run["run_id"], "created_utc": completed, "reason": "particle_states_not_retained"}
            receipt_bytes = encode_record("retention_receipt", receipt)
            registry.append({"kind": "retention_receipt", "path": "results/state_retention_receipt.json", "sha256": hashlib.sha256(receipt_bytes).hexdigest(), "size_bytes": len(receipt_bytes)})
        metrics = {
            "n_input": len(selected), "n_survivors": count,
            "conditional_efficiency": count / len(selected), "elapsed_s": float(elapsed),
            "selection_sha256": sampling["selected_identities_sha256"],
            "provenance": mot_2d_result_provenance(run, configuration),
        }
        return WorkerProduct(
            results={"schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["results"], "run_id": run["run_id"], "completed_utc": completed, "states_retained": retained, "suitability": "individual_only", "metrics": metrics, "artifacts": registry},
            receipt=receipt, artifacts=output_artifacts,
        )


class Mot2DBoundedLocalExecutionPool(BoundedLocalExecutionPool):
    def __init__(self, repository_root: Path, authority: ExecutionAuthority, **kwargs: Any):
        worker_factory = kwargs.pop(
            "worker_factory", lambda: Mot2DLocalWorker(repository_root)
        )
        super().__init__(
            repository_root, authority, worker_factory=worker_factory,
            allowed_family="mot_2d", thread_name_prefix="mot2d-local", **kwargs,
        )
