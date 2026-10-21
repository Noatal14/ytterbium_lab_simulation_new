"""Guarded Confirmation completion and no-submit Sensitivity preparation."""
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

from workflow_api.mot_2d_plan import (
    render_confirmation_transition, render_sensitivity_transition,
)
from workflow_api.pinned_ssh import (
    PinnedSshPolicy, PinnedSshProcessError, PinnedSshRunner, ReceiverOperation,
)
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.zeus_confirmation import ZeusConfirmationCoordinator, ZeusConfirmationError
from workflow_api.zeus_snapshot import ZeusProfile

TOKEN_LIFETIME_SECONDS = 300
MAX_PENDING_PREVIEWS = 32
JOB_FILE = "jobs/05_sensitivity.pbs"
OUTPUT_FILES = frozenset({
    "winners.json", "sensitivity/tasks.json", JOB_FILE, "campaign.json",
})


class ZeusSensitivityError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RemoteConfirmationState:
    lifecycle: str
    scheduler: Mapping[str, Any]
    rows: tuple[Mapping[str, Any], ...]
    branch: str
    receipt: Mapping[str, Any] | None = None


class SensitivityTransport(Protocol):
    def inspect(self, **payload: object) -> RemoteConfirmationState: ...
    def prepare(self, **payload: object) -> RemoteConfirmationState: ...


@dataclass(frozen=True)
class _Pending:
    session_id: str
    campaign_id: str
    profile: ZeusProfile
    commit: str
    relative: str
    confirmation_submission_key: str
    confirmation_submission_nonce: str
    confirmation_job_id: str
    rows_digest: str
    files: Mapping[str, str]
    transition_key: str
    nonce: str
    expires: float
    result: Mapping[str, object] | None = None


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


