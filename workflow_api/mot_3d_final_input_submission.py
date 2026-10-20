"""Guarded submission of the three-step final-validation input chain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from workflow_api.platform_io import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from typing import Any, Mapping

from workflow_api.mot_3d_closure_submission import validate_prior_transition_sync
from workflow_api.mot_3d_discovery_transition import _DIRECTORY_FLAGS, _strict_json
from workflow_api.mot_3d_finalist_transition import Mot3DFinalistTransitionCoordinator
from workflow_api.mot_3d_linear_submission import validate_linear_submission_state
from workflow_api.mot_3d_preliminary_transition import _read_relative
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.zeus_discovery_submission import canonical_digest
from workflow_api.zeus_snapshot import ZeusProfile

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
TTL = 300
FILES = frozenset(
    {
        "campaign.json",
        "selection/locked_nominals.json",
        "jobs/final_validation_inputs/01_generate_zeeman.pbs",
        "jobs/final_validation_inputs/02_generate_2d_survivors.pbs",
        "jobs/final_validation_inputs/03_freeze_inputs.pbs",
    }
)
CODE_FILES = frozenset(
    {
        "config.py",
        "studies/mot_3d_campaign.py",
        "studies/zeeman/generate_ensembles.py",
        "studies/mot_2d/production.py",
        "workflow_api/mot_3d_final_input_submission.py",
        "workflow_api/mot_3d_final_input_submission_remote.py",
        "workflow_api/mot_3d_linear_submission.py",
        "workflow_api/mot_3d_linear_submission_remote.py",
        "workflow_api/mot_3d_finalist_results.py",
        "workflow_api/mot_3d_finalist_transition.py",
        "workflow_api/mot_3d_finalist_transition_remote.py",
        "workflow_api/mot_3d_preliminary_transition_remote.py",
        "workflow_api/verified_artifact_bundle.py",
        "lab_setup/specifications/laboratory_physical_v1.json",
        "lab_setup/specifications/mot_3d_timestep_policy_v2.json",
    }
)


class Mot3DFinalInputSubmissionError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RemoteFinalInputSubmissionState:
    lifecycle: str
    branch: str
    jobs: Mapping[str, str | None]
    nonce: str | None
    submitted_unix_s: int | None
    completed_array_tasks: int
    completed_scalar_jobs: int


@dataclass
class _Pending:
    session_id: str
    campaign_id: str
    profile: ZeusProfile
    relative: str
    commit: str
    identity: Mapping[str, Any]
    submission_key: str
    nonce: str
    expires: float
    result: Mapping[str, Any] | None = None
    terminal_error: str | None = None


class Mot3DFinalInputSubmissionCoordinator:
    def __init__(
        self,
        repository_root,
        ssh_executable,
        git_executable,
        *,
        clock=time.time,
        token_factory=None,
        transport_factory=None,
    ):
        self.root = Path(repository_root).resolve(strict=True)
        self.ssh = Path(ssh_executable).resolve(strict=True)
        self.git = Path(git_executable).resolve(strict=True)
        self.clock = clock
        self.transport_factory = transport_factory or self._default_transport
        self._previews = PreviewRegistry(clock=clock, token_factory=token_factory)
        self._confirm_lock = threading.Lock()

    def _default_transport(self, profile):
        from workflow_api.mot_3d_final_input_submission_remote_client import (
            PinnedSshMot3DFinalInputSubmissionTransport,
        )

        return PinnedSshMot3DFinalInputSubmissionTransport(self.root, self.ssh, profile)

    def _plan(self, request):
        if (
            not isinstance(request, Mapping)
            or set(request) != {"campaign_id", "username", "project_directory"}
            or type(request.get("campaign_id")) is not str
        ):
            raise Mot3DFinalInputSubmissionError("request_invalid")
        try:
            profile = ZeusProfile.parse(
                {
                    "username": request["username"],
                    "project_directory": request["project_directory"],
                }
            )
            authority = Mot3DFinalistTransitionCoordinator(
                self.root, self.ssh, self.git, transport_factory=lambda _profile: None
            )
            base = authority._recovery_plan(request)
            campaign_id, _, campaign, manifest, commit = base[:5]
            expected_paths = base[9]
            if (
                manifest.get("stage") != "final_validation_input_generation"
                or manifest.get("name") != campaign.name
            ):
                raise ValueError
            campaign_fd = os.open(campaign, _DIRECTORY_FLAGS)
            try:
                sync, sync_raw = validate_prior_transition_sync(
                    campaign_fd,
                    expected_paths,
                    "finalist_selection_to_final_validation_inputs.json",
                )
                files = {
                    name: hashlib.sha256(_read_relative(campaign_fd, name)).hexdigest()
                    for name in FILES
                }
            finally:
                os.close(campaign_fd)
            stage = manifest["stages"]["final_validation_input_generation"]
            logical = campaign.relative_to(self.root).as_posix()
            if (
                stage.get("classification") != "new_unopened_inputs_after_nominal_lock"
                or stage.get("zeeman_seeds") != list(range(3035, 3055))
                or stage.get("mot_seeds") != list(range(43035, 43055))
                or stage.get("locked_nominals")
                != f"{logical}/selection/locked_nominals.json"
                or stage.get("zeeman_job")
                != f"{logical}/jobs/final_validation_inputs/01_generate_zeeman.pbs"
                or stage.get("mot_job")
                != f"{logical}/jobs/final_validation_inputs/02_generate_2d_survivors.pbs"
                or stage.get("freeze_job")
                != f"{logical}/jobs/final_validation_inputs/03_freeze_inputs.pbs"
                or stage.get("input_manifest")
                != f"{logical}/final_validation_inputs/input_manifest.json"
            ):
                raise ValueError
            science = {
                "classification": stage["classification"],
                "zeeman_seeds": list(range(3035, 3055)),
                "mot_seeds": list(range(43035, 43055)),
                "zeeman_tasks": 20,
                "mot_tasks": 20,
                "npools": 200,
                "dependency": "afterok linear chain",
                "resources": {
                    "zeeman": {"ncpus": 200, "memory_gb": 64, "walltime": "08:00:00"},
                    "mot_2d": {"ncpus": 200, "memory_gb": 64, "walltime": "12:00:00"},
                    "freeze": {"ncpus": 1, "memory_gb": 8, "walltime": "00:30:00"},
                },
            }
            root_fd = os.open(self.root, _DIRECTORY_FLAGS)
            try:
                code_files = {
                    name: hashlib.sha256(_read_relative(root_fd, name)).hexdigest()
                    for name in CODE_FILES
                }
            finally:
                os.close(root_fd)
            identity = {
                "campaign_sha256": files["campaign.json"],
                "local_transition_receipt_sha256": hashlib.sha256(sync_raw).hexdigest(),
                "transition_key": sync["transition_key"],
                "remote_transition_receipt_sha256": sync["remote_receipt_sha256"],
                "bundle_sha256": sync["bundle_sha256"],
                "files": files,
                "science": science,
                "physical_model_sha256": manifest["provenance"][
                    "physical_model_sha256"
                ],
                "upstream_campaign_sha256": manifest["upstream_2d_campaign"][
                    "campaign_sha256"
                ],
                "upstream_final_report_sha256": manifest["upstream_2d_campaign"][
                    "final_report_sha256"
                ],
                "timestep_policy_sha256": manifest["design"]["timestep_evidence"][
                    "policy_sha256"
                ],
                "code_files": code_files,
            }
            if (
                type(commit) is not str
                or HEX40.fullmatch(commit) is None
                or any(
                    type(identity[key]) is not str
                    or HEX64.fullmatch(identity[key]) is None
                    for key in (
                        "transition_key",
                        "remote_transition_receipt_sha256",
                        "bundle_sha256",
                        "physical_model_sha256",
                        "upstream_campaign_sha256",
                        "upstream_final_report_sha256",
                        "timestep_policy_sha256",
                    )
                )
            ):
                raise ValueError
        except Mot3DFinalInputSubmissionError:
            raise
        except Exception as exc:
            raise Mot3DFinalInputSubmissionError(
                "final_input_preparation_invalid"
            ) from exc
        revision = subprocess.run(
            [self.git, "-C", self.root, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        dirty = subprocess.run(
            [
                self.git,
                "-C",
                self.root,
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if (
            revision.returncode
            or revision.stderr
            or revision.stdout.strip() != commit
            or dirty.returncode
            or dirty.stderr
            or dirty.stdout
        ):
            raise Mot3DFinalInputSubmissionError("local_files_changed")
        relative = campaign.relative_to(self.root).as_posix()
        key = canonical_digest({"campaign": relative, "commit": commit, **identity})
        return campaign_id, profile, campaign, manifest, commit, identity, key, relative

    def _inspect(self, request, operation="inspect"):
        plan = self._plan(request)
        transport = self.transport_factory(plan[1])
        payload = {
            "campaign": plan[7],
            "commit": plan[4],
            "submission_key": plan[6],
            "identity": plan[5],
        }
        state = getattr(transport, operation)(**payload)
        validate_linear_submission_state(
            state, operation, error=Mot3DFinalInputSubmissionError
        )
        return plan, transport, state

    @staticmethod
    def _chain(state):
        return {
            "dependency": "afterok linear chain",
            "jobs": [
                {"id": name, "job_id": state.jobs[name]}
                for name in ("zeeman", "mot_2d", "freeze")
            ],
        }

    def status(self, request):
        plan, _, state = self._inspect(request, "status")
        action = "review_submission" if state.lifecycle == "eligible" else "wait"
        if state.lifecycle in {
            "partial",
            "outcome_unknown",
            "held",
            "completed_failed",
            "status_unknown",
        }:
            action = "inspect_zeus"
        if state.lifecycle == "completed_success_unvalidated":
            action = "validate_generated_inputs"
        return {
            "source": "zeus",
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "campaign": {
                "id": plan[0],
                "name": plan[3]["name"],
                "stage": "final_validation_input_generation",
            },
            "chain": {"status": state.lifecycle, **self._chain(state)},
            "scheduler": {
                "expected_array_tasks": 40,
                "expected_scalar_jobs": 1,
                "completed_array_tasks": state.completed_array_tasks,
                "completed_scalar_jobs": state.completed_scalar_jobs,
            },
            "next_action": action,
            "local_sync": {
                "status": "synchronized",
                "receipt_sha256": plan[5]["local_transition_receipt_sha256"],
            },
        }

    def preview(self, request, *, session_id):
        plan, _, state = self._inspect(request)
        if state.lifecycle != "eligible":
            raise Mot3DFinalInputSubmissionError("final_input_already_started")
        expires = self.clock() + TTL
        pending = _Pending(
            session_id,
            plan[0],
            plan[1],
            plan[7],
            plan[4],
            plan[5],
            plan[6],
            secrets.token_hex(16),
            expires,
        )
        try:
            token = self._previews.add(pending, expires_at=expires, capacity=32)
        except OverflowError as exc:
            raise Mot3DFinalInputSubmissionError("too_many_pending_previews") from exc
        return {
            "preview_token": token,
            "expires_in_seconds": TTL,
            "campaign": {"id": plan[0], "name": plan[3]["name"], "git_commit": plan[4]},
            "stage": {
                "id": "final_validation_input_generation",
                "label": "Final validation input generation",
            },
            "chain": {
                "dependency": "afterok linear chain",
                "steps": [
                    {
                        "id": "zeeman",
                        "tasks": 20,
                        "resources": plan[5]["science"]["resources"]["zeeman"],
                    },
                    {
                        "id": "mot_2d",
                        "tasks": 20,
                        "resources": plan[5]["science"]["resources"]["mot_2d"],
                    },
                    {
                        "id": "freeze",
                        "tasks": 1,
                        "resources": plan[5]["science"]["resources"]["freeze"],
                    },
                ],
            },
            "science": plan[5]["science"],
            "effects": {
                "submit_input_generation": True,
                "start_final_validation": False,
                "advance_campaign": False,
                "modify_files": False,
            },
            "local_sync": {
                "status": "synchronized",
                "receipt_sha256": plan[5]["local_transition_receipt_sha256"],
            },
        }

    def confirm(self, request, *, session_id):
        if (
            not isinstance(request, Mapping)
            or set(request) != {"preview_token"}
            or type(request.get("preview_token")) is not str
        ):
            raise Mot3DFinalInputSubmissionError("request_invalid")
        with self._confirm_lock:
            record = self._previews.get(request["preview_token"])
            pending = record.value if record else None
            if pending is None or not secrets.compare_digest(
                pending.session_id, session_id
            ):
                raise Mot3DFinalInputSubmissionError("confirmation_invalid")
            if pending.result is not None:
                return dict(pending.result)
            if pending.terminal_error:
                raise Mot3DFinalInputSubmissionError(pending.terminal_error)
            if self.clock() > pending.expires:
                raise Mot3DFinalInputSubmissionError("confirmation_expired")
            again = {
                "campaign_id": pending.campaign_id,
                "username": pending.profile.username,
                "project_directory": pending.profile.project_directory,
            }
            plan = self._plan(again)
            if (plan[4], plan[5], plan[6]) != (
                pending.commit,
                pending.identity,
                pending.submission_key,
            ):
                raise Mot3DFinalInputSubmissionError("local_or_remote_evidence_changed")
            transport = self.transport_factory(pending.profile)
            try:
                state = transport.submit(
                    campaign=pending.relative,
                    commit=pending.commit,
                    submission_key=pending.submission_key,
                    identity=pending.identity,
                    nonce=pending.nonce,
                )
                validate_linear_submission_state(
                    state, "submit", error=Mot3DFinalInputSubmissionError
                )
            except Exception as exc:
                pending.terminal_error = "final_input_submission_outcome_unknown"
                raise Mot3DFinalInputSubmissionError(pending.terminal_error) from exc
            if state.lifecycle != "submitted":
                pending.terminal_error = (
                    "final_input_submission_outcome_unknown"
                    if state.lifecycle == "outcome_unknown"
                    else "final_input_partial_submission"
                )
                raise Mot3DFinalInputSubmissionError(pending.terminal_error)
            pending.result = {
                "status": "submitted",
                "campaign_id": pending.campaign_id,
                "stage": "final_validation_input_generation",
                "chain": self._chain(state),
                "submitted_to_zeus": True,
                "simulation_started": True,
                "final_validation_started": False,
                "local_sync": {
                    "status": "synchronized",
                    "receipt_sha256": pending.identity[
                        "local_transition_receipt_sha256"
                    ],
                },
            }
            return dict(pending.result)
