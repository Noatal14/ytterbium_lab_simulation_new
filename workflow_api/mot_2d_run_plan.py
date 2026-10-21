"""Pure admission and immutable review plan for one individual 2D-MOT run."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from config import (
    FORCE_SCALE_N,
    MOT_2D_SIM_CONFIG,
    ZEEMAN_FIELD_CONFIG,
    ZEEMAN_LASER_CONFIG,
)
from lab_setup.numerical_policy import NUMERICAL_POLICY, NUMERICAL_POLICY_SHA256, NUMERICAL_POLICY_VERSION
from lab_setup.physical_specification import LABORATORY_PHYSICAL_SPECIFICATION, LABORATORY_SPEC_SHA256, LABORATORY_SPEC_VERSION
from lab_setup.mag_field_Zeeman import resolved_zeeman_field_construction
from lab_setup.zeeman_laser_setup import resolved_zeeman_laser_parameters
from workflow_api.mot_2d_individual_sources import ResolvedMot2DSource, resolve_individual_mot_2d_source
from workflow_api.mot_2d_run_specification import MOT_2D_RUN_SPECIFICATION, MOT_2D_RUN_SPEC_SHA256, MOT_2D_RUN_SPEC_VERSION
from workflow_api.run_records import record_sha256, validate_record
from workflow_api.run_specification import INDIVIDUAL_RUN_SPECIFICATION, local_worker_maximum, require_local_worker_budget


@dataclass(frozen=True)
class Mot2DRunRequest:
    source_id: str
    particle_count: int
    selection_seed: int
    mot_seed: int
    s0: float
    detuning_gamma: float
    magnet_radius_m: float
    npools: int
    retain_particle_states: bool
    execution_mode: str


@dataclass(frozen=True)
class Mot2DRunReview:
    family: str
    source_id: str
    source_qualification: str
    execution_mode: str
    particle_count: int
    selection_seed: int
    mot_seed: int
    controls: Mapping[str, float]
    retain_particle_states: bool
    suitability: str
    locked_settings: Mapping[str, Any]
    output_disposition: str


@dataclass(frozen=True)
class Mot2DRunPlan:
    request: Mot2DRunRequest
    review: Mot2DRunReview
    run: Mapping[str, Any]
    configuration: Mapping[str, Any]
    inputs: Mapping[str, Any]
    status: Mapping[str, Any]
    plan_sha256: str

    def storage_records(self) -> dict[str, dict[str, Any]]:
        return {key: _plain(value) for key, value in (("run", self.run), ("configuration", self.configuration), ("inputs", self.inputs), ("status", self.status))}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain(child) for child in value]
    if isinstance(value, list):
        return [_plain(child) for child in value]
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def validate_mot_2d_run_request(value: Mapping[str, Any]) -> Mot2DRunRequest:
    spec = MOT_2D_RUN_SPECIFICATION
    if isinstance(value, Mapping) and set(value) == set(spec["request_fields"]) - {"npools"}:
        mode = value.get("execution_mode")
        value = {
            **value,
            "npools": (
                spec["local_worker_count"]["default"]
                if mode == "local"
                else spec["workers_by_execution_mode"]["zeus"]
            ),
        }
    if not isinstance(value, Mapping) or set(value) != set(spec["request_fields"]):
        raise ValueError("Individual 2D-MOT request fields are invalid.")
    mode = value["execution_mode"]
    if mode not in INDIVIDUAL_RUN_SPECIFICATION["execution_modes"]:
        raise ValueError("Execution mode is invalid.")
    count = value["particle_count"]
    policy = spec["particle_count"]
    if isinstance(count, bool) or not isinstance(count, int) or not policy["minimum"] <= count <= policy["maximum_by_execution_mode"][mode]:
        raise ValueError("Particle count is outside the supported operational limit.")
    seeds = []
    for name in ("selection_seed", "mot_seed"):
        seed = value[name]; seed_policy = spec[name]
        if isinstance(seed, bool) or not isinstance(seed, int) or not seed_policy["minimum"] <= seed <= seed_policy["maximum"]:
            raise ValueError(f"{name} is outside the supported range.")
        seeds.append(seed)
    controls = []
    for name in ("s0", "detuning_gamma", "magnet_radius_m"):
        item = value[name]; bounds = spec["controls"][name]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) or not bounds["minimum"] <= item <= bounds["maximum"]:
            raise ValueError(f"{name} is outside the reviewed range.")
        controls.append(float(item))
    if not isinstance(value["source_id"], str) or re.fullmatch(r"mot2d-source-[0-9a-f]{32}", value["source_id"]) is None or not isinstance(value["retain_particle_states"], bool):
        raise ValueError("Source or retention choice is invalid.")
    npools = value["npools"]
    worker_policy = spec["local_worker_count"]
    if (
        isinstance(npools, bool)
        or not isinstance(npools, int)
        or (
            mode == "local"
            and not worker_policy["minimum"] <= npools <= worker_policy["maximum"]
        )
        or (mode == "zeus" and npools != spec["workers_by_execution_mode"]["zeus"])
    ):
        raise ValueError("Worker count is outside the supported range.")
    return Mot2DRunRequest(value["source_id"], count, seeds[0], seeds[1], *controls, npools, value["retain_particle_states"], mode)


def _sample(source: ResolvedMot2DSource, count: int, seed: int) -> dict[str, Any]:
    if count > source.pooled_particle_count:
        raise ValueError("Particle count exceeds the selected source.")
    bit_generator = np.random.PCG64(seed)
    swaps: dict[int, int] = {}
    selected = []
    modulus = 1 << 64
    for index in range(count):
        bound = source.pooled_particle_count - index
        limit = modulus - (modulus % bound)
        while True:
            raw = int(bit_generator.random_raw())
            if raw < limit:
                offset = raw % bound
                break
        chosen_index = index + offset
        chosen_value = swaps.get(chosen_index, chosen_index)
        swaps[chosen_index] = swaps.get(index, index)
        selected.append(chosen_value)
    global_rows = np.asarray(sorted(selected), dtype=np.int64)
    counts = np.asarray([record["survivor_count"] for record in source.records], dtype=np.int64)
    boundaries = np.cumsum(counts)
    record_indices = np.searchsorted(boundaries, global_rows, side="right")
    starts = np.concatenate((np.array([0], dtype=np.int64), boundaries[:-1]))
    local_rows = global_rows - starts[record_indices]
    identities = [[int(record_index), int(row)] for record_index, row in zip(record_indices, local_rows)]
    digest = hashlib.sha256(json.dumps(identities, separators=(",", ":")).encode()).hexdigest()
    return {
        "algorithm": MOT_2D_RUN_SPECIFICATION["sampling"]["algorithm"],
        "version": MOT_2D_RUN_SPECIFICATION["sampling"]["version"],
        "canonical_order": MOT_2D_RUN_SPECIFICATION["sampling"]["canonical_order"],
        "selection_seed": seed,
        "selected_count": count,
        "selected_identities": identities,
        "selected_identities_sha256": digest,
    }


def _artifacts(source: ResolvedMot2DSource) -> list[dict[str, Any]]:
    artifacts = []
    for index, record_value in enumerate(source.records):
        record = _plain(record_value)
        pairs = [("states", record["path"], record["sha256"])]
        if "metadata_path" in record:
            pairs.append(("metadata", record["metadata_path"], record["metadata_sha256"]))
        for role, path, digest in pairs:
            artifacts.append({
                "id": f"source-{index:03d}-{role}", "role": f"zeeman_{role}",
                "path": path, "sha256": digest,
                "size_bytes": record["size_bytes"] if role == "states" else record["metadata_size_bytes"],
                "provenance": {"source_id": source.source_id, "source_record_index": index, "source_fingerprint": source.fingerprint},
            })
    return artifacts


def _outputs(retained: bool) -> list[dict[str, Any]]:
    layout = INDIVIDUAL_RUN_SPECIFICATION["layout"]
    return [
        {"kind": "summary", "path": layout["result_registry"], "required": True},
        {"kind": "particle_states" if retained else "retention_receipt", "path": layout["particle_states"] if retained else layout["retention_receipt"], "required": True},
        {"kind": "run_log", "path": "logs/run.log", "required": False},
    ]


def build_mot_2d_run_plan(request_value: Mapping[str, Any], *, repository_root: Path, run_id: str, git_revision: str, created_utc: str) -> Mot2DRunPlan:
    request = validate_mot_2d_run_request(request_value)
    if request.execution_mode == "local" and "npools" not in request_value:
        request = replace(request, npools=min(request.npools, local_worker_maximum(request.particle_count)))
    require_local_worker_budget(request.execution_mode, request.particle_count, request.npools)
    root = Path(repository_root).resolve(strict=True)
    source = resolve_individual_mot_2d_source(root, request.source_id)
    sampling = _sample(source, request.particle_count, request.selection_seed)
    numerical = NUMERICAL_POLICY["mot_2d"]
    fixed = MOT_2D_RUN_SPECIFICATION["fixed_classification"]
    if numerical["solver"] != fixed["solver"] or numerical["dt_s"] != fixed["timestep_s"] or numerical["t_max_s"] != fixed["t_max_s"] or MOT_2D_SIM_CONFIG != {"dt_s": fixed["timestep_s"], "t_max_s": fixed["t_max_s"], "start_distance_m": fixed["start_distance_m"]} or FORCE_SCALE_N != fixed["force_scale_N"]:
        raise RuntimeError("Active 2D-MOT numerics contradict the reviewed policy.")
    physical = LABORATORY_PHYSICAL_SPECIFICATION
    field = resolved_zeeman_field_construction(
        radii_m=ZEEMAN_FIELD_CONFIG["radii_m"], positions_m=ZEEMAN_FIELD_CONFIG["positions_m"], tilt_angles_deg=ZEEMAN_FIELD_CONFIG["tilt_angles_deg"],
        angle_deg=physical["apparatus"]["zeeman_arm_angle_deg"], start_distance_m=physical["apparatus"]["zeeman_start_distance_m"],
    )
    resolved = {
        "admission_specification": {"version": MOT_2D_RUN_SPEC_VERSION, "sha256": MOT_2D_RUN_SPEC_SHA256},
        "physical_specification": _plain(physical), "numerical_policy": {"solver": fixed["solver"], "dt_s": fixed["timestep_s"], "t_max_s": fixed["t_max_s"]},
        "input_source": {"id": source.source_id, "kind": source.source_kind, "qualification": source.source_qualification, "fingerprint": source.fingerprint, "pooled_particle_count": source.pooled_particle_count, "records": [_plain(record) for record in source.records]},
        "sampling": sampling,
        "mot_2d": {"laser": {"s0": request.s0, "detuning_gamma": request.detuning_gamma, "swap_polarization": False}, "magnet_radius_m": request.magnet_radius_m, "capture_criterion_version": "mot_2d_extract_survivors_v1"},
        "upstream_zeeman_boundary": {"field": field, "laser": resolved_zeeman_laser_parameters(**ZEEMAN_LASER_CONFIG)},
        "simulation": {"particle_count": request.particle_count, "mot_seed": request.mot_seed, "stochastic": True, "gravity_enabled": True, "start_distance_m": fixed["start_distance_m"], "force_scale_N": fixed["force_scale_N"]},
        "execution": {"mode": request.execution_mode, "workers": request.npools},
    }
    configuration = {"schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["configuration"], "run_id": run_id, "family": "mot_2d", "laboratory_spec": {"version": LABORATORY_SPEC_VERSION, "sha256": LABORATORY_SPEC_SHA256}, "numerical_policy": {"version": NUMERICAL_POLICY_VERSION, "sha256": NUMERICAL_POLICY_SHA256}, "resolved": resolved}
    inputs = {"schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["inputs"], "run_id": run_id, "family": "mot_2d", "artifacts": _artifacts(source)}
    run = {"schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["run"], "run_id": run_id, "family": "mot_2d", "created_utc": created_utc, "execution_mode": request.execution_mode, "git_revision": git_revision, "configuration_sha256": record_sha256("configuration", configuration), "inputs_sha256": record_sha256("inputs", inputs), "particle_count": request.particle_count, "seed": request.mot_seed, "solver": fixed["solver"], "timestep_s": fixed["timestep_s"], "retention": {"particle_states": request.retain_particle_states}, "outputs": _outputs(request.retain_particle_states), "suitability": "individual_only"}
    status = {"schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["status"], "run_id": run_id, "revision": 0, "state": "configured", "updated_utc": created_utc, "execution": {"mode": request.execution_mode, "local_pid": None, "zeus_job_id": None}, "error": None}
    for kind, record in (("configuration", configuration), ("inputs", inputs), ("run", run), ("status", status)):
        validate_record(kind, record)
    controls = {"s0": request.s0, "detuning_gamma": request.detuning_gamma, "magnet_radius_m": request.magnet_radius_m}
    locked = {"solver": fixed["solver"], "timestep_s": fixed["timestep_s"], "t_max_s": fixed["t_max_s"], "capture_criterion_version": fixed["capture_criterion_version"], "sampling_algorithm": sampling["algorithm"], "sampling_version": sampling["version"], "workers": resolved["execution"]["workers"]}
    review = Mot2DRunReview("mot_2d", source.source_id, source.source_qualification, request.execution_mode, request.particle_count, request.selection_seed, request.mot_seed, _freeze(controls), request.retain_particle_states, "individual_only", _freeze(locked), "retain_survivor_states" if request.retain_particle_states else "discard_survivor_states_after_summary")
    records = {"run": run, "configuration": configuration, "inputs": inputs, "status": status}
    plan_sha256 = hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return Mot2DRunPlan(request, review, _freeze(run), _freeze(configuration), _freeze(inputs), _freeze(status), plan_sha256)
