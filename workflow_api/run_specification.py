"""Strict immutable loader for the individual-run storage contract.

This specification describes storage and lifecycle semantics only.  Scientific
configuration fields and approved numerical values remain owned by their
family-specific validators and the versioned laboratory/numerical policies.
"""

from __future__ import annotations

import hashlib
import json
from workflow_api.platform_io import os
from pathlib import Path, PurePosixPath
import stat
from types import MappingProxyType


SPECIFICATION_PATH = (
    Path(__file__).with_name("specifications") / "individual_run_v1.json"
)
MAX_SPECIFICATION_BYTES = 64 * 1024
_RECORD_VERSIONS = {
    "run": "individual-run-v1",
    "configuration": "run-configuration-v1",
    "inputs": "run-inputs-v1",
    "status": "run-status-v1",
    "results": "run-results-v1",
    "retention_receipt": "state-retention-receipt-v1",
}
_IMMUTABLE_FILES = ["run.json", "configuration.json", "inputs.json"]
_MUTABLE_FILES = ["status.json"]
_OUTPUT_KINDS = [
    "summary",
    "particle_states",
    "retention_receipt",
    "run_log",
    "scheduler_receipt",
]
_TRANSITIONS = {
    "configured": ["validated", "cancelled"],
    "validated": ["reviewed", "configured", "cancelled"],
    "reviewed": ["queued", "running", "configured", "cancelled"],
    "queued": ["running", "failed", "outcome_unknown", "cancelled"],
    "running": ["succeeded", "failed", "outcome_unknown", "cancelled"],
    "succeeded": [],
    "failed": [],
    "outcome_unknown": [],
    "cancelled": [],
}
_TERMINAL_STATES = ["succeeded", "failed", "outcome_unknown", "cancelled"]
_LIMITS = {
    "run_id_max_characters": 96,
    "json_max_bytes": 8 * 1024 * 1024,
    "artifact_count_maximum": 128,
    "path_max_bytes": 512,
}


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"Invalid {label} schema.")


def _string_list(value, label, *, unique=True):
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or (unique and len(value) != len(set(value)))
    ):
        raise ValueError(f"Invalid {label}.")


def _relative_path(value, label):
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or not value.isprintable()
        or len(value.encode("utf-8")) > _LIMITS["path_max_bytes"]
    ):
        raise ValueError(f"Invalid {label}.")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError(f"Invalid {label}.")


