"""Guarded at-most-once submission of the canonical 3D preliminary check."""

from __future__ import annotations

from lab_setup.mot_3d_timestep_policy import MOT_3D_TIMESTEP_POLICY

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

from workflow_api.discovery import build_registry
from workflow_api.mot_3d_discovery_transition import (
    EXPECTED_BUNDLE_PATHS,
    _bounded_read_at,
    _open_directory_at,
    _strict_json,
    _DIRECTORY_FLAGS,
)
from workflow_api.mot_3d_stage_topology import (
    FAMILIES,
    PRELIMINARY_CHECK_TOPOLOGY,
    public_chain,
)
from workflow_api.mot_3d_selection_submission import (
    exact_jobs as shared_exact_jobs,
    validate_selection_submission_state,
)
from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshProcessError,
    PinnedSshRunner,
    ReceiverOperation,
)
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.zeus_discovery_submission import canonical_digest
from workflow_api.zeus_snapshot import ZEUS_HOST, ZeusProfile

TTL = 300
CAPACITY = 32
HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ARRAY_JOB = re.compile(r"^\d+\[\]\.zeus-master$")
SCALAR_JOB = re.compile(r"^\d+\.zeus-master$")
FILES = (
    frozenset(
        name
        for family in FAMILIES
        for name in PRELIMINARY_CHECK_TOPOLOGY.jobs[family].values()
    )
    | frozenset(f"selection/discovery/{family}.json" for family in FAMILIES)
    | {"campaign.json"}
)
CODE_FILES = frozenset(
    {
        "config.py",
        "simulations/mot_3d.py",
        "studies/mot_3d_campaign.py",
        "studies/mot_3d/integrity.py",
        "studies/mot_3d/analysis/retention.py",
        "studies/mot_3d/preliminary/run.py",
        "studies/mot_3d/preliminary/merge.py",
        "workflow_api/mot_3d_selection_submission_remote.py",
        "workflow_api/mot_3d_preliminary_submission_remote.py",
        "lab_setup/specifications/laboratory_physical_v1.json",
        "lab_setup/specifications/mot_3d_timestep_policy_v2.json",
    }
)


class Mot3DPreliminarySubmissionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RemotePreliminarySubmissionState:
    lifecycle: str
    branch: str
    jobs: Mapping[str, Mapping[str, str | None]]
    nonce: str | None
    submitted_unix_s: int | None
    completed_array_tasks: int
    completed_merge_jobs: int


class PreliminarySubmissionTransport(Protocol):
    def inspect(self, **payload: object) -> RemotePreliminarySubmissionState: ...
    def submit(self, **payload: object) -> RemotePreliminarySubmissionState: ...
    def status(self, **payload: object) -> RemotePreliminarySubmissionState: ...


