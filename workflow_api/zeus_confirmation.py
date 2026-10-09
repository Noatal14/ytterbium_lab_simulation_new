"""Guarded Refinement completion and Confirmation preparation."""
from __future__ import annotations
import base64,hashlib,json,math,os,re,secrets,shlex,subprocess,threading,time
from dataclasses import dataclass,replace
from datetime import datetime,timezone
from pathlib import Path
from typing import Any,Mapping
from workflow_api.zeus_refinement_submission import ZeusRefinementSubmissionCoordinator,ZeusRefinementSubmissionError
from workflow_api.zeus_snapshot import ZEUS_HOST,ZeusProfile
from workflow_api.mot_2d_plan import render_confirmation_transition

TOKEN_LIFETIME_SECONDS=300
class ZeusConfirmationError(RuntimeError):
    def __init__(self,code):super().__init__(code);self.code=code
@dataclass(frozen=True)
class RemoteRefineState:
    lifecycle:str;rounds:tuple[Mapping[str,Any],...];rows:tuple[Mapping[str,Any],...];branch:str;receipt:Mapping[str,Any]|None=None
@dataclass(frozen=True)
class _Pending:
    session_id:str;campaign_id:str;profile:ZeusProfile;commit:str;relative:str;chain_key:str;rows_digest:str;files:Mapping[str,str];nonce:str;expires:float;result:Mapping[str,object]|None=None