def _validate(value):
    _exact(
        value,
        {
            "spec_version",
            "record_versions",
            "layout",
            "execution_modes",
            "lifecycle",
            "output_kinds",
            "retention",
            "suitability_levels",
            "limits",
        },
        "individual-run specification",
    )
    if value["spec_version"] != "individual-run-specification-v1":
        raise ValueError("Invalid individual-run specification version.")

    versions = value["record_versions"]
    _exact(
        versions,
        {"run", "configuration", "inputs", "status", "results", "retention_receipt"},
        "record versions",
    )
    if versions != _RECORD_VERSIONS:
        raise ValueError("Invalid record versions.")

    layout = value["layout"]
    _exact(
        layout,
        {
            "root",
            "families",
            "immutable_files",
            "mutable_files",
            "result_registry",
            "particle_states",
            "retention_receipt",
            "logs_directory",
        },
        "run layout",
    )
    if layout["root"] != "data/runs" or layout["families"] != [
        "zeeman",
        "mot_2d",
        "mot_3d",
    ]:
        raise ValueError("Invalid canonical run root or families.")
    if layout["immutable_files"] != _IMMUTABLE_FILES:
        raise ValueError("Invalid immutable record files.")
    if layout["mutable_files"] != _MUTABLE_FILES:
        raise ValueError("Invalid mutable record files.")
    expected_layout_paths = {
        "result_registry": "results/summary.json",
        "particle_states": "results/states.npy",
        "retention_receipt": "results/state_retention_receipt.json",
        "logs_directory": "logs",
    }
    if any(layout[key] != expected for key, expected in expected_layout_paths.items()):
        raise ValueError("Invalid canonical run layout paths.")
    for key in (
        "root",
        "result_registry",
        "particle_states",
        "retention_receipt",
        "logs_directory",
    ):
        _relative_path(layout[key], key)
    for path in layout["immutable_files"] + layout["mutable_files"]:
        _relative_path(path, "record path")
    all_paths = (
        layout["immutable_files"]
        + layout["mutable_files"]
        + [layout[key] for key in ("result_registry", "particle_states", "retention_receipt")]
    )
    if len(all_paths) != len(set(all_paths)):
        raise ValueError("Run layout contains duplicate paths.")

    if value["execution_modes"] != ["local", "zeus"]:
        raise ValueError("Invalid execution modes.")
    if value["output_kinds"] != _OUTPUT_KINDS:
        raise ValueError("Invalid output kinds.")
    if value["suitability_levels"] != ["individual_only", "campaign_input"]:
        raise ValueError("Invalid suitability levels.")

    lifecycle = value["lifecycle"]
    _exact(lifecycle, {"initial", "terminal", "transitions"}, "lifecycle")
    transitions = lifecycle["transitions"]
    if not isinstance(transitions, dict) or not transitions:
        raise ValueError("Invalid lifecycle transitions.")
    states = set(transitions)
    if (
        lifecycle["initial"] != "configured"
        or lifecycle["terminal"] != _TERMINAL_STATES
        or transitions != _TRANSITIONS
        or states != set(_TRANSITIONS)
    ):
        raise ValueError("Invalid lifecycle semantics.")

    retention = value["retention"]
    _exact(
        retention,
        {
            "particle_states_field",
            "retained_requires",
            "retained_forbids",
            "not_retained_requires",
            "not_retained_forbids",
        },
        "retention contract",
    )
    if retention["particle_states_field"] != "particle_states":
        raise ValueError("Invalid retention field.")
    for key in (
        "retained_requires",
        "retained_forbids",
        "not_retained_requires",
        "not_retained_forbids",
    ):
        _relative_path(retention[key], key)
    if (
        retention["retained_requires"] != layout["particle_states"]
        or retention["retained_forbids"] != layout["retention_receipt"]
        or retention["not_retained_requires"] != layout["retention_receipt"]
        or retention["not_retained_forbids"] != layout["particle_states"]
    ):
        raise ValueError("Retention rules do not match the canonical layout.")

    limits = value["limits"]
    _exact(
        limits,
        {
            "run_id_max_characters",
            "json_max_bytes",
            "artifact_count_maximum",
            "path_max_bytes",
        },
        "run limits",
    )
    if limits != _LIMITS:
        raise ValueError("Invalid run limits.")
    return value


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate specification key {key!r}.")
        value[key] = item
    return value


def _read_validated():
    try:
        before = SPECIFICATION_PATH.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SPECIFICATION_BYTES:
            raise ValueError
        descriptor = os.open(
            SPECIFICATION_PATH, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            ) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
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
            if len(raw) > MAX_SPECIFICATION_BYTES or len(raw) != opened.st_size or (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            ):
                raise ValueError
        finally:
            os.close(descriptor)
        current = SPECIFICATION_PATH.lstat()
        if not stat.S_ISREG(current.st_mode) or (
            current.st_dev,
            current.st_ino,
            current.st_size,
            current.st_mtime_ns,
        ) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ):
            raise ValueError
        return _validate(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError("The bundled individual-run specification is invalid.") from error


_VALUE = _read_validated()
INDIVIDUAL_RUN_SPECIFICATION = _freeze(_VALUE)
INDIVIDUAL_RUN_SPEC_VERSION = _VALUE["spec_version"]
INDIVIDUAL_RUN_SPEC_SHA256 = _digest(_VALUE)
