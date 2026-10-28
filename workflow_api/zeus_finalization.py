"""Explicit, no-submission finalization of sealed 2D-MOT Production evidence."""

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
from typing import Any, Mapping, Protocol

from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshProcessError,
    PinnedSshRunner,
    ReceiverOperation,
)
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.discovery import build_registry
from workflow_api.manifest_codec import read_manifest
from workflow_api.zeus_snapshot import ZeusProfile
from workflow_api.mot_2d_spec import validate_campaign_policy

TOKEN_LIFETIME_SECONDS = 300
MAX_PENDING_PREVIEWS = 32


class ZeusFinalizationError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RemoteProductionState:
    lifecycle: str
    scheduler: Mapping[str, Any]
    evidence_digest: str
    files: Mapping[str, str]
    results: tuple[Mapping[str, Any], ...]
    production_identity: Mapping[str, Any]
    branch: str
    receipt: Mapping[str, Any] | None = None


class FinalizationTransport(Protocol):
    def inspect(self, **payload: object) -> RemoteProductionState: ...
    def finalize(self, **payload: object) -> RemoteProductionState: ...


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
    evidence_digest: str
    files: Mapping[str, str]
    results_digest: str
    finalization_key: str
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


class ZeusFinalizationCoordinator:
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
            lambda profile: PinnedSshFinalizationTransport(self.root, self.ssh, profile)
        )
        self._previews = PreviewRegistry[_Pending](
            clock=clock, token_factory=token_factory
        )
        self._confirm = threading.Lock()
        from workflow_api.mot_2d_collection import CollectionCoordinator

        self.collection = CollectionCoordinator(self)

    def collection_preview(self, request, *, session_id):
        try:
            return self.collection.preview(request, session_id=session_id)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ZeusFinalizationError("collection_invalid") from exc

    def collection_confirm(self, request, *, session_id):
        try:
            return self.collection.confirm(request, session_id=session_id)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ZeusFinalizationError("collection_invalid") from exc

    def _base_plan(self, request: Mapping[str, object]):
        try:
            if set(request) != {"campaign_id", "username", "project_directory"}:
                raise ValueError()
            campaign_id = request["campaign_id"]
            if not isinstance(campaign_id, str):
                raise ValueError()
            profile = ZeusProfile.parse(
                {
                    "username": request["username"],
                    "project_directory": request["project_directory"],
                }
            )
            entry = build_registry(self.root).get(campaign_id)
            if entry is None or entry.family != "mot_2d":
                raise ValueError()
            manifest = read_manifest(entry.manifest).model
            campaign = entry.manifest.parent
            commit = manifest["provenance"]["git_commit"]
        except Exception:
            raise ZeusFinalizationError("campaign_not_found") from None
        return campaign_id, profile, campaign, manifest, commit

    def _remote_payload(self, base: tuple[Any, ...]) -> dict[str, object]:
        (_, _, campaign, _, commit) = base
        return {
            "campaign": campaign.relative_to(self.root).as_posix(),
            "commit": commit,
        }

    def _inspect(self, request: Mapping[str, object]):
        base = self._base_plan(request)
        state = self.transport_factory(base[1]).inspect(**self._remote_payload(base))
        self._validate_state(state, base[3])
        identity = dict(state.production_identity)
        results = [dict(item) for item in state.results]
        results_digest = _digest(results) if results else ""
        finalization_key = ""
        if state.lifecycle in {"ready_to_finalize", "campaign_complete"}:
            finalization_key = _digest(
                {
                    "campaign": base[2].relative_to(self.root).as_posix(),
                    "commit": base[4],
                    "production_submission_key": identity["submission_key"],
                    "production_submission_nonce": identity["submission_nonce"],
                    "production_job_id": identity["job_id"],
                    "evidence_digest": state.evidence_digest,
                    "files": dict(state.files),
                    "results_digest": results_digest,
                }
            )
        plan = (
            *base,
            identity["production_files"],
            identity["transition_nonce"],
            identity["transition_digest"],
            identity["submission_key"],
            identity["submission_nonce"],
            identity["job_id"],
            state.evidence_digest,
            dict(state.files),
            results_digest,
            finalization_key,
        )
        if state.lifecycle == "campaign_complete":
            self._validate_receipt(state, plan)
        return plan, state

    @staticmethod
    def _validate_state(
        state: RemoteProductionState, manifest: Mapping[str, Any]
    ) -> None:
        try:
            acceptance = validate_campaign_policy(dict(manifest))
        except ValueError as error:
            raise ZeusFinalizationError("remote_response_invalid") from error
        expected_suitability = (
            "acceptance_only" if acceptance else "eligible_as_3d_campaign_input"
        )
        allowed = {
            "queued",
            "running",
            "held",
            "failed",
            "status_unknown",
            "awaiting_outputs",
            "outputs_invalid",
            "ready_to_finalize",
            "campaign_complete",
        }
        expected = 20 * len(manifest["s0_values"])
        scheduler = state.scheduler
        identity = state.production_identity
        production_files = (
            identity.get("production_files") if isinstance(identity, dict) else None
        )
        if (
            state.lifecycle not in allowed
            or not state.branch
            or len(state.branch) > 256
            or not state.branch.isprintable()
            or not isinstance(scheduler, dict)
            or set(scheduler)
            != {"state", "task_count", "counts", "job_id", "submission_nonce"}
            or not isinstance(identity, dict)
            or set(identity)
            != {
                "production_files",
                "transition_nonce",
                "transition_digest",
                "submission_key",
                "submission_nonce",
                "job_id",
            }
            or not isinstance(production_files, dict)
            or set(production_files)
            != {
                "sensitivity_summary.json",
                "production/tasks.json",
                "jobs/06_production.pbs",
                "campaign.json",
            }
            or any(
                not re.fullmatch(r"[0-9a-f]{64}", str(value))
                for value in production_files.values()
            )
            or identity.get("job_id") != scheduler.get("job_id")
            or identity.get("submission_nonce") != scheduler.get("submission_nonce")
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(identity.get("submission_key", ""))
            )
            or not re.fullmatch(
                r"[0-9a-f]{32}", str(identity.get("submission_nonce", ""))
            )
            or not re.fullmatch(
                r"[0-9a-f]{32}", str(identity.get("transition_nonce", ""))
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(identity.get("transition_digest", ""))
            )
            or scheduler.get("task_count") != expected
            or not re.fullmatch(
                r"\d+\[\]\.zeus-master", str(scheduler.get("job_id", ""))
            )
        ):
            raise ZeusFinalizationError("remote_response_invalid")
        counts = scheduler.get("counts")
        if (
            not isinstance(counts, dict)
            or set(counts) != {"queued", "running", "held", "succeeded", "failed"}
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in counts.values()
            )
            or sum(counts.values())
            != (0 if scheduler.get("state") == "unknown" else expected)
        ):
            raise ZeusFinalizationError("remote_response_invalid")
        scheduler_state = scheduler.get("state")
        if scheduler_state not in {
            "queued",
            "running",
            "held",
            "completed_success",
            "completed_failed",
            "unknown",
        }:
            raise ZeusFinalizationError("remote_response_invalid")
        ready = state.lifecycle in {"ready_to_finalize", "campaign_complete"}
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
            raise ZeusFinalizationError("remote_response_invalid")
        expected_files = {
            *(
                f"production/s0_{float(value):.6f}".replace(".", "p") + "/summary.json"
                for value in manifest["s0_values"]
            ),
            "final_report.json",
            "campaign.json",
        }
        if ready:
            if (
                not re.fullmatch(r"[0-9a-f]{64}", state.evidence_digest)
                or set(state.files) != expected_files
                or any(
                    not re.fullmatch(r"[0-9a-f]{64}", str(value))
                    for value in state.files.values()
                )
                or len(state.results) != len(manifest["s0_values"])
            ):
                raise ZeusFinalizationError("remote_response_invalid")
            for result in state.results:
                required = {
                    "s0",
                    "n_ensembles",
                    "total_input",
                    "total_survivors",
                    "recommended_parameters",
                    "prediction",
                    "target_uncertainty_passes",
                    "robustness_status",
                    "near_optimality_status",
                    "warnings",
                    "retention",
                    "output_suitability",
                }
                if (
                    set(result) != required
                    or result["n_ensembles"] != 20
                    or result["retention"] != "retained"
                    or result["output_suitability"] != expected_suitability
                ):
                    raise ZeusFinalizationError("remote_response_invalid")
        elif state.evidence_digest or state.files or state.results:
            raise ZeusFinalizationError("remote_response_invalid")

    @staticmethod
    def _validate_receipt(state: RemoteProductionState, plan: tuple[Any, ...]) -> None:
        receipt = state.receipt
        exact = {
            "status",
            "nonce",
            "finalization_key",
            "commit",
            "production_submission_key",
            "production_submission_nonce",
            "production_job_id",
            "evidence_digest",
            "files",
            "results_digest",
            "results",
            "scheduler",
            "completed_unix_s",
        }
        if (
            not isinstance(receipt, dict)
            or set(receipt) != exact
            or receipt.get("status") != "campaign_complete"
            or receipt.get("finalization_key") != plan[14]
            or receipt.get("commit") != plan[4]
            or receipt.get("production_submission_key") != plan[8]
            or receipt.get("production_submission_nonce") != plan[9]
            or receipt.get("production_job_id") != plan[10]
            or receipt.get("evidence_digest") != plan[11]
            or receipt.get("files") != plan[12]
            or receipt.get("results_digest") != plan[13]
            or receipt.get("results") != [dict(item) for item in state.results]
            or receipt.get("scheduler") != dict(state.scheduler)
            or not re.fullmatch(r"[0-9a-f]{32}", str(receipt.get("nonce", "")))
            or not isinstance(receipt.get("completed_unix_s"), int)
            or isinstance(receipt.get("completed_unix_s"), bool)
            or not 0 <= receipt["completed_unix_s"] <= 253402300799
        ):
            raise ZeusFinalizationError("finalization_outcome_unknown")

    def _collection_sync_status(self, campaign, receipt):
        try:
            return self.collection.status(campaign, receipt)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ZeusFinalizationError("collection_conflict") from exc

    def status(self, request):
        plan, state = self._inspect(request)
        valid = state.lifecycle in {"ready_to_finalize", "campaign_complete"}
        return {
            "source": "zeus",
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "campaign": {
                "id": plan[0],
                "name": plan[3]["name"],
                "stage": (
                    "complete"
                    if state.lifecycle == "campaign_complete"
                    else "production"
                ),
            },
            "production": {
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
                "completed_ensembles": (state.scheduler["task_count"] if valid else 0),
                "expected_ensembles": 20 * len(plan[3]["s0_values"]),
            },
            "next_action": (
                "review_finalization"
                if state.lifecycle == "ready_to_finalize"
                else "none" if state.lifecycle == "campaign_complete" else "wait"
            ),
            "local_sync": (
                self._collection_sync_status(plan[2], state.receipt)
                if state.lifecycle == "campaign_complete"
                else {"status": "not_synchronized"}
            ),
            **(
                {"results": [dict(item) for item in state.results]}
                if state.lifecycle == "campaign_complete"
                else {}
            ),
        }

    def preview(self, request, *, session_id: str):
        plan, state = self._inspect(request)
        if state.lifecycle != "ready_to_finalize":
            raise ZeusFinalizationError("production_not_complete")
        expires = self.clock() + TOKEN_LIFETIME_SECONDS
        pending = _Pending(
            session_id,
            plan[0],
            plan[1],
            plan[4],
            plan[2].relative_to(self.root).as_posix(),
            plan[8],
            plan[9],
            plan[10],
            plan[11],
            plan[12],
            plan[13],
            plan[14],
            secrets.token_hex(16),
            expires,
        )
        token = self._previews.add(
            pending, expires_at=expires, capacity=MAX_PENDING_PREVIEWS
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
            "from_stage": "production",
            "to_stage": "complete",
            "production": {
                "job_id": state.scheduler["job_id"],
                "completed_ensembles": 20 * len(plan[3]["s0_values"]),
                "expected_ensembles": 20 * len(plan[3]["s0_values"]),
            },
            "results": [dict(item) for item in state.results],
            "artifacts": {
                "create": sorted(
                    name for name in state.files if name != "campaign.json"
                ),
                "update": ["campaign.json"],
            },
            "effects": {
                "finalize_campaign": True,
                "submit_job": False,
                "start_simulation": False,
                "overwrite_existing": False,
            },
            "local_sync": {"status": "not_synchronized"},
        }

    def confirm(self, request, *, session_id: str):
        if set(request) != {"preview_token"}:
            raise ZeusFinalizationError("request_invalid")
        token = request["preview_token"]
        with self._confirm:
            record = self._previews.get(token)
            pending = None if record is None else record.value
            if pending is None or not secrets.compare_digest(
                pending.session_id, session_id
            ):
                raise ZeusFinalizationError("confirmation_invalid")
            if pending.result is not None:
                return dict(pending.result)
            if self.clock() > pending.expires:
                raise ZeusFinalizationError("confirmation_expired")
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
                plan[9],
                plan[10],
                plan[11],
                plan[12],
                plan[13],
                plan[14],
            )
            expected = (
                pending.commit,
                pending.submission_key,
                pending.submission_nonce,
                pending.job_id,
                pending.evidence_digest,
                pending.files,
                pending.results_digest,
                pending.finalization_key,
            )
            if state.lifecycle != "ready_to_finalize" or identity != expected:
                raise ZeusFinalizationError("remote_files_changed")
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
                    "evidence_digest": pending.evidence_digest,
                    "final_files": dict(pending.files),
                    "results_digest": pending.results_digest,
                    "finalization_key": pending.finalization_key,
                    "nonce": pending.nonce,
                }
            )
            transport = self.transport_factory(plan[1])
            try:
                completed = transport.finalize(**payload)
                self._validate_state(completed, plan[3])
                self._validate_receipt(completed, plan)
                if completed.receipt.get("nonce") != pending.nonce:
                    raise ZeusFinalizationError("finalization_outcome_unknown")
            except Exception as error:
                raise ZeusFinalizationError("finalization_outcome_unknown") from error
            result = {
                "status": "campaign_complete",
                "campaign_id": pending.campaign_id,
                "stage": "complete",
                "results": [dict(item) for item in completed.results],
                "submitted_to_zeus": False,
                "simulation_started": False,
                "local_sync": {"status": "not_synchronized"},
            }
            self._previews.replace(token, replace(pending, result=result))
            return result


