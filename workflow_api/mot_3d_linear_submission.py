"""Closed public state contract for an ordered three-job submission chain."""

from __future__ import annotations

import re
from typing import Mapping

HEX32 = re.compile(r"^[0-9a-f]{32}$")
ARRAY = re.compile(r"^\d+\[\]\.zeus-master$")
SCALAR = re.compile(r"^\d+\.zeus-master$")
STEPS = ("zeeman", "mot_2d", "freeze")


def validate_linear_submission_state(
    state, operation, *, error, code="remote_response_invalid"
):
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
            "completed_success_unvalidated",
            "status_unknown",
            "partial",
            "outcome_unknown",
        },
    }.get(operation)
    if allowed is None or state.lifecycle not in allowed:
        raise error(code)
    if not isinstance(state.jobs, Mapping) or set(state.jobs) != set(STEPS):
        raise error(code)
    jobs = [state.jobs[name] for name in STEPS]
    prefix = 0
    for index, job in enumerate(jobs):
        if job is None:
            if any(value is not None for value in jobs[index + 1 :]):
                raise error(code)
            break
        pattern = ARRAY if index < 2 else SCALAR
        if type(job) is not str or pattern.fullmatch(job) is None:
            raise error(code)
        prefix += 1
    numeric = [job.split("[", 1)[0].split(".", 1)[0] for job in jobs if job]
    if len(numeric) != len(set(numeric)):
        raise error(code)
    if state.lifecycle == "eligible" and prefix != 0:
        raise error(code)
    if state.lifecycle == "partial" and prefix not in {1, 2}:
        raise error(code)
    if state.lifecycle == "outcome_unknown" and prefix not in {0, 1, 2}:
        raise error(code)
    if (
        state.lifecycle not in {"eligible", "partial", "outcome_unknown"}
        and prefix != 3
    ):
        raise error(code)
    if state.lifecycle == "eligible":
        if state.nonce is not None or state.submitted_unix_s is not None:
            raise error(code)
    elif type(state.nonce) is not str or HEX32.fullmatch(state.nonce) is None:
        raise error(code)
    if state.lifecycle in {"partial", "outcome_unknown"}:
        if state.submitted_unix_s is not None:
            raise error(code)
    elif state.lifecycle != "eligible" and (
        type(state.submitted_unix_s) is not int
        or not 0 <= state.submitted_unix_s <= 253402300799
    ):
        raise error(code)
    counts = (state.completed_array_tasks, state.completed_scalar_jobs)
    if any(type(value) is not int for value in counts) or not (
        0 <= counts[0] <= 40 and 0 <= counts[1] <= 1
    ):
        raise error(code)
    if state.lifecycle == "completed_success_unvalidated" and counts != (40, 1):
        raise error(code)
    if state.lifecycle in {
        "eligible",
        "submitted",
        "partial",
        "outcome_unknown",
    } and counts != (0, 0):
        raise error(code)