class ZeusConfirmationCoordinator:
    def __init__(self,root:Path,ssh:Path,git:Path,*,clock=time.time,transport_factory=None):self.root=root.resolve(strict=True);self.ssh=ssh.resolve(strict=True);self.git=git.resolve(strict=True);self.clock=clock;self.transport_factory=transport_factory or (lambda p:PinnedSshConfirmationTransport(self.root,self.ssh,p));self._pending={};self._lock=threading.RLock();self._confirm=threading.Lock()
    def _plan(self,request):
        try:
            base=ZeusRefinementSubmissionCoordinator(self.root,self.ssh,self.git);prepared=base.prepare_chain_plan(request);campaign_id,profile,campaign,manifest,commit,refine_files,key,screen_digest,screening_key=prepared.campaign_id,prepared.profile,prepared.campaign,prepared.manifest,prepared.commit,prepared.refine_files,prepared.chain_key,prepared.screen_digest,prepared.screening_submission_key
        except ZeusRefinementSubmissionError as error:raise ZeusConfirmationError(error.code) from error
        return campaign_id,profile,campaign,manifest,commit,dict(refine_files),key,screen_digest,screening_key
    def _inspect(self,request):
        plan=self._plan(request);campaign_id,profile,campaign,_,commit,files,key,screen_digest,screening_key=plan
        state=self.transport_factory(profile).inspect(campaign=campaign.relative_to(self.root).as_posix(),commit=commit,refine_files=files,chain_key=key,screen_digest=screen_digest,screening_submission_key=screening_key)
        expected=len(plan[3]["s0_values"])*3
        if len(state.rounds)!=4 or not state.branch or state.lifecycle not in {"queued","running","held","failed","status_unknown","awaiting_outputs","outputs_invalid","ready_to_prepare_confirmation","confirmation_prepared"}:raise ZeusConfirmationError("remote_response_invalid")
        ids=[]
        for index,row in enumerate(state.rounds,1):
            if not isinstance(row,dict) or set(row)!={"round","job_id","depends_on_job_id","scheduler"} or row["round"]!=index or not re.fullmatch(r"\d+\[\]\.zeus-master",str(row["job_id"])) or row["job_id"] in ids or row["depends_on_job_id"]!=(ids[index-2] if index>1 else None):raise ZeusConfirmationError("remote_response_invalid")
            ids.append(row["job_id"]);scheduler=row["scheduler"]
            if not isinstance(scheduler,dict) or set(scheduler)!={"state","task_count","counts"} or scheduler["state"] not in {"queued","running","held","completed_success","completed_failed","unknown"} or scheduler["task_count"]!=expected or not isinstance(scheduler["counts"],dict) or set(scheduler["counts"])!={"queued","running","held","succeeded","failed"} or any(not isinstance(value,int) or isinstance(value,bool) or value<0 for value in scheduler["counts"].values()) or sum(scheduler["counts"].values())!=expected:raise ZeusConfirmationError("remote_response_invalid")
            counts=scheduler["counts"];coherent=(scheduler["state"]=="queued" and counts["queued"]>0) or (scheduler["state"]=="running" and counts["running"]>0) or (scheduler["state"]=="held" and counts["held"]>0) or (scheduler["state"]=="completed_success" and counts["succeeded"]==expected) or (scheduler["state"]=="completed_failed" and counts["failed"]>0) or scheduler["state"]=="unknown"
            if not coherent:raise ZeusConfirmationError("remote_response_invalid")
        valid=state.lifecycle in {"ready_to_prepare_confirmation","confirmation_prepared"}
        round_states=[row["scheduler"]["state"] for row in state.rounds]
        lifecycle_coherent=(valid or state.lifecycle in {"awaiting_outputs","outputs_invalid"}) and all(value=="completed_success" for value in round_states) or state.lifecycle=="running" and "running" in round_states or state.lifecycle=="queued" and "queued" in round_states or state.lifecycle=="held" and "held" in round_states or state.lifecycle=="failed" and "completed_failed" in round_states or state.lifecycle=="status_unknown" and "unknown" in round_states
        if not lifecycle_coherent:raise ZeusConfirmationError("remote_response_invalid")
        if valid and len(state.rows)!=len(plan[3]["s0_values"])*30 or not valid and state.rows:raise ZeusConfirmationError("remote_response_invalid")
        seen=set();per_s0={float(value):0 for value in plan[3]["s0_values"]}
        for row in state.rows:
            if not isinstance(row,dict) or set(row)!={"s0","detuning_gamma","magnet_radius","mean_conditional_efficiency","source"} or any(isinstance(row[key],bool) or not isinstance(row[key],(int,float)) or not math.isfinite(row[key]) for key in ("s0","detuning_gamma","magnet_radius","mean_conditional_efficiency")) or not isinstance(row["source"],str) or not re.fullmatch(r"refine/s0_[0-9]+p[0-9]{6}/worker[0-2]/trials/trial_[0-9]{4}\.json",row["source"]) or row["source"] in seen or float(row["s0"]) not in per_s0:raise ZeusConfirmationError("remote_response_invalid")
            seen.add(row["source"]);per_s0[float(row["s0"])]+=1
        if valid and any(count!=30 for count in per_s0.values()):raise ZeusConfirmationError("remote_response_invalid")
        return plan,state
    def status(self,request):
        plan,state=self._inspect(request);campaign_id,_,_,manifest,*_=plan;expected=len(manifest["s0_values"])*30;valid=state.lifecycle in {"ready_to_prepare_confirmation","confirmation_prepared"};invalid=state.lifecycle=="outputs_invalid"
        return {"source":"zeus","queried_at":datetime.now(timezone.utc).isoformat(),"campaign":{"id":campaign_id,"name":manifest["name"],"stage":"confirmation" if state.lifecycle=="confirmation_prepared" else "refine"},"chain":{"status":state.lifecycle,"rounds":[dict(row) for row in state.rounds]},"validation":{"status":"valid" if valid else "invalid" if invalid else "not_ready","completed_trials":expected if valid else 0,"expected_trials":expected,"candidate_count":len(manifest["s0_values"])*5 if valid else 0},"next_action":"review_confirmation_preparation" if state.lifecycle=="ready_to_prepare_confirmation" else "none" if state.lifecycle=="confirmation_prepared" else "inspect_zeus" if state.lifecycle in {"failed","held","status_unknown","outputs_invalid"} else "wait","local_sync":{"status":"not_synchronized"}}
    def preview(self,request,*,session_id):
        plan,state=self._inspect(request);campaign_id,profile,campaign,manifest,commit,_,key,_,_=plan
        if state.lifecycle!="ready_to_prepare_confirmation":raise ZeusConfirmationError({"awaiting_outputs":"refine_outputs_pending","outputs_invalid":"refine_outputs_invalid","confirmation_prepared":"confirmation_already_prepared"}.get(state.lifecycle,"refinement_chain_not_complete"))
        rows=[dict(x) for x in state.rows];rendered=render_confirmation_transition(self._remote_manifest(manifest,campaign,self.root),campaign,self.root,rows);files={name:hashlib.sha256(data).hexdigest() for name,data in rendered.items()};digest=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest();token=secrets.token_urlsafe(32);pending=_Pending(session_id,campaign_id,profile,commit,campaign.relative_to(self.root).as_posix(),key,digest,files,secrets.token_hex(16),self.clock()+TOKEN_LIFETIME_SECONDS)
        with self._lock:self._pending[token]=pending
        candidates=[];selected=json.loads(rendered["refined_candidates.json"])
        for group in selected.values():
            for rank,row in enumerate(group,1):candidates.append({"s0":row["s0"],"rank":rank,"detuning_gamma":row["detuning_gamma"],"magnet_radius_m":row["magnet_radius"],"mean_conditional_efficiency":row["mean_conditional_efficiency"],"source":row["source"]})
        fixed=manifest["fixed_design"];ids=[row["job_id"] for row in state.rounds]
        return {"preview_token":token,"expires_in_seconds":TOKEN_LIFETIME_SECONDS,"campaign":{"id":campaign_id,"name":manifest["name"],"git_commit":commit,"s0_values":manifest["s0_values"]},"from_stage":"refine","to_stage":"confirmation","bounds":{"detuning_gamma":{"low":fixed["detuning_bounds_gamma"][0],"high":fixed["detuning_bounds_gamma"][1]},"magnet_radius_m":{"low":fixed["magnet_radius_bounds_m"][0],"high":fixed["magnet_radius_bounds_m"][1]}},"refinement":{"round_job_ids":ids,"completed_trials":len(rows),"expected_trials":len(manifest["s0_values"])*30,"candidates":candidates},"artifacts":{"create":["refined_candidates.json","confirmation/tasks.json","jobs/04_confirmation.pbs"],"update":["campaign.json"]},"job":{"file":"jobs/04_confirmation.pbs","kind":"array","task_count":len(manifest["s0_values"])*5,"array_throttle":3,"queue":"zeus_combined_q","cores_per_task":200,"memory_per_task_bytes":68719476736,"walltime_seconds":36000},"effects":{"prepare_confirmation":True,"submit_confirmation":False,"start_simulation":False,"overwrite_existing":False},"local_sync":{"status":"not_synchronized"}}
    @staticmethod
    def _remote_manifest(manifest,campaign,root):
        value=json.loads(json.dumps(manifest));value["stage"]="refine";argument=campaign.relative_to(root).as_posix();count=len(value["s0_values"])*3
        value.setdefault("stages",{})["refine"]={"tasks":count,"cumulative_trial_targets":[3,6,9,10],"round_job_files":[f"{argument}/jobs/03_refine_round_{index:02d}.pbs" for index in range(1,5)],"submit_chain":f"{argument}/jobs/03_submit_refinement_chain.sh","dependency":"afterok"}
        return value
    def confirm(self,request,*,session_id):
        if set(request)!={"preview_token"} or not isinstance(request.get("preview_token"),str):raise ZeusConfirmationError("request_invalid")
        with self._confirm:
            pending=self._pending.get(request["preview_token"])
            if pending is None or not secrets.compare_digest(pending.session_id,session_id):raise ZeusConfirmationError("confirmation_invalid")
            if pending.result:return dict(pending.result)
            if self.clock()>pending.expires:raise ZeusConfirmationError("confirmation_expired")
            plan,state=self._inspect({"campaign_id":pending.campaign_id,"username":pending.profile.username,"project_directory":pending.profile.project_directory});_,profile,_,_,commit,_,key,_,_=plan;rows=[dict(x) for x in state.rows]
            if state.lifecycle!="ready_to_prepare_confirmation" or commit!=pending.commit or key!=pending.chain_key or hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()!=pending.rows_digest:raise ZeusConfirmationError("local_files_changed")
            result_state=self.transport_factory(profile).prepare(campaign=pending.relative,commit=commit,refine_files=plan[5],chain_key=key,screen_digest=plan[7],screening_submission_key=plan[8],rows_digest=pending.rows_digest,confirmation_files=pending.files,nonce=pending.nonce)
            receipt=result_state.receipt;exact={"status","nonce","chain_key","commit","rows_digest","rows","files","rounds","completed_unix_s"}
            if result_state.lifecycle!="confirmation_prepared" or not isinstance(receipt,dict) or set(receipt)!=exact or receipt.get("status")!="confirmation_prepared" or receipt.get("nonce")!=pending.nonce or receipt.get("chain_key")!=key or receipt.get("commit")!=commit or receipt.get("rows_digest")!=pending.rows_digest or receipt.get("rows")!=rows or receipt.get("files")!=pending.files or receipt.get("rounds")!=[dict(row) for row in result_state.rounds] or not isinstance(receipt.get("completed_unix_s"),int) or isinstance(receipt.get("completed_unix_s"),bool) or not 0<=receipt["completed_unix_s"]<=253402300799:raise ZeusConfirmationError("transition_outcome_unknown")
            result={"status":"confirmation_prepared","campaign_id":pending.campaign_id,"stage":"confirmation","artifacts":{"created":3,"updated":1},"submitted_to_zeus":False,"simulation_started":False,"local_sync":{"status":"not_synchronized"}};self._pending[request["preview_token"]]=replace(pending,result=result);return result

