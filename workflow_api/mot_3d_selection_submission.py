"""Shared closed contract for guarded 3D selection-stage submissions.

This module deliberately contains no filesystem, SSH, or scientific execution
code.  Preliminary Check and Refinement use the same four-job topology and
lifecycle matrix; keeping that matrix here prevents their safety rules from
drifting while stage-specific coordinators retain their own evidence checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Protocol

from workflow_api.mot_3d_stage_topology import FAMILIES, SelectionStageTopology

HEX32 = re.compile(r"^[0-9a-f]{32}$")
ARRAY_JOB = re.compile(r"^\d+\[\]\.zeus-master$")
SCALAR_JOB = re.compile(r"^\d+\.zeus-master$")


class SelectionSubmissionState(Protocol):
    lifecycle: str
    branch: str
    jobs: Mapping[str, Mapping[str, str | None]]
    nonce: str | None
    submitted_unix_s: int | None
    completed_array_tasks: int
    completed_merge_jobs: int


@dataclass(frozen=True)
class SelectionSubmissionContract:
    stage: str
    label: str
    topology: SelectionStageTopology
    already_started_code: str
    partial_code: str
    outcome_unknown_code: str


def exact_jobs(
    value: object, *, populated: bool, error: type[Exception], code: str
) -> dict[str, dict[str, str | None]]:
    if not isinstance(value, Mapping) or set(value) != set(FAMILIES):
        raise error(code)
    result: dict[str, dict[str, str | None]] = {}
    for family in FAMILIES:
        row = value[family]
        if not isinstance(row, Mapping) or set(row) != {"array", "merge"}:
            raise error(code)
        array, merge = row["array"], row["merge"]
        if populated:
            if (
                not isinstance(array, str)
                or not ARRAY_JOB.fullmatch(array)
                or not isinstance(merge, str)
                or not SCALAR_JOB.fullmatch(merge)
            ):
                raise error(code)
        elif array is not None or merge is not None:
            raise error(code)
        result[family] = {"array": array, "merge": merge}
    _require_unique_ids(result, error=error, code=code)
    return result


def _require_unique_ids(jobs, *, error: type[Exception], code: str) -> None:
    numeric = [
        job.split("[", 1)[0].split(".", 1)[0]
        for row in jobs.values()
        for job in row.values()
        if isinstance(job, str)
    ]
    if len(numeric) != len(set(numeric)):
        raise error(code)


def validate_selection_submission_state(
    state: SelectionSubmissionState,
    operation: str,
    *,
    error: type[Exception],
    code: str = "remote_response_invalid",
) -> None:
    allowed = {
        "inspect": {"eligible", "submitted", "partial", "outcome_unknown"},
        "submit": {"submitted", "partial", "outcome_unknown"},
        "status": {
            "eligible",
            "submitted",
            "queued",
            "running",
            "held",
            "completed_failed",
            "completed_success",
            "status_unknown",
            "partial",
            "outcome_unknown",
        },
    }.get(operation)
    if (
        allowed is None
        or state.lifecycle not in allowed
        or not isinstance(state.branch, str)
        or not state.branch
        or len(state.branch) > 256
        or not state.branch.isprintable()
    ):
        raise error(code)

    prefix = state.lifecycle in {"partial", "outcome_unknown"}
    if prefix:
        jobs = _validate_prefix(state.jobs, state.lifecycle, error=error, code=code)
    else:
        jobs = exact_jobs(
            state.jobs,
            populated=state.lifecycle != "eligible",
            error=error,
            code=code,
        )
    _require_unique_ids(jobs, error=error, code=code)

    counts = (state.completed_array_tasks, state.completed_merge_jobs)
    if any(type(value) is not int for value in counts) or not (
        0 <= counts[0] <= 6 and 0 <= counts[1] <= 2
    ):
        raise error(code)
    has_identity = state.lifecycle != "eligible"
    if has_identity and (
        not isinstance(state.nonce, str) or not HEX32.fullmatch(state.nonce)
    ):
        raise error(code)
    if prefix:
        if state.submitted_unix_s is not None or counts != (0, 0):
            raise error(code)
    elif has_identity:
        if (
            type(state.submitted_unix_s) is not int
            or not 0 <= state.submitted_unix_s <= 253402300799
        ):
            raise error(code)
    elif (
        state.nonce is not None
        or state.submitted_unix_s is not None
        or counts != (0, 0)
    ):
        raise error(code)
    if state.lifecycle == "completed_success" and counts != (6, 2):
        raise error(code)
    if state.lifecycle in {"eligible", "submitted"} and counts != (0, 0):
        raise error(code)
    if state.lifecycle == "running" and counts == (6, 2):
        raise error(code)


def _validate_prefix(value, lifecycle, *, error: type[Exception], code: str):
    if not isinstance(value, Mapping) or set(value) != set(FAMILIES):
        raise error(code)
    result = {}
    present = []
    for family in FAMILIES:
        row = value[family]
        if not isinstance(row, Mapping) or set(row) != {"array", "merge"}:
            raise error(code)
        array, merge = row["array"], row["merge"]
        if array is not None and (
            not isinstance(array, str) or not ARRAY_JOB.fullmatch(array)
        ):
            raise error(code)
        if merge is not None and (
            array is None
            or not isinstance(merge, str)
            or not SCALAR_JOB.fullmatch(merge)
        ):
            raise error(code)
        result[family] = {"array": array, "merge": merge}
        present.extend((array is not None, merge is not None))
    count = sum(present)
    minimum = 1 if lifecycle == "partial" else 0
    if not minimum <= count <= 3 or present != [index < count for index in range(4)]:
        raise error(code)
    return result


def public_lifecycle(lifecycle: str) -> str:
    return {
        "eligible": "not_submitted",
        "completed_success": "completed_success_unvalidated",
    }.get(lifecycle, lifecycle)


def next_action(lifecycle: str) -> str:
    public = public_lifecycle(lifecycle)
    if public == "not_submitted":
        return "review_submission"
    if public in {"submitted", "queued", "running"}:
        return "wait"
    if public == "completed_success_unvalidated":
        return "await_result_synchronization"
    return "inspect_zeus"