class ZeusSensitivityCoordinator:
    def __init__(self, repository_root: Path, ssh_executable: Path, git_executable: Path,
                 *, clock=time.time, token_factory=None, transport_factory=None):
        self.root = repository_root.resolve(strict=True)
        self.ssh = ssh_executable.resolve(strict=True)
        self.git = git_executable.resolve(strict=True)
        self.clock = clock
        self.transport_factory = transport_factory or (
            lambda profile: PinnedSshSensitivityTransport(self.root, self.ssh, profile)
        )
        self._previews = PreviewRegistry[_Pending](clock=clock, token_factory=token_factory)
        self._confirm = threading.Lock()

    def _base_plan(self, request: Mapping[str, object]):
        try:
            coordinator = ZeusConfirmationCoordinator(
                self.root, self.ssh, self.git
            )
            confirmation_plan, state = coordinator._inspect(request)
        except ZeusConfirmationError as error:
            raise ZeusSensitivityError(error.code) from error
        (campaign_id, profile, campaign, initial_manifest, commit, _, chain_key,
         _, _) = confirmation_plan
        receipt = state.receipt
        if state.lifecycle != "confirmation_prepared" or not isinstance(receipt, dict):
            raise ZeusSensitivityError("confirmation_not_prepared")
        confirmation_files = receipt.get("files")
        if (receipt.get("chain_key") != chain_key or receipt.get("commit") != commit
                or not isinstance(confirmation_files, dict)
                or set(confirmation_files) != {
                    "refined_candidates.json", "confirmation/tasks.json",
                    "jobs/04_confirmation.pbs", "campaign.json",
                }):
            raise ZeusSensitivityError("confirmation_preparation_invalid")
        prior = coordinator._remote_manifest(initial_manifest, campaign, self.root)
        rendered = render_confirmation_transition(
            prior, campaign, self.root, [dict(row) for row in receipt["rows"]]
        )
        manifest = json.loads(rendered["campaign.json"])
        if hashlib.sha256(rendered["campaign.json"]).hexdigest() != confirmation_files["campaign.json"]:
            raise ZeusSensitivityError("confirmation_preparation_invalid")
        transition_nonce = receipt["nonce"]
        transition_digest = hashlib.sha256(json.dumps(
            receipt, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        relative = campaign.relative_to(self.root).as_posix()
        submission_key = hashlib.sha256(json.dumps({
            "campaign": relative, "commit": commit,
            "transition_nonce": transition_nonce,
            "transition_digest": transition_digest,
            "files": confirmation_files,
            "job_file": "jobs/04_confirmation.pbs",
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return (campaign_id, profile, campaign, manifest, commit,
                dict(confirmation_files), transition_nonce, transition_digest,
                submission_key)

    def _remote_payload(self, plan: tuple[Any, ...]) -> dict[str, object]:
        (_, _, campaign, _, commit, files, transition_nonce,
         transition_digest, submission_key) = plan[:9]
        root = self.root
        return {
            "campaign": campaign.relative_to(root).as_posix(),
            "commit": commit,
            "confirmation_files": files,
            "confirmation_transition_nonce": transition_nonce,
            "confirmation_transition_digest": transition_digest,
            "confirmation_submission_key": submission_key,
        }

    def _inspect(self, request: Mapping[str, object]):
        base = self._base_plan(request)
        profile = base[1]
        state = self.transport_factory(profile).inspect(**self._remote_payload(base))
        self._validate_state(state, base[3])
        rows = [dict(row) for row in state.rows]
        rendered: dict[str, bytes] = {}
        files: dict[str, str] = {}
        rows_digest = ""
        transition_key = ""
        if state.lifecycle in {"ready_to_prepare_sensitivity", "sensitivity_prepared"}:
            rendered = render_sensitivity_transition(base[3], base[2], self.root, rows)
            files = {name: hashlib.sha256(data).hexdigest()
                     for name, data in rendered.items()}
            rows_digest = _canonical_digest(rows)
            transition_key = _canonical_digest({
                "campaign": base[2].relative_to(self.root).as_posix(),
                "commit": base[4],
                "confirmation_submission_key": base[8],
                "confirmation_submission_nonce": state.scheduler["submission_nonce"],
                "confirmation_job_id": state.scheduler["job_id"],
                "rows_digest": rows_digest,
                "files": files,
            })
        plan = (*base, files, rows_digest, transition_key)
        if state.lifecycle == "sensitivity_prepared":
            self._validate_receipt(state, plan)
        return plan, state

    @staticmethod
    def _validate_state(state: RemoteConfirmationState, manifest: Mapping[str, Any]) -> None:
        allowed = {"queued", "running", "held", "failed", "status_unknown",
                   "awaiting_outputs", "outputs_invalid",
                   "ready_to_prepare_sensitivity", "sensitivity_prepared"}
        if (state.lifecycle not in allowed or not state.branch
                or len(state.branch) > 256 or not state.branch.isprintable()):
            raise ZeusSensitivityError("remote_response_invalid")
        scheduler = state.scheduler
        expected = len(manifest["s0_values"]) * 5
        if (not isinstance(scheduler, dict)
                or set(scheduler) != {"state", "task_count", "counts", "job_id",
                                      "submission_nonce"}
                or scheduler["task_count"] != expected
                or not re.fullmatch(r"\d+\[\]\.zeus-master", str(scheduler["job_id"]))
                or not re.fullmatch(r"[0-9a-f]{32}", str(scheduler["submission_nonce"]))):
            raise ZeusSensitivityError("remote_response_invalid")
        counts = scheduler.get("counts")
        if (not isinstance(counts, dict)
                or set(counts) != {"queued", "running", "held", "succeeded", "failed"}
                or any(not isinstance(value, int) or isinstance(value, bool) or value < 0
                       for value in counts.values())):
            raise ZeusSensitivityError("remote_response_invalid")
        scheduler_state = scheduler.get("state")
        if scheduler_state not in {"queued", "running", "held", "completed_success",
                                   "completed_failed", "unknown"}:
            raise ZeusSensitivityError("remote_response_invalid")
        if sum(counts.values()) != (0 if scheduler_state == "unknown" else expected):
            raise ZeusSensitivityError("remote_response_invalid")
        ready = state.lifecycle in {"ready_to_prepare_sensitivity", "sensitivity_prepared"}
        if ready and len(state.rows) != expected or not ready and state.rows:
            raise ZeusSensitivityError("remote_response_invalid")
        coherent = (
            ready and scheduler_state == "completed_success" and counts["succeeded"] == expected
            or state.lifecycle == "queued" and scheduler_state == "queued" and counts["queued"] > 0
            or state.lifecycle == "running" and scheduler_state == "running" and counts["running"] > 0
            or state.lifecycle == "held" and scheduler_state == "held" and counts["held"] > 0
            or state.lifecycle == "failed" and scheduler_state == "completed_failed" and counts["failed"] > 0
            or state.lifecycle == "status_unknown" and scheduler_state == "unknown"
            or state.lifecycle in {"awaiting_outputs", "outputs_invalid"}
               and scheduler_state == "completed_success" and counts["succeeded"] == expected
        )
        if not coherent:
            raise ZeusSensitivityError("remote_response_invalid")

    @staticmethod
    def _validate_receipt(state: RemoteConfirmationState, plan: tuple[Any, ...]) -> None:
        receipt = state.receipt
        exact = {"status", "nonce", "transition_key", "commit",
                 "confirmation_submission_key", "confirmation_submission_nonce",
                 "confirmation_job_id", "rows_digest", "rows", "files",
                 "scheduler", "completed_unix_s"}
        if (not isinstance(receipt, dict) or set(receipt) != exact
                or receipt.get("status") != "sensitivity_prepared"
                or not re.fullmatch(r"[0-9a-f]{32}", str(receipt.get("nonce", "")))
                or receipt.get("transition_key") != plan[11]
                or receipt.get("commit") != plan[4]
                or receipt.get("confirmation_submission_key") != plan[8]
                or receipt.get("confirmation_submission_nonce") != state.scheduler["submission_nonce"]
                or receipt.get("confirmation_job_id") != state.scheduler["job_id"]
                or receipt.get("rows_digest") != plan[10]
                or receipt.get("rows") != [dict(row) for row in state.rows]
                or receipt.get("files") != plan[9]
                or receipt.get("scheduler") != dict(state.scheduler)
                or not isinstance(receipt.get("completed_unix_s"), int)
                or isinstance(receipt.get("completed_unix_s"), bool)
                or not 0 <= receipt["completed_unix_s"] <= 253402300799):
            raise ZeusSensitivityError("transition_outcome_unknown")

    def status(self, request: Mapping[str, object]):
        plan, state = self._inspect(request)
        expected = len(plan[3]["s0_values"]) * 5
        valid = state.lifecycle in {"ready_to_prepare_sensitivity", "sensitivity_prepared"}
        invalid = state.lifecycle == "outputs_invalid"
        return {
            "source": "zeus", "queried_at": datetime.now(timezone.utc).isoformat(),
            "campaign": {"id": plan[0], "name": plan[3]["name"],
                         "stage": "sensitivity" if state.lifecycle == "sensitivity_prepared"
                         else "confirmation"},
            "confirmation": {"status": state.lifecycle,
                             "job_id": state.scheduler["job_id"],
                             "scheduler": dict(state.scheduler)},
            "validation": {"status": "valid" if valid else "invalid" if invalid else "not_ready",
                           "completed_points": expected if valid else 0,
                           "expected_points": expected},
            "next_action": "review_sensitivity_preparation" if state.lifecycle == "ready_to_prepare_sensitivity"
                           else "none" if state.lifecycle == "sensitivity_prepared"
                           else "inspect_zeus" if state.lifecycle in {"held", "failed", "status_unknown", "outputs_invalid"}
                           else "wait",
            "local_sync": {"status": "not_synchronized"},
        }

    def preview(self, request: Mapping[str, object], *, session_id: str):
        plan, state = self._inspect(request)
        if state.lifecycle != "ready_to_prepare_sensitivity":
            code = {"awaiting_outputs": "confirmation_outputs_pending",
                    "outputs_invalid": "confirmation_outputs_invalid",
                    "sensitivity_prepared": "sensitivity_already_prepared"}.get(
                        state.lifecycle, "confirmation_not_complete")
            raise ZeusSensitivityError(code)
        expires = self.clock() + TOKEN_LIFETIME_SECONDS
        pending = _Pending(
            session_id, plan[0], plan[1], plan[4],
            plan[2].relative_to(self.root).as_posix(), plan[8],
            state.scheduler["submission_nonce"], state.scheduler["job_id"],
            plan[10], plan[9], plan[11], secrets.token_hex(16), expires,
        )
        try:
            token = self._previews.add(pending, expires_at=expires,
                                       capacity=MAX_PENDING_PREVIEWS)
        except OverflowError as error:
            raise ZeusSensitivityError("too_many_pending_previews") from error
        tasks = json.loads(render_sensitivity_transition(
            plan[3], plan[2], self.root, [dict(row) for row in state.rows]
        )["sensitivity/tasks.json"])
        return {
            "preview_token": token, "expires_in_seconds": TOKEN_LIFETIME_SECONDS,
            "campaign": {"id": plan[0], "name": plan[3]["name"],
                         "git_commit": plan[4], "s0_values": plan[3]["s0_values"]},
            "from_stage": "confirmation", "to_stage": "sensitivity",
            "confirmation": {"job_id": state.scheduler["job_id"],
                             "completed_points": len(state.rows),
                             "expected_points": len(plan[3]["s0_values"]) * 5},
            "artifacts": {"create": ["winners.json", "sensitivity/tasks.json", JOB_FILE],
                          "update": ["campaign.json"]},
            "job": {"file": JOB_FILE, "kind": "array", "task_count": len(tasks),
                    "array_throttle": 3, "queue": "zeus_combined_q",
                    **reviewed_job_resources(plan[3], 'sensitivity', {"cores_per_task":200, "memory_per_task_bytes":68719476736, "walltime_seconds":36000})},
            "effects": {"prepare_sensitivity": True, "submit_sensitivity": False,
                        "start_simulation": False, "overwrite_existing": False},
            "local_sync": {"status": "not_synchronized"},
        }

    def confirm(self, request: Mapping[str, object], *, session_id: str):
        if set(request) != {"preview_token"} or not isinstance(request.get("preview_token"), str):
            raise ZeusSensitivityError("request_invalid")
        token = request["preview_token"]
        with self._confirm:
            record = self._previews.get(token)
            pending = None if record is None else record.value
            if pending is None or not secrets.compare_digest(pending.session_id, session_id):
                raise ZeusSensitivityError("confirmation_invalid")
            if pending.result is not None:
                return dict(pending.result)
            if self.clock() > pending.expires:
                raise ZeusSensitivityError("confirmation_expired")
            plan, state = self._inspect({
                "campaign_id": pending.campaign_id,
                "username": pending.profile.username,
                "project_directory": pending.profile.project_directory,
            })
            identity = (plan[4], plan[8], state.scheduler["submission_nonce"],
                        state.scheduler["job_id"], plan[10], plan[9], plan[11])
            expected = (pending.commit, pending.confirmation_submission_key,
                        pending.confirmation_submission_nonce, pending.confirmation_job_id,
                        pending.rows_digest, pending.files, pending.transition_key)
            if state.lifecycle != "ready_to_prepare_sensitivity" or identity != expected:
                raise ZeusSensitivityError("local_files_changed")
            payload = self._remote_payload(plan)
            payload.update({"rows_digest": pending.rows_digest,
                            "sensitivity_files": dict(pending.files),
                            "transition_key": pending.transition_key,
                            "nonce": pending.nonce})
            transport = self.transport_factory(plan[1])
            try:
                result_state = transport.prepare(**payload)
                self._validate_state(result_state, plan[3])
                self._validate_receipt(result_state, plan)
                if result_state.receipt.get("nonce") != pending.nonce:
                    raise ZeusSensitivityError("transition_outcome_unknown")
            except Exception as error:
                raise ZeusSensitivityError("transition_outcome_unknown") from error
            result = {"status": "sensitivity_prepared", "campaign_id": pending.campaign_id,
                      "stage": "sensitivity", "artifacts": {"created": 3, "updated": 1},
                      "submitted_to_zeus": False, "simulation_started": False,
                      "local_sync": {"status": "not_synchronized"}}
            self._previews.replace(token, replace(pending, result=result))
            return result


class PinnedSshSensitivityTransport:
    def __init__(self, root: Path, ssh: Path, profile: ZeusProfile, *, timeout=90):
        self.profile = profile
        self.runner = PinnedSshRunner(PinnedSshPolicy.sensitivity_preparation(
            root, ssh, timeout=timeout
        ))

    def _call(self, operation, payload):
        if operation not in {"inspect", "prepare"}:
            raise ZeusSensitivityError("remote_response_invalid")
        try:
            return self._call_response(operation, payload)
        except Exception as error:
            # Once a write-capable invocation begins, failure cannot prove that
            # publication did not happen. Keep strict parsing; require inspection.
            if operation == "prepare":
                raise ZeusSensitivityError("transition_outcome_unknown") from error
            raise

    def _call_response(self, operation: str, payload: Mapping[str, object]):
        pinned = {"inspect": ReceiverOperation.INSPECT,
                  "prepare": ReceiverOperation.PREPARE}.get(operation)
        if pinned is None:
            raise ZeusSensitivityError("remote_response_invalid")
        try:
            result = self.runner.run(pinned, self.profile, payload)
        except (subprocess.TimeoutExpired, PinnedSshProcessError):
            raise ZeusSensitivityError(
                "transition_outcome_unknown" if operation == "prepare" else "zeus_timeout"
            ) from None
        if result.returncode or result.stderr:
            raise ZeusSensitivityError(
                "transition_outcome_unknown" if operation == "prepare" else "remote_response_invalid"
            )
        try:
            data = json.loads(result.stdout)
        except Exception:
            raise ZeusSensitivityError("remote_response_invalid") from None
        if not isinstance(data, dict):
            raise ZeusSensitivityError("remote_response_invalid")
        if "error" in data:
            raise ZeusSensitivityError(str(data["error"]))
        if set(data) != {"lifecycle", "scheduler", "rows", "branch", "receipt"}:
            raise ZeusSensitivityError("remote_response_invalid")
        if not isinstance(data["scheduler"], dict) or not isinstance(data["rows"], list):
            raise ZeusSensitivityError("remote_response_invalid")
        if data["receipt"] is not None and not isinstance(data["receipt"], dict):
            raise ZeusSensitivityError("remote_response_invalid")
        return RemoteConfirmationState(data["lifecycle"], data["scheduler"],
                                       tuple(data["rows"]), data["branch"], data["receipt"])

    def inspect(self, **payload): return self._call("inspect", payload)
    def prepare(self, **payload): return self._call("prepare", payload)
