"""Explicit, at-most-once submission of the canonical refinement chain."""
from __future__ import annotations
import base64,hashlib,json,os,re,secrets,shlex,subprocess,threading,time
from dataclasses import dataclass,replace
from datetime import datetime,timezone
from pathlib import Path
from typing import Mapping,Protocol
from types import MappingProxyType
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.zeus_refinement import ZeusRefinementCoordinator,ZeusRefinementError
from workflow_api.zeus_snapshot import ZEUS_HOST,ZeusProfile

TOKEN_LIFETIME_SECONDS=300;MAX_PENDING_PREVIEWS=32;JOB_RE=re.compile(r"^\d+\[\]\.zeus-master$")
TARGETS=(3,6,9,10);FILES=tuple(f"jobs/03_refine_round_{i:02d}.pbs" for i in range(1,5))
class ZeusRefinementSubmissionError(RuntimeError):
    def __init__(self,code:str):super().__init__(code);self.code=code
@dataclass(frozen=True)
class RemoteChainState:
    status:str;branch:str|None=None;job_ids:tuple[str,...]=();nonce:str|None=None;completed_unix_s:int|None=None
@dataclass(frozen=True)
class PreparedRefinementChainPlan:
    campaign_id:str;profile:ZeusProfile;campaign:Path;commit:str
    refine_files:Mapping[str,str];chain_key:str;screen_digest:str;screening_submission_key:str
    _manifest_json:str
    @property
    def manifest(self)->dict[str,object]:return json.loads(self._manifest_json)
class ChainTransport(Protocol):
    def inspect(self,**payload:object)->RemoteChainState:...
    def submit(self,**payload:object)->RemoteChainState:...
@dataclass(frozen=True)
class _Pending:
    session_id:str;campaign_id:str;profile:ZeusProfile;commit:str;relative:str;files:Mapping[str,str];chain_key:str;nonce:str;expires:float;result:Mapping[str,object]|None=None;terminal_error:str|None=None

