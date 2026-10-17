"""Neutral mechanics for an at-most-once three-step PBS chain.

Stage wrappers supply a fully attested immutable plan.  This module deliberately
knows nothing about campaign science or finalist-selection artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping
try:
    import fcntl
except ImportError:  # Only imported on Windows; remote execution remains POSIX.
    from workflow_api.platform_io import locking as fcntl, os, re

from workflow_api.mot_3d_selection_submission_remote import (
    ARRAY,
    SCALAR,
    digest,
    publish_at,
    replace_at,
    strict_json_at,
    unlink_at,
    qstat_fields,
    one_state,
    regular_exists_at,
)

HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
STEPS = ("zeeman", "mot_2d", "freeze")
MAX_STAMP = 253402300799


def _stamp(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_STAMP


@dataclass(frozen=True)
class LinearStep:
    name: str
    job_file: str
    kind: str
    task_count: int
    depends_on: str | None

    def __post_init__(self):
        if (
            self.name not in STEPS
            or self.kind not in {"array", "scalar"}
            or type(self.task_count) is not int
            or self.task_count != (20 if self.kind == "array" else 1)
            or (self.depends_on is not None and self.depends_on not in STEPS)
            or not self.job_file.startswith("jobs/")
            or ".." in self.job_file.split("/")
        ):
            raise ValueError("invalid linear step")


@dataclass(frozen=True)
class LinearDescriptor:
    stage: str
    receipt_kind: str
    error_prefix: str
    steps: tuple[LinearStep, ...]

    def __post_init__(self):
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.stage)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.error_prefix)
            or type(self.steps) is not tuple
            or tuple(step.name for step in self.steps) != STEPS
            or tuple(step.depends_on for step in self.steps)
            != (None, "zeeman", "mot_2d")
            or tuple(step.kind for step in self.steps) != ("array", "array", "scalar")
        ):
            raise ValueError("invalid linear descriptor")


@dataclass(frozen=True)
class FrozenLinearPlan:
    campaign: str
    commit: str
    submission_key: str
    nonce: str
    pbs: Mapping[str, bytes]

    def __post_init__(self):
        if (
            type(self.campaign) is not str
            or type(self.commit) is not str
            or HEX40.fullmatch(self.commit) is None
            or type(self.submission_key) is not str
            or HEX64.fullmatch(self.submission_key) is None
            or type(self.nonce) is not str
            or HEX32.fullmatch(self.nonce) is None
            or not isinstance(self.pbs, Mapping)
            or set(self.pbs) != set(STEPS)
            or any(type(raw) is not bytes or not raw for raw in self.pbs.values())
        ):
            raise ValueError("invalid frozen linear plan")
        object.__setattr__(self, "pbs", MappingProxyType(dict(self.pbs)))


@dataclass(frozen=True)
class LinearState:
    lifecycle: str
    branch: str
    jobs: Mapping[str, str | None]
    nonce: str | None
    submitted_unix_s: int | None
    completed_array_tasks: int = 0
    completed_scalar_jobs: int = 0


def canonical_prefix(jobs: object) -> tuple[str, ...]:
    """Return and strictly validate the durable canonical job-id prefix."""
    if not isinstance(jobs, Mapping) or set(jobs) != set(STEPS):
        raise ValueError("invalid job chain")
    prefix: list[str] = []
    absent = False
    numbers: set[str] = set()
    for index, name in enumerate(STEPS):
        value = jobs[name]
        if value is None:
            absent = True
            continue
        pattern = ARRAY if index < 2 else SCALAR
        if absent or type(value) is not str or pattern.fullmatch(value) is None:
            raise ValueError("invalid job chain")
        number = value.split("[", 1)[0].split(".", 1)[0]
        if number in numbers:
            raise ValueError("duplicate job id")
        numbers.add(number)
        prefix.append(value)
    return tuple(prefix)


def qsub_argv(step: LinearStep, jobs: Mapping[str, str | None]) -> list[str]:
    if step.kind == "array":
        argv = ["/usr/local/bin/qsub"]
        if step.depends_on is not None:
            dependency = jobs[step.depends_on]
            if type(dependency) is not str or ARRAY.fullmatch(dependency) is None:
                raise ValueError("missing dependency")
            argv += ["-W", f"depend=afterok:{dependency}"]
        return argv + ["-J", "0-19:1"]
    dependency = jobs[step.depends_on or ""]
    if type(dependency) is not str or ARRAY.fullmatch(dependency) is None:
        raise ValueError("missing dependency")
    return ["/usr/local/bin/qsub", "-W", f"depend=afterok:{dependency}"]


def submission_key(campaign: str, commit: str, identity: Mapping[str, object]) -> str:
    return digest({"campaign": campaign, "commit": commit, **identity})


def compatibility(
    descriptor: LinearDescriptor,
    jobs: Mapping[str, str | None],
    status: str,
    plan: FrozenLinearPlan,
    created_unix_s: int,
) -> dict[str, object]:
    canonical_prefix(jobs)
    if status not in {"submitting", "partial_failure", "submitted"}:
        raise ValueError("invalid compatibility status")
    if status == "submitted" and len(canonical_prefix(jobs)) != 3:
        raise ValueError("incomplete submitted chain")
    return {
        "kind": descriptor.receipt_kind,
        "status": status,
        "submission_key": plan.submission_key,
        "nonce": plan.nonce,
        "commit": plan.commit,
        "created_unix_s": created_unix_s,
        "zeeman_array_job_id": jobs["zeeman"],
        "mot_array_job_id": jobs["mot_2d"],
        "freeze_job_id": jobs["freeze"],
    }


def execute_chain(
    descriptor: LinearDescriptor,
    plan: FrozenLinearPlan,
    *,
    submissions_fd: int,
    campaign_fd: int,
    run: Callable[..., tuple[int, bytes, bytes]],
    reattest: Callable[[], None],
    now: Callable[[], int],
) -> tuple[str, Mapping[str, str | None], int | None]:
    """Submit a frozen chain, durably recording every ambiguity boundary.

    Callers must hold the campaign submission lock for the whole call. Existing
    receipts are intentionally handled by the wrapper's reconciliation pass;
    this function only starts a previously absent chain.
    """
    jobs: dict[str, str | None] = {name: None for name in STEPS}
    created = now()
    global_pending = f"{descriptor.stage}.pending.json"
    global_final = f"{descriptor.stage}.json"
    publish_at(
        submissions_fd,
        global_pending,
        {
            "version": 1,
            "status": "pending",
            "submission_key": plan.submission_key,
            "nonce": plan.nonce,
            "commit": plan.commit,
            "created_unix_s": created,
        },
    )
    compat_name = f"{descriptor.stage}_submission.json"
    publish_at(
        campaign_fd,
        compat_name,
        compatibility(descriptor, jobs, "submitting", plan, created),
    )
    for step in descriptor.steps:
        pending_name = f"{descriptor.stage}_{step.name}.pending.json"
        done_name = f"{descriptor.stage}_{step.name}.json"
        pending = {
            "status": "pending",
            "submission_key": plan.submission_key,
            "nonce": plan.nonce,
            "commit": plan.commit,
            "step": step.name,
            "pbs_sha256": __import__("hashlib").sha256(plan.pbs[step.name]).hexdigest(),
            "depends_on": jobs.get(step.depends_on) if step.depends_on else None,
            "created_unix_s": now(),
        }
        publish_at(submissions_fd, pending_name, pending)
        reattest()
        try:
            code, stdout, stderr = run(
                qsub_argv(step, jobs), input_data=plan.pbs[step.name]
            )
            job_id = stdout.decode("ascii", "strict").strip()
        except Exception:
            return "outcome_unknown", MappingProxyType(jobs), None
        pattern = ARRAY if step.kind == "array" else SCALAR
        if code or stderr or pattern.fullmatch(job_id) is None:
            return "outcome_unknown", MappingProxyType(jobs), None
        prior = dict(jobs)
        jobs[step.name] = job_id
        canonical_prefix(jobs)
        publish_at(
            submissions_fd,
            done_name,
            {
                **pending,
                "status": "submitted",
                "job_id": job_id,
                "completed_unix_s": now(),
            },
        )
        unlink_at(submissions_fd, pending_name)
        old = compatibility(descriptor, prior, "submitting", plan, created)
        replace_at(
            campaign_fd,
            compat_name,
            compatibility(descriptor, jobs, "submitting", plan, created),
            old,
        )
    reattest()
    submitted = now()
    publish_at(
        submissions_fd,
        global_final,
        {
            "version": 1,
            "status": "submitted",
            "submission_key": plan.submission_key,
            "nonce": plan.nonce,
            "commit": plan.commit,
            "jobs": jobs,
            "created_unix_s": created,
            "submitted_unix_s": submitted,
        },
    )
    replace_at(
        campaign_fd,
        compat_name,
        compatibility(descriptor, jobs, "submitted", plan, created),
        compatibility(descriptor, jobs, "submitting", plan, created),
    )
    unlink_at(submissions_fd, global_pending)
    return "submitted", MappingProxyType(jobs), submitted


def scheduler_state(
    jobs: Mapping[str, str | None],
    *,
    run: Callable[..., tuple[int, bytes, bytes]],
) -> tuple[str, int, int]:
    """Return conservative lifecycle and exact completed 20+20/scalar counts."""
    if len(canonical_prefix(jobs)) != 3:
        raise ValueError("scheduler requires complete chain")
    states: list[str] = []
    completed_arrays = completed_scalars = 0
    for index, name in enumerate(STEPS):
        job = jobs[name]
        assert isinstance(job, str)
        try:
            code, raw, err = run(
                ["/usr/local/bin/qstat", "-x", "-t", "-f", job],
                limit=4 * 1024 * 1024,
            )
        except Exception:
            states.append("status_unknown")
            continue
        fields = qstat_fields(raw)
        if code or err or fields is None:
            states.append("status_unknown")
            continue
        if index == 2:
            if set(fields) != {job}:
                states.append("status_unknown")
                continue
            state = one_state(fields[job])
            completed_scalars += int(state == "completed_success")
            states.append(state)
            continue
        prefix = job.split("[]", 1)[0]
        expected = {f"{prefix}[{task}].zeus-master" for task in range(20)}
        if not expected.issubset(fields) or set(fields) - expected not in (
            set(),
            {job},
        ):
            states.append("status_unknown")
            continue
        child_states = [one_state(fields[key]) for key in expected]
        completed_arrays += child_states.count("completed_success")
        parent = one_state(fields[job]) if job in fields else None
        if parent in {"completed_failed", "held", "status_unknown"}:
            states.append(parent)
        elif parent in {"queued", "running"} and all(
            value == "completed_success" for value in child_states
        ):
            states.append("status_unknown")
        else:
            states.append(
                next(
                    (
                        value
                        for value in (
                            "completed_failed",
                            "held",
                            "status_unknown",
                            "running",
                            "queued",
                        )
                        if value in child_states
                    ),
                    "completed_success",
                )
            )
    lifecycle = next(
        (
            value
            for value in (
                "completed_failed",
                "held",
                "status_unknown",
                "running",
                "queued",
            )
            if value in states
        ),
        "completed_success_unvalidated",
    )
    return lifecycle, completed_arrays, completed_scalars


def recover_prefix(
    descriptor: LinearDescriptor,
    plan: FrozenLinearPlan,
    *,
    submissions_fd: int,
) -> tuple[dict[str, str | None], int]:
    """Strictly recover the durable canonical prefix from completed receipts."""
    jobs: dict[str, str | None] = {name: None for name in STEPS}
    created: int | None = None
    absent = False
    for index, step in enumerate(descriptor.steps):
        name = f"{descriptor.stage}_{step.name}.json"
        if not regular_exists_at(submissions_fd, name):
            absent = True
            continue
        row = strict_json_at(
            submissions_fd,
            name,
            keys={
                "status",
                "submission_key",
                "nonce",
                "commit",
                "step",
                "pbs_sha256",
                "depends_on",
                "created_unix_s",
                "job_id",
                "completed_unix_s",
            },
        )
        if absent:
            raise ValueError("noncanonical receipt prefix")
        matcher = ARRAY if index < 2 else SCALAR
        if (
            row["status"] != "submitted"
            or row["submission_key"] != plan.submission_key
            or row["nonce"] != plan.nonce
            or row["commit"] != plan.commit
            or row["step"] != step.name
            or row["pbs_sha256"]
            != __import__("hashlib").sha256(plan.pbs[step.name]).hexdigest()
            or row["depends_on"] != (jobs[step.depends_on] if step.depends_on else None)
            or not _stamp(row["created_unix_s"])
            or not _stamp(row["completed_unix_s"])
            or row["completed_unix_s"] < row["created_unix_s"]
            or type(row["job_id"]) is not str
            or matcher.fullmatch(row["job_id"]) is None
        ):
            raise ValueError("invalid completed receipt")
        created = (
            row["created_unix_s"]
            if created is None
            else min(created, row["created_unix_s"])
        )
        jobs[step.name] = row["job_id"]
    canonical_prefix(jobs)
    return jobs, created if created is not None else 0


def reconcile_chain(
    descriptor: LinearDescriptor,
    plan: FrozenLinearPlan,
    *,
    submissions_fd: int,
    campaign_fd: int,
    mutate: bool = True,
) -> tuple[str, Mapping[str, str | None], int | None]:
    """Reconcile only durable, exact receipt states without issuing qsub."""
    allowed = {
        f"{descriptor.stage}.pending.json",
        f"{descriptor.stage}.json",
        *(f"{descriptor.stage}_{step.name}.pending.json" for step in descriptor.steps),
        *(f"{descriptor.stage}_{step.name}.json" for step in descriptor.steps),
        f"{descriptor.stage}.lock",
    }
    names = set(os.listdir(submissions_fd))
    owned = {
        name
        for name in names
        if name == f"{descriptor.stage}.lock"
        or name.startswith(f"{descriptor.stage}.")
        or name.startswith(f"{descriptor.stage}_")
    }
    if owned - allowed:
        raise ValueError("unexpected submission receipt")
    pending_name = f"{descriptor.stage}.pending.json"
    final_name = f"{descriptor.stage}.json"
    has_pending = regular_exists_at(submissions_fd, pending_name)
    has_final = regular_exists_at(submissions_fd, final_name)
    if not has_pending and not has_final:
        if owned & (allowed - {f"{descriptor.stage}.lock"}):
            raise ValueError("receipts without global intent")
        return "eligible", MappingProxyType({name: None for name in STEPS}), None
    source = final_name if has_final and not has_pending else pending_name
    source_keys = (
        {
            "version",
            "status",
            "submission_key",
            "nonce",
            "commit",
            "jobs",
            "created_unix_s",
            "submitted_unix_s",
        }
        if source == final_name
        else {
            "version",
            "status",
            "submission_key",
            "nonce",
            "commit",
            "created_unix_s",
        }
    )
    pending = strict_json_at(submissions_fd, source, keys=source_keys)
    if (
        pending
        != {
            "version": 1,
            "status": "submitted" if source == final_name else "pending",
            "submission_key": plan.submission_key,
            "nonce": plan.nonce,
            "commit": plan.commit,
            "created_unix_s": pending.get("created_unix_s"),
            **(
                {
                    "jobs": pending.get("jobs"),
                    "submitted_unix_s": pending.get("submitted_unix_s"),
                }
                if source == final_name
                else {}
            ),
        }
        or not _stamp(pending["created_unix_s"])
        or (
            source == final_name
            and (
                not _stamp(pending["submitted_unix_s"])
                or pending["submitted_unix_s"] < pending["created_unix_s"]
            )
        )
    ):
        raise ValueError("invalid global intent")
    created = pending["created_unix_s"]
    jobs, _ = recover_prefix(descriptor, plan, submissions_fd=submissions_fd)
    prefix = len(canonical_prefix(jobs))
    for index, step in enumerate(descriptor.steps):
        step_pending = f"{descriptor.stage}_{step.name}.pending.json"
        if not regular_exists_at(submissions_fd, step_pending):
            continue
        row = strict_json_at(
            submissions_fd,
            step_pending,
            keys={
                "status",
                "submission_key",
                "nonce",
                "commit",
                "step",
                "pbs_sha256",
                "depends_on",
                "created_unix_s",
            },
        )
        expected_dependency = jobs[step.depends_on] if step.depends_on else None
        expected = {
            "status": "pending",
            "submission_key": plan.submission_key,
            "nonce": plan.nonce,
            "commit": plan.commit,
            "step": step.name,
            "pbs_sha256": __import__("hashlib").sha256(plan.pbs[step.name]).hexdigest(),
            "depends_on": expected_dependency,
            "created_unix_s": row.get("created_unix_s"),
        }
        if row != expected or not _stamp(row["created_unix_s"]):
            raise ValueError("invalid step intent")
        if index < prefix:
            if mutate:
                unlink_at(submissions_fd, step_pending)
        elif index == prefix:
            return "outcome_unknown", MappingProxyType(jobs), None
        else:
            raise ValueError("noncanonical pending step")
    compat_name = f"{descriptor.stage}_submission.json"
    compat = strict_json_at(campaign_fd, compat_name)
    expected_current = compatibility(
        descriptor,
        jobs,
        "submitted" if has_final and prefix == 3 else "submitting",
        plan,
        created,
    )
    if compat != expected_current:
        full_submitting = compatibility(descriptor, jobs, "submitting", plan, created)
        if has_final and prefix == 3 and compat == full_submitting:
            if mutate:
                replace_at(campaign_fd, compat_name, expected_current, compat)
            else:
                return "outcome_unknown", MappingProxyType(jobs), None
            compat = expected_current
        else:
            if prefix == 0:
                raise ValueError("invalid compatibility receipt")
            previous = dict(jobs)
            previous[STEPS[prefix - 1]] = None
            if compat != compatibility(
                descriptor, previous, "submitting", plan, created
            ):
                raise ValueError("invalid compatibility receipt")
            if mutate:
                replace_at(campaign_fd, compat_name, expected_current, compat)
            else:
                return "partial", MappingProxyType(jobs), None
    if prefix < 3:
        return "partial", MappingProxyType(jobs), None
    final = {
        "version": 1,
        "status": "submitted",
        "submission_key": plan.submission_key,
        "nonce": plan.nonce,
        "commit": plan.commit,
        "jobs": jobs,
        "created_unix_s": created,
    }
    if has_final:
        observed = strict_json_at(submissions_fd, final_name)
        submitted = observed.get("submitted_unix_s")
        if (
            observed != {**final, "submitted_unix_s": submitted}
            or not _stamp(submitted)
            or submitted < created
        ):
            raise ValueError("invalid final receipt")
    else:
        return "outcome_unknown", MappingProxyType(jobs), None
    submitted = observed["submitted_unix_s"]
    current = strict_json_at(campaign_fd, compat_name)
    target = compatibility(descriptor, jobs, "submitted", plan, created)
    if current != target:
        if current != expected_current:
            raise ValueError("invalid final compatibility receipt")
        if mutate:
            replace_at(campaign_fd, compat_name, target, current)
        else:
            return "outcome_unknown", MappingProxyType(jobs), None
    if has_pending and mutate:
        unlink_at(submissions_fd, pending_name)
    return "submitted", MappingProxyType(jobs), submitted


def with_submission_lock(lock_fd: int, operation: Callable[[], object]) -> object:
    """Run one reconciliation/submission transaction under a nonblocking lock."""
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise RuntimeError("submission_busy") from exc
    try:
        return operation()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)


def reconcile_operation(
    operation: str,
    descriptor: LinearDescriptor,
    plan: FrozenLinearPlan,
    *,
    branch: str,
    lock_fd: int,
    submissions_fd: int,
    campaign_fd: int,
    run: Callable[..., tuple[int, bytes, bytes]],
    reattest: Callable[[], None],
    now: Callable[[], int],
) -> LinearState:
    """Own the locked inspect/status/submit state machine for a frozen plan."""
    if operation not in {"inspect", "status", "submit"}:
        raise ValueError("invalid operation")

    def transaction():
        lifecycle, jobs, submitted = reconcile_chain(
            descriptor,
            plan,
            submissions_fd=submissions_fd,
            campaign_fd=campaign_fd,
            mutate=operation == "submit",
        )
        if lifecycle == "eligible" and operation == "submit":
            lifecycle, jobs, submitted = execute_chain(
                descriptor,
                plan,
                submissions_fd=submissions_fd,
                campaign_fd=campaign_fd,
                run=run,
                reattest=reattest,
                now=now,
            )
        arrays = scalars = 0
        if lifecycle == "submitted" and operation == "status":
            lifecycle, arrays, scalars = scheduler_state(jobs, run=run)
        return LinearState(
            lifecycle,
            branch,
            jobs,
            None if lifecycle == "eligible" else plan.nonce,
            submitted,
            arrays,
            scalars,
        )

    return with_submission_lock(lock_fd, transaction)
