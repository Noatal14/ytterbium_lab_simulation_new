"""Strict immutable loader for the versioned numerical integration policy."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from pathlib import Path
from types import MappingProxyType

SPECIFICATION_PATH = Path(__file__).with_name("specifications") / "numerical_policy_v1.json"
MAX_SPECIFICATION_BYTES = 32 * 1024


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"Invalid {label} schema.")


def _positive(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"Invalid {label}.")


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
    if (not isinstance(candidates, list) or not candidates
            or any(isinstance(item, bool) or not isinstance(item, (int, float))
                   or not math.isfinite(item) or item <= 0 for item in candidates)
            or any(left <= right for left, right in zip(candidates, candidates[1:]))):
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
    try:
        before = SPECIFICATION_PATH.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SPECIFICATION_BYTES:
            raise ValueError
        descriptor = os.open(SPECIFICATION_PATH, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_SPECIFICATION_BYTES
                    or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                    != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)):
                raise ValueError
            chunks, remaining = [], MAX_SPECIFICATION_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(16 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
            if (len(raw) > MAX_SPECIFICATION_BYTES
                    or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                    != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)):
                raise ValueError
        finally:
            os.close(descriptor)
        return _validate(json.loads(raw.decode("utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError("The bundled numerical policy is invalid.") from error


_VALUE = _read_validated()
NUMERICAL_POLICY = _freeze(_VALUE)
NUMERICAL_POLICY_VERSION = _VALUE["spec_version"]
NUMERICAL_POLICY_SHA256 = _digest(_VALUE)
