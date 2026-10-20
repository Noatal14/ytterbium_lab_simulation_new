"""Validated, explicit Sensitivity-to-Production preparation on Zeus."""

from __future__ import annotations
from workflow_api.mot_2d_spec import reviewed_job_resources, refinement_targets, trial_budget

import hashlib
import json
import re
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from workflow_api.mot_2d_plan import render_production_transition
from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshProcessError,
    PinnedSshRunner,
    ReceiverOperation,
)
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.zeus_sensitivity_submission import (
    ZeusSensitivitySubmissionCoordinator,
    ZeusSensitivitySubmissionError,
)
from workflow_api.zeus_sensitivity import (
    ZeusSensitivityCoordinator,
    ZeusSensitivityError,
)
from workflow_api.zeus_snapshot import ZeusProfile

TOKEN_LIFETIME_SECONDS = 300
MAX_PENDING_PREVIEWS = 32
JOB_FILE = "jobs/06_production.pbs"
OUTPUT_FILES = frozenset(
    {
        "sensitivity_summary.json",
        "production/tasks.json",
        JOB_FILE,
        "campaign.json",
    }
)


class ZeusProductionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RemoteSensitivityState:
    lifecycle: str
    scheduler: Mapping[str, Any]
    rows: tuple[Mapping[str, Any], ...]
    branch: str
    receipt: Mapping[str, Any] | None = None


class ProductionTransport(Protocol):
    def inspect(self, **payload: object) -> RemoteSensitivityState: ...
    def prepare(self, **payload: object) -> RemoteSensitivityState: ...


@dataclass(frozen=True)
class _Pending:
    session_id: str
    campaign_id: str
    profile: ZeusProfile
    commit: str
    relative: str
    submission_key: str
    submission_nonce: str
    job_id: str
    rows_digest: str
    files: Mapping[str, str]
    transition_key: str
    nonce: str
    expires: float
    result: Mapping[str, object] | None = None


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