class ZeusRefinementSubmissionCoordinator:
    def __init__(self,repository_root:Path,ssh_executable:Path,git_executable:Path,*,clock=time.time,token_factory=None,transport_factory=None):
        self.root=repository_root.resolve(strict=True);self.ssh=ssh_executable.resolve(strict=True);self.git=git_executable.resolve(strict=True);self.clock=clock
        self.transport_factory=transport_factory or (lambda p:PinnedSshRefinementSubmissionTransport(self.root,self.ssh,p));self._previews=PreviewRegistry[_Pending](clock=clock,token_factory=token_factory);self._confirm=threading.Lock()
    @staticmethod
    def _profile(request):
        try:return ZeusProfile.parse({"username":request.get("username"),"project_directory":request.get("project_directory")})
        except ValueError as error:raise ZeusRefinementSubmissionError("profile_invalid") from error
    def prepare_chain_plan(self,request)->PreparedRefinementChainPlan:
        if set(request)!={"campaign_id","username","project_directory"} or not isinstance(request.get("campaign_id"),str):raise ZeusRefinementSubmissionError("request_invalid")
        profile=self._profile(request);coordinator=ZeusRefinementCoordinator(self.root,self.ssh,self.git)
        try:
            evidence=coordinator.inspect_evidence(request);campaign_id,plan,state=evidence.campaign_id,evidence.canonical_plan,evidence.state
        except ZeusRefinementError as error:raise ZeusRefinementSubmissionError(error.code) from error
        if state.lifecycle!="refinement_prepared":raise ZeusRefinementSubmissionError("refinement_not_prepared")
        campaign,manifest,remote_manifest,commit,_,_,screen_digest,screening_key=plan;rows=[dict(x) for x in state.rows]
        from workflow_api.mot_2d_plan import render_refine_transition
        rendered=render_refine_transition(remote_manifest,campaign,self.root,rows);files={name:hashlib.sha256(rendered[name]).hexdigest() for name in (*FILES,"campaign.json","screening_candidates.json","refine/tasks.json","jobs/03_submit_refinement_chain.sh")}
        key=hashlib.sha256(json.dumps({"campaign":campaign.relative_to(self.root).as_posix(),"commit":commit,"files":files,"screen_digest":screen_digest,"screening_key":screening_key},sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return PreparedRefinementChainPlan(campaign_id,profile,campaign,commit,MappingProxyType(files),key,screen_digest,screening_key,json.dumps(manifest,sort_keys=True,separators=(",",":")))
    def _plan(self,request):
        plan=self.prepare_chain_plan(request)
        return plan.campaign_id,plan.profile,plan.campaign,plan.manifest,plan.commit,dict(plan.refine_files),plan.chain_key,plan.screen_digest,plan.screening_submission_key
    def preview(self,request,*,session_id):
        campaign_id,profile,campaign,manifest,commit,files,key,screen_digest,screening_key=self._plan(request);relative=campaign.relative_to(self.root).as_posix()
        state=self.transport_factory(profile).inspect(campaign=relative,commit=commit,refine_files=files,chain_key=key,screen_digest=screen_digest,screening_submission_key=screening_key,nonce=None)
        if state.status=="submitted":raise ZeusRefinementSubmissionError("refinement_chain_already_submitted")
        if state.status=="partial":raise ZeusRefinementSubmissionError("refinement_chain_partially_submitted")
        if state.status=="ambiguous":raise ZeusRefinementSubmissionError("refinement_submission_outcome_unknown")
        if state.status!="eligible" or not state.branch:raise ZeusRefinementSubmissionError("remote_response_invalid")
        expires=self.clock()+TOKEN_LIFETIME_SECONDS;pending=_Pending(session_id,campaign_id,profile,commit,relative,files,key,secrets.token_hex(16),expires)
        try:token=self._previews.add(pending,expires_at=expires,capacity=MAX_PENDING_PREVIEWS)
        except OverflowError as error:raise ZeusRefinementSubmissionError("too_many_pending_previews") from error
        tasks=len(manifest["s0_values"])*3;rounds=[]
        for index,(target,file) in enumerate(zip(TARGETS,FILES),1):rounds.append({"round":index,"file":file,"cumulative_target":target,"kind":"array","task_count":tasks,"array_throttle":3,"queue":"zeus_combined_q","cores_per_task":200,"memory_per_task_bytes":68719476736,"walltime_seconds":72000,"depends_on":None if index==1 else index-1})
        return {"preview_token":token,"expires_in_seconds":TOKEN_LIFETIME_SECONDS,"campaign":{"id":campaign_id,"name":manifest["name"],"git_commit":commit,"s0_values":manifest["s0_values"]},"stage":{"id":"refine","label":"Refinement"},"chain":{"dependency":"afterok","rounds":rounds},"remote":{"host":ZEUS_HOST,"project_directory":profile.project_directory,"commit":commit,"branch":state.branch,"dirty":False},"effects":{"submit_refinement_chain":True,"start_simulation":True,"submit_later_stages":False,"modify_files":False},"local_sync":{"status":"not_synchronized"}}
    def status(self,request):
        campaign_id,profile,campaign,manifest,commit,files,key,screen_digest,screening_key=self._plan(request);state=self.transport_factory(profile).inspect(campaign=campaign.relative_to(self.root).as_posix(),commit=commit,refine_files=files,chain_key=key,screen_digest=screen_digest,screening_submission_key=screening_key,nonce=None)
        public={"eligible":"not_submitted","submitted":"submitted","partial":"partial","ambiguous":"outcome_unknown"}.get(state.status)
        if public is None:raise ZeusRefinementSubmissionError("remote_response_invalid")
        rounds=[]
        for index in range(1,5):
            job=state.job_ids[index-1] if index<=len(state.job_ids) else None
            unresolved=state.status=="ambiguous" and len(state.job_ids)<4 and index==len(state.job_ids)+1
            rounds.append({"round":index,"state":"submitted" if job else "unknown" if unresolved else "not_submitted","job_id":job,"depends_on_job_id":None if index==1 or not (job or unresolved) else state.job_ids[index-2]})
        action={"eligible":"review_submission","submitted":"none","partial":"inspect_zeus","ambiguous":"inspect_zeus"}[state.status]
        return {"source":"zeus","queried_at":datetime.now(timezone.utc).isoformat(),"campaign":{"id":campaign_id,"name":manifest["name"],"stage":"refine"},"chain":{"status":public,"dependency":"afterok","rounds":rounds},"next_action":action,"local_sync":{"status":"not_synchronized"}}
    def confirm(self,request,*,session_id):
        if set(request)!={"preview_token"} or not isinstance(request.get("preview_token"),str):raise ZeusRefinementSubmissionError("request_invalid")
        token=request["preview_token"]
        with self._confirm:
            record=self._previews.get(token);pending=record.value if record is not None else None
            if pending is None or not secrets.compare_digest(pending.session_id,session_id):raise ZeusRefinementSubmissionError("confirmation_invalid")
            if pending.result is not None:return dict(pending.result)
            if pending.terminal_error is not None:raise ZeusRefinementSubmissionError(pending.terminal_error)
            if self.clock()>pending.expires:raise ZeusRefinementSubmissionError("confirmation_expired")
            plan=self._plan({"campaign_id":pending.campaign_id,"username":pending.profile.username,"project_directory":pending.profile.project_directory});_,profile,campaign,_,commit,files,key,screen_digest,screening_key=plan
            if commit!=pending.commit or files!=pending.files or key!=pending.chain_key or campaign.relative_to(self.root).as_posix()!=pending.relative:raise ZeusRefinementSubmissionError("local_files_changed")
            try:state=self.transport_factory(profile).submit(campaign=pending.relative,commit=commit,refine_files=files,chain_key=key,screen_digest=screen_digest,screening_submission_key=screening_key,nonce=pending.nonce)
            except ZeusRefinementSubmissionError as error:
                if error.code in {"refinement_submission_outcome_unknown","refinement_already_started","remote_response_invalid"}:self._previews.replace(token,replace(pending,terminal_error=error.code))
                raise
            if state.status!="submitted" or len(state.job_ids)!=4 or len(set(state.job_ids))!=4 or state.nonce!=pending.nonce or not isinstance(state.completed_unix_s,int) or isinstance(state.completed_unix_s,bool) or not 0<=state.completed_unix_s<=253402300799:
                self._previews.replace(token,replace(pending,terminal_error="refinement_submission_outcome_unknown"));raise ZeusRefinementSubmissionError("refinement_submission_outcome_unknown")
            try:submitted_at=datetime.fromtimestamp(state.completed_unix_s,tz=timezone.utc).isoformat()
            except (OSError,OverflowError,ValueError):
                self._previews.replace(token,replace(pending,terminal_error="refinement_submission_outcome_unknown"));raise ZeusRefinementSubmissionError("refinement_submission_outcome_unknown") from None
            result={"status":"submitted","campaign_id":pending.campaign_id,"stage":"refine","chain":{"status":"submitted","rounds":[{"round":i,"job_id":job,"depends_on_job_id":None if i==1 else state.job_ids[i-2]} for i,job in enumerate(state.job_ids,1)]},"submitted_at":submitted_at,"local_sync":{"status":"not_synchronized"}}
            self._previews.replace(token,replace(pending,result=result))
            return result

class PinnedSshRefinementSubmissionTransport:
    def __init__(self,root,ssh,profile,*,timeout=150):self.root=root;self.ssh=ssh;self.profile=profile;self.timeout=timeout
    def _call(self,operation,payload):
        receiver=Path(__file__).with_name("zeus_refinement_submission_remote.py").read_bytes();encoded=base64.urlsafe_b64encode(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).decode();script=base64.urlsafe_b64encode(receiver).decode();wrapper="import base64,sys;code=base64.urlsafe_b64decode(sys.argv[1]);sys.argv=sys.argv[2:];exec(compile(code,'<refine-submit>','exec'),{'__name__':'__main__'})";remote=shlex.join(("python3","-c",wrapper,script,operation,self.profile.username,self.profile.project_directory,encoded));argv=[str(self.ssh),"-F","none","-T","-o","BatchMode=yes","-o","PasswordAuthentication=no","-o","KbdInteractiveAuthentication=no","-o","StrictHostKeyChecking=yes","-o","ForwardAgent=no","-o","ClearAllForwardings=yes",f"{self.profile.username}@{ZEUS_HOST}",remote]
        try:r=subprocess.run(argv,cwd=self.root,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=self.timeout,check=False)
        except subprocess.TimeoutExpired:raise ZeusRefinementSubmissionError("refinement_submission_outcome_unknown" if operation=="submit" else "zeus_timeout") from None
        if r.returncode or r.stderr:raise ZeusRefinementSubmissionError("refinement_submission_outcome_unknown" if operation=="submit" else "remote_response_invalid")
        try:data=json.loads(r.stdout)
        except Exception:raise ZeusRefinementSubmissionError("refinement_submission_outcome_unknown" if operation=="submit" else "remote_response_invalid") from None
        if not isinstance(data,dict):raise ZeusRefinementSubmissionError("remote_response_invalid")
        if "error" in data:raise ZeusRefinementSubmissionError(str(data["error"]))
        if set(data)!={"status","branch","job_ids","nonce","completed_unix_s"}:raise ZeusRefinementSubmissionError("remote_response_invalid")
        status=data["status"];ids=data["job_ids"]
        if status not in {"eligible","submitted","partial","ambiguous"} or not isinstance(data["branch"],str) or not isinstance(ids,list) or any(not isinstance(x,str) or not JOB_RE.fullmatch(x) for x in ids):raise ZeusRefinementSubmissionError("remote_response_invalid")
        nonce=data["nonce"];stamp=data["completed_unix_s"]
        if nonce is not None and (not isinstance(nonce,str) or not re.fullmatch(r"[0-9a-f]{32}",nonce)):raise ZeusRefinementSubmissionError("remote_response_invalid")
        if stamp is not None and (not isinstance(stamp,int) or isinstance(stamp,bool) or stamp<0):raise ZeusRefinementSubmissionError("remote_response_invalid")
        if not data["branch"] or len(data["branch"])>256 or not data["branch"].isprintable():raise ZeusRefinementSubmissionError("remote_response_invalid")
        coherent=(status=="eligible" and not ids and nonce is None and stamp is None) or (status=="submitted" and len(ids)==4 and len(set(ids))==4 and nonce is not None and stamp is not None) or (status=="partial" and 0<len(ids)<4 and len(set(ids))==len(ids) and nonce is None and stamp is None) or (status=="ambiguous" and len(ids)<=4 and len(set(ids))==len(ids) and stamp is None)
        if not coherent:raise ZeusRefinementSubmissionError("remote_response_invalid")
        return RemoteChainState(status,data["branch"],tuple(ids),nonce,stamp)
    def inspect(self,**payload):return self._call("inspect",payload)
    def submit(self,**payload):return self._call("submit",payload)