@dataclass(frozen=True)
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
    result: Mapping[str, object] | None = None
    terminal_error: str | None = None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_at(root_fd: int, relative: str, limit: int = 8 * 1024 * 1024) -> bytes:
    candidate = Path(relative)
    parts = candidate.parts
    if (
        candidate.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise OSError("unsafe relative path")
    descriptor = root_fd
    opened: list[int] = []
    try:
        for part in parts[:-1]:
            descriptor = _open_directory_at(descriptor, part, create=False)
            opened.append(descriptor)
        return _bounded_read_at(descriptor, parts[-1], limit)
    finally:
        for value in reversed(opened):
            try:
                import os

                os.close(value)
            except OSError:
                pass


def _exact_jobs(value: object, *, populated: bool) -> dict[str, dict[str, str | None]]:
    return shared_exact_jobs(
        value,
        populated=populated,
        error=Mot3DPreliminarySubmissionError,
        code="remote_response_invalid",
    )


class Mot3DPreliminarySubmissionCoordinator:
    error_type = Mot3DPreliminarySubmissionError
    topology = PRELIMINARY_CHECK_TOPOLOGY
    stage_id = "preliminary_check"
    stage_label = "Preliminary check"
    submit_effect = "submit_preliminary_check"
    already_started_code = "preliminary_already_started"
    partial_code = "preliminary_partial_submission"
    outcome_unknown_code = "preliminary_submission_outcome_unknown"
    completed_action = "validate_outputs"

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
            lambda profile: self._default_transport(profile)
        )
        self._previews = PreviewRegistry[_Pending](
            clock=clock, token_factory=token_factory
        )
        self._confirm = threading.Lock()

    def _default_transport(self, profile):
        return PinnedSshMot3DPreliminarySubmissionTransport(
            self.root, self.ssh, profile
        )

    def _status_local_sync(self, _plan):
        return {"status": "not_synchronized"}

    def _preview_local_sync(self, _pending):
        return None

    def _confirm_local_sync(self, _pending):
        return {"status": "not_synchronized"}

    def _plan(self, request: Mapping[str, object]):
        if (
            not isinstance(request, Mapping)
            or set(request) != {"campaign_id", "username", "project_directory"}
            or not isinstance(request.get("campaign_id"), str)
        ):
            raise Mot3DPreliminarySubmissionError("request_invalid")
        try:
            profile = ZeusProfile.parse(
                {
                    "username": request["username"],
                    "project_directory": request["project_directory"],
                }
            )
        except (KeyError, ValueError) as exc:
            raise Mot3DPreliminarySubmissionError("profile_invalid") from exc
        entry = build_registry(self.root).get(request["campaign_id"])
        if entry is None or entry.family != "mot_3d":
            raise Mot3DPreliminarySubmissionError("campaign_not_found")
        campaign = entry.manifest.parent
        import os

        campaign_fd = os.open(campaign, _DIRECTORY_FLAGS)
        try:
            manifest_raw = _read_at(campaign_fd, "campaign.json")
            manifest = _strict_json(manifest_raw)
            local_receipt_raw = _read_at(
                campaign_fd, ".mot_ui/sync/discovery_to_preliminary.json", 256 * 1024
            )
            local_receipt = _strict_json(local_receipt_raw)
            if (
                not isinstance(manifest, dict)
                or manifest.get("stage") != "preliminary_check"
                or manifest.get("name") != campaign.name
            ):
                raise ValueError
            commit = manifest.get("provenance", {}).get("git_commit")
            if not isinstance(commit, str) or not HEX40.fullmatch(commit):
                raise ValueError
            receipt_keys = {
                "status",
                "transition_key",
                "remote_receipt_sha256",
                "bundle_sha256",
                "files",
                "completed_unix_s",
            }
            if (
                not isinstance(local_receipt, dict)
                or set(local_receipt) != receipt_keys
                or local_receipt.get("status") != "synchronized"
                or not isinstance(local_receipt.get("files"), dict)
                or set(local_receipt["files"]) != EXPECTED_BUNDLE_PATHS
                or local_receipt["files"].get("campaign.json") != _sha(manifest_raw)
                or any(
                    not HEX64.fullmatch(str(value))
                    for value in local_receipt["files"].values()
                )
            ):
                raise ValueError
            for name, expected in local_receipt["files"].items():
                if _sha(_read_at(campaign_fd, name)) != expected:
                    raise ValueError
            stage = manifest.get("stages", {}).get("preliminary_check")
            if (
                not isinstance(stage, dict)
                or stage.get("classification")
                != "candidate_selection_not_final_validation"
                or stage.get("input_role") != "preliminary_check"
            ):
                raise ValueError
            files = {name: _sha(_read_at(campaign_fd, name)) for name in FILES}
            if files["campaign.json"] != _sha(manifest_raw):
                raise ValueError
            design = manifest.get("design", {})
            science = {
                "classification": stage["classification"],
                "candidates_per_family": PRELIMINARY_CHECK_TOPOLOGY.candidates_per_family,
                "input_ensembles": 4,
                "particles_per_ensemble": 150,
                "total_particles": 600,
                "recoil_seeds": [41001, 41002, 41003],
                "dt_s": design.get("screening_dt_s"),
                "t_max_s": MOT_3D_TIMESTEP_POLICY["t_max_s"],
                "solver": design.get("solver"),
                "selection_seed": 51001,
                "bootstrap_replicates": 10000,
                "bootstrap_seed": 52001,
            }
            if (
                not isinstance(science["dt_s"], (int, float))
                or isinstance(science["dt_s"], bool)
                or science["dt_s"] <= 0
                or not isinstance(science["solver"], str)
                or not science["solver"]
            ):
                raise ValueError
            identity = {
                "campaign_sha256": files["campaign.json"],
                "local_transition_receipt_sha256": _sha(local_receipt_raw),
                "transition_key": local_receipt.get("transition_key"),
                "remote_transition_receipt_sha256": local_receipt.get(
                    "remote_receipt_sha256"
                ),
                "bundle_sha256": local_receipt.get("bundle_sha256"),
                "files": files,
                "science": science,
                "physical_model_sha256": manifest.get("provenance", {}).get(
                    "physical_model_sha256"
                ),
                "upstream_campaign_sha256": manifest.get(
                    "upstream_2d_campaign", {}
                ).get("campaign_sha256"),
                "upstream_final_report_sha256": manifest.get(
                    "upstream_2d_campaign", {}
                ).get("final_report_sha256"),
                "timestep_policy_sha256": manifest.get("design", {})
                .get("timestep_evidence", {})
                .get("policy_sha256"),
                "code_files": {
                    name: _sha((self.root / name).read_bytes()) for name in CODE_FILES
                },
            }
            if any(
                not HEX64.fullmatch(str(identity[key]))
                for key in (
                    "transition_key",
                    "remote_transition_receipt_sha256",
                    "bundle_sha256",
                    "physical_model_sha256",
                    "upstream_campaign_sha256",
                    "upstream_final_report_sha256",
                    "timestep_policy_sha256",
                )
            ):
                raise ValueError
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise Mot3DPreliminarySubmissionError(
                "preliminary_preparation_invalid"
            ) from exc
        finally:
            os.close(campaign_fd)
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
            raise Mot3DPreliminarySubmissionError("local_files_changed")
        relative = campaign.relative_to(self.root).as_posix()
        key = canonical_digest({"campaign": relative, "commit": commit, **identity})
        return (
            str(request["campaign_id"]),
            profile,
            campaign,
            manifest,
            commit,
            identity,
            key,
            relative,
        )

    @staticmethod
    def _payload(plan, nonce=None):
        value = {
            "campaign": plan[7],
            "commit": plan[4],
            "identity": plan[5],
            "submission_key": plan[6],
        }
        if nonce is not None:
            value["nonce"] = nonce
        return value

    @staticmethod
    def _validate(state: RemotePreliminarySubmissionState, operation: str):
        validate_selection_submission_state(
            state,
            operation,
            error=Mot3DPreliminarySubmissionError,
        )

    def _remote(self, plan, operation, nonce=None):
        transport = self.transport_factory(plan[1])
        payload = self._payload(plan, nonce)
        state = getattr(transport, operation)(**payload)
        self._validate(state, operation)
        return state

    def status(self, request):
        plan = self._plan(request)
        state = self._remote(plan, "status")
        from workflow_api.mot_3d_selection_submission import public_lifecycle

        public = public_lifecycle(state.lifecycle)
        action = (
            "review_submission"
            if public == "not_submitted"
            else (
                "wait"
                if public in {"submitted", "queued", "running"}
                else (
                    self.completed_action
                    if public == "completed_success_unvalidated"
                    else "inspect_zeus"
                )
            )
        )
        return {
            "source": "zeus",
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "campaign": {
                "id": plan[0],
                "name": plan[3]["name"],
                "stage": self.stage_id,
            },
            "submission": {
                "status": public,
                "chain": public_chain(state.jobs, topology=self.topology),
            },
            "scheduler": {
                "expected_array_tasks": 6,
                "expected_merge_jobs": 2,
                "completed_array_tasks": state.completed_array_tasks,
                "completed_merge_jobs": state.completed_merge_jobs,
            },
            "validation": {
                "status": "not_started",
                "expected_candidates_per_family": 12,
                "expected_recoil_seeds_per_candidate": 3,
            },
            "next_action": action,
            "local_sync": self._status_local_sync(plan),
        }

    def preview(self, request, *, session_id: str):
        plan = self._plan(request)
        state = self._remote(plan, "inspect")
        if state.lifecycle != "eligible":
            code = (
                self.already_started_code
                if state.lifecycle == "submitted"
                else (
                    self.partial_code
                    if state.lifecycle == "partial"
                    else self.outcome_unknown_code
                )
            )
            raise Mot3DPreliminarySubmissionError(code)
        expires = self.clock() + TTL
        pending = _Pending(
            session_id,
            plan[0],
            plan[1],
            plan[2].relative_to(self.root).as_posix(),
            plan[4],
            plan[5],
            plan[6],
            secrets.token_hex(16),
            expires,
        )
        try:
            token = self._previews.add(pending, expires_at=expires, capacity=CAPACITY)
        except OverflowError as exc:
            raise Mot3DPreliminarySubmissionError("too_many_pending_previews") from exc
        t = self.topology
        result = {
            "preview_token": token,
            "expires_in_seconds": TTL,
            "campaign": {"id": plan[0], "name": plan[3]["name"], "git_commit": plan[4]},
            "stage": {"id": self.stage_id, "label": self.stage_label},
            "chain": {
                "families": [
                    {"id": family, "array_tasks": 3, "merge_jobs": 1}
                    for family in FAMILIES
                ],
                "qsub_calls": 4,
                "dependency": t.dependency,
            },
            "resources": {
                "array": {
                    "ncpus_per_task": t.array_ncpus,
                    "memory_gb_per_task": t.array_memory_gb,
                    "walltime": t.array_walltime,
                },
                "merge": {
                    "ncpus": t.merge_ncpus,
                    "memory_gb": t.merge_memory_gb,
                    "walltime": t.merge_walltime,
                },
            },
            "science": dict(plan[5]["science"]),
            "remote": {
                "host": ZEUS_HOST,
                "project_directory": plan[1].project_directory,
                "commit": plan[4],
                "branch": state.branch,
                "dirty": False,
            },
            "effects": {
                self.submit_effect: True,
                "start_simulation": True,
                "submit_later_stages": False,
                "modify_campaign_files": False,
                "record_submission_receipt": True,
            },
        }
        local_sync = self._preview_local_sync(pending)
        if local_sync is not None:
            result["local_sync"] = local_sync
        return result

    def confirm(self, request, *, session_id: str):
        if (
            not isinstance(request, Mapping)
            or set(request) != {"preview_token"}
            or not isinstance(request.get("preview_token"), str)
        ):
            raise Mot3DPreliminarySubmissionError("request_invalid")
        token = request["preview_token"]
        with self._confirm:
            record = self._previews.get(token)
            pending = record.value if record else None
            if pending is None or not secrets.compare_digest(
                pending.session_id, session_id
            ):
                raise Mot3DPreliminarySubmissionError("confirmation_invalid")
            if pending.result is not None:
                return dict(pending.result)
            if pending.terminal_error:
                raise Mot3DPreliminarySubmissionError(pending.terminal_error)
            if self.clock() > pending.expires:
                raise Mot3DPreliminarySubmissionError("confirmation_expired")
            plan = self._plan(
                {
                    "campaign_id": pending.campaign_id,
                    "username": pending.profile.username,
                    "project_directory": pending.profile.project_directory,
                }
            )
            if (
                plan[2].relative_to(self.root).as_posix(),
                plan[4],
                plan[5],
                plan[6],
            ) != (
                pending.relative,
                pending.commit,
                pending.identity,
                pending.submission_key,
            ):
                raise Mot3DPreliminarySubmissionError("local_files_changed")
            try:
                state = self._remote(plan, "submit", pending.nonce)
            except Mot3DPreliminarySubmissionError as exc:
                if exc.code in {
                    self.outcome_unknown_code,
                    self.already_started_code,
                    "remote_response_invalid",
                }:
                    self._previews.replace(
                        token, replace(pending, terminal_error=exc.code)
                    )
                raise
            if (
                state.lifecycle != "submitted"
                or state.nonce != pending.nonce
                or state.submitted_unix_s is None
            ):
                self._previews.replace(
                    token,
                    replace(pending, terminal_error=self.outcome_unknown_code),
                )
                raise Mot3DPreliminarySubmissionError(self.outcome_unknown_code)
            result = {
                "status": "submitted",
                "campaign_id": pending.campaign_id,
                "stage": self.stage_id,
                "chain": public_chain(state.jobs, topology=self.topology),
                "submitted_at": datetime.fromtimestamp(
                    state.submitted_unix_s, tz=timezone.utc
                ).isoformat(),
                "local_sync": self._confirm_local_sync(pending),
            }
            self._previews.replace(token, replace(pending, result=result))
            return result


