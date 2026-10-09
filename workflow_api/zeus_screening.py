"""Guarded smoke lifecycle inspection and screening preparation on Zeus.

This boundary can inspect one recorded smoke job and publish the deterministic
screening plan.  It contains no scheduler submission operation.
"""

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

from workflow_api.discovery import build_registry
from workflow_api.mot_2d_plan import render_campaign_files, render_screen_transition
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshRunner,
    ReceiverOperation,
)
from workflow_api.zeus_snapshot import ZeusProfile
from workflow_api.zeus_transfer import CampaignArtifactPlanner, ZeusPreparationError, _load_manifest

TOKEN_LIFETIME_SECONDS = 300
MAX_PENDING_PREVIEWS = 32
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class ZeusScreeningError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code); self.code = code


@dataclass(frozen=True)
class RemoteSmokeState:
    lifecycle: str
    job_id: str
    raw_state: str
    exit_status: int | None
    points: tuple[Mapping[str, Any], ...] = ()
    artifact_count: int = 0
    branch: str = ""


class ScreeningTransport(Protocol):
    def inspect(self, **payload: object) -> RemoteSmokeState: ...
    def prepare(self, **payload: object) -> RemoteSmokeState: ...


@dataclass(frozen=True)
class _Pending:
    session_id: str; campaign_id: str; profile: ZeusProfile; commit: str
    campaign_relative: str; job_id: str; smoke_digest: str
    prepared_files: Mapping[str, str]; submission_key: str
    transition_files: Mapping[str, str]; nonce: str; expires_at: float
    result: Mapping[str, object] | None = None