class ZeusProductionCoordinator:
    def __init__(
        self,
        repository_root: Path,
        ssh_executable: Path,
        git_executable: Path,
        *,
        clock=time.time,
        token_factory=None,
        transport_factory=None,
    ):
        self.root = repository_root.resolve(strict=True)
        self.ssh = ssh_executable.resolve(strict=True)
        self.git = git_executable.resolve(strict=True)
        self.clock = clock
        self.transport_factory = transport_factory or (
            lambda profile: PinnedSshProductionTransport(self.root, self.ssh, profile)
        )
        self._previews = PreviewRegistry[_Pending](
            clock=clock, token_factory=token_factory
        )
        self._confirm = threading.Lock()

    def _base_plan(self, request: Mapping[str, object]):
        try:
            coordinator = ZeusSensitivitySubmissionCoordinator(
                self.root, self.ssh, self.git
            )
            plan = coordinator._plan(request)
            (
                campaign_id,
                profile,
                campaign,
                manifest,
                commit,
                files,
                transition_nonce,
                transition_digest,
                submission_key,
            ) = plan
            transport, payload = coordinator._remote(
                profile,
                campaign.relative_to(self.root).as_posix(),
                commit,
                files,
                transition_nonce,
                transition_digest,
                submission_key,
                None,
            )
            state = transport.status(**payload)
        except ZeusSensitivitySubmissionError as error:
            raise ZeusProductionError(error.code) from error
        if state.status != "completed_success" or not state.job_id or not state.nonce:
            raise ZeusProductionError("sensitivity_not_complete")
        return (*plan, state.nonce, state.job_id)

    def _confirmation_rows(self, request: Mapping[str, object], base: tuple[Any, ...]):
        try:
            _, state = ZeusSensitivityCoordinator(
                self.root, self.ssh, self.git
            )._inspect(request)
        except ZeusSensitivityError as error:
            raise ZeusProductionError(error.code) from error
        if (
            state.lifecycle != "sensitivity_prepared"
            or not isinstance(state.receipt, dict)
            or state.receipt.get("nonce") != base[6]
        ):
            raise ZeusProductionError("sensitivity_preparation_invalid")
        return [dict(row) for row in state.receipt["rows"]]

    @staticmethod
    def _remote_payload(plan: tuple[Any, ...]) -> dict[str, object]:
        (
            _,
            _,
            campaign,
            _,
            commit,
            files,
            transition_nonce,
            transition_digest,
            submission_key,
            submission_nonce,
            job_id,
        ) = plan[:11]
        return {
            "campaign": campaign.relative_to(campaign.parents[3]).as_posix(),
            "commit": commit,
            "sensitivity_files": files,
            "sensitivity_transition_nonce": transition_nonce,
            "sensitivity_transition_digest": transition_digest,
            "sensitivity_submission_key": submission_key,
            "sensitivity_submission_nonce": submission_nonce,
            "sensitivity_job_id": job_id,
        }

    def _inspect(self, request: Mapping[str, object]):
        base = self._base_plan(request)
        state = self.transport_factory(base[1]).inspect(**self._remote_payload(base))
        self._validate_state(state, base[3])
        rows = [dict(row) for row in state.rows]
        files = {}
        rows_digest = ""
        transition_key = ""
        if state.lifecycle in {"ready_to_prepare_production", "production_prepared"}:
            confirmation = self._confirmation_rows(request, base)
            rendered = render_production_transition(
                base[3], base[2], self.root, confirmation, rows
            )
            files = {
                name: hashlib.sha256(data).hexdigest()
                for name, data in rendered.items()
            }
            rows_digest = _digest(rows)
            transition_key = _digest(
                {
                    "campaign": base[2].relative_to(self.root).as_posix(),
                    "commit": base[4],
                    "sensitivity_submission_key": base[8],
                    "sensitivity_submission_nonce": base[9],
                    "sensitivity_job_id": base[10],
                    "rows_digest": rows_digest,
                    "files": files,
                }
            )
        plan = (*base[:9], files, rows_digest, transition_key)
        if state.lifecycle == "production_prepared":
            self._validate_receipt(state, plan, base)
        return plan, state

    @staticmethod
    def _validate_state(
        state: RemoteSensitivityState, manifest: Mapping[str, Any]
    ) -> None:
        allowed = {
            "queued",
            "running",
            "held",
            "failed",
            "status_unknown",
            "awaiting_outputs",
            "outputs_invalid",
            "ready_to_prepare_production",
            "production_prepared",
        }
        scheduler = state.scheduler
        expected = len(manifest["s0_values"]) * 17
        if (
            state.lifecycle not in allowed
            or not state.branch
            or len(state.branch) > 256
            or not state.branch.isprintable()
            or not isinstance(scheduler, dict)
            or set(scheduler)
            != {"state", "task_count", "counts", "job_id", "submission_nonce"}
        ):
            raise ZeusProductionError("remote_response_invalid")
        if (
            scheduler.get("task_count") != expected
            or not re.fullmatch(
                r"\d+\[\]\.zeus-master", str(scheduler.get("job_id", ""))
            )
            or not re.fullmatch(
                r"[0-9a-f]{32}", str(scheduler.get("submission_nonce", ""))
            )
        ):
            raise ZeusProductionError("remote_response_invalid")
        counts = scheduler.get("counts")
        if (
            not isinstance(counts, dict)
            or set(counts) != {"queued", "running", "held", "succeeded", "failed"}
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in counts.values()
            )
        ):
            raise ZeusProductionError("remote_response_invalid")
        scheduler_state = scheduler.get("state")
        if scheduler_state not in {
            "queued",
            "running",
            "held",
            "completed_success",
            "completed_failed",
            "unknown",
        }:
            raise ZeusProductionError("remote_response_invalid")
        if sum(counts.values()) != (0 if scheduler_state == "unknown" else expected):
            raise ZeusProductionError("remote_response_invalid")
        ready = state.lifecycle in {
            "ready_to_prepare_production",
            "production_prepared",
        }
        if (ready and len(state.rows) != expected) or (not ready and state.rows):
            raise ZeusProductionError("remote_response_invalid")
        coherent = (
            ready
            and scheduler_state == "completed_success"
            and counts["succeeded"] == expected
            or state.lifecycle == "queued"
            and scheduler_state == "queued"
            and counts["queued"] > 0
            or state.lifecycle == "running"
            and scheduler_state == "running"
            and counts["running"] > 0
            or state.lifecycle == "held"
            and scheduler_state == "held"
            and counts["held"] > 0
            or state.lifecycle == "failed"
            and scheduler_state == "completed_failed"
            and counts["failed"] > 0
            or state.lifecycle == "status_unknown"
            and scheduler_state == "unknown"
            or state.lifecycle in {"awaiting_outputs", "outputs_invalid"}
            and scheduler_state == "completed_success"
            and counts["succeeded"] == expected
        )
        if not coherent:
            raise ZeusProductionError("remote_response_invalid")

    @staticmethod
    def _validate_receipt(
        state: RemoteSensitivityState, plan: tuple[Any, ...], base: tuple[Any, ...]
    ) -> None:
        receipt = state.receipt
        exact = {
            "status",
            "nonce",
            "transition_key",
            "commit",
            "sensitivity_submission_key",
            "sensitivity_submission_nonce",
            "sensitivity_job_id",
            "rows_digest",
            "rows",
            "files",
            "scheduler",
            "completed_unix_s",
        }
        if (
            not isinstance(receipt, dict)
            or set(receipt) != exact
            or receipt.get("status") != "production_prepared"
            or receipt.get("transition_key") != plan[11]
            or receipt.get("commit") != plan[4]
            or receipt.get("sensitivity_submission_key") != base[8]
            or receipt.get("sensitivity_submission_nonce") != base[9]
            or receipt.get("sensitivity_job_id") != base[10]
            or receipt.get("rows_digest") != plan[10]
            or receipt.get("rows") != [dict(row) for row in state.rows]
            or receipt.get("files") != plan[9]
            or receipt.get("scheduler") != dict(state.scheduler)
            or not re.fullmatch(r"[0-9a-f]{32}", str(receipt.get("nonce", "")))
            or not isinstance(receipt.get("completed_unix_s"), int)
            or isinstance(receipt.get("completed_unix_s"), bool)
            or not 0 <= receipt["completed_unix_s"] <= 253402300799
        ):
            raise ZeusProductionError("transition_outcome_unknown")

    def status(self, request):
        plan, state = self._inspect(request)
        expected = len(plan[3]["s0_values"]) * 17
        valid = state.lifecycle in {
            "ready_to_prepare_production",
            "production_prepared",
        }
        return {
            "source": "zeus",
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "campaign": {
                "id": plan[0],
                "name": plan[3]["name"],
                "stage": (
                    "production"
                    if state.lifecycle == "production_prepared"
                    else "sensitivity"
                ),
            },
            "sensitivity": {
                "status": state.lifecycle,
                "job_id": state.scheduler["job_id"],
                "scheduler": dict(state.scheduler),
            },
            "validation": {
                "status": (
                    "valid"
                    if valid
                    else (
                        "invalid"
                        if state.lifecycle == "outputs_invalid"
                        else "not_ready"
                    )
                ),
                "completed_points": expected if valid else 0,
                "expected_points": expected,
            },
            "next_action": (
                "review_production_preparation"
                if state.lifecycle == "ready_to_prepare_production"
                else "none" if state.lifecycle == "production_prepared" else "wait"
            ),
            "local_sync": {"status": "not_synchronized"},
        }

    def preview(self, request, *, session_id: str):
        plan, state = self._inspect(request)
        if state.lifecycle != "ready_to_prepare_production":
            raise ZeusProductionError("sensitivity_not_complete")
        expires = self.clock() + TOKEN_LIFETIME_SECONDS
        pending = _Pending(
            session_id,
            plan[0],
            plan[1],
            plan[4],
            plan[2].relative_to(self.root).as_posix(),
            plan[8],
            state.scheduler["submission_nonce"],
            state.scheduler["job_id"],
            plan[10],
            plan[9],
            plan[11],
            secrets.token_hex(16),
            expires,
        )
        token = self._previews.add(
            pending, expires_at=expires, capacity=MAX_PENDING_PREVIEWS
        )
        tasks = json.loads(
            render_production_transition(
                plan[3],
                plan[2],
                self.root,
                self._confirmation_rows(request, self._base_plan(request)),
                [dict(row) for row in state.rows],
            )["production/tasks.json"]
        )
        return {
            "preview_token": token,
            "expires_in_seconds": TOKEN_LIFETIME_SECONDS,
            "campaign": {
                "id": plan[0],
                "name": plan[3]["name"],
                "git_commit": plan[4],
                "s0_values": plan[3]["s0_values"],
            },
            "from_stage": "sensitivity",
            "to_stage": "production",
            "sensitivity": {
                "job_id": state.scheduler["job_id"],
                "completed_points": len(state.rows),
                "expected_points": len(state.rows),
            },
            "artifacts": {
                "create": [
                    "sensitivity_summary.json",
                    "production/tasks.json",
                    JOB_FILE,
                ],
                "update": ["campaign.json"],
            },
            "job": {
                "file": JOB_FILE,
                "kind": "array",
                "task_count": len(tasks),
                "array_throttle": 4,
                "queue": "zeus_combined_q",
                **reviewed_job_resources(plan[3], 'production', {"cores_per_task":150, "memory_per_task_bytes":68719476736, "walltime_seconds":43200}),
            },
            "effects": {
                "prepare_production": True,
                "submit_production": False,
                "start_simulation": False,
                "overwrite_existing": False,
            },
            "local_sync": {"status": "not_synchronized"},
        }

    def confirm(self, request, *, session_id: str):
        if set(request) != {"preview_token"}:
            raise ZeusProductionError("request_invalid")
        token = request["preview_token"]
        with self._confirm:
            record = self._previews.get(token)
            pending = None if record is None else record.value
            if pending is None or not secrets.compare_digest(
                pending.session_id, session_id
            ):
                raise ZeusProductionError("confirmation_invalid")
            if pending.result is not None:
                return dict(pending.result)
            if self.clock() > pending.expires:
                raise ZeusProductionError("confirmation_expired")
            plan, state = self._inspect(
                {
                    "campaign_id": pending.campaign_id,
                    "username": pending.profile.username,
                    "project_directory": pending.profile.project_directory,
                }
            )
            identity = (
                plan[4],
                plan[8],
                state.scheduler["submission_nonce"],
                state.scheduler["job_id"],
                plan[10],
                plan[9],
                plan[11],
            )
            expected = (
                pending.commit,
                pending.submission_key,
                pending.submission_nonce,
                pending.job_id,
                pending.rows_digest,
                pending.files,
                pending.transition_key,
            )
            if state.lifecycle != "ready_to_prepare_production" or identity != expected:
                raise ZeusProductionError("local_files_changed")
            payload = self._remote_payload(
                self._base_plan(
                    {
                        "campaign_id": pending.campaign_id,
                        "username": pending.profile.username,
                        "project_directory": pending.profile.project_directory,
                    }
                )
            )
            payload.update(
                {
                    "rows_digest": pending.rows_digest,
                    "production_files": dict(pending.files),
                    "transition_key": pending.transition_key,
                    "nonce": pending.nonce,
                }
            )
            result_state = self.transport_factory(plan[1]).prepare(**payload)
            self._validate_state(result_state, plan[3])
            self._validate_receipt(
                result_state,
                plan,
                self._base_plan(
                    {
                        "campaign_id": pending.campaign_id,
                        "username": pending.profile.username,
                        "project_directory": pending.profile.project_directory,
                    }
                ),
            )
            result = {
                "status": "production_prepared",
                "campaign_id": pending.campaign_id,
                "stage": "production",
                "artifacts": {"created": 3, "updated": 1},
                "submitted_to_zeus": False,
                "simulation_started": False,
                "local_sync": {"status": "not_synchronized"},
            }
            self._previews.replace(token, replace(pending, result=result))
            return result


