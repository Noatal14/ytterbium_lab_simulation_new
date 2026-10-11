"""Strict immutable loader for the versioned numerical integration policy."""

from __future__ import annotations

import os
from pathlib import Path

from lab_setup.strict_specification import (
    canonical_digest as _digest,
    freeze as _freeze,
    read_strict_json,
    require_exact_keys as _exact,
    require_finite_number,
)

SPECIFICATION_PATH = Path(__file__).with_name("specifications") / "numerical_policy_v1.json"
MAX_SPECIFICATION_BYTES = 32 * 1024


def _positive(value, label):
    require_finite_number(value, label, lo=0)


def _solver(value, expected, label):
    if value != expected:
        raise ValueError(f"Invalid {label} solver.")


def _validate(value):
    _exact(value, {"spec_version", "zeeman", "mot_2d", "mot_3d"}, "numerical policy")
    if value["spec_version"] != "numerical-policy-v1":
        raise ValueError("Invalid numerical policy version.")
    for stage, expected_solver in (("zeeman", "RK4StCustom"), ("mot_2d", "RK4StHybridCustom")):
        section = value[stage]
        _exact(section, {"solver", "dt_s", "t_max_s"}, stage)
        _solver(section["solver"], expected_solver, stage)
        _positive(section["dt_s"], f"{stage} dt")
        _positive(section["t_max_s"], f"{stage} t_max")
        if section["dt_s"] >= section["t_max_s"]:
            raise ValueError(f"Invalid {stage} timestep horizon.")
    mot_3d = value["mot_3d"]
    _exact(mot_3d, {
        "solver", "dt_s", "screening_dt_s", "production_dt_s",
        "dt_validation_candidates_s", "dt_validation_reference_s", "t_max_s",
    }, "mot_3d")
    _solver(mot_3d["solver"], "RK4StHybridCustom", "mot_3d")
    for key in ("dt_s", "screening_dt_s", "production_dt_s", "dt_validation_reference_s", "t_max_s"):
        _positive(mot_3d[key], f"mot_3d {key}")
    candidates = mot_3d["dt_validation_candidates_s"]
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Invalid mot_3d validation candidates.")
    for item in candidates:
        try:
            _positive(item, "mot_3d validation candidate")
        except ValueError as error:
            raise ValueError("Invalid mot_3d validation candidates.") from error
    if any(left <= right for left, right in zip(candidates, candidates[1:])):
        raise ValueError("Invalid mot_3d validation candidates.")
    if (mot_3d["dt_s"] != mot_3d["screening_dt_s"]
            or mot_3d["production_dt_s"] > mot_3d["screening_dt_s"]
            or mot_3d["screening_dt_s"] not in candidates
            or mot_3d["production_dt_s"] not in candidates
            or mot_3d["dt_validation_reference_s"] >= min(candidates)
            or any(item >= mot_3d["t_max_s"] for item in candidates)):
        raise ValueError("Invalid mot_3d numerical-policy relationships.")
    return value


def _read_validated():
    return read_strict_json(
        SPECIFICATION_PATH,
        _validate,
        max_bytes=MAX_SPECIFICATION_BYTES,
        error_message="The bundled numerical policy is invalid.",
    )


_VALUE = _read_validated()
NUMERICAL_POLICY = _freeze(_VALUE)
NUMERICAL_POLICY_VERSION = _VALUE["spec_version"]
NUMERICAL_POLICY_SHA256 = _digest(_VALUE)