class ZeusScreeningCoordinator:
    """Session-bound orchestration for inspection and one explicit transition."""

    def __init__(self, repository_root: Path, ssh_executable: Path, git_executable: Path,
                 *, clock=time.time, token_factory=None, transport_factory=None):
        self.root=repository_root.resolve(strict=True); self.ssh=ssh_executable.resolve(strict=True); self.git=git_executable.resolve(strict=True)
        self.clock=clock; self.transport_factory=transport_factory or (lambda profile: PinnedSshScreeningTransport(self.root,self.ssh,profile))
        self._previews = PreviewRegistry[_Pending](
            clock=clock,
            token_factory=token_factory,
        )
        self._confirm_lock=threading.Lock()

    def _revision(self) -> tuple[str,bool]:
        env={"PATH":str(self.git.parent),"HOME":str(Path.home()),"LC_ALL":"C","GIT_CONFIG_NOSYSTEM":"1","GIT_OPTIONAL_LOCKS":"0","GIT_TERMINAL_PROMPT":"0"}
        def run(args:list[str])->bytes:
            try: result=subprocess.run([str(self.git),*args],cwd=self.root,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,shell=False,close_fds=True,timeout=10,check=False)
            except subprocess.TimeoutExpired: raise ZeusScreeningError("local_repository_unavailable") from None
            if result.returncode or result.stderr or len(result.stdout)>1024*1024: raise ZeusScreeningError("local_repository_unavailable")
            return result.stdout
        try:
            commit=run(["rev-parse","--verify","HEAD^{commit}"]).decode("ascii").strip()
            dirty=bool(run(["status","--porcelain=v1","--untracked-files=no","--", "workflow_api", "studies", "simulations", "utils", "config.py", "lab_setup"]))
        except UnicodeError: raise ZeusScreeningError("local_repository_unavailable") from None
        if not COMMIT_RE.fullmatch(commit): raise ZeusScreeningError("local_repository_unavailable")
        return commit,not dirty

    def _plan(self,campaign_id:str)->tuple[Path,dict[str,Any],str,dict[str,str],str,dict[str,str]]:
        entry=build_registry(self.root).get(campaign_id)
        if entry is None or entry.family!="mot_2d": raise ZeusScreeningError("campaign_not_found")
        try: manifest=_load_manifest(entry.manifest)
        except ZeusPreparationError as error: raise ZeusScreeningError("campaign_not_canonical") from error
        campaign=entry.manifest.parent
        if manifest.get("stage")!="smoke": raise ZeusScreeningError("campaign_not_smoke")
        try:
            artifact_plan=CampaignArtifactPlanner(self.root).plan(campaign);selected,commit=artifact_plan.files,artifact_plan.commit
            canonical=render_campaign_files(manifest,campaign,self.root)
            transition=render_screen_transition(manifest,campaign,self.root)
        except Exception as error: raise ZeusScreeningError("campaign_not_canonical") from error
        if entry.manifest.read_bytes()!=canonical["campaign.json"]: raise ZeusScreeningError("campaign_not_canonical")
        files={name:hashlib.sha256(content).hexdigest() for name,content in transition.items()}
        relative=campaign.relative_to(self.root).as_posix()
        prepared={path:item[1] for path,item in selected.items()}
        job=f"{relative}/jobs/01_smoke.pbs"
        submission_key=hashlib.sha256(json.dumps({"campaign":relative,"commit":commit,"manifest":prepared[f'{relative}/campaign.json'],"pbs":prepared[job]},sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return campaign,manifest,commit,prepared,submission_key,files

    @staticmethod
    def _profile(request:Mapping[str,object])->ZeusProfile:
        try: return ZeusProfile.parse({"username":request.get("username"),"project_directory":request.get("project_directory")})
        except ValueError as error: raise ZeusScreeningError("profile_invalid") from error

    @staticmethod
    def _unpack_plan(value: tuple) -> tuple[Path,dict[str,Any],str,dict[str,str],str,dict[str,str]]:
        # The five-item form is retained only as a test seam for older fake
        # coordinators; the production planner always returns the full bound
        # prepared-file map and submission key.
        if len(value)==5:
            campaign,manifest,commit,legacy_digest,files=value
            return campaign,manifest,commit,{"test-fixture":str(legacy_digest)},str(legacy_digest),files
        return value

    def _inspect(self,request:Mapping[str,object])->tuple[str,Path,dict[str,Any],str,str,dict[str,str],ZeusProfile,RemoteSmokeState]:
        if set(request)!={"campaign_id","username","project_directory"} or not isinstance(request.get("campaign_id"),str): raise ZeusScreeningError("request_invalid")
        campaign_id=str(request["campaign_id"]); profile=self._profile(request)
        campaign,manifest,commit,prepared,submission_key,files=self._unpack_plan(self._plan(campaign_id))
        local,clean=self._revision()
        if not clean or local!=commit: raise ZeusScreeningError("local_checkout_mismatch")
        relative=campaign.relative_to(self.root).as_posix()
        state=self.transport_factory(profile).inspect(campaign=relative,commit=commit,prepared_files=prepared,submission_key=submission_key,transition_files=files)
        return campaign_id,campaign,manifest,commit,submission_key,files,profile,state

    def status(self,request:Mapping[str,object],*,session_id:str) -> dict[str,object]:
        campaign_id,_,manifest,_,_,_,_,state=self._inspect(request)
        validation="valid" if state.lifecycle in {"ready_to_prepare_screen","screen_prepared"} else "invalid" if state.lifecycle=="outputs_invalid" else "not_ready"
        action={"queued":"wait","running":"wait","awaiting_outputs":"wait","held_attention":"inspect_on_zeus","failed":"inspect_on_zeus","outputs_invalid":"inspect_on_zeus","unknown":"inspect_on_zeus","ready_to_prepare_screen":"review_screening_preparation","screen_prepared":"none"}[state.lifecycle]
        scheduler_state=state.lifecycle if state.lifecycle in {"queued","running","held_attention"} else "completed_success" if state.lifecycle in {"awaiting_outputs","ready_to_prepare_screen","screen_prepared","outputs_invalid"} else "completed_failed" if state.lifecycle=="failed" else "unknown"
        return {"source":"zeus","queried_at":datetime.now(timezone.utc).isoformat(),"campaign":{"id":campaign_id,"name":manifest["name"],"stage":"screen" if state.lifecycle=="screen_prepared" else "smoke"},"submission":{"job_id":state.job_id},"scheduler":{"state":scheduler_state,"raw_state":state.raw_state,"exit_status":state.exit_status},"validation":{"status":validation,"points":[dict(row) for row in state.points],"artifact_count":state.artifact_count},"lifecycle":state.lifecycle,"next_action":action}

    def preview(self,request:Mapping[str,object],*,session_id:str)->dict[str,object]:
        campaign_id,campaign,manifest,commit,submission_key,files,profile,state=self._inspect(request)
        if state.lifecycle=="screen_prepared": raise ZeusScreeningError("screening_already_prepared")
        mapping={"queued":"smoke_running","running":"smoke_running","awaiting_outputs":"smoke_outputs_pending","held_attention":"smoke_held","failed":"smoke_failed","outputs_invalid":"smoke_outputs_invalid","unknown":"smoke_status_unknown"}
        if state.lifecycle!="ready_to_prepare_screen": raise ZeusScreeningError(mapping.get(state.lifecycle,"smoke_status_unknown"))
        smoke_digest=hashlib.sha256(json.dumps([dict(row) for row in state.points],sort_keys=True).encode()).hexdigest()
        _,_,_,prepared,_,_=self._unpack_plan(self._plan(campaign_id))
        expires_at = self.clock() + TOKEN_LIFETIME_SECONDS
        pending=_Pending(session_id,campaign_id,profile,commit,campaign.relative_to(self.root).as_posix(),state.job_id,smoke_digest,prepared,submission_key,files,secrets.token_hex(16),expires_at)
        try:
            token = self._previews.add(
                pending,
                expires_at=expires_at,
                capacity=MAX_PENDING_PREVIEWS,
            )
        except OverflowError as error:
            raise ZeusScreeningError("too_many_pending_previews") from error
        return {"preview_token":token,"expires_in_seconds":TOKEN_LIFETIME_SECONDS,"campaign":{"id":campaign_id,"name":manifest["name"],"git_commit":commit},"from_stage":"smoke","to_stage":"screen","smoke":{"job_id":state.job_id,"points":[dict(row) for row in state.points],"artifact_count":state.artifact_count},"artifacts":{"create":["screen/tasks.json","jobs/02_screen.pbs"],"update":["campaign.json"]},"effects":{"prepare_screening":True,"submit_screening":False,"start_simulation":False,"overwrite_existing":False},"local_sync":{"status":"not_synchronized"}}

    def confirm(self,request:Mapping[str,object],*,session_id:str)->dict[str,object]:
        if set(request)!={"preview_token"} or not isinstance(request.get("preview_token"),str): raise ZeusScreeningError("request_invalid")
        token=str(request["preview_token"])
        with self._confirm_lock:
            record = self._previews.get(token)
            pending = record.value if record is not None else None
            if pending is None or not secrets.compare_digest(pending.session_id,session_id): raise ZeusScreeningError("confirmation_invalid")
            if pending.result is not None: return dict(pending.result)
            if self.clock()>pending.expires_at:
                self._previews.pop(token)
                raise ZeusScreeningError("confirmation_expired")
            campaign,_,commit,prepared,submission_key,files=self._unpack_plan(self._plan(pending.campaign_id)); local,clean=self._revision()
            if not clean or local!=commit or commit!=pending.commit or files!=pending.transition_files or prepared!=pending.prepared_files or submission_key!=pending.submission_key or campaign.relative_to(self.root).as_posix()!=pending.campaign_relative: raise ZeusScreeningError("local_files_changed")
            state=self.transport_factory(pending.profile).prepare(campaign=pending.campaign_relative,commit=commit,prepared_files=prepared,submission_key=submission_key,transition_files=files,smoke_digest=pending.smoke_digest,nonce=pending.nonce)
            if state.lifecycle!="screen_prepared": raise ZeusScreeningError("transition_outcome_unknown")
            result={"status":"screening_prepared","campaign_id":pending.campaign_id,"stage":"screen","artifacts":{"created":2,"updated":1},"submitted_to_zeus":False,"simulation_started":False,"local_sync":{"status":"not_synchronized"}}
            self._previews.replace(token,replace(pending,result=result))
            return result


class PinnedSshScreeningTransport:
    """Fixed SSH adapter.  It can invoke only the repository's pinned receiver."""
    def __init__(self,root:Path,ssh:Path,profile:ZeusProfile,*,timeout:float=45):
        self.root=root;self.ssh=ssh;self.profile=profile;self.timeout=timeout;self.runner=PinnedSshRunner(PinnedSshPolicy.screening_preparation(root,ssh,timeout=timeout))
    def _call(self,operation:str,payload:Mapping[str,object])->RemoteSmokeState:
        if operation not in {"inspect","prepare"}: raise ZeusScreeningError("remote_response_invalid")
        pinned_operation={"inspect":ReceiverOperation.INSPECT,"prepare":ReceiverOperation.PREPARE}.get(operation)
        if pinned_operation is None:raise ZeusScreeningError("remote_response_invalid")
        try:result=self.runner.run(pinned_operation,self.profile,payload)
        except subprocess.TimeoutExpired: raise ZeusScreeningError("transition_outcome_unknown" if operation=="prepare" else "zeus_timeout") from None
        stderr=result.stderr.decode("utf-8","replace").lower()
        if result.returncode and not result.stdout:
            if "host key verification failed" in stderr: raise ZeusScreeningError("zeus_host_key_untrusted")
            if "permission denied" in stderr: raise ZeusScreeningError("zeus_authentication_required")
            if "could not resolve hostname" in stderr or "connection refused" in stderr: raise ZeusScreeningError("zeus_unreachable")
        if stderr: raise ZeusScreeningError("transition_outcome_unknown" if operation=="prepare" else "remote_response_invalid")
        try:data=json.loads(result.stdout.decode("utf-8","strict"))
        except Exception:raise ZeusScreeningError("transition_outcome_unknown" if operation=="prepare" else "remote_response_invalid") from None
        if not isinstance(data,dict):raise ZeusScreeningError("remote_response_invalid")
        if "error" in data:raise ZeusScreeningError(str(data["error"]))
        if result.returncode: raise ZeusScreeningError("transition_outcome_unknown" if operation=="prepare" else "remote_response_invalid")
        if set(data)!={"lifecycle","job_id","raw_state","exit_status","points","artifact_count"}: raise ZeusScreeningError("remote_response_invalid")
        if data.get("lifecycle") not in {"queued","running","awaiting_outputs","held_attention","failed","outputs_invalid","ready_to_prepare_screen","screen_prepared","unknown"}: raise ZeusScreeningError("remote_response_invalid")
        if not isinstance(data.get("job_id"),str) or not isinstance(data.get("raw_state"),str) or data.get("exit_status") is not None and not isinstance(data.get("exit_status"),int) or not isinstance(data.get("points"),list) or not isinstance(data.get("artifact_count"),int): raise ZeusScreeningError("remote_response_invalid")
        try:return RemoteSmokeState(str(data["lifecycle"]),str(data["job_id"]),str(data["raw_state"]),data["exit_status"],tuple(data.get("points",[])),int(data.get("artifact_count",0)))
        except Exception:raise ZeusScreeningError("remote_response_invalid") from None
    def inspect(self,**payload:object)->RemoteSmokeState:return self._call("inspect",payload)
    def prepare(self,**payload:object)->RemoteSmokeState:return self._call("prepare",payload)
