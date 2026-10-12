"""Bounded local execution of one immutable individual 3D-MOT plan."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Protocol

import numpy as np

from studies.mot_3d.analysis.retention import analyze_results, final_states_on_grid
from studies.mot_3d.discovery.optimize import build_profile_from_parameters
from workflow_api.mot_2d_local_execution import _attest_artifact
from workflow_api.mot_3d_individual_sources import individual_mot_3d_source_scan_limits
from workflow_api.mot_3d_run_specification import MOT_3D_RUN_SPECIFICATION
from workflow_api.run_execution import (
    ExecutionAuthority,
    IndividualRunExecutionCoordinator,
    WorkerProduct,
    WorkerProductError,
    WorkerRequest,
    mot_3d_result_provenance,
)
from workflow_api.run_records import encode_record
from workflow_api.run_specification import INDIVIDUAL_RUN_SPECIFICATION
from workflow_api.zeeman_local_execution import BoundedLocalExecutionPool


_MAX_SELECTED_BYTES = 1_000 * 6 * 8


class Mot3DEngine(Protocol):
    def __call__(self, survivor_states: np.ndarray, **kwargs: Any) -> tuple[Any, Any]: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trusted_engine(survivor_states: np.ndarray, **kwargs: Any):
    from simulations.mot_3d import mot_3d_simulation

    return mot_3d_simulation(survivor_states, **kwargs)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain(child) for child in value]
    return value


def _validated_selection(
    sampling: Mapping[str, Any], records: list[Mapping[str, Any]], count: int
) -> tuple[tuple[int, int], ...]:
    policy = MOT_3D_RUN_SPECIFICATION["sampling"]
    identities = sampling.get("selected_identities")
    if (
        sampling.get("algorithm") != policy["algorithm"]
        or sampling.get("version") != policy["version"]
        or sampling.get("canonical_order") != policy["canonical_order"]
        or sampling.get("selected_count") != count
        or isinstance(sampling.get("selected_count"), bool)
        or not isinstance(identities, (list, tuple))
        or len(identities) != count
        or count * 6 * 8 > _MAX_SELECTED_BYTES
    ):
        raise WorkerProductError("Frozen 3D-MOT selection policy is inconsistent.")
    normalized = []
    for identity in identities:
        if (
            not isinstance(identity, (list, tuple))
            or len(identity) != 2
            or any(isinstance(item, bool) or not isinstance(item, int) for item in identity)
        ):
            raise WorkerProductError("Frozen 3D-MOT selection identity is invalid.")
        record_index, row_index = identity
        if not 0 <= record_index < len(records) or not 0 <= row_index < records[record_index]["survivor_count"]:
            raise WorkerProductError("Frozen 3D-MOT selection is out of range.")
        normalized.append((record_index, row_index))
    frozen = tuple(normalized)
    if len(set(frozen)) != len(frozen) or tuple(sorted(frozen)) != frozen:
        raise WorkerProductError("Frozen 3D-MOT selection is duplicated or non-canonical.")
    encoded = json.dumps([list(item) for item in frozen], separators=(",", ":")).encode()
    if hashlib.sha256(encoded).hexdigest() != sampling.get("selected_identities_sha256"):
        raise WorkerProductError("Frozen 3D-MOT selection digest is inconsistent.")
    return frozen


def materialize_frozen_selection(
    repository_root: Path, request: WorkerRequest
) -> tuple[np.ndarray, tuple[tuple[int, int], ...]]:
    run = request.run
    resolved = request.configuration["resolved"]
    source = resolved["input_source"]
    records = list(source["records"])
    identities = _validated_selection(resolved["sampling"], records, run["particle_count"])
    artifacts: dict[tuple[int, str], Mapping[str, Any]] = {}
    total_state_bytes = 0
    for artifact in request.inputs["artifacts"]:
        provenance = artifact["provenance"]
        index = provenance["source_record_index"]
        role = artifact["role"]
        kind = "states" if role == "mot_2d_states" else "metadata" if role == "mot_2d_metadata" else None
        if kind is None or provenance["source_id"] != source["id"] or provenance["source_fingerprint"] != source["fingerprint"]:
            raise WorkerProductError("Frozen 3D-MOT input provenance is inconsistent.")
        key = (index, kind)
        if key in artifacts:
            raise WorkerProductError("Frozen 3D-MOT inputs contain duplicates.")
        artifacts[key] = artifact
        if kind == "states":
            total_state_bytes += artifact["size_bytes"]
    limits = individual_mot_3d_source_scan_limits()
    if total_state_bytes > limits.maximum_total_bytes:
        raise WorkerProductError("Frozen 3D-MOT source exceeds the admitted byte limit.")
    expected = {
        (index, kind)
        for index, record in enumerate(records)
        for kind in (("states", "metadata") if "metadata_path" in record else ("states",))
    }
    if set(artifacts) != expected:
        raise WorkerProductError("Frozen 3D-MOT input registry is incomplete.")
    requested: dict[int, list[int]] = {}
    for record_index, row_index in identities:
        requested.setdefault(record_index, []).append(row_index)
    selected: dict[tuple[int, int], np.ndarray] = {}
    for index, record in enumerate(records):
        state = artifacts[(index, "states")]
        if (
            state["path"] != record["path"]
            or state["sha256"] != record["sha256"]
            or state["size_bytes"] != record["size_bytes"]
            or tuple(record["shape"]) != (record["survivor_count"], 6)
            or record["dtype"] != "float64"
        ):
            raise WorkerProductError("Frozen 3D-MOT state evidence is inconsistent.")
        rows = _attest_artifact(
            repository_root,
            state,
            selected_rows=tuple(requested.get(index, ())),
            expected_shape=tuple(record["shape"]),
        )
        selected.update({(index, row): value for row, value in rows.items()})
        if "metadata_path" in record:
            metadata = artifacts[(index, "metadata")]
            if metadata["path"] != record["metadata_path"] or metadata["sha256"] != record["metadata_sha256"] or metadata["size_bytes"] != record["metadata_size_bytes"]:
                raise WorkerProductError("Frozen 3D-MOT metadata evidence is inconsistent.")
            _attest_artifact(repository_root, metadata)
    try:
        values = np.ascontiguousarray(np.stack([selected[item] for item in identities]), dtype=np.float64)
    except (KeyError, TypeError, ValueError) as error:
        raise WorkerProductError("Frozen 3D-MOT selection is out of range.") from error
    return values, identities


class Mot3DLocalWorker:
    def __init__(
        self,
        repository_root: Path,
        *,
        engine: Mot3DEngine = _trusted_engine,
        analyzer: Callable[..., Mapping[str, Any]] = analyze_results,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self.root = repository_root.resolve(strict=True)
        self._engine = engine; self._analyzer = analyzer
        self._monotonic = monotonic; self._clock = clock

    def run(self, request: WorkerRequest) -> WorkerProduct:
        run = request.run; configuration = request.configuration
        resolved = configuration["resolved"]
        if run["family"] != "mot_3d" or run["execution_mode"] != "local":
            raise WorkerProductError("3D-MOT worker received the wrong run family or mode.")
        fixed = MOT_3D_RUN_SPECIFICATION["fixed_classification"]
        numerical = resolved["numerical_policy"]
        execution = resolved["execution"]
        simulation = resolved["simulation"]
        mot = resolved["mot_3d"]
        expected_profile, expected_parameters, expected_derived = build_profile_from_parameters(mot["geometry_family"], mot["parameters"])
        if (
            run["particle_count"] > MOT_3D_RUN_SPECIFICATION["particle_count"]["maximum_by_execution_mode"]["local"]
            or execution != {"mode": "local", "workers": MOT_3D_RUN_SPECIFICATION["workers_by_execution_mode"]["local"]}
            or simulation["particle_count"] != run["particle_count"]
            or simulation["stochastic"] is not True
            or simulation["gravity_enabled"] is not fixed["gravity_enabled"]
            or numerical != {"solver": fixed["solver"], "dt_s": fixed["timestep_s"], "t_max_s": fixed["t_max_s"], "convergence_claim": fixed["convergence_claim"]}
            or _plain(mot["parameters"]) != _plain(expected_parameters)
            or _plain(mot["derived_parameters"]) != _plain(expected_derived)
            or _plain(mot["resolved_profile"]) != _plain(expected_profile)
            or _plain(mot["capture"]) != _plain(fixed["capture"])
        ):
            raise WorkerProductError("Reviewed 3D-MOT settings differ from the trusted runtime.")
        selected, _ = materialize_frozen_selection(self.root, request)
        started = self._monotonic()
        outcome = self._engine(
            selected,
            _3d_mot_config=_plain(expected_profile),
            gravity_enabled=fixed["gravity_enabled"],
            npools=execution["workers"],
            dt=numerical["dt_s"],
            t_max=numerical["t_max_s"],
            seed=simulation["simulation_seed"],
            capture_config=_plain(mot["capture"]),
        )
        elapsed = self._monotonic() - started
        if not isinstance(outcome, tuple) or len(outcome) != 2 or not math.isfinite(elapsed) or elapsed < 0:
            raise WorkerProductError("3D-MOT engine returned an invalid outcome.")
        trajectories, captured_value = outcome
        if not isinstance(trajectories, (list, tuple)) or len(trajectories) != len(selected):
            raise WorkerProductError("3D-MOT trajectory count is inconsistent.")
        captured = np.asarray(captured_value)
        if captured.dtype != np.dtype(np.float64) or captured.ndim != 2 or captured.shape[1] != 6 or len(captured) > len(selected) or not np.all(np.isfinite(captured)):
            raise WorkerProductError("3D-MOT captured states are inconsistent.")
        time_points = np.linspace(0.0, numerical["t_max_s"], int(np.ceil(numerical["t_max_s"] / numerical["dt_s"])) + 1)
        analysis = self._analyzer(
            trajectories, time_points, capture_config=_plain(mot["capture"])
        )
        try:
            usable = np.asarray(analysis["eligible_masks"][:, -1], dtype=bool)
            residence = np.asarray(analysis["residence_eligible_masks"][:, -1], dtype=bool)
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise WorkerProductError("3D-MOT capture analysis is invalid.") from error
        if usable.shape != (len(selected),) or residence.shape != (len(selected),):
            raise WorkerProductError("3D-MOT capture outcomes are scientifically inconsistent.")
        final_states, final_available = final_states_on_grid(
            trajectories, numerical["t_max_s"]
        )
        expected_captured = np.ascontiguousarray(final_states[residence])
        if (
            final_available.shape != (len(selected),)
            or np.any(residence & ~usable)
            or np.any(residence & ~final_available)
            or captured.shape != expected_captured.shape
            or not np.array_equal(captured, expected_captured)
        ):
            raise WorkerProductError("3D-MOT capture outcomes are scientifically inconsistent.")
        completed = self._clock(); retained = bool(run["retention"]["particle_states"])
        artifacts: dict[str, bytes] = {}; receipt = None; registry = []
        if retained:
            stream = BytesIO(); np.save(stream, np.ascontiguousarray(captured), allow_pickle=False)
            content = stream.getvalue(); artifacts["results/states.npy"] = content
            registry.append({"kind": "particle_states", "path": "results/states.npy", "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)})
        else:
            receipt = {"schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["retention_receipt"], "run_id": run["run_id"], "created_utc": completed, "reason": "particle_states_not_retained"}
            content = encode_record("retention_receipt", receipt)
            registry.append({"kind": "retention_receipt", "path": "results/state_retention_receipt.json", "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)})
        n_input = len(selected); usable_count = int(usable.sum()); residence_count = int(residence.sum())
        metrics = {
            "n_input": n_input,
            "usable_at_end_count": usable_count,
            "usable_at_end_fraction": usable_count / n_input,
            "residence_qualified_captured_count": residence_count,
            "residence_qualified_captured_fraction": residence_count / n_input,
            "elapsed_s": float(elapsed),
            "selection_sha256": resolved["sampling"]["selected_identities_sha256"],
            "provenance": mot_3d_result_provenance(run, configuration),
        }
        return WorkerProduct(
            results={"schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["results"], "run_id": run["run_id"], "completed_utc": completed, "states_retained": retained, "suitability": "individual_only", "metrics": metrics, "artifacts": registry},
            receipt=receipt,
            artifacts=artifacts,
        )


class Mot3DBoundedLocalExecutionPool(BoundedLocalExecutionPool):
    def __init__(self, repository_root: Path, authority: ExecutionAuthority, **kwargs: Any):
        worker_factory = kwargs.pop("worker_factory", lambda: Mot3DLocalWorker(repository_root))
        super().__init__(repository_root, authority, worker_factory=worker_factory, allowed_family="mot_3d", thread_name_prefix="mot3d-local", **kwargs)
