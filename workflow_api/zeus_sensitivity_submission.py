"""Explicit at-most-once submission of the prepared Sensitivity array."""
from __future__ import annotations

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
from typing import Mapping, Protocol

from workflow_api.preview_registry import PreviewRegistry
from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshProcessError,
    PinnedSshRunner,
    ReceiverOperation,
)
from workflow_api.zeus_sensitivity import ZeusSensitivityCoordinator, ZeusSensitivityError
from workflow_api.zeus_snapshot import ZEUS_HOST, ZeusProfile

TOKEN_LIFETIME_SECONDS = 300
MAX_PENDING_PREVIEWS = 32
JOB_RE = re.compile(r"^\d+\[\]\.zeus-master$")
JOB_FILE = "jobs/05_sensitivity.pbs"


class ZeusSensitivitySubmissionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RemoteSensitivitySubmissionState:
    status: str
    branch: str | None = None
    job_id: str | None = None
    nonce: str | None = None
    completed_unix_s: int | None = None


class SensitivitySubmissionTransport(Protocol):
    def inspect(self, **payload: object) -> RemoteSensitivitySubmissionState: ...
    def submit(self, **payload: object) -> RemoteSensitivitySubmissionState: ...
    def status(self, **payload: object) -> RemoteSensitivitySubmissionState: ...


@dataclass(frozen=True)
class _Pending:
    session_id: str
    campaign_id: str
    profile: ZeusProfile
    commit: str
    relative: str
    transition_nonce: str
    transition_digest: str
    files: Mapping[str, str]
    submission_key: str
    nonce: str
    expires: float
    result: Mapping[str, object] | None = None
    terminal_error: str | None = None