class PinnedSshConfirmationTransport:
    def __init__(self,root,ssh,profile,*,timeout=90):self.root=root;self.ssh=ssh;self.profile=profile;self.timeout=timeout
    def _call(self,operation,payload):
        receiver=Path(__file__).with_name("zeus_confirmation_remote.py").read_bytes();encoded=base64.urlsafe_b64encode(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).decode();script=base64.urlsafe_b64encode(receiver).decode();wrapper="import base64,sys;code=base64.urlsafe_b64decode(sys.argv[1]);sys.argv=sys.argv[2:];exec(compile(code,'<confirmation>','exec'),{'__name__':'__main__'})";remote=shlex.join(("python3","-c",wrapper,script,operation,self.profile.username,self.profile.project_directory,encoded))
        try:result=subprocess.run([str(self.ssh),"-F","none","-T","-o","BatchMode=yes","-o","PasswordAuthentication=no","-o","KbdInteractiveAuthentication=no","-o","StrictHostKeyChecking=yes","-o","ForwardAgent=no","-o","ClearAllForwardings=yes",f"{self.profile.username}@{ZEUS_HOST}",remote],cwd=self.root,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=self.timeout,check=False)
        except (subprocess.TimeoutExpired,OSError):raise ZeusConfirmationError("transition_outcome_unknown" if operation=="prepare" else "zeus_timeout") from None
        if result.returncode or result.stderr:raise ZeusConfirmationError("transition_outcome_unknown" if operation=="prepare" else "remote_response_invalid")
        try:data=json.loads(result.stdout)
        except Exception:raise ZeusConfirmationError("remote_response_invalid") from None
        if "error" in data:raise ZeusConfirmationError(data["error"])
        if not isinstance(data,dict) or set(data)!={"lifecycle","rounds","rows","branch","receipt"} or not isinstance(data["rounds"],list) or len(data["rounds"])!=4 or not isinstance(data["rows"],list) or not isinstance(data["branch"],str) or not data["branch"] or len(data["branch"])>256 or not data["branch"].isprintable() or data["receipt"] is not None and not isinstance(data["receipt"],dict):raise ZeusConfirmationError("remote_response_invalid")
        return RemoteRefineState(data["lifecycle"],tuple(data["rounds"]),tuple(data["rows"]),data["branch"],data["receipt"])
    def inspect(self,**payload):return self._call("inspect",payload)
    def prepare(self,**payload):return self._call("prepare",payload)