class PinnedSshMot3DPreliminarySubmissionTransport:
    def __init__(self, root: Path, ssh: Path, profile: ZeusProfile, *, timeout=60):
        self.profile = profile
        self.runner = PinnedSshRunner(
            PinnedSshPolicy.mot_3d_preliminary_submission(root, ssh, timeout=timeout)
        )

    def _call(self, operation, payload):
        op = {
            "inspect": ReceiverOperation.INSPECT,
            "submit": ReceiverOperation.SUBMIT,
            "status": ReceiverOperation.STATUS,
        }[operation]
        try:
            result = self.runner.run(op, self.profile, payload)
        except (subprocess.TimeoutExpired, PinnedSshProcessError):
            raise Mot3DPreliminarySubmissionError(
                "preliminary_submission_outcome_unknown"
                if operation == "submit"
                else "zeus_timeout"
            ) from None
        if result.returncode or result.stderr:
            raise Mot3DPreliminarySubmissionError(
                "preliminary_submission_outcome_unknown"
                if operation == "submit"
                else "remote_response_invalid"
            )
        try:
            data = json.loads(result.stdout)
        except Exception:
            raise Mot3DPreliminarySubmissionError("remote_response_invalid") from None
        if not isinstance(data, dict) or set(data) != {
            "lifecycle",
            "branch",
            "jobs",
            "submission_nonce",
            "submitted_unix_s",
            "completed_array_tasks",
            "completed_merge_jobs",
        }:
            raise Mot3DPreliminarySubmissionError("remote_response_invalid")
        return RemotePreliminarySubmissionState(
            data["lifecycle"],
            data["branch"],
            data["jobs"],
            data["submission_nonce"],
            data["submitted_unix_s"],
            data["completed_array_tasks"],
            data["completed_merge_jobs"],
        )

    def inspect(self, **payload):
        return self._call("inspect", payload)

    def submit(self, **payload):
        return self._call("submit", payload)

    def status(self, **payload):
        return self._call("status", payload)
