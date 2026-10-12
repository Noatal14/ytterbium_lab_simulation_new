"""Pure admission and immutable review plan for one individual 3D-MOT run."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from lab_setup.numerical_policy import NUMERICAL_POLICY_SHA256, NUMERICAL_POLICY_VERSION
from lab_setup.physical_specification import LABORATORY_PHYSICAL_SPECIFICATION, LABORATORY_SPEC_SHA256, LABORATORY_SPEC_VERSION
from workflow_api.mot_3d_individual_sources import ResolvedMot3DSource, resolve_individual_mot_3d_source
from workflow_api.mot_3d_run_specification import MOT_3D_RUN_SPECIFICATION, MOT_3D_RUN_SPEC_SHA256, MOT_3D_RUN_SPEC_VERSION
from workflow_api.run_records import record_sha256, validate_record
from workflow_api.run_specification import INDIVIDUAL_RUN_SPECIFICATION


@dataclass(frozen=True)
class Mot3DRunRequest:
    source_id: str
    geometry_family: str
    particle_count: int
    selection_seed: int
    simulation_seed: int
    parameters: Mapping[str, float]
    npools: int
    retain_particle_states: bool
    execution_mode: str


@dataclass(frozen=True)
class Mot3DRunReview:
    family: str
    source_id: str
    source_qualification: str
    geometry_family: str
    execution_mode: str
    particle_count: int
    selection_seed: int
    simulation_seed: int
    parameters: Mapping[str, float]
    retain_particle_states: bool
    suitability: str
    locked_settings: Mapping[str, Any]
    output_disposition: str


@dataclass(frozen=True)
class Mot3DRunPlan:
    request: Mot3DRunRequest
    review: Mot3DRunReview
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


def validate_mot_3d_run_request(value: Mapping[str, Any]) -> Mot3DRunRequest:
    spec = MOT_3D_RUN_SPECIFICATION
    if type(value) is dict and set(value) == set(spec["request_fields"]) - {"npools"}:
        mode = value.get("execution_mode")
        value = {
            **value,
            "npools": (
                spec["local_worker_count"]["default"]
                if mode == "local"
                else spec["workers_by_execution_mode"]["zeus"]
            ),
        }
    if type(value) is not dict or set(value) != set(spec["request_fields"]):
        raise ValueError("Individual 3D-MOT request fields are invalid.")
    mode = value["execution_mode"]
    family = value["geometry_family"]
    if mode not in INDIVIDUAL_RUN_SPECIFICATION["execution_modes"] or family not in spec["geometry_families"]:
        raise ValueError("Execution mode or geometry family is invalid.")
    count = value["particle_count"]
    policy = spec["particle_count"]
    if isinstance(count, bool) or not isinstance(count, int) or not policy["minimum"] <= count <= policy["maximum_by_execution_mode"][mode]:
        raise ValueError("Particle count is outside the supported operational limit.")
    seeds = []
    for name in ("selection_seed", "simulation_seed"):
        seed = value[name]; seed_policy = spec[name]
        if isinstance(seed, bool) or not isinstance(seed, int) or not seed_policy["minimum"] <= seed <= seed_policy["maximum"]:
            raise ValueError(f"{name} is outside the supported range.")
        seeds.append(seed)
    source_id = value["source_id"]
    if not isinstance(source_id, str) or re.fullmatch(r"mot3d-source-[0-9a-f]{32}", source_id) is None or not isinstance(value["retain_particle_states"], bool):
        raise ValueError("Source or retention choice is invalid.")
    parameters = value["parameters"]
    expected = dict(spec["common_controls"])
    expected.update(spec["family_controls"][family])
    if type(parameters) is not dict or set(parameters) != set(expected):
        raise ValueError("Geometry parameters are invalid.")
    normalized = {}
    for name, bounds in expected.items():
        item = parameters[name]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) or not bounds["minimum"] <= item <= bounds["maximum"]:
            raise ValueError(f"{name} is outside the reviewed range.")
        normalized[name] = float(item)
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
    return Mot3DRunRequest(source_id, family, count, seeds[0], seeds[1], _freeze(normalized), npools, value["retain_particle_states"], mode)


def _sample(source: ResolvedMot3DSource, count: int, seed: int) -> dict[str, Any]:
    if count > source.pooled_particle_count:
        raise ValueError("Particle count exceeds the selected source.")
    generator = np.random.PCG64(seed); swaps: dict[int, int] = {}; selected = []; modulus = 1 << 64
    for index in range(count):
        bound = source.pooled_particle_count - index; limit = modulus - modulus % bound
        while True:
            raw = int(generator.random_raw())
            if raw < limit:
                offset = raw % bound; break
        chosen = index + offset
        selected.append(swaps.get(chosen, chosen)); swaps[chosen] = swaps.get(index, index)
    rows = np.asarray(sorted(selected), dtype=np.int64)
    counts = np.asarray([record["survivor_count"] for record in source.records], dtype=np.int64)
    boundaries = np.cumsum(counts); indices = np.searchsorted(boundaries, rows, side="right")
    starts = np.concatenate((np.array([0], dtype=np.int64), boundaries[:-1]))
    identities = [[int(record), int(row)] for record, row in zip(indices, rows - starts[indices])]
    digest = hashlib.sha256(json.dumps(identities, separators=(",", ":")).encode()).hexdigest()
    sampling = MOT_3D_RUN_SPECIFICATION["sampling"]
    return {"algorithm": sampling["algorithm"], "version": sampling["version"], "canonical_order": sampling["canonical_order"], "selection_seed": seed, "selected_count": count, "selected_identities": identities, "selected_identities_sha256": digest}


def _artifacts(source: ResolvedMot3DSource) -> list[dict[str, Any]]:
    artifacts = []
    for index, frozen in enumerate(source.records):
        record = _plain(frozen)
        pairs = [("states", record["path"], record["sha256"], record["size_bytes"])]
        if "metadata_path" in record:
            pairs.append(("metadata", record["metadata_path"], record["metadata_sha256"], record["metadata_size_bytes"]))
        for role, path, digest, size in pairs:
            artifacts.append({"id": f"source-{index:03d}-{role}", "role": f"mot_2d_{role}", "path": path, "sha256": digest, "size_bytes": size, "provenance": {"source_id": source.source_id, "source_record_index": index, "source_fingerprint": source.fingerprint}})
    return artifacts


def _outputs(retained: bool) -> list[dict[str, Any]]:
    layout = INDIVIDUAL_RUN_SPECIFICATION["layout"]
    return [
        {"kind": "summary", "path": layout["result_registry"], "required": True},
        {"kind": "particle_states" if retained else "retention_receipt", "path": layout["particle_states"] if retained else layout["retention_receipt"], "required": True},
        {"kind": "run_log", "path": "logs/run.log", "required": False},
    ]


def build_mot_3d_run_plan(request_value: Mapping[str, Any], *, repository_root: Path, run_id: str, git_revision: str, created_utc: str) -> Mot3DRunPlan:
    # Keep the HTTP server's import boundary free of the simulation/study graph.
    # Planning is the first operation that actually needs the established 3D
    # profile builder, so load it only at that boundary.
    from studies.mot_3d.discovery.optimize import build_profile_from_parameters

    request = validate_mot_3d_run_request(request_value)
    root = Path(repository_root).resolve(strict=True)
    source = resolve_individual_mot_3d_source(root, request.source_id)
    sampling = _sample(source, request.particle_count, request.selection_seed)
    fixed = MOT_3D_RUN_SPECIFICATION["fixed_classification"]
    profile, parameters, derived = build_profile_from_parameters(request.geometry_family, request.parameters)
    resolved = {
        "admission_specification": {"version": MOT_3D_RUN_SPEC_VERSION, "sha256": MOT_3D_RUN_SPEC_SHA256},
        "physical_specification": _plain(LABORATORY_PHYSICAL_SPECIFICATION),
        "numerical_policy": {"solver": fixed["solver"], "dt_s": fixed["timestep_s"], "t_max_s": fixed["t_max_s"], "convergence_claim": fixed["convergence_claim"]},
        "input_source": {"id": source.source_id, "kind": source.source_kind, "qualification": source.source_qualification, "fingerprint": source.fingerprint, "pooled_particle_count": source.pooled_particle_count, "records": [_plain(record) for record in source.records]},
        "sampling": sampling,
        "mot_3d": {"geometry_family": request.geometry_family, "parameters": _plain(parameters), "derived_parameters": _plain(derived), "resolved_profile": _plain(profile), "capture": _plain(fixed["capture"])},
        "simulation": {"particle_count": request.particle_count, "simulation_seed": request.simulation_seed, "stochastic": True, "gravity_enabled": fixed["gravity_enabled"]},
        "execution": {"mode": request.execution_mode, "workers": request.npools},
    }
    configuration = {"schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["configuration"], "run_id": run_id, "family": "mot_3d", "laboratory_spec": {"version": LABORATORY_SPEC_VERSION, "sha256": LABORATORY_SPEC_SHA256}, "numerical_policy": {"version": NUMERICAL_POLICY_VERSION, "sha256": NUMERICAL_POLICY_SHA256}, "resolved": resolved}
    inputs = {"schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["inputs"], "run_id": run_id, "family": "mot_3d", "artifacts": _artifacts(source)}
    run = {"schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["run"], "run_id": run_id, "family": "mot_3d", "created_utc": created_utc, "execution_mode": request.execution_mode, "git_revision": git_revision, "configuration_sha256": record_sha256("configuration", configuration), "inputs_sha256": record_sha256("inputs", inputs), "particle_count": request.particle_count, "seed": request.simulation_seed, "solver": fixed["solver"], "timestep_s": fixed["timestep_s"], "retention": {"particle_states": request.retain_particle_states}, "outputs": _outputs(request.retain_particle_states), "suitability": "individual_only"}
    status = {"schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["status"], "run_id": run_id, "revision": 0, "state": "configured", "updated_utc": created_utc, "execution": {"mode": request.execution_mode, "local_pid": None, "zeus_job_id": None}, "error": None}
    for kind, record in (("configuration", configuration), ("inputs", inputs), ("run", run), ("status", status)):
        validate_record(kind, record)
    locked = {"solver": fixed["solver"], "timestep_s": fixed["timestep_s"], "t_max_s": fixed["t_max_s"], "convergence_claim": fixed["convergence_claim"], "capture": _plain(fixed["capture"]), "sampling_algorithm": sampling["algorithm"], "sampling_version": sampling["version"], "workers": resolved["execution"]["workers"]}
    review = Mot3DRunReview("mot_3d", source.source_id, source.source_qualification, request.geometry_family, request.execution_mode, request.particle_count, request.selection_seed, request.simulation_seed, request.parameters, request.retain_particle_states, "individual_only", _freeze(locked), "retain_survivor_states" if request.retain_particle_states else "discard_survivor_states_after_summary")
    records = {"run": run, "configuration": configuration, "inputs": inputs, "status": status}
    digest = hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return Mot3DRunPlan(request, review, _freeze(run), _freeze(configuration), _freeze(inputs), _freeze(status), digest)
