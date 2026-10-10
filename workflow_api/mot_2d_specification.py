"""Strict immutable view of the versioned 2D-MOT display specification."""

from __future__ import annotations

import json
import math
import os
import stat
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

SPECIFICATION_PATH = Path(__file__).with_name("specifications") / "mot_2d_v1.json"


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _validate(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "spec_version",
        "stage_order",
        "design",
        "stages",
    }:
        raise ValueError("Invalid 2D-MOT specification.")
    order = value["stage_order"]
    design = value["design"]
    stages = value["stages"]
    if (
        value["spec_version"] != "mot_2d-v1"
        or not isinstance(order, list)
        or len(order) != len(set(order))
        or not all(isinstance(x, str) for x in order)
    ):
        raise ValueError("Invalid 2D-MOT specification.")
    if (
        not isinstance(design, dict)
        or not isinstance(stages, dict)
        or set(stages) != set(order)
    ):
        raise ValueError("Invalid 2D-MOT specification.")
    if any(
        not isinstance(row, dict) or not isinstance(row.get("label"), str)
        for row in stages.values()
    ):
        raise ValueError("Invalid 2D-MOT specification.")
    design_keys = {
        "solver",
        "working_dt_s",
        "final_dt_s",
        "ensemble_count",
        "prepared_file_count",
        "workers_per_s0",
        "screen_trials_per_worker",
        "refine_trials_per_worker",
        "screen_candidates_per_s0",
        "confirmation_candidates_per_s0",
    }
    if (
        set(design) != design_keys
        or not isinstance(design["solver"], str)
        or not design["solver"]
    ):
        raise ValueError("Invalid 2D-MOT specification.")
    float_keys = {"working_dt_s", "final_dt_s"}
    integer_keys = design_keys - {"solver", *float_keys}
    if any(
        isinstance(design[key], bool)
        or not isinstance(design[key], int)
        or design[key] <= 0
        for key in integer_keys
    ):
        raise ValueError("Invalid 2D-MOT specification.")
    if any(
        isinstance(design[key], bool)
        or not isinstance(design[key], (int, float))
        or not math.isfinite(design[key])
        or design[key] <= 0
        for key in float_keys
    ):
        raise ValueError("Invalid 2D-MOT specification.")
    stage_keys = {
        "smoke": {
            "label",
            "job_file",
            "cores_per_task",
            "memory_per_task_bytes",
            "walltime_seconds",
            "array_throttle",
            "artifacts",
        },
        "screen": {
            "label",
            "job_file",
            "cores_per_task",
            "memory_per_task_bytes",
            "walltime_seconds",
            "array_throttle",
            "artifacts",
        },
        "refine": {
            "label",
            "round_job_files",
            "submit_chain",
            "cumulative_trial_targets",
            "dependency",
            "cores_per_task",
            "memory_per_task_bytes",
            "walltime_seconds",
            "array_throttle",
            "artifacts",
        },
        "confirmation": {
            "label",
            "job_file",
            "cores_per_task",
            "memory_per_task_bytes",
            "walltime_seconds",
            "array_throttle",
            "artifacts",
        },
        "sensitivity": {"label"},
        "production": {"label"},
    }
    if order != [
        "smoke",
        "screen",
        "refine",
        "confirmation",
        "sensitivity",
        "production",
    ]:
        raise ValueError("Invalid 2D-MOT specification.")
    for name, row in stages.items():
        if set(row) != stage_keys[name]:
            raise ValueError("Invalid 2D-MOT specification.")
        if not row["label"].strip() or len(row["label"]) > 64:
            raise ValueError("Invalid 2D-MOT specification.")
        for key in (
            "cores_per_task",
            "memory_per_task_bytes",
            "walltime_seconds",
            "array_throttle",
        ):
            if key in row and (
                not isinstance(row[key], int)
                or isinstance(row[key], bool)
                or row[key] <= 0
            ):
                raise ValueError("Invalid 2D-MOT specification.")
        for key in ("artifacts", "round_job_files", "cumulative_trial_targets"):
            if key in row and (not isinstance(row[key], list) or not row[key]):
                raise ValueError("Invalid 2D-MOT specification.")
        for key in ("artifacts", "round_job_files"):
            if key in row and (
                len(row[key]) != len(set(row[key]))
                or any(
                    not isinstance(item, str)
                    or not item
                    or item.startswith("/")
                    or ".." in Path(item).parts
                    for item in row[key]
                )
            ):
                raise ValueError("Invalid 2D-MOT specification.")
        for key in ("job_file", "submit_chain"):
            if key in row and (
                not isinstance(row[key], str)
                or not row[key].startswith("jobs/")
                or ".." in Path(row[key]).parts
            ):
                raise ValueError("Invalid 2D-MOT specification.")
    targets = stages["refine"]["cumulative_trial_targets"]
    if any(
        not isinstance(item, int) or isinstance(item, bool) or item <= 0
        for item in targets
    ) or targets != sorted(set(targets)):
        raise ValueError("Invalid 2D-MOT specification.")
    if stages["refine"]["dependency"] != "afterok":
        raise ValueError("Invalid 2D-MOT specification.")
    return value


def _read_validated() -> dict[str, Any]:
    try:
        metadata = SPECIFICATION_PATH.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 128 * 1024:
            raise ValueError
        descriptor = os.open(
            SPECIFICATION_PATH, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            raw = os.read(descriptor, 128 * 1024 + 1)
        finally:
            os.close(descriptor)
        if len(raw) > 128 * 1024:
            raise ValueError
        return _validate(json.loads(raw.decode("utf-8")))
    except (OSError, json.JSONDecodeError, UnicodeError, ValueError) as error:
        raise RuntimeError("The bundled 2D-MOT specification is invalid.") from error


@lru_cache(maxsize=1)
def load_mot_2d_specification() -> Mapping[str, Any]:
    return _freeze(_read_validated())


MOT_2D_SPECIFICATION = load_mot_2d_specification()


def render_typescript_specification() -> str:
    """Render the checked-in TypeScript artifact; callers choose where to write it."""
    value = _read_validated()
    body = json.dumps(value, indent=2, sort_keys=True)
    return (
        "// Generated from workflow_api/specifications/mot_2d_v1.json; do not edit.\nexport const MOT_2D_SPECIFICATION_V1 = "
        + body
        + " as const;\n"
    )