class ZeusSensitivitySubmissionCoordinator:
    def __init__(self, repository_root: Path, ssh_executable: Path, git_executable: Path,
                 *, clock=time.time, token_factory=None, transport_factory=None):
        self.root = repository_root.resolve(strict=True)
        self.ssh = ssh_executable.resolve(strict=True)
        self.git = git_executable.resolve(strict=True)
        self.clock = clock
        self.transport_factory = transport_factory or (
            lambda profile: PinnedSshSensitivitySubmissionTransport(
                self.root, self.ssh, profile
            )
        )
        self._previews = PreviewRegistry[_Pending](clock=clock, token_factory=token_factory)
        self._confirm = threading.Lock()

    def _plan(self, request: Mapping[str, object]):
        try:
            coordinator = ZeusSensitivityCoordinator(self.root, self.ssh, self.git)
            plan, state = coordinator._inspect(request)
        except ZeusSensitivityError as error:
            raise ZeusSensitivitySubmissionError(error.code) from error
        (campaign_id, profile, campaign, manifest, commit, _confirmation_files,
         _confirmation_transition_nonce, _confirmation_transition_digest,
         _confirmation_submission_key, prepared_files, _rows_digest,
         transition_key) = plan
        if state.lifecycle != "sensitivity_prepared" or not isinstance(state.receipt, dict):
            raise ZeusSensitivitySubmissionError("sensitivity_not_prepared")
        receipt = state.receipt
        transition_digest = hashlib.sha256(json.dumps(
            receipt, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        files = receipt.get("files")
        if (
            not isinstance(files, dict)
            or set(files) != {
                "winners.json", "sensitivity/tasks.json",
                JOB_FILE, "campaign.json",
            }
            or any(not re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in files.values())
            or receipt.get("transition_key") != transition_key
            or files != prepared_files
            or receipt.get("commit") != commit
            or not re.fullmatch(r"[0-9a-f]{32}", str(receipt.get("nonce", "")))
        ):
            raise ZeusSensitivitySubmissionError("sensitivity_preparation_invalid")
        relative = campaign.relative_to(self.root).as_posix()
        key = hashlib.sha256(json.dumps({
            "campaign": relative,
            "commit": commit,
            "transition_nonce": receipt["nonce"],
            "transition_digest": transition_digest,
            "files": files,
            "job_file": JOB_FILE,
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return campaign_id, profile, campaign, manifest, commit, dict(files), receipt["nonce"], transition_digest, key

    def _remote(self, profile, relative, commit, files, transition_nonce, transition_digest, key, nonce):
        return self.transport_factory(profile), {
            "campaign": relative, "commit": commit,
            "sensitivity_files": files,
            "transition_nonce": transition_nonce,
            "transition_digest": transition_digest,
            "submission_key": key, "nonce": nonce,
        }

    def status(self, request):
        campaign_id, profile, campaign, manifest, commit, files, transition_nonce, transition_digest, key = self._plan(request)
        transport, payload = self._remote(profile, campaign.relative_to(self.root).as_posix(), commit, files, transition_nonce, transition_digest, key, None)
        state = transport.status(**payload)
        public = {
            "eligible": "not_submitted", "queued": "queued",
            "running": "running", "held": "held",
            "completed_success": "completed_success",
            "completed_failed": "completed_failed",
            "status_unknown": "status_unknown",
            "ambiguous": "outcome_unknown",
        }.get(state.status)
        if public is None:
            raise ZeusSensitivitySubmissionError("remote_response_invalid")
        return {
            "source": "zeus", "queried_at": datetime.now(timezone.utc).isoformat(),
            "campaign": {"id": campaign_id, "name": manifest["name"], "stage": "sensitivity"},
            "submission": {"status": public, "job_id": state.job_id},
            "next_action": "review_submission" if state.status == "eligible" else "inspect_zeus" if state.status in {"ambiguous", "held", "completed_failed", "status_unknown"} else "wait" if state.status in {"queued", "running"} else "validate_outputs",
            "local_sync": {"status": "not_synchronized"},
        }

    def preview(self, request, *, session_id: str):
        campaign_id, profile, campaign, manifest, commit, files, transition_nonce, transition_digest, key = self._plan(request)
        relative = campaign.relative_to(self.root).as_posix()
        transport, payload = self._remote(profile, relative, commit, files, transition_nonce, transition_digest, key, None)
        state = transport.inspect(**payload)
        if state.status == "submitted":
            raise ZeusSensitivitySubmissionError("sensitivity_already_submitted")
        if state.status == "ambiguous":
            raise ZeusSensitivitySubmissionError("sensitivity_submission_outcome_unknown")
        if state.status != "eligible" or not state.branch:
            raise ZeusSensitivitySubmissionError("remote_response_invalid")
        expires = self.clock() + TOKEN_LIFETIME_SECONDS
        pending = _Pending(session_id, campaign_id, profile, commit, relative, transition_nonce, transition_digest,
                           files, key, secrets.token_hex(16), expires)
        try:
            token = self._previews.add(pending, expires_at=expires, capacity=MAX_PENDING_PREVIEWS)
        except OverflowError as error:
            raise ZeusSensitivitySubmissionError("too_many_pending_previews") from error
        tasks = manifest.get("stages", {}).get("sensitivity", {}).get("tasks")
        if not isinstance(tasks, int) or isinstance(tasks, bool) or not 1 <= tasks <= 1000:
            raise ZeusSensitivitySubmissionError("sensitivity_preparation_invalid")
        return {
            "preview_token": token, "expires_in_seconds": TOKEN_LIFETIME_SECONDS,
            "campaign": {"id": campaign_id, "name": manifest["name"], "git_commit": commit, "s0_values": manifest["s0_values"]},
            "stage": {"id": "sensitivity", "label": "Sensitivity"},
            "job": {"file": JOB_FILE, "kind": "array", "task_count": tasks,
                    "array_throttle": 3, "queue": "zeus_combined_q",
                    "cores_per_task": 200, "memory_per_task_bytes": 68719476736,
                    "walltime_seconds": 36000},
            "remote": {"host": ZEUS_HOST, "project_directory": profile.project_directory,
                       "commit": commit, "branch": state.branch, "dirty": False},
            "effects": {"submit_sensitivity": True, "start_simulation": True,
                        "submit_later_stages": False,
                        "modify_campaign_files": False,
                        "record_submission_receipt": True},
            "local_sync": {"status": "not_synchronized"},
        }

    def confirm(self, request, *, session_id: str):
        if set(request) != {"preview_token"} or not isinstance(request.get("preview_token"), str):
            raise ZeusSensitivitySubmissionError("request_invalid")
        token = request["preview_token"]
        with self._confirm:
            record = self._previews.get(token)
            pending = record.value if record is not None else None
            if pending is None or not secrets.compare_digest(pending.session_id, session_id):
                raise ZeusSensitivitySubmissionError("sensitivity_invalid")
            if pending.result is not None:
                return dict(pending.result)
            if pending.terminal_error is not None:
                raise ZeusSensitivitySubmissionError(pending.terminal_error)
            if self.clock() > pending.expires:
                raise ZeusSensitivitySubmissionError("sensitivity_expired")
            plan = self._plan({"campaign_id": pending.campaign_id,
                               "username": pending.profile.username,
                               "project_directory": pending.profile.project_directory})
            _, profile, campaign, _, commit, files, transition_nonce, transition_digest, key = plan
            if (commit, files, transition_nonce, transition_digest, key, campaign.relative_to(self.root).as_posix()) != (
                pending.commit, pending.files, pending.transition_nonce, pending.transition_digest,
                pending.submission_key, pending.relative,
            ):
                raise ZeusSensitivitySubmissionError("local_files_changed")
            transport, payload = self._remote(profile, pending.relative, commit, files, transition_nonce, transition_digest, key, pending.nonce)
            try:
                state = transport.submit(**payload)
            except ZeusSensitivitySubmissionError as error:
                if error.code in {"sensitivity_submission_outcome_unknown", "sensitivity_already_submitted", "remote_response_invalid"}:
                    self._previews.replace(token, replace(pending, terminal_error=error.code))
                raise
            if (state.status != "submitted" or state.job_id is None or
                    state.nonce != pending.nonce or state.completed_unix_s is None):
                self._previews.replace(token, replace(pending, terminal_error="sensitivity_submission_outcome_unknown"))
                raise ZeusSensitivitySubmissionError("sensitivity_submission_outcome_unknown")
            try:
                submitted_at = datetime.fromtimestamp(
                    state.completed_unix_s, tz=timezone.utc
                ).isoformat()
            except (OverflowError, OSError, ValueError):
                self._previews.replace(
                    token,
                    replace(
                        pending,
                        terminal_error="sensitivity_submission_outcome_unknown",
                    ),
                )
                raise ZeusSensitivitySubmissionError(
                    "sensitivity_submission_outcome_unknown"
                ) from None
            result = {"status": "submitted", "campaign_id": pending.campaign_id,
                      "stage": "sensitivity", "job_id": state.job_id,
                      "submitted_at": submitted_at,
                      "local_sync": {"status": "not_synchronized"}}
            self._previews.replace(token, replace(pending, result=result))
            return result


class PinnedSshSensitivitySubmissionTransport:
    def __init__(self, root: Path, ssh: Path, profile: ZeusProfile, *, timeout=60):
        self.profile = profile
        self.runner = PinnedSshRunner(PinnedSshPolicy.sensitivity_submission(root, ssh, timeout=timeout))

    def _call(self, operation: str, payload):
        pinned = {"inspect": ReceiverOperation.INSPECT, "submit": ReceiverOperation.SUBMIT,
                  "status": ReceiverOperation.STATUS}.get(operation)
        if pinned is None:
            raise ZeusSensitivitySubmissionError("remote_response_invalid")
        try:
            result = self.runner.run(pinned, self.profile, payload)
        except (subprocess.TimeoutExpired, PinnedSshProcessError):
            raise ZeusSensitivitySubmissionError(
                "sensitivity_submission_outcome_unknown" if operation == "submit"
                else "zeus_timeout"
            ) from None
        if result.returncode or result.stderr:
            raise ZeusSensitivitySubmissionError(
                "sensitivity_submission_outcome_unknown" if operation == "submit"
                else "remote_response_invalid"
            )
        try:
            data = json.loads(result.stdout)
        except Exception:
            raise ZeusSensitivitySubmissionError(
                "sensitivity_submission_outcome_unknown" if operation == "submit"
                else "remote_response_invalid"
            ) from None
        if not isinstance(data, dict):
            raise ZeusSensitivitySubmissionError("remote_response_invalid")
        if "error" in data:
            raise ZeusSensitivitySubmissionError(str(data["error"]))
        if set(data) != {"status", "branch", "job_id", "nonce", "completed_unix_s"}:
            raise ZeusSensitivitySubmissionError("remote_response_invalid")
        status = data["status"]
        allowed = {
            "inspect": {"eligible", "submitted", "ambiguous"},
            "submit": {"submitted", "ambiguous"},
            "status": {"eligible", "ambiguous", "queued", "running", "held",
                       "completed_success", "completed_failed", "status_unknown"},
        }[operation]
        if status not in allowed:
            raise ZeusSensitivitySubmissionError("remote_response_invalid")
        branch = data["branch"]
        if not isinstance(branch, str) or not branch or len(branch) > 256 or not branch.isprintable():
            raise ZeusSensitivitySubmissionError("remote_response_invalid")
        job_id, nonce, stamp = data["job_id"], data["nonce"], data["completed_unix_s"]
        if status == "eligible" and any(value is not None for value in (job_id, nonce, stamp)):
            raise ZeusSensitivitySubmissionError("remote_response_invalid")
        if status == "ambiguous" and (
            job_id is not None
            or stamp is not None
            or (
                nonce is not None
                and (
                    not isinstance(nonce, str)
                    or not re.fullmatch(r"[0-9a-f]{32}", nonce)
                )
            )
        ):
            raise ZeusSensitivitySubmissionError("remote_response_invalid")
        if status in {"submitted", "queued", "running", "held", "completed_success",
                      "completed_failed", "status_unknown"} and (
            not isinstance(job_id, str) or not JOB_RE.fullmatch(job_id)
            or not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce)
            or not isinstance(stamp, int) or isinstance(stamp, bool)
            or not 0 <= stamp <= 253402300799
            or (operation == "submit" and nonce != payload.get("nonce"))
        ):
            raise ZeusSensitivitySubmissionError(
                "sensitivity_submission_outcome_unknown" if operation == "submit"
                else "remote_response_invalid"
            )
        return RemoteSensitivitySubmissionState(status, branch, job_id, nonce, stamp)

    def inspect(self, **payload): return self._call("inspect", payload)
    def submit(self, **payload): return self._call("submit", payload)
    def status(self, **payload): return self._call("status", payload)
