"""Strict immutable loader for individual 3D-MOT admission policy."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Any

from config import (
    DEFAULT_NUM_POOLS,
    MOT_3D_CAPTURE_CONFIG,
    MOT_3D_CONFIGURATIONS,
    MOT_3D_OPTIMIZATION_CONFIG,
    MOT_3D_SIM_CONFIG,
)
from lab_setup.mot_3d_timestep_policy import MOT_3D_TIMESTEP_POLICY


SPECIFICATION_PATH = (
    Path(__file__).with_name("specifications") / "mot_3d_individual_v1.json"
)
MAX_SPECIFICATION_BYTES = 64 * 1024
_FIELDS = [
    "source_id", "geometry_family", "particle_count", "selection_seed",
    "simulation_seed", "parameters", "retain_particle_states", "execution_mode",
]
_FAMILIES = ["angled_donut", "single_pass"]
_COMMON = (
    "green_s0", "green_detuning_gamma", "green_waist_m", "blue_s0",
    "blue_waist_m", "magnetic_gradient_G_cm",
)
_FAMILY = {
    "angled_donut": ("blue_detuning_gamma", "core_shell_split_radius_m"),
    "single_pass": (
        "blue_detuning_anchor_gamma", "blue_crossing_angle_deg",
        "blue_crossing_z_offset_m",
    ),
}


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _unique(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise ValueError("Duplicate specification key.")
        value[key] = child
    return value


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _expected_bounds() -> tuple[dict[str, tuple[float, float]], dict[str, dict[str, tuple[float, float]]]]:
    common = MOT_3D_OPTIMIZATION_CONFIG["common"]
    common_bounds = {
        name: tuple(common[f"{name}_bounds"]) for name in _COMMON
    }
    family_bounds = {
        family: {
            name: tuple(MOT_3D_OPTIMIZATION_CONFIG[family][f"{name}_bounds"])
            for name in names
        }
        for family, names in _FAMILY.items()
    }
    return common_bounds, family_bounds


def _expected_defaults() -> dict[str, dict[str, float]]:
    donut = MOT_3D_CONFIGURATIONS["angled_donut"]
    single = MOT_3D_CONFIGURATIONS["single_pass"]
    anchor = single["399"]["detuning_gamma"]
    # The runnable profile stores the resolved blue detuning.  The individual
    # contract exposes the campaign's anchor parameterization, so derive the
    # unique anchor that round-trips to that runnable profile.
    settings = MOT_3D_OPTIMIZATION_CONFIG["single_pass"]
    slowing_position = (
        single["blue_crossing_z_offset_m"]
        - settings["slowing_position_waist_factor"] * single["399"]["waist_m"]
    )
    field_g = single["magnetic_gradient_G_cm"] * abs(100.0 * slowing_position)
    reference_position = (
        settings["reference_crossing_z_offset_m"]
        - settings["slowing_position_waist_factor"]
        * settings["reference_blue_waist_m"]
    )
    reference_field_g = settings["reference_gradient_G_cm"] * abs(
        100.0 * reference_position
    )
    resolved_at_zero = settings["blue_zeeman_gamma_per_G"] * (
        field_g - reference_field_g
    )
    return {
        "angled_donut": {
            "green_s0": donut["556"]["s0"],
            "green_detuning_gamma": donut["556"]["detuning_gamma"],
            "green_waist_m": donut["556"]["waist_m"],
            "blue_s0": donut["399"]["s0"],
            "blue_waist_m": donut["399"]["waist_m"],
            "magnetic_gradient_G_cm": donut["magnetic_gradient_G_cm"],
            "blue_detuning_gamma": donut["399"]["detuning_gamma"],
            "core_shell_split_radius_m": donut["399"]["inner_cutoff_radius_m"],
        },
        "single_pass": {
            "green_s0": single["556"]["s0"],
            "green_detuning_gamma": single["556"]["detuning_gamma"],
            "green_waist_m": single["556"]["waist_m"],
            "blue_s0": single["399"]["s0"],
            "blue_waist_m": single["399"]["waist_m"],
            "magnetic_gradient_G_cm": single["magnetic_gradient_G_cm"],
            "blue_detuning_anchor_gamma": anchor - resolved_at_zero,
            "blue_crossing_angle_deg": single["blue_crossing_angle_deg"],
            "blue_crossing_z_offset_m": single["blue_crossing_z_offset_m"],
        },
    }


def _validate_range(row: Any, expected: tuple[float, float]) -> None:
    if (
        not isinstance(row, dict)
        or set(row) != {"minimum", "maximum"}
        or not all(_finite_number(value) for value in row.values())
        or (row["minimum"], row["maximum"]) != expected
        or row["minimum"] >= row["maximum"]
    ):
        raise ValueError("Invalid 3D-MOT control range.")


def _validate(value: Any) -> dict[str, Any]:
    keys = {
        "spec_version", "request_fields", "geometry_families", "particle_count",
        "selection_seed", "simulation_seed", "common_controls", "family_controls",
        "defaults", "workers_by_execution_mode", "sampling", "fixed_classification",
    }
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or value["spec_version"] != "mot-3d-individual-v1"
        or value["request_fields"] != _FIELDS
        or value["geometry_families"] != _FAMILIES
    ):
        raise ValueError("Invalid individual 3D-MOT specification.")
    particle_policy = {
        "minimum": 1,
        "default": 200,
        "maximum_by_execution_mode": {"local": 1000, "zeus": 50000},
    }
    if value["particle_count"] != particle_policy:
        raise ValueError("Invalid particle policy.")
    seed_policy = {"minimum": 0, "maximum": 4294967295, "default": 42}
    if value["selection_seed"] != seed_policy or value["simulation_seed"] != seed_policy:
        raise ValueError("Invalid seed policy.")
    common_bounds, family_bounds = _expected_bounds()
    if set(value["common_controls"]) != set(common_bounds):
        raise ValueError("Invalid common controls.")
    for name, expected in common_bounds.items():
        _validate_range(value["common_controls"][name], expected)
    if set(value["family_controls"]) != set(family_bounds):
        raise ValueError("Invalid family controls.")
    for family, bounds in family_bounds.items():
        if set(value["family_controls"][family]) != set(bounds):
            raise ValueError("Invalid family controls.")
        for name, expected in bounds.items():
            _validate_range(value["family_controls"][family][name], expected)
    expected_defaults = _expected_defaults()
    if set(value["defaults"]) != set(expected_defaults):
        raise ValueError("Invalid 3D-MOT defaults.")
    for family, expected in expected_defaults.items():
        observed = value["defaults"][family]
        if set(observed) != set(expected) or any(
            not _finite_number(item) or not math.isclose(float(item), float(expected[name]), rel_tol=0.0, abs_tol=1e-15)
            for name, item in observed.items()
        ):
            raise ValueError("Individual defaults do not match the runnable profile.")
        all_bounds = common_bounds | family_bounds[family]
        if any(not all_bounds[name][0] <= observed[name] <= all_bounds[name][1] for name in observed):
            raise ValueError("Individual default is outside its reviewed range.")
    if value["workers_by_execution_mode"] != {"local": DEFAULT_NUM_POOLS, "zeus": 200}:
        raise ValueError("Invalid worker policy.")
    if value["sampling"] != {
        "algorithm": "pcg64-raw-partial-fisher-yates-unbiased",
        "version": "v1",
        "canonical_order": "constituent-record-order-then-row-index",
    }:
        raise ValueError("Invalid sampling policy.")
    expected_fixed = {
        "suitability": "individual_only",
        "solver": MOT_3D_SIM_CONFIG["solver"],
        "timestep_s": MOT_3D_SIM_CONFIG["dt_s"],
        # Individual 3D runs use the canonical campaign horizon.  This is an
        # explicit part of this versioned contract, not the shorter generic
        # presentation/default horizon exposed by MOT_3D_SIM_CONFIG.
        "t_max_s": 0.1,
        "convergence_claim": "not_established",
        "gravity_enabled": True,
        "capture": {
            "capture_radius_m": MOT_3D_CAPTURE_CONFIG["capture_radius_m"],
            "minimum_residence_time_s": MOT_3D_CAPTURE_CONFIG["minimum_residence_time_s"],
            "maximum_final_speed_m_s": MOT_3D_CAPTURE_CONFIG["maximum_final_speed_m_s"],
        },
        "green_full_angle_deg": MOT_3D_OPTIMIZATION_CONFIG["single_pass"]["green_full_angle_deg"],
        "donut_shared_aperture_radius_m": MOT_3D_OPTIMIZATION_CONFIG["angled_donut"]["shared_aperture_radius_m"],
        "single_pass_green_aperture_radius_m": MOT_3D_OPTIMIZATION_CONFIG["single_pass"]["green_aperture_radius_m"],
        "single_pass_blue_aperture_radius_m": MOT_3D_OPTIMIZATION_CONFIG["single_pass"]["blue_aperture_radius_m"],
    }
    if (
        value["fixed_classification"] != expected_fixed
        or MOT_3D_TIMESTEP_POLICY["search_dt_s"] != expected_fixed["timestep_s"]
        or MOT_3D_TIMESTEP_POLICY["convergence_claim"] != "not_established"
    ):
        raise ValueError("Invalid fixed classification.")
    return value


def _read() -> dict[str, Any]:
    try:
        before = SPECIFICATION_PATH.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SPECIFICATION_BYTES:
            raise ValueError
        descriptor = os.open(
            SPECIFICATION_PATH, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            opened = os.fstat(descriptor)
            raw = os.read(descriptor, MAX_SPECIFICATION_BYTES + 1)
            after = os.fstat(descriptor)
            identity = lambda item: (
                item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns,
            )
            if (
                len(raw) != opened.st_size
                or len(raw) > MAX_SPECIFICATION_BYTES
                or identity(opened) != identity(before)
                or identity(after) != identity(opened)
            ):
                raise ValueError
        finally:
            os.close(descriptor)
        return _validate(
            json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError(
            "The bundled individual 3D-MOT specification is invalid."
        ) from error


_VALUE = _read()
MOT_3D_RUN_SPECIFICATION = _freeze(_VALUE)
MOT_3D_RUN_SPEC_VERSION = _VALUE["spec_version"]
MOT_3D_RUN_SPEC_SHA256 = hashlib.sha256(
    json.dumps(_VALUE, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
