"""Pure scientific admission and review plan for one canonical Zeeman run.

No function in this module writes files, starts a process, or contacts Zeus.
The returned records are ready for the D2 storage boundary, but publishing them
belongs to a later explicitly confirmed service.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping

from config import (
    ACTIVE_ZEEMAN_MAGNET_PROFILE,
    COLLIMATION_ANGLE_DEG,
    FORCE_SCALE_N,
    ZEEMAN_FIELD_CONFIG,
    ZEEMAN_LASER_CONFIG,
    ZEEMAN_SIM_CONFIG,
)
from lab_setup.numerical_policy import (
    NUMERICAL_POLICY,
    NUMERICAL_POLICY_SHA256,
    NUMERICAL_POLICY_VERSION,
)
from lab_setup.mag_field_Zeeman import resolved_zeeman_field_construction
from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_PHYSICAL_SPECIFICATION,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
)
from lab_setup.zeeman_laser_setup import resolved_zeeman_laser_parameters
from workflow_api.run_records import record_sha256, validate_record
from workflow_api.run_specification import INDIVIDUAL_RUN_SPECIFICATION
from workflow_api.zeeman_run_specification import (
    ZEEMAN_RUN_SPECIFICATION,
    ZEEMAN_RUN_SPEC_SHA256,
    ZEEMAN_RUN_SPEC_VERSION,
    local_worker_maximum,
)


@dataclass(frozen=True)
class ZeemanRunRequest:
    particle_count: int
    seed: int
    mot_2d_s0: float
    mot_2d_detuning_gamma: float
    mot_2d_magnet_radius_m: float
    npools: int
    retain_particle_states: bool
    execution_mode: str


@dataclass(frozen=True)
class ZeemanRunReview:
    family: str
    execution_mode: str
    particle_count: int
    seed: int
    mot_2d_s0: float
    mot_2d_detuning_gamma: float
    mot_2d_magnet_radius_m: float
    npools: int
    retain_particle_states: bool
    suitability: str
    locked_settings: Mapping[str, Any]
    output_disposition: str


@dataclass(frozen=True)
class ZeemanRunPlan:
    request: ZeemanRunRequest
    review: ZeemanRunReview
    run: Mapping[str, Any]
    configuration: Mapping[str, Any]
    inputs: Mapping[str, Any]
    status: Mapping[str, Any]
    plan_sha256: str

    def storage_records(self) -> dict[str, dict[str, Any]]:
        """Return detached JSON-native copies for the D2 storage boundary."""
        return {
            "run": _plain(self.run),
            "configuration": _plain(self.configuration),
            "inputs": _plain(self.inputs),
            "status": _plain(self.status),
        }


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


def validate_zeeman_run_request(value: Mapping[str, Any]) -> ZeemanRunRequest:
    legacy_fields = {
        "particle_count", "seed", "retain_particle_states", "execution_mode",
    }
    if isinstance(value, Mapping) and set(value) == legacy_fields:
        mode = value.get("execution_mode")
        controls = ZEEMAN_RUN_SPECIFICATION["mot_2d_controls"]
        value = {
            **value,
            "mot_2d_s0": controls["s0"]["default"],
            "mot_2d_detuning_gamma": controls["detuning_gamma"]["default"],
            "mot_2d_magnet_radius_m": controls["magnet_radius_m"]["default"],
            "npools": (
                ZEEMAN_RUN_SPECIFICATION["worker_policy"]["local"]["default"]
                if mode == "local"
                else ZEEMAN_RUN_SPECIFICATION["worker_policy"]["zeus"]["fixed"]
            ),
        }
    if not isinstance(value, Mapping) or set(value) != set(
        ZEEMAN_RUN_SPECIFICATION["request_fields"]
    ):
        raise ValueError("Individual Zeeman-run request fields are invalid.")
    particle_count = value["particle_count"]
    seed = value["seed"]
    mot_2d_s0 = value["mot_2d_s0"]
    mot_2d_detuning = value["mot_2d_detuning_gamma"]
    mot_2d_radius = value["mot_2d_magnet_radius_m"]
    npools = value["npools"]
    retain = value["retain_particle_states"]
    mode = value["execution_mode"]
    if not isinstance(mode, str) or mode not in INDIVIDUAL_RUN_SPECIFICATION[
        "execution_modes"
    ]:
        raise ValueError("Execution mode is invalid.")
    particle_policy = ZEEMAN_RUN_SPECIFICATION["particle_count"]
    if (
        isinstance(particle_count, bool)
        or not isinstance(particle_count, int)
        or not particle_policy["minimum"]
        <= particle_count
        <= particle_policy["maximum_by_execution_mode"][mode]
    ):
        raise ValueError("Particle count is outside the supported limit.")
    seed_policy = ZEEMAN_RUN_SPECIFICATION["seed"]
    if (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or not seed_policy["minimum"] <= seed <= seed_policy["maximum"]
    ):
        raise ValueError("Seed is outside the supported range.")
    if not isinstance(retain, bool):
        raise ValueError("Particle-state retention choice is invalid.")
    controls = ZEEMAN_RUN_SPECIFICATION["mot_2d_controls"]
    for name, candidate in (
        ("s0", mot_2d_s0),
        ("detuning_gamma", mot_2d_detuning),
        ("magnet_radius_m", mot_2d_radius),
    ):
        policy = controls[name]
        if (
            isinstance(candidate, bool)
            or not isinstance(candidate, (int, float))
            or not policy["minimum"] <= float(candidate) <= policy["maximum"]
        ):
            raise ValueError(f"2D-MOT boundary {name} is outside the supported range.")
    worker_policy = ZEEMAN_RUN_SPECIFICATION["worker_policy"]
    local_maximum = local_worker_maximum(particle_count)
    valid_workers = (
        isinstance(npools, int)
        and not isinstance(npools, bool)
        and (
            worker_policy["local"]["minimum"]
            <= npools
            <= local_maximum
            if mode == "local"
            else npools == worker_policy["zeus"]["fixed"]
        )
    )
    if not valid_workers:
        raise ValueError("Worker-pool size is outside the supported range.")
    return ZeemanRunRequest(
        particle_count,
        seed,
        float(mot_2d_s0),
        float(mot_2d_detuning),
        float(mot_2d_radius),
        npools,
        retain,
        mode,
    )


def _resolved_configuration(request: ZeemanRunRequest) -> dict[str, Any]:
    numerical = NUMERICAL_POLICY["zeeman"]
    canonical_profile = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]
    field_arrays = [
        _plain(ZEEMAN_FIELD_CONFIG[key])
        for key in ("radii_m", "positions_m", "tilt_angles_deg")
    ]
    expected_arrays = [
        _plain(canonical_profile[key])
        for key in ("radii_m", "positions_m", "tilt_angles_deg")
    ]
    field_sha256 = hashlib.sha256(
        json.dumps(field_arrays, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if (
        ACTIVE_ZEEMAN_MAGNET_PROFILE != CANONICAL_ZEEMAN_PROFILE_NAME
        or numerical["solver"] != "RK4StCustom"
        or numerical["dt_s"] != ZEEMAN_SIM_CONFIG["dt_s"]
        or numerical["t_max_s"] != ZEEMAN_SIM_CONFIG["t_max_s"]
        or field_arrays != expected_arrays
        or field_sha256 != CANONICAL_ZEEMAN_PROFILE_SHA256
    ):
        raise RuntimeError("Active Zeeman configuration contradicts bundled policy.")
    laser = resolved_zeeman_laser_parameters(**ZEEMAN_LASER_CONFIG)
    field = resolved_zeeman_field_construction(
        radii_m=ZEEMAN_FIELD_CONFIG["radii_m"],
        positions_m=ZEEMAN_FIELD_CONFIG["positions_m"],
        tilt_angles_deg=ZEEMAN_FIELD_CONFIG["tilt_angles_deg"],
        angle_deg=LABORATORY_PHYSICAL_SPECIFICATION["apparatus"][
            "zeeman_arm_angle_deg"
        ],
        start_distance_m=LABORATORY_PHYSICAL_SPECIFICATION["apparatus"][
            "zeeman_start_distance_m"
        ],
    )
    return {
        "admission_specification": {
            "version": ZEEMAN_RUN_SPEC_VERSION,
            "sha256": ZEEMAN_RUN_SPEC_SHA256,
        },
        "physical_specification": _plain(LABORATORY_PHYSICAL_SPECIFICATION),
        "numerical_policy": _plain(numerical),
        "source": {
            "collimation_angle_deg": float(COLLIMATION_ANGLE_DEG),
            "angular_broadening_factor": 1.0,
        },
        "zeeman": {
            "magnet_profile_name": CANONICAL_ZEEMAN_PROFILE_NAME,
            "magnet_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
            "field": field,
            "laser": laser,
        },
        "simulation": {
            "particle_count": request.particle_count,
            "seed": request.seed,
            "stochastic": True,
            "gravity_enabled": True,
            "start_distance_m": float(ZEEMAN_SIM_CONFIG["start_distance_m"]),
            "cutoff_distance_m": float(ZEEMAN_SIM_CONFIG["cutoff_distance_m"]),
            "force_scale_N": float(FORCE_SCALE_N),
        },
        "execution": {
            "mode": request.execution_mode,
            "workers": request.npools,
        },
        # The current engine includes this boundary configuration even though
        # the run stops at the Zeeman exit. Freeze it rather than hiding an
        # implementation dependency from provenance.
        "downstream_boundary": {
            "mot_2d_laser": {
                "s0": request.mot_2d_s0,
                "detuning_gamma": request.mot_2d_detuning_gamma,
                "swap_polarization": False,
            },
            "mot_2d_magnet_radius_m": request.mot_2d_magnet_radius_m,
        },
    }


def _outputs(retained: bool) -> list[dict[str, Any]]:
    layout = INDIVIDUAL_RUN_SPECIFICATION["layout"]
    disposition = layout["particle_states"] if retained else layout["retention_receipt"]
    return [
        {"kind": "summary", "path": layout["result_registry"], "required": True},
        {
            "kind": "particle_states" if retained else "retention_receipt",
            "path": disposition,
            "required": True,
        },
        {"kind": "run_log", "path": "logs/run.log", "required": False},
    ]


def build_zeeman_run_plan(
    request_value: Mapping[str, Any],
    *,
    run_id: str,
    git_revision: str,
    created_utc: str,
) -> ZeemanRunPlan:
    request = validate_zeeman_run_request(request_value)
    resolved = _resolved_configuration(request)
    configuration = {
        "schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"][
            "configuration"
        ],
        "run_id": run_id,
        "family": "zeeman",
        "laboratory_spec": {
            "version": LABORATORY_SPEC_VERSION,
            "sha256": LABORATORY_SPEC_SHA256,
        },
        "numerical_policy": {
            "version": NUMERICAL_POLICY_VERSION,
            "sha256": NUMERICAL_POLICY_SHA256,
        },
        "resolved": resolved,
    }
    inputs = {
        "schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["inputs"],
        "run_id": run_id,
        "family": "zeeman",
        "artifacts": [],
    }
    outputs = _outputs(request.retain_particle_states)
    run = {
        "schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["run"],
        "run_id": run_id,
        "family": "zeeman",
        "created_utc": created_utc,
        "execution_mode": request.execution_mode,
        "git_revision": git_revision,
        "configuration_sha256": record_sha256("configuration", configuration),
        "inputs_sha256": record_sha256("inputs", inputs),
        "particle_count": request.particle_count,
        "seed": request.seed,
        "solver": str(NUMERICAL_POLICY["zeeman"]["solver"]),
        "timestep_s": float(NUMERICAL_POLICY["zeeman"]["dt_s"]),
        "retention": {"particle_states": request.retain_particle_states},
        "outputs": outputs,
        "suitability": "individual_only",
    }
    status = {
        "schema_version": INDIVIDUAL_RUN_SPECIFICATION["record_versions"]["status"],
        "run_id": run_id,
        "revision": 0,
        "state": "configured",
        "updated_utc": created_utc,
        "execution": {
            "mode": request.execution_mode,
            "local_pid": None,
            "zeus_job_id": None,
        },
        "error": None,
    }
    for kind, record in (
        ("configuration", configuration),
        ("inputs", inputs),
        ("run", run),
        ("status", status),
    ):
        validate_record(kind, record)

    locked = {
        "magnet_profile_name": CANONICAL_ZEEMAN_PROFILE_NAME,
        "magnet_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
        "laser_s0": float(ZEEMAN_LASER_CONFIG["s0"]),
        "laser_detuning_gamma": float(ZEEMAN_LASER_CONFIG["detuning_gamma"]),
        "solver": str(NUMERICAL_POLICY["zeeman"]["solver"]),
        "timestep_s": float(NUMERICAL_POLICY["zeeman"]["dt_s"]),
        "t_max_s": float(NUMERICAL_POLICY["zeeman"]["t_max_s"]),
        "workers": request.npools,
    }
    review = ZeemanRunReview(
        family="zeeman",
        execution_mode=request.execution_mode,
        particle_count=request.particle_count,
        seed=request.seed,
        mot_2d_s0=request.mot_2d_s0,
        mot_2d_detuning_gamma=request.mot_2d_detuning_gamma,
        mot_2d_magnet_radius_m=request.mot_2d_magnet_radius_m,
        npools=request.npools,
        retain_particle_states=request.retain_particle_states,
        suitability="individual_only",
        locked_settings=_freeze(locked),
        output_disposition=(
            "retain_survivor_states"
            if request.retain_particle_states
            else "discard_survivor_states_after_summary"
        ),
    )
    records = {
        "run": run,
        "configuration": configuration,
        "inputs": inputs,
        "status": status,
    }
    plan_sha256 = hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ZeemanRunPlan(
        request=request,
        review=review,
        run=_freeze(run),
        configuration=_freeze(configuration),
        inputs=_freeze(inputs),
        status=_freeze(status),
        plan_sha256=plan_sha256,
    )