class PinnedSshFinalizationTransport:
    def __init__(self, root: Path, ssh: Path, profile: ZeusProfile, *, timeout=180):
        self.profile = profile
        self.runner = PinnedSshRunner(
            PinnedSshPolicy.finalization(root, ssh, timeout=timeout)
        )

    def _call(self, operation, payload):
        if operation not in {"inspect", "finalize"}:
            raise ZeusFinalizationError("remote_response_invalid")
        try:
            return self._call_response(operation, payload)
        except Exception as error:
            # Once a write-capable invocation begins, failure cannot prove that
            # publication did not happen. Keep strict parsing; require inspection.
            if operation == "finalize":
                raise ZeusFinalizationError("finalization_outcome_unknown") from error
            raise

    def _call_response(self, operation: str, payload: Mapping[str, object]):
        pinned = {
            "inspect": ReceiverOperation.INSPECT,
            "finalize": ReceiverOperation.PREPARE,
        }[operation]
        try:
            result = self.runner.run(pinned, self.profile, payload)
        except (subprocess.TimeoutExpired, PinnedSshProcessError):
            raise ZeusFinalizationError(
                "finalization_outcome_unknown"
                if operation == "finalize"
                else "zeus_timeout"
            ) from None
        if result.returncode or result.stderr:
            raise ZeusFinalizationError("remote_response_invalid")
        try:
            data = json.loads(result.stdout)
        except Exception:
            raise ZeusFinalizationError("remote_response_invalid") from None
        exact = {
            "lifecycle",
            "scheduler",
            "evidence_digest",
            "files",
            "results",
            "production_identity",
            "branch",
            "receipt",
        }
        if not isinstance(data, dict) or set(data) != exact:
            raise ZeusFinalizationError("remote_response_invalid")
        return RemoteProductionState(
            data["lifecycle"],
            data["scheduler"],
            data["evidence_digest"],
            data["files"],
            tuple(data["results"]),
            data["production_identity"],
            data["branch"],
            data["receipt"],
        )

    def retrieve(self, **payload):
        try:
            result = self.runner.run(ReceiverOperation.RETRIEVE, self.profile, payload)
        except (subprocess.TimeoutExpired, PinnedSshProcessError):
            raise ZeusFinalizationError("zeus_timeout") from None
        if result.returncode or result.stderr:
            if result.returncode == 20 and not result.stderr:
                from workflow_api.verified_artifact_bundle import _strict_json

                try:
                    value = _strict_json(result.stdout)
                    if value == {"error": "collection_too_large"}:
                        raise ZeusFinalizationError("collection_too_large")
                except (ValueError, TypeError):
                    pass
            raise ZeusFinalizationError("remote_response_invalid")
        from workflow_api.verified_artifact_bundle import _strict_json

        try:
            return _strict_json(result.stdout)
        except (ValueError, TypeError, UnicodeError):
            raise ZeusFinalizationError("remote_response_invalid") from None

    def inspect(self, **payload):
        return self._call("inspect", payload)

    def finalize(self, **payload):
        return self._call("finalize", payload)
