"""Explicit at-most-once submission of the prepared 2D-MOT screening PBS."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import stat as stat_module
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
from workflow_api.zeus_snapshot import ZEUS_HOST, ZeusProfile
from workflow_api.zeus_transfer import CampaignArtifactPlanner, ZeusPreparationError, _load_manifest
from workflow_api.zeus_submission import SAFE_UNTRACKED_ROOTS, SAFE_UNTRACKED_SUFFIXES
from workflow_api.zeus_submission import RepositoryRevisionService, ZeusSubmissionError

TOKEN_LIFETIME_SECONDS=300;MAX_PENDING_PREVIEWS=32
COMMIT_RE=re.compile(r"^[0-9a-f]{40}$");JOB_RE=re.compile(r"^\d+\[\]\.zeus-master$")


class ZeusScreenSubmissionError(RuntimeError):
    def __init__(self,code:str):super().__init__(code);self.code=code


@dataclass(frozen=True)
class RemoteSubmissionState:
    status:str;branch:str|None=None;job_id:str|None=None;validated_smoke_job_id:str|None=None;nonce:str|None=None;submitted_unix_s:int|None=None


class SubmissionTransport(Protocol):
    def inspect(self,**payload:object)->RemoteSubmissionState:...
    def submit(self,**payload:object)->RemoteSubmissionState:...


@dataclass(frozen=True)
class _Pending:
    session_id:str;campaign_id:str;profile:ZeusProfile;commit:str;campaign_relative:str
    prepared_files:Mapping[str,str];transition_files:Mapping[str,str];transition_digest:str
    submission_key:str;nonce:str;expires_at:float;result:Mapping[str,object]|None=None
    terminal_error:str|None=None


class ZeusScreenSubmissionCoordinator:
    def __init__(self,repository_root:Path,ssh_executable:Path,git_executable:Path,*,clock=time.time,token_factory=None,transport_factory=None):
        self.root=repository_root.resolve(strict=True);self.ssh=ssh_executable.resolve(strict=True);self.git=git_executable.resolve(strict=True);self.clock=clock
        self.transport_factory=transport_factory or (lambda profile:PinnedSshScreenSubmissionTransport(self.root,self.ssh,profile))
        self._previews=PreviewRegistry[_Pending](clock=clock,token_factory=token_factory);self._confirm_lock=threading.Lock()

    def _revision(self)->tuple[str,bool]:
        try:
            revision=RepositoryRevisionService(self.root,self.git).inspect();return revision.commit,revision.clean
        except ZeusSubmissionError as error:raise ZeusScreenSubmissionError(error.code) from error

    def _safe_untracked_status(self,raw:bytes)->bool:
        try:
            for record in raw.split(b"\0"):
                if not record:continue
                if len(record)<4 or record[:2]!=b"??" or record[2:3]!=b" ":return False
                text=record[3:].decode("utf-8","strict");pure=Path(text)
                if pure.is_absolute() or pure.as_posix()!=text or any(part in {"",".",".."} for part in pure.parts):return False
                if not pure.parts or pure.parts[0] not in SAFE_UNTRACKED_ROOTS or pure.suffix.lower() not in SAFE_UNTRACKED_SUFFIXES:return False
                if not stat_module.S_ISREG((self.root/pure).lstat().st_mode):return False
            return True
        except (OSError,UnicodeError):return False

    def _plan(self,campaign_id:str):
        entry=build_registry(self.root).get(campaign_id)
        if entry is None or entry.family!="mot_2d":raise ZeusScreenSubmissionError("campaign_not_found")
        try:manifest=_load_manifest(entry.manifest)
        except ZeusPreparationError as error:raise ZeusScreenSubmissionError("campaign_not_canonical") from error
        campaign=entry.manifest.parent
        if manifest.get("stage")!="smoke":raise ZeusScreenSubmissionError("campaign_not_canonical")
        try:
            artifact_plan=CampaignArtifactPlanner(self.root).plan(campaign);selected,commit=artifact_plan.files,artifact_plan.commit
            initial=render_campaign_files(manifest,campaign,self.root);transition=render_screen_transition(manifest,campaign,self.root)
        except Exception as error:raise ZeusScreenSubmissionError("campaign_not_canonical") from error
        if entry.manifest.read_bytes()!=initial["campaign.json"]:raise ZeusScreenSubmissionError("campaign_not_canonical")
        prepared={path:item[1] for path,item in selected.items()};relative=campaign.relative_to(self.root).as_posix()
        transition_hashes={name:hashlib.sha256(content).hexdigest() for name,content in transition.items()}
        transition_digest=hashlib.sha256(json.dumps(transition_hashes,sort_keys=True).encode()).hexdigest()
        key=hashlib.sha256(json.dumps({"campaign":relative,"commit":commit,"screen_manifest":transition_hashes["campaign.json"],"screen_pbs":transition_hashes["jobs/02_screen.pbs"],"transition":transition_digest},sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return campaign,manifest,commit,prepared,transition_hashes,transition_digest,key

    @staticmethod
    def _profile(request:Mapping[str,object])->ZeusProfile:
        try:return ZeusProfile.parse({"username":request.get("username"),"project_directory":request.get("project_directory")})
        except ValueError as error:raise ZeusScreenSubmissionError("profile_invalid") from error

    def preview(self,request:Mapping[str,object],*,session_id:str)->dict[str,object]:
        if set(request)!={"campaign_id","username","project_directory"} or not isinstance(request.get("campaign_id"),str):raise ZeusScreenSubmissionError("request_invalid")
        campaign_id=str(request["campaign_id"]);profile=self._profile(request);campaign,manifest,commit,prepared,transition,digest,key=self._plan(campaign_id)
        local,clean=self._revision()
        if not clean or local!=commit:raise ZeusScreenSubmissionError("local_checkout_mismatch")
        relative=campaign.relative_to(self.root).as_posix();state=self.transport_factory(profile).inspect(campaign=relative,commit=commit,prepared_files=prepared,transition_files=transition,transition_digest=digest,submission_key=key,nonce=None)
        if state.status=="ambiguous":raise ZeusScreenSubmissionError("screening_submission_outcome_unknown")
        if state.status=="submitted":raise ZeusScreenSubmissionError("screening_already_submitted")
        if state.status!="eligible" or not state.branch or state.validated_smoke_job_id is None:raise ZeusScreenSubmissionError("remote_response_invalid")
        expires=self.clock()+TOKEN_LIFETIME_SECONDS
        pending=_Pending(session_id,campaign_id,profile,commit,relative,prepared,transition,digest,key,secrets.token_hex(16),expires)
        try:token=self._previews.add(pending,expires_at=expires,capacity=MAX_PENDING_PREVIEWS)
        except OverflowError as error:raise ZeusScreenSubmissionError("too_many_pending_previews") from error
        tasks=len(manifest["s0_values"])*3
        return {"preview_token":token,"expires_in_seconds":TOKEN_LIFETIME_SECONDS,"campaign":{"id":campaign_id,"name":manifest["name"],"git_commit":commit,"s0_values":manifest["s0_values"]},"stage":{"id":"screen","label":"Screening","purpose":"Run the broad paired search for each fixed s₀ value."},"job":{"file":"jobs/02_screen.pbs","kind":"array","task_count":tasks,"array_throttle":3,"queue":"zeus_combined_q","cores_per_task":200,"memory_per_task_bytes":68719476736,"walltime_seconds":86400},"remote":{"host":ZEUS_HOST,"project_directory":profile.project_directory,"commit":commit,"branch":state.branch,"dirty":False},"inputs":{"verified_count":72,"status":"ready"},"smoke":{"status":"validated","job_id":state.validated_smoke_job_id,"point_count":len(manifest["s0_values"])},"effects":{"submit_screening":True,"submit_later_stages":False,"modify_files":False},"later_stages_locked":True}

    def confirm(self,request:Mapping[str,object],*,session_id:str)->dict[str,object]:
        if set(request)!={"preview_token"} or not isinstance(request.get("preview_token"),str):raise ZeusScreenSubmissionError("request_invalid")
        token=str(request["preview_token"])
        with self._confirm_lock:
            record=self._previews.get(token);pending=record.value if record is not None else None
            if pending is None or not secrets.compare_digest(pending.session_id,session_id):raise ZeusScreenSubmissionError("confirmation_invalid")
            if pending.result is not None:return dict(pending.result)
            if pending.terminal_error is not None:raise ZeusScreenSubmissionError(pending.terminal_error)
            if self.clock()>pending.expires_at:
                self._previews.pop(token)
                raise ZeusScreenSubmissionError("confirmation_expired")
            campaign,_,commit,prepared,transition,digest,key=self._plan(pending.campaign_id);local,clean=self._revision()
            if not clean or local!=commit or commit!=pending.commit or campaign.relative_to(self.root).as_posix()!=pending.campaign_relative or prepared!=pending.prepared_files or transition!=pending.transition_files or digest!=pending.transition_digest or key!=pending.submission_key:raise ZeusScreenSubmissionError("local_files_changed")
            try:state=self.transport_factory(pending.profile).submit(campaign=pending.campaign_relative,commit=commit,prepared_files=prepared,transition_files=transition,transition_digest=digest,submission_key=key,nonce=pending.nonce)
            except ZeusScreenSubmissionError as error:
                if error.code in {
                    "screening_submission_outcome_unknown",
                    "screening_already_submitted",
                    "screening_already_started",
                    "screening_submission_record_invalid",
                }:
                    self._previews.replace(token,replace(pending,terminal_error=error.code))
                raise
            if state.status!="submitted" or state.job_id is None or state.nonce!=pending.nonce or state.submitted_unix_s is None:
                self._previews.replace(token,replace(pending,terminal_error="screening_submission_outcome_unknown"));raise ZeusScreenSubmissionError("screening_submission_outcome_unknown")
            try:submitted_at=datetime.fromtimestamp(state.submitted_unix_s,tz=timezone.utc).isoformat()
            except (OSError,OverflowError,ValueError):
                self._previews.replace(token,replace(pending,terminal_error="screening_submission_outcome_unknown"));raise ZeusScreenSubmissionError("screening_submission_outcome_unknown") from None
            result={"status":"submitted","campaign_id":pending.campaign_id,"stage":"screen","job_id":state.job_id,"submitted_at":submitted_at,"later_stages_locked":True}
            self._previews.replace(token,replace(pending,result=result))
            return result


class PinnedSshScreenSubmissionTransport:
    def __init__(self,root:Path,ssh:Path,profile:ZeusProfile,*,timeout:float=45):
        self.root=root;self.ssh=ssh;self.profile=profile;self.timeout=timeout
        self.runner=PinnedSshRunner(PinnedSshPolicy.screening_submission(root,ssh,timeout=timeout))
    def _call(self,operation:str,payload:Mapping[str,object])->RemoteSubmissionState:
        if operation not in {"inspect","submit"}:raise ZeusScreenSubmissionError("remote_response_invalid")
        pinned_operation={"inspect":ReceiverOperation.INSPECT,"submit":ReceiverOperation.SUBMIT}.get(operation)
        if pinned_operation is None:raise ZeusScreenSubmissionError("remote_response_invalid")
        try:r=self.runner.run(pinned_operation,self.profile,payload)
        except subprocess.TimeoutExpired:raise ZeusScreenSubmissionError("screening_submission_outcome_unknown" if operation=="submit" else "zeus_timeout") from None
        stderr=r.stderr.decode("utf-8","replace").lower()
        if r.returncode and not r.stdout:
            if "host key verification failed" in stderr:raise ZeusScreenSubmissionError("zeus_host_key_untrusted")
            if "permission denied" in stderr:raise ZeusScreenSubmissionError("zeus_authentication_required")
            if "could not resolve hostname" in stderr or "connection refused" in stderr:raise ZeusScreenSubmissionError("zeus_unreachable")
        if stderr:raise ZeusScreenSubmissionError("screening_submission_outcome_unknown" if operation=="submit" else "remote_response_invalid")
        try:data=json.loads(r.stdout.decode("utf-8","strict"))
        except Exception:raise ZeusScreenSubmissionError("screening_submission_outcome_unknown" if operation=="submit" else "remote_response_invalid") from None
        if not isinstance(data,dict):raise ZeusScreenSubmissionError("remote_response_invalid")
        if "error" in data:raise ZeusScreenSubmissionError(str(data["error"]))
        status=data.get("status")
        allowed={"eligible","ambiguous","submitted"}
        if r.returncode or status not in allowed:raise ZeusScreenSubmissionError("screening_submission_outcome_unknown" if operation=="submit" else "remote_response_invalid")
        expected={"eligible":{"status","branch","validated_smoke_job_id"},"ambiguous":{"status","branch","validated_smoke_job_id","nonce"},"submitted":{"status","branch","validated_smoke_job_id","version","submission_key","transition_digest","nonce","job_file","commit","created_unix_s","job_id","completed_unix_s"}}[str(status)] if operation=="inspect" else {"status","version","submission_key","transition_digest","nonce","job_file","commit","created_unix_s","job_id","completed_unix_s"}
        if set(data)!=expected:raise ZeusScreenSubmissionError("screening_submission_outcome_unknown" if operation=="submit" else "remote_response_invalid")
        branch=data.get("branch")
        if operation=="inspect" and (not isinstance(branch,str) or not branch or len(branch)>256 or not branch.isprintable()):raise ZeusScreenSubmissionError("remote_response_invalid")
        smoke_job=data.get("validated_smoke_job_id")
        if operation=="inspect" and (not isinstance(smoke_job,str) or not re.fullmatch(r"\d+(?:\[\])?\.zeus-master",smoke_job)):raise ZeusScreenSubmissionError("remote_response_invalid")
        job_id=data.get("job_id")
        if status=="submitted" and (not isinstance(job_id,str) or not JOB_RE.fullmatch(job_id)):raise ZeusScreenSubmissionError("screening_submission_outcome_unknown" if operation=="submit" else "remote_response_invalid")
        nonce=data.get("nonce");timestamp=data.get("completed_unix_s")
        if status in {"ambiguous","submitted"} and (not isinstance(nonce,str) or not re.fullmatch(r"[0-9a-f]{32}",nonce)):raise ZeusScreenSubmissionError("screening_submission_outcome_unknown" if operation=="submit" else "remote_response_invalid")
        if status=="submitted" and (not isinstance(timestamp,int) or isinstance(timestamp,bool) or not 0<=timestamp<=253402300799):raise ZeusScreenSubmissionError("screening_submission_outcome_unknown" if operation=="submit" else "remote_response_invalid")
        if status=="submitted":
            created=data.get("created_unix_s")
            expected_job=f"{payload.get('campaign')}/jobs/02_screen.pbs"
            if data.get("version")!=1 or data.get("submission_key")!=payload.get("submission_key") or data.get("transition_digest")!=payload.get("transition_digest") or data.get("job_file")!=expected_job or data.get("commit")!=payload.get("commit") or data.get("nonce")!=payload.get("nonce") or not isinstance(created,int) or isinstance(created,bool) or not 0<=created<=timestamp:
                raise ZeusScreenSubmissionError("screening_submission_outcome_unknown" if operation=="submit" else "remote_response_invalid")
        return RemoteSubmissionState(str(status),branch if isinstance(branch,str) else None,job_id,smoke_job if isinstance(smoke_job,str) else None,nonce if isinstance(nonce,str) else None,timestamp if isinstance(timestamp,int) else None)
    def inspect(self,**payload:object)->RemoteSubmissionState:return self._call("inspect",payload)
    def submit(self,**payload:object)->RemoteSubmissionState:return self._call("submit",payload)
