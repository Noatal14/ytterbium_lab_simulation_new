"""Guarded Screening completion and Refinement preparation coordinator."""
from __future__ import annotations
import base64,hashlib,json,os,re,secrets,shlex,subprocess,threading,time
from dataclasses import dataclass,replace
from datetime import datetime,timezone
from pathlib import Path
from typing import Mapping,Protocol,Any

from workflow_api.discovery import build_registry
from workflow_api.mot_2d_plan import render_campaign_files,render_screen_transition,render_refine_transition
from workflow_api.zeus_snapshot import ZEUS_HOST,ZeusProfile
from workflow_api.zeus_transfer import CampaignArtifactPlanner,ZeusPreparationError,_load_manifest
from workflow_api.zeus_submission import RepositoryRevisionService

TOKEN_LIFETIME_SECONDS=300;MAX_PENDING_PREVIEWS=32
class ZeusRefinementError(RuntimeError):
    def __init__(self,code:str):super().__init__(code);self.code=code

@dataclass(frozen=True)
class RemoteScreenState:
    lifecycle:str;job_id:str;raw_state:str;exit_status:int|None;task_count:int;counts:Mapping[str,int];rows:tuple[Mapping[str,Any],...]=();branch:str|None=None

class RefinementTransport(Protocol):
    def inspect(self,**payload:object)->RemoteScreenState:...
    def prepare(self,**payload:object)->RemoteScreenState:...

@dataclass(frozen=True)
class _Pending:
    session_id:str;campaign_id:str;profile:ZeusProfile;commit:str;campaign_relative:str;rows_digest:str;screening_key:str;refine_files:Mapping[str,str];nonce:str;expires_at:float;result:Mapping[str,object]|None=None