class PinnedSshProductionTransport:
    def __init__(self, root: Path, ssh: Path, profile: ZeusProfile, *, timeout=90):
        self.profile = profile
        self.runner = PinnedSshRunner(
            PinnedSshPolicy.production_preparation(root, ssh, timeout=timeout)
        )

    def _call(self, operation: str, payload: Mapping[str, object]):
        pinned = {
            "inspect": ReceiverOperation.INSPECT,
            "prepare": ReceiverOperation.PREPARE,
        }[operation]
        try:
            result = self.runner.run(pinned, self.profile, payload)
        except (subprocess.TimeoutExpired, PinnedSshProcessError):
            raise ZeusProductionError(
                "transition_outcome_unknown"
                if operation == "prepare"
                else "zeus_timeout"
            ) from None
        if result.returncode or result.stderr:
            raise ZeusProductionError("remote_response_invalid")
        try:
            data = json.loads(result.stdout)
        except Exception:
            raise ZeusProductionError("remote_response_invalid") from None
        if not isinstance(data, dict) or set(data) != {
            "lifecycle",
            "scheduler",
            "rows",
            "branch",
            "receipt",
        }:
            raise ZeusProductionError("remote_response_invalid")
        return RemoteSensitivityState(
            data["lifecycle"],
            data["scheduler"],
            tuple(data["rows"]),
            data["branch"],
            data["receipt"],
        )

    def inspect(self, **payload):
        return self._call("inspect", payload)

    def prepare(self, **payload):
        return self._call("prepare", payload)
