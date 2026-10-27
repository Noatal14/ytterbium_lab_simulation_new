"""Strict immutable loader for individual 2D-MOT admission policy."""

from __future__ import annotations

import hashlib
import json
import math
from workflow_api.platform_io import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Any

from workflow_api.individual_limits import particle_policy
from config import DEFAULT_NUM_POOLS
from lab_setup.numerical_policy import NUMERICAL_POLICY


SPECIFICATION_PATH = Path(__file__).with_name("specifications") / "mot_2d_individual_v1.json"
MAX_SPECIFICATION_BYTES = 32 * 1024
_FIELDS = ["source_id", "particle_count", "selection_seed", "mot_seed", "s0", "detuning_gamma", "magnet_radius_m", "npools", "retain_particle_states", "execution_mode"]


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


def _validate(value: Any) -> dict[str, Any]:
    keys = {"spec_version", "request_fields", "particle_count", "selection_seed", "mot_seed", "controls", "workers_by_execution_mode", "local_worker_count", "sampling", "fixed_classification"}
    if not isinstance(value, dict) or set(value) != keys or value["spec_version"] != "mot-2d-individual-v1" or value["request_fields"] != _FIELDS:
        raise ValueError("Invalid individual 2D-MOT specification.")
    modes = {"local", "zeus"}
    particles = value["particle_count"]
    if set(particles) != {"minimum", "default", "maximum_by_execution_mode"} or set(particles["maximum_by_execution_mode"]) != modes:
        raise ValueError("Invalid particle policy.")
    integers = [particles["minimum"], particles["default"], *particles["maximum_by_execution_mode"].values()]
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in integers) or particles != particle_policy():
        raise ValueError("Invalid particle policy.")
    for name in ("selection_seed", "mot_seed"):
        policy = value[name]
        if set(policy) != {"minimum", "maximum", "default"} or policy != {"minimum": 0, "maximum": 4294967295, "default": 42}:
            raise ValueError("Invalid seed policy.")
    # The s0 interval is the explicitly approved individual-run UI operating
    # range.  It is not a claim that every value is physically optimal.
    expected_controls = {"s0": (0.1, 3.0, 1.3), "detuning_gamma": (-1.55, -0.85, -0.9196610026631429), "magnet_radius_m": (0.045, 0.051, 0.04676406447474441)}
    if set(value["controls"]) != set(expected_controls):
        raise ValueError("Invalid controls.")
    for name, expected in expected_controls.items():
        row = value["controls"][name]
        if set(row) != {"minimum", "maximum", "default"} or tuple(row[key] for key in ("minimum", "maximum", "default")) != expected or any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) for item in row.values()):
            raise ValueError("Invalid controls.")
    if value["workers_by_execution_mode"] != {"local": DEFAULT_NUM_POOLS, "zeus": 200}:
        raise ValueError("Invalid worker policy.")
    if value["local_worker_count"] != {"minimum": 1, "maximum": 256, "default": DEFAULT_NUM_POOLS}:
        raise ValueError("Invalid local worker policy.")
    if value["sampling"] != {"algorithm": "pcg64-raw-partial-fisher-yates-unbiased", "version": "v1", "canonical_order": "constituent-record-order-then-row-index"}:
        raise ValueError("Invalid sampling policy.")
    fixed = value["fixed_classification"]
    expected_fixed = {"suitability": "individual_only", "solver": "RK4StHybridCustom", "timestep_s": 0.000000625, "t_max_s": 0.025, "start_distance_m": 0.1, "force_scale_N": 3.141895058426422e-20, "capture_criterion_version": "mot_2d_extract_survivors_v1"}
    if fixed != expected_fixed or NUMERICAL_POLICY["mot_2d"]["solver"] != fixed["solver"] or NUMERICAL_POLICY["mot_2d"]["dt_s"] != fixed["timestep_s"] or NUMERICAL_POLICY["mot_2d"]["t_max_s"] != fixed["t_max_s"]:
        raise ValueError("Invalid fixed classification.")
    return value


def _read() -> dict[str, Any]:
    try:
        before = SPECIFICATION_PATH.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SPECIFICATION_BYTES:
            raise ValueError
        descriptor = os.open(SPECIFICATION_PATH, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor); raw = os.read(descriptor, MAX_SPECIFICATION_BYTES + 1); after = os.fstat(descriptor)
            if len(raw) != opened.st_size or len(raw) > MAX_SPECIFICATION_BYTES or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
                raise ValueError
        finally:
            os.close(descriptor)
        return _validate(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError("The bundled individual 2D-MOT specification is invalid.") from error


_VALUE = _read()
MOT_2D_RUN_SPECIFICATION = _freeze(_VALUE)
MOT_2D_RUN_SPEC_VERSION = _VALUE["spec_version"]
MOT_2D_RUN_SPEC_SHA256 = hashlib.sha256(json.dumps(_VALUE, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