class ZeusRefinementCoordinator:
    def __init__(self,repository_root:Path,ssh_executable:Path,git_executable:Path,*,clock=time.time,transport_factory=None):
        self.root=repository_root.resolve(strict=True);self.ssh=ssh_executable.resolve(strict=True);self.git=git_executable.resolve(strict=True);self.clock=clock
        self.transport_factory=transport_factory or (lambda profile:PinnedSshRefinementTransport(self.root,self.ssh,profile));self._pending={};self._lock=threading.RLock();self._confirm_lock=threading.Lock()
    @staticmethod
    def _profile(request):
        try:return ZeusProfile.parse({"username":request.get("username"),"project_directory":request.get("project_directory")})
        except ValueError as error:raise ZeusRefinementError("profile_invalid") from error
    def _revision(self):
        try:
            revision=RepositoryRevisionService(self.root,self.git).inspect();return revision.commit,revision.clean
        except Exception as error:raise ZeusRefinementError(getattr(error,"code","local_repository_unavailable")) from error
    def _plan(self,campaign_id:str):
        entry=build_registry(self.root).get(campaign_id)
        if entry is None or entry.family!="mot_2d":raise ZeusRefinementError("campaign_not_found")
        try:manifest=_load_manifest(entry.manifest);campaign=entry.manifest.parent;artifact_plan=CampaignArtifactPlanner(self.root).plan(campaign);selected,commit=artifact_plan.files,artifact_plan.commit;initial=render_campaign_files(manifest,campaign,self.root);screen=render_screen_transition(manifest,campaign,self.root)
        except Exception as error:raise ZeusRefinementError("campaign_not_canonical") from error
        if manifest.get("stage")!="smoke" or entry.manifest.read_bytes()!=initial["campaign.json"]:raise ZeusRefinementError("campaign_not_canonical")
        prepared={path:item[1] for path,item in selected.items()};relative=campaign.relative_to(self.root).as_posix();screen_hashes={name:hashlib.sha256(content).hexdigest() for name,content in screen.items()};screen_digest=hashlib.sha256(json.dumps(screen_hashes,sort_keys=True).encode()).hexdigest();screening_key=hashlib.sha256(json.dumps({"campaign":relative,"commit":commit,"screen_manifest":screen_hashes["campaign.json"],"screen_pbs":screen_hashes["jobs/02_screen.pbs"],"transition":screen_digest},sort_keys=True,separators=(",",":")).encode()).hexdigest();remote_manifest=json.loads(screen["campaign.json"])
        return campaign,manifest,remote_manifest,commit,prepared,screen_hashes,screen_digest,screening_key
    def _inspect(self,request):
        if set(request)!={"campaign_id","username","project_directory"} or not isinstance(request.get("campaign_id"),str):raise ZeusRefinementError("request_invalid")
        profile=self._profile(request);plan=self._plan(str(request["campaign_id"]));campaign,_,_,commit,prepared,screen,screen_digest,key=plan;local,clean=self._revision()
        if not clean or local!=commit:raise ZeusRefinementError("local_checkout_mismatch")
        state=self.transport_factory(profile).inspect(campaign=campaign.relative_to(self.root).as_posix(),commit=commit,prepared_files=prepared,screen_files=screen,screen_digest=screen_digest,screening_submission_key=key)
        expected_tasks=len(plan[1]["s0_values"])*3;expected_trials=expected_tasks*17;count_keys={"queued","running","held","succeeded","failed"};valid_lifecycles={"ready_to_prepare_refinement","refinement_prepared"};terminal_lifecycles=valid_lifecycles|{"awaiting_outputs","outputs_invalid"}
        if state.task_count!=expected_tasks or set(state.counts)!=count_keys or any(not isinstance(value,int) or isinstance(value,bool) or value<0 for value in state.counts.values()):raise ZeusRefinementError("remote_response_invalid")
        coherent=sum(state.counts.values())==expected_tasks and (state.lifecycle not in terminal_lifecycles or state.counts["succeeded"]==expected_tasks and state.exit_status==0 and state.raw_state in {"F","X"}) and (state.lifecycle!="screen_running" or state.counts["running"]>0) and (state.lifecycle!="screen_queued" or state.counts["queued"]>0) and (state.lifecycle!="screen_held" or state.counts["held"]>0) and (state.lifecycle!="screen_failed" or state.counts["failed"]>0)
        if not coherent or state.lifecycle in valid_lifecycles and len(state.rows)!=expected_trials or state.lifecycle not in {"screen_queued","screen_running","screen_held","screen_failed","screen_status_unknown",*terminal_lifecycles}:raise ZeusRefinementError("remote_response_invalid")
        return str(request["campaign_id"]),profile,plan,state
    @staticmethod
    def _scheduler(state):
        mapping={"screen_queued":"queued","screen_running":"running","screen_held":"held","screen_failed":"completed_failed","screen_status_unknown":"unknown","awaiting_outputs":"completed_success","outputs_invalid":"completed_success","ready_to_prepare_refinement":"completed_success","refinement_prepared":"completed_success"}
        return mapping.get(state.lifecycle,"unknown")
    def status(self,request):
        campaign_id,_,plan,state=self._inspect(request);_,manifest,_,_,_,_,_,_=plan;valid=state.lifecycle in {"ready_to_prepare_refinement","refinement_prepared"};invalid=state.lifecycle=="outputs_invalid";expected=len(manifest["s0_values"])*3*17
        actions={"ready_to_prepare_refinement":"review_refinement_preparation","refinement_prepared":"none","screen_held":"inspect_zeus","screen_failed":"inspect_zeus","screen_status_unknown":"inspect_zeus"}
        return {"source":"zeus","queried_at":datetime.now(timezone.utc).isoformat(),"campaign":{"id":campaign_id,"name":manifest["name"],"stage":"refine" if state.lifecycle=="refinement_prepared" else "screen"},"submission":{"job_id":state.job_id},"scheduler":{"state":self._scheduler(state),"raw_state":state.raw_state,"exit_status":state.exit_status,"task_count":state.task_count,"counts":dict(state.counts)},"validation":{"status":"valid" if valid else "invalid" if invalid else "not_ready","completed_trials":expected if valid else 0,"expected_trials":expected,"candidate_count":len(manifest["s0_values"])*3 if valid else 0},"lifecycle":state.lifecycle,"next_action":actions.get(state.lifecycle,"wait")}
    def preview(self,request,*,session_id:str):
        campaign_id,profile,plan,state=self._inspect(request);campaign,manifest,remote_manifest,commit,_,_,_,key=plan
        blockers={"screen_queued":"screen_queued","screen_running":"screen_running","screen_held":"screen_held","screen_failed":"screen_failed","screen_status_unknown":"screen_status_unknown","awaiting_outputs":"screen_outputs_pending","outputs_invalid":"screen_outputs_invalid","refinement_prepared":"refinement_already_prepared"}
        if state.lifecycle!="ready_to_prepare_refinement":raise ZeusRefinementError(blockers.get(state.lifecycle,"remote_response_invalid"))
        rows=[dict(row) for row in state.rows];files=render_refine_transition(remote_manifest,campaign,self.root,rows);hashes={name:hashlib.sha256(content).hexdigest() for name,content in files.items()};rows_digest=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest();token=secrets.token_urlsafe(32);pending=_Pending(session_id,campaign_id,profile,commit,campaign.relative_to(self.root).as_posix(),rows_digest,key,hashes,secrets.token_hex(16),self.clock()+TOKEN_LIFETIME_SECONDS)
        with self._lock:
            self._pending={k:v for k,v in self._pending.items() if v.expires_at>=self.clock()}
            if len(self._pending)>=MAX_PENDING_PREVIEWS:raise ZeusRefinementError("too_many_pending_previews")
            self._pending[token]=pending
        candidates=[]
        selected=json.loads(files["screening_candidates.json"])
        for s0_rows in selected.values():
            for rank,row in enumerate(s0_rows,1):candidates.append({"s0":row["s0"],"rank":rank,"detuning_gamma":row["detuning_gamma"],"magnet_radius_m":row["magnet_radius"],"mean_conditional_efficiency":row["mean_conditional_efficiency"],"source":row["source"]})
        create=["screening_candidates.json","refine/tasks.json",*[f"jobs/03_refine_round_{index:02d}.pbs" for index in range(1,5)],"jobs/03_submit_refinement_chain.sh"]
        fixed=manifest["fixed_design"];return {"preview_token":token,"expires_in_seconds":TOKEN_LIFETIME_SECONDS,"campaign":{"id":campaign_id,"name":manifest["name"],"git_commit":commit,"s0_values":manifest["s0_values"]},"from_stage":"screen","to_stage":"refine","bounds":{"detuning_gamma":{"low":fixed["detuning_bounds_gamma"][0],"high":fixed["detuning_bounds_gamma"][1]},"magnet_radius_m":{"low":fixed["magnet_radius_bounds_m"][0],"high":fixed["magnet_radius_bounds_m"][1]}},"screening":{"job_id":state.job_id,"completed_trials":len(rows),"expected_trials":len(manifest["s0_values"])*51,"candidates":candidates},"artifacts":{"create":create,"update":["campaign.json"]},"effects":{"prepare_refinement":True,"submit_refinement":False,"start_simulation":False,"overwrite_existing":False},"local_sync":{"status":"not_synchronized"}}
    def confirm(self,request,*,session_id:str):
        if set(request)!={"preview_token"} or not isinstance(request.get("preview_token"),str):raise ZeusRefinementError("request_invalid")
        token=str(request["preview_token"])
        with self._confirm_lock:
            with self._lock:pending=self._pending.get(token)
            if pending is None or not secrets.compare_digest(pending.session_id,session_id):raise ZeusRefinementError("confirmation_invalid")
            if pending.result is not None:return dict(pending.result)
            if self.clock()>pending.expires_at:raise ZeusRefinementError("confirmation_expired")
            _,profile,plan,state=self._inspect({"campaign_id":pending.campaign_id,"username":pending.profile.username,"project_directory":pending.profile.project_directory});campaign,_,remote_manifest,commit,prepared,screen,screen_digest,key=plan;rows=[dict(row) for row in state.rows];files=render_refine_transition(remote_manifest,campaign,self.root,rows);hashes={name:hashlib.sha256(content).hexdigest() for name,content in files.items()};digest=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
            if state.lifecycle!="ready_to_prepare_refinement" or commit!=pending.commit or digest!=pending.rows_digest or key!=pending.screening_key or hashes!=pending.refine_files:raise ZeusRefinementError("local_files_changed")
            result_state=self.transport_factory(profile).prepare(campaign=pending.campaign_relative,commit=commit,prepared_files=prepared,screen_files=screen,screen_digest=screen_digest,screening_submission_key=key,rows_digest=digest,refine_files=hashes,nonce=pending.nonce)
            if result_state.lifecycle!="refinement_prepared":raise ZeusRefinementError("transition_outcome_unknown")
            result={"status":"refinement_prepared","campaign_id":pending.campaign_id,"stage":"refine","artifacts":{"created":7,"updated":1},"submitted_to_zeus":False,"simulation_started":False,"local_sync":{"status":"not_synchronized"}}
            with self._lock:self._pending[token]=replace(pending,result=result)
            return result

