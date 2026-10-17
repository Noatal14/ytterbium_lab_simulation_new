"""Strict immutable loader for the individual Zeeman-run admission contract."""

from __future__ import annotations

import hashlib
import json
from workflow_api.platform_io import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Any

from config import DEFAULT_NUM_PARTICLES, DEFAULT_NUM_POOLS, DEFAULT_RANDOM_SEED
from workflow_api.mot_2d_run_specification import MOT_2D_RUN_SPECIFICATION


SPECIFICATION_PATH = (
    Path(__file__).with_name("specifications") / "zeeman_individual_v1.json"
)
MAX_SPECIFICATION_BYTES = 32 * 1024
_REQUEST_FIELDS = [
    "particle_count",
    "seed",
    "mot_2d_s0",
    "mot_2d_detuning_gamma",
    "mot_2d_magnet_radius_m",
    "npools",
    "retain_particle_states",
    "execution_mode",
]
_EXECUTION_MODES = {"local", "zeus"}


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"Invalid {label} schema.")
    return value


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"Invalid {label}.")
    return value


def _nonnegative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Invalid {label}.")
    return value


def _validate(value: Any) -> dict[str, Any]:
    row = _exact(
        value,
        {
            "spec_version",
            "request_fields",
            "particle_count",
            "seed",
            "mot_2d_controls",
            "worker_policy",
            "fixed_classification",
        },
        "individual Zeeman-run specification",
    )
    if row["spec_version"] != "zeeman-individual-v1":
        raise ValueError("Invalid individual Zeeman-run specification version.")
    if row["request_fields"] != _REQUEST_FIELDS:
        raise ValueError("Invalid individual Zeeman-run request fields.")

    particles = _exact(
        row["particle_count"],
        {"minimum", "default_by_execution_mode", "maximum_by_execution_mode"},
        "particle-count policy",
    )
    defaults = _exact(
        particles["default_by_execution_mode"],
        _EXECUTION_MODES,
        "particle-count execution defaults",
    )
    maximums = _exact(
        particles["maximum_by_execution_mode"],
        _EXECUTION_MODES,
        "particle-count execution limits",
    )
    minimum = _positive_integer(particles["minimum"], "minimum particle count")
    for mode in _EXECUTION_MODES:
        default = _positive_integer(defaults[mode], f"{mode} default particle count")
        maximum = _positive_integer(maximums[mode], f"{mode} particle-count limit")
        if not minimum <= default <= maximum:
            raise ValueError("Invalid particle-count policy relationship.")
    if defaults["zeus"] != DEFAULT_NUM_PARTICLES:
        raise ValueError("Zeus particle-count default diverges from the active configuration.")

    seed = _exact(row["seed"], {"minimum", "maximum", "default"}, "seed policy")
    seed_minimum = _nonnegative_integer(seed["minimum"], "minimum seed")
    seed_maximum = _nonnegative_integer(seed["maximum"], "maximum seed")
    seed_default = _nonnegative_integer(seed["default"], "default seed")
    if not seed_minimum <= seed_default <= seed_maximum:
        raise ValueError("Invalid seed policy relationship.")
    if seed_default != DEFAULT_RANDOM_SEED:
        raise ValueError("Seed default diverges from the active configuration.")

    controls = _exact(
        row["mot_2d_controls"],
        {"s0", "detuning_gamma", "magnet_radius_m"},
        "2D-MOT boundary controls",
    )
    expected_controls = {
        name: dict(policy)
        for name, policy in MOT_2D_RUN_SPECIFICATION["controls"].items()
    }
    if controls != expected_controls:
        raise ValueError("Invalid 2D-MOT boundary control policy.")

    workers = _exact(row["worker_policy"], _EXECUTION_MODES, "worker policy")
    local = _exact(workers["local"], {"minimum", "maximum", "default"}, "local worker policy")
    zeus = _exact(workers["zeus"], {"fixed"}, "Zeus worker policy")
    for key in ("minimum", "maximum", "default"):
        _positive_integer(local[key], f"local worker {key}")
    _positive_integer(zeus["fixed"], "Zeus worker count")
    if not local["minimum"] <= local["default"] <= local["maximum"]:
        raise ValueError("Invalid local worker policy relationship.")
    if local["default"] != DEFAULT_NUM_POOLS:
        raise ValueError("Local worker count diverges from the active configuration.")

    classification = _exact(
        row["fixed_classification"],
        {"suitability", "magnet_profile_policy", "solver_policy"},
        "fixed classification",
    )
    if classification != {
        "suitability": "individual_only",
        "magnet_profile_policy": "canonical_only",
        "solver_policy": "bundled_numerical_policy",
    }:
        raise ValueError("Invalid individual Zeeman-run classification.")
    return row


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate specification key {key!r}.")
        value[key] = item
    return value


def _read_validated() -> dict[str, Any]:
    try:
        before = SPECIFICATION_PATH.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SPECIFICATION_BYTES:
            raise ValueError
        descriptor = os.open(
            SPECIFICATION_PATH, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            opened = os.fstat(descriptor)
            identity = (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            )
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_size > MAX_SPECIFICATION_BYTES
                or identity
                != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            ):
                raise ValueError
            chunks = []
            remaining = MAX_SPECIFICATION_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(16 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
            if (
                len(raw) != opened.st_size
                or len(raw) > MAX_SPECIFICATION_BYTES
                or (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                )
                != identity
            ):
                raise ValueError
        finally:
            os.close(descriptor)
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        return _validate(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError(
            "The bundled individual Zeeman-run specification is invalid."
        ) from error


_VALUE = _read_validated()
ZEEMAN_RUN_SPECIFICATION = _freeze(_VALUE)
ZEEMAN_RUN_SPEC_VERSION = _VALUE["spec_version"]
ZEEMAN_RUN_SPEC_SHA256 = _digest(_VALUE)


def local_worker_maximum(particle_count: int, *, available_cpus: int | None = None) -> int:
    """Return the reviewed host-safe process limit for one local Zeeman run."""
    if isinstance(particle_count, bool) or not isinstance(particle_count, int) or particle_count < 1:
        raise ValueError("Particle count is invalid for the local worker policy.")
    detected = os.cpu_count() if available_cpus is None else available_cpus
    if isinstance(detected, bool) or not isinstance(detected, int) or detected < 1:
        detected = 1
    return min(
        ZEEMAN_RUN_SPECIFICATION["worker_policy"]["local"]["maximum"],
        detected,
        particle_count,
    )


def render_typescript_specification() -> str:
    """Render the checked-in browser contract from the validated authority."""
    body = json.dumps(_VALUE, indent=2, sort_keys=True)
    return (
        "// Generated from workflow_api/specifications/zeeman_individual_v1.json; "
        "do not edit.\n"
        f"export const ZEEMAN_INDIVIDUAL_SPECIFICATION_V1 = {body} as const;\n"
    )