class PinnedSshRefinementTransport:
    def __init__(self,root:Path,ssh:Path,profile:ZeusProfile,*,timeout=60):self.root=root;self.ssh=ssh;self.profile=profile;self.timeout=timeout
    def _call(self,operation,payload):
        receiver=Path(__file__).with_name("zeus_refinement_remote.py").read_bytes();encoded=base64.urlsafe_b64encode(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).decode();script=base64.urlsafe_b64encode(receiver).decode();wrapper="import base64,sys;code=base64.urlsafe_b64decode(sys.argv[1]);sys.argv=sys.argv[2:];exec(compile(code,'<refine>','exec'),{'__name__':'__main__'})";remote=shlex.join(("python3","-c",wrapper,script,operation,self.profile.username,self.profile.project_directory,encoded));argv=[str(self.ssh),"-F","none","-T","-o","BatchMode=yes","-o","PasswordAuthentication=no","-o","KbdInteractiveAuthentication=no","-o","StrictHostKeyChecking=yes","-o","ForwardAgent=no","-o","ClearAllForwardings=yes",f"{self.profile.username}@{ZEUS_HOST}",remote]
        try:r=subprocess.run(argv,cwd=self.root,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=self.timeout,check=False)
        except subprocess.TimeoutExpired:raise ZeusRefinementError("transition_outcome_unknown" if operation=="prepare" else "zeus_timeout") from None
        if r.returncode or r.stderr:raise ZeusRefinementError("transition_outcome_unknown" if operation=="prepare" else "remote_response_invalid")
        try:data=json.loads(r.stdout)
        except Exception:raise ZeusRefinementError("remote_response_invalid") from None
        if "error" in data:raise ZeusRefinementError(data["error"])
        required={"lifecycle","job_id","raw_state","exit_status","task_count","counts","rows","branch"}
        if not isinstance(data,dict) or set(data)!=required:raise ZeusRefinementError("remote_response_invalid")
        counts=data.get("counts");allowed_lifecycles={"screen_queued","screen_running","screen_held","screen_failed","screen_status_unknown","awaiting_outputs","outputs_invalid","ready_to_prepare_refinement","refinement_prepared"}
        if data.get("lifecycle") not in allowed_lifecycles or not re.fullmatch(r"\d+\[\]\.zeus-master",str(data.get("job_id",""))) or not isinstance(data.get("raw_state"),str) or not isinstance(data.get("task_count"),int) or isinstance(data.get("task_count"),bool) or data["task_count"]<1 or not isinstance(counts,dict) or set(counts)!={"queued","running","held","succeeded","failed"} or any(not isinstance(value,int) or isinstance(value,bool) or value<0 for value in counts.values()) or not isinstance(data.get("rows"),list) or not isinstance(data.get("branch"),str) or not data["branch"] or not data["branch"].isprintable() or data.get("exit_status") is not None and (not isinstance(data["exit_status"],int) or isinstance(data["exit_status"],bool)):raise ZeusRefinementError("remote_response_invalid")
        return RemoteScreenState(data["lifecycle"],data["job_id"],data["raw_state"],data["exit_status"],data["task_count"],data["counts"],tuple(data["rows"]),data["branch"])
    def inspect(self,**payload):return self._call("inspect",payload)
    def prepare(self,**payload):return self._call("prepare",payload)
