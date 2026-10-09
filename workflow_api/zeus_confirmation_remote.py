"""Pinned Refinement-chain inspector and no-submit Confirmation publisher."""
from __future__ import annotations
import base64,fcntl,hashlib,json,os,re,stat,subprocess,sys,time
from pathlib import Path,PurePosixPath
def fail(code,status=20):print(json.dumps({"error":code}));raise SystemExit(status)
def sha(path,limit=64*1024*1024):
    row=path.lstat()
    if not stat.S_ISREG(row.st_mode) or path.is_symlink() or row.st_size<0 or row.st_size>limit:fail("transition_conflict")
    digest=hashlib.sha256();remaining=row.st_size
    with path.open("rb") as stream:
        while remaining:
            chunk=stream.read(min(1024*1024,remaining))
            if not chunk:fail("transition_conflict")
            digest.update(chunk);remaining-=len(chunk)
        if stream.read(1):fail("transition_conflict")
    return digest.hexdigest()
def no_links(root,path):
    current=root
    for part in path.relative_to(root).parts:
        current/=part
        if current.exists() and current.is_symlink():fail("transition_conflict")
def read_json(path,limit=8*1024*1024):
    try:
        row=path.lstat()
        if not stat.S_ISREG(row.st_mode) or path.is_symlink() or not 0<row.st_size<=limit:raise ValueError()
        return json.loads(path.read_text("utf-8"))
    except Exception:fail("transition_conflict")
def safe_status(raw,root):
    try:
        for record in raw.split(b"\0"):
            if not record:continue
            if record[:3]!=b"?? ":return False
            pure=PurePosixPath(record[3:].decode("utf-8","strict"));path=root.joinpath(*pure.parts)
            if pure.is_absolute() or any(part in {"",".",".."} for part in pure.parts) or pure.parts[0] not in {"data","graphs"} or pure.suffix.lower() not in {".json",".npy",".csv",".db",".sqlite",".pbs",".out",".err",".txt",".sh",".lock"} or path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):return False
        return True
    except Exception:return False
def publish(path,data,mode=0o600):
    tmp=path.parent/f".{path.name}.{os.getpid()}.tmp";fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),mode)
    try:
        with os.fdopen(fd,"wb") as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        try:os.link(tmp,path,follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes()!=data:fail("transition_conflict")
    finally:
        try:tmp.unlink()
        except FileNotFoundError:pass
    descriptor=os.open(path.parent,os.O_RDONLY);os.fsync(descriptor);os.close(descriptor)
def atomic_json(path,value):publish(path,(json.dumps(value,sort_keys=True)+"\n").encode())
def timestamp(value):return isinstance(value,int) and not isinstance(value,bool) and 0<=value<=253402300799
def parse_round(output,job,task_count,index,job_ids,parser):
    jobs=parser(output);prefix=job.replace("[].zeus-master","");children={f"{prefix}[{i}].zeus-master" for i in range(task_count)};ids=[row.get("id") for row in jobs]
    if any(not isinstance(row,dict) or "id" not in row for row in jobs) or len(ids)!=len(set(ids)) or set(ids) not in (children,children|{job}) or len(jobs) not in {task_count,task_count+1}:raise ValueError("scheduler records")
    by_id={row["id"]:row for row in jobs};dependencies=re.findall(r"depend\s*=\s*([^\s,]+)",output);expected=[] if index==1 else ["afterok:"+job_ids[index-2]+"@zeus-master"]
    if dependencies not in (expected,[] if index==1 else ["afterok:"+job_ids[index-2]]):raise ValueError("scheduler dependency")
    counts={"queued":0,"running":0,"held":0,"succeeded":0,"failed":0};unknown=False
    for child in children:
        row=by_id[child];state=row.get("state");key={"queued":"queued","running":"running","held_attention":"held","completed_success":"succeeded","completed_failed":"failed"}.get(state)
        if key is None:raise ValueError("scheduler state")
        else:
            if key=="succeeded" and row.get("exit_status")!=0:raise ValueError("scheduler exit")
            counts[key]+=1
    scheduler="completed_success" if counts["succeeded"]==task_count else "completed_failed" if counts["failed"] else "held" if counts["held"] else "running" if counts["running"] else "queued" if counts["queued"] else "unknown"
    return {"round":index,"job_id":job,"depends_on_job_id":None if index==1 else job_ids[index-2],"scheduler":{"state":scheduler,"task_count":task_count,"counts":counts}},unknown
def chain_lifecycle(rounds,unknown):
    counts=[row["scheduler"]["counts"] for row in rounds]
    # Failure dominates downstream dependency holds.  A hold is never treated
    # as benign without independently verifiable scheduler evidence.
    if any(row["failed"] for row in counts):return "failed"
    if any(row["held"] for row in counts):return "held"
    if any(row["running"] for row in counts):return "running"
    if any(row["queued"] for row in counts):return "queued"
    if unknown or any(row["succeeded"]!=rounds[index]["scheduler"]["task_count"] for index,row in enumerate(counts)):return "status_unknown"
    return "completed_success"
def completed_rounds(value,job_ids,task_count):
    if not isinstance(value,list) or len(value)!=4:return False
    for index,row in enumerate(value,1):
        counts={"queued":0,"running":0,"held":0,"succeeded":task_count,"failed":0}
        expected={"round":index,"job_id":job_ids[index-1],"depends_on_job_id":None if index==1 else job_ids[index-2],"scheduler":{"state":"completed_success","task_count":task_count,"counts":counts}}
        if row!=expected:return False
    return True
def main():
    if len(sys.argv)!=5 or sys.argv[1] not in {"inspect","prepare"}:fail("invalid_request")
    operation,username,requested,encoded=sys.argv[1:]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,31}",username):fail("invalid_request")
    try:root=Path(requested).resolve(strict=True);payload=json.loads(base64.urlsafe_b64decode(encoded))
    except Exception:fail("invalid_request")
    if root!=Path("/home")/username/"ytterbium_lab_simulation_new" or not isinstance(payload,dict):fail("remote_project_missing")
    inspect_keys={"campaign","commit","refine_files","chain_key","screen_digest","screening_submission_key"};prepare_keys=inspect_keys|{"rows_digest","confirmation_files","nonce"}
    if set(payload)!=(inspect_keys if operation=="inspect" else prepare_keys):fail("invalid_request")
    pure=PurePosixPath(payload["campaign"]);commit=payload["commit"]
    if pure.is_absolute() or pure.parts[:3]!=("data","optimization","mot_2d") or len(pure.parts)!=4 or any(part in {"",".",".."} for part in pure.parts) or not re.fullmatch(r"[0-9a-f]{40}",str(commit)) or not re.fullmatch(r"[0-9a-f]{64}",str(payload["chain_key"])):fail("invalid_request")
    campaign=root.joinpath(*pure.parts);no_links(root,campaign)
    try:
        head=subprocess.run(["/usr/bin/git","rev-parse","HEAD"],cwd=root,text=True,capture_output=True,timeout=10,check=True).stdout.strip();dirty=subprocess.run(["/usr/bin/git","status","--porcelain=v1","-z","--untracked-files=all"],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=True).stdout;branch=subprocess.run(["/usr/bin/git","branch","--show-current"],cwd=root,text=True,capture_output=True,timeout=10,check=True).stdout.strip()
    except Exception:fail("remote_checkout_mismatch")
    if head!=commit or not branch or not safe_status(dirty,root):fail("remote_checkout_mismatch")
    manifest=read_json(campaign/"campaign.json");metadata=campaign/".mot_ui";transitions=metadata/"transitions";submissions=metadata/"submissions"
    for path in (metadata,transitions,submissions,campaign/"refine",campaign/"jobs"):no_links(campaign,path)
    refine_receipt=read_json(transitions/"refine.json");chain=read_json(submissions/"refinement_chain.json");refine_files=payload["refine_files"]
    if not isinstance(refine_files,dict) or set(refine_files)!={"campaign.json","screening_candidates.json","refine/tasks.json","jobs/03_refine_round_01.pbs","jobs/03_refine_round_02.pbs","jobs/03_refine_round_03.pbs","jobs/03_refine_round_04.pbs","jobs/03_submit_refinement_chain.sh"} or any(not re.fullmatch(r"[0-9a-f]{64}",str(value)) for value in refine_files.values()):fail("invalid_request")
    if set(refine_receipt)!={"status","nonce","job_id","rows_digest","rows","refine_files","commit","screening_submission_key","screen_digest","completed_unix_s"} or refine_receipt["status"]!="refinement_prepared" or refine_receipt["commit"]!=commit or refine_receipt["refine_files"]!=refine_files or refine_receipt["screen_digest"]!=payload["screen_digest"] or refine_receipt["screening_submission_key"]!=payload["screening_submission_key"] or not re.fullmatch(r"[0-9a-f]{32}",str(refine_receipt["nonce"])) or not re.fullmatch(r"\d+\[\]\.zeus-master",str(refine_receipt["job_id"])) or not re.fullmatch(r"[0-9a-f]{64}",str(refine_receipt["rows_digest"])) or not isinstance(refine_receipt["rows"],list) or hashlib.sha256(json.dumps(refine_receipt["rows"],sort_keys=True).encode()).hexdigest()!=refine_receipt["rows_digest"] or not re.fullmatch(r"[0-9a-f]{64}",str(refine_receipt["screening_submission_key"])) or not re.fullmatch(r"[0-9a-f]{64}",str(refine_receipt["screen_digest"])) or not timestamp(refine_receipt["completed_unix_s"]):fail("transition_conflict")
    for name,expected in refine_files.items():
        path=campaign/name;no_links(campaign,path)
        if name=="campaign.json" and manifest.get("stage")=="confirmation":
            prior_manifest=json.loads(json.dumps(manifest));prior_manifest["stage"]="refine";prior_manifest.get("stages",{}).pop("confirmation",None)
            observed=hashlib.sha256((json.dumps(prior_manifest,indent=2,sort_keys=True)+"\n").encode()).hexdigest()
        else:observed=sha(path) if path.is_file() else ""
        if observed!=expected:fail("transition_conflict")
    if set(chain)!={"status","chain_key","nonce","commit","job_ids","created_unix_s","completed_unix_s"} or chain["status"]!="submitted" or chain["chain_key"]!=payload["chain_key"] or chain["commit"]!=commit or not re.fullmatch(r"[0-9a-f]{32}",str(chain["nonce"])) or not timestamp(chain["created_unix_s"]) or not timestamp(chain["completed_unix_s"]) or chain["completed_unix_s"]<chain["created_unix_s"] or not isinstance(chain["job_ids"],list) or len(chain["job_ids"])!=4 or len(set(chain["job_ids"]))!=4 or any(not re.fullmatch(r"\d+\[\]\.zeus-master",str(job)) for job in chain["job_ids"]):fail("submission_record_invalid")
    step_created=[];step_completed=[]
    for index,job in enumerate(chain["job_ids"],1):
        step=read_json(submissions/f"refinement_round_{index:02d}.json")
        exact={"status","chain_key","nonce","round","pbs_sha256","depends_on","created_unix_s","job_id","completed_unix_s"}
        if set(step)!=exact or step["status"]!="submitted" or step["job_id"]!=job or step["chain_key"]!=payload["chain_key"] or step["nonce"]!=chain["nonce"] or step["round"]!=index or step["pbs_sha256"]!=refine_files[f"jobs/03_refine_round_{index:02d}.pbs"] or step["depends_on"]!=(chain["job_ids"][index-2] if index>1 else None) or not timestamp(step["created_unix_s"]) or not timestamp(step["completed_unix_s"]) or step["completed_unix_s"]<step["created_unix_s"]:fail("submission_record_invalid")
        step_created.append(step["created_unix_s"]);step_completed.append(step["completed_unix_s"])
    if any(chain["created_unix_s"]>value for value in step_created) or any(step_completed[i]>step_created[i+1] for i in range(3)) or chain["completed_unix_s"]<max(step_completed):fail("submission_record_invalid")
    receipt=transitions/"confirmation.json";pending=transitions/"confirmation.pending.json";lock=transitions/"confirmation.lock"
    if manifest.get("stage")=="confirmation":
        if not receipt.exists():
            if operation!="prepare" or not pending.exists():fail("transition_outcome_unknown")
            no_links(campaign,lock)
            lock_fd=os.open(lock,os.O_RDWR|os.O_CREAT|getattr(os,"O_NOFOLLOW",0),0o600)
            try:
                fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(lock_fd);fail("transition_busy")
            try:
                # Crash recovery is a state transition too.  Re-read all
                # durable state while holding the same lock used by the
                # original publisher so two retries cannot both finalize it.
                manifest=read_json(campaign/"campaign.json")
                if manifest.get("stage")!="confirmation" or receipt.exists() or not pending.exists():fail("transition_outcome_unknown")
                pending_record=read_json(pending)
                if set(pending_record)!={"status","nonce","chain_key","rows_digest","files","rounds","created_unix_s"} or pending_record["status"]!="confirmation_pending" or pending_record["nonce"]!=payload.get("nonce") or pending_record["chain_key"]!=payload["chain_key"] or pending_record["rows_digest"]!=payload.get("rows_digest") or pending_record["files"]!=payload.get("confirmation_files") or not completed_rounds(pending_record["rounds"],chain["job_ids"],len(manifest["s0_values"])*3) or not timestamp(pending_record["created_unix_s"]):fail("transition_outcome_unknown")
                prior=json.loads(json.dumps(manifest));prior["stage"]="refine";prior["stages"].pop("confirmation",None)
                from workflow_api.mot_2d_screen import validate_refine_outputs
                locked=validate_refine_outputs(campaign,prior)
                from workflow_api.mot_2d_plan import render_confirmation_transition
                rendered=render_confirmation_transition(prior,campaign,root,locked);hashes={name:hashlib.sha256(data).hexdigest() for name,data in rendered.items()}
                if hashes!=pending_record["files"] or hashlib.sha256(json.dumps(locked,sort_keys=True).encode()).hexdigest()!=pending_record["rows_digest"] or (campaign/"campaign.json").read_bytes()!=rendered["campaign.json"] or any(not (campaign/name).is_file() or sha(campaign/name)!=value for name,value in hashes.items()):raise ValueError()
                recovered={"status":"confirmation_prepared","nonce":payload["nonce"],"chain_key":payload["chain_key"],"commit":commit,"rows_digest":pending_record["rows_digest"],"rows":locked,"files":hashes,"rounds":pending_record["rounds"],"completed_unix_s":int(time.time())};atomic_json(receipt,recovered);pending.unlink();descriptor=os.open(transitions,os.O_RDONLY);os.fsync(descriptor);os.close(descriptor)
            except SystemExit:raise
            except Exception:fail("transition_outcome_unknown")
            finally:
                fcntl.flock(lock_fd,fcntl.LOCK_UN);os.close(lock_fd)
            print(json.dumps({"lifecycle":"confirmation_prepared","rounds":recovered["rounds"],"rows":locked,"branch":branch,"receipt":recovered}));return
        record=read_json(receipt)
        exact={"status","nonce","chain_key","commit","rows_digest","rows","files","rounds","completed_unix_s"}
        if set(record)!=exact or record["status"]!="confirmation_prepared" or record["chain_key"]!=payload["chain_key"] or record["commit"]!=commit or not re.fullmatch(r"[0-9a-f]{32}",str(record["nonce"])) or not timestamp(record["completed_unix_s"]) or hashlib.sha256(json.dumps(record["rows"],sort_keys=True).encode()).hexdigest()!=record["rows_digest"]:fail("transition_outcome_unknown")
        try:
            prior=json.loads(json.dumps(manifest));prior["stage"]="refine";prior["stages"].pop("confirmation",None)
            from workflow_api.mot_2d_screen import validate_refine_outputs
            canonical_rows=validate_refine_outputs(campaign,prior)
            from workflow_api.mot_2d_plan import render_confirmation_transition
            canonical=render_confirmation_transition(prior,campaign,root,canonical_rows);hashes={name:hashlib.sha256(data).hexdigest() for name,data in canonical.items()}
            if record["rows"]!=canonical_rows or record["files"]!=hashes or not completed_rounds(record["rounds"],chain["job_ids"],len(manifest["s0_values"])*3) or any(not (campaign/name).is_file() or sha(campaign/name)!=value for name,value in hashes.items()):raise ValueError()
        except Exception:fail("transition_outcome_unknown")
        print(json.dumps({"lifecycle":"confirmation_prepared","rounds":record["rounds"],"rows":record["rows"],"branch":branch,"receipt":record}));return
    if manifest.get("stage")!="refine":fail("campaign_not_refine")
    pending_exists=pending.exists()
    for path in (pending,campaign/"refined_candidates.json",campaign/"confirmation",campaign/"jobs/04_confirmation.pbs"):
        no_links(campaign,path)
        if path.is_symlink() or path.exists() and (operation=="inspect" or not pending_exists):fail("transition_outcome_unknown")
    task_count=len(manifest["s0_values"])*3;rounds=[];any_unknown=False
    from workflow_api.zeus_snapshot import _parse_qstat
    for index,job in enumerate(chain["job_ids"],1):
        result=subprocess.run(["/usr/local/bin/qstat","-x","-t","-f",job],cwd=root,text=True,capture_output=True,timeout=20,check=False)
        if result.returncode or result.stderr:fail("scheduler_unavailable")
        try:round_row,unknown=parse_round(result.stdout,job,task_count,index,chain["job_ids"],_parse_qstat)
        except Exception:fail("scheduler_unavailable")
        rounds.append(round_row);any_unknown|=unknown
    rows=[]
    lifecycle=chain_lifecycle(rounds,any_unknown)
    if lifecycle=="completed_success":
        from workflow_api.mot_2d_screen import validate_refine_outputs
        try:rows=validate_refine_outputs(campaign,manifest)
        except FileNotFoundError:lifecycle="awaiting_outputs";rows=[]
        except Exception:lifecycle="outputs_invalid";rows=[]
        else:
            if rows!=refine_receipt.get("rows") or hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()!=refine_receipt.get("rows_digest"):lifecycle="outputs_invalid";rows=[]
            else:lifecycle="ready_to_prepare_confirmation"
    if lifecycle!="ready_to_prepare_confirmation" or operation=="inspect":print(json.dumps({"lifecycle":lifecycle,"rounds":rounds,"rows":rows,"branch":branch,"receipt":None}));return
    rows_digest=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    if rows_digest!=payload["rows_digest"]:fail("transition_conflict")
    from workflow_api.mot_2d_plan import render_confirmation_transition
    rendered=render_confirmation_transition(manifest,campaign,root,rows);hashes={name:hashlib.sha256(data).hexdigest() for name,data in rendered.items()}
    if hashes!=payload["confirmation_files"] or not re.fullmatch(r"[0-9a-f]{32}",str(payload["nonce"])):fail("transition_conflict")
    lock_fd=os.open(lock,os.O_RDWR|os.O_CREAT|getattr(os,"O_NOFOLLOW",0),0o600)
    try:fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:os.close(lock_fd);fail("transition_busy")
    try:
        # Re-check every scheduler child, dependency, manifest, and scientific output under the lock.
        locked_manifest=read_json(campaign/"campaign.json")
        if locked_manifest!=manifest:fail("transition_conflict")
        for round_index,job in enumerate(chain["job_ids"],1):
            checked=subprocess.run(["/usr/local/bin/qstat","-x","-t","-f",job],cwd=root,text=True,capture_output=True,timeout=20,check=False)
            try:checked_round,checked_unknown=parse_round(checked.stdout,job,task_count,round_index,chain["job_ids"],_parse_qstat)
            except Exception:fail("refine_status_unknown")
            if checked.returncode or checked.stderr or checked_unknown or checked_round["scheduler"]["state"]!="completed_success":fail("refine_status_unknown")
        locked=validate_refine_outputs(campaign,manifest)
        if hashlib.sha256(json.dumps(locked,sort_keys=True).encode()).hexdigest()!=rows_digest:fail("transition_conflict")
        for path in (receipt,pending,lock,campaign/"confirmation",campaign/"confirmation/tasks.json",campaign/"jobs/04_confirmation.pbs",campaign/"refined_candidates.json"):no_links(campaign,path)
        if receipt.exists():fail("transition_outcome_unknown")
        pending_payload={"status":"confirmation_pending","nonce":payload["nonce"],"chain_key":payload["chain_key"],"rows_digest":rows_digest,"files":hashes,"rounds":rounds,"created_unix_s":int(time.time())}
        if pending.exists():
            existing=read_json(pending)
            if {key:existing.get(key) for key in pending_payload if key!="created_unix_s"}!={key:value for key,value in pending_payload.items() if key!="created_unix_s"}:fail("transition_outcome_unknown")
        else:atomic_json(pending,pending_payload)
        for name,data in rendered.items():
            if name=="campaign.json":continue
            target=campaign/name;target.parent.mkdir(parents=True,exist_ok=True);publish(target,data,0o755 if target.suffix==".pbs" else 0o644)
        temporary=campaign/f".campaign.{payload['nonce']}.tmp"
        with temporary.open("xb") as stream:stream.write(rendered["campaign.json"]);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,campaign/"campaign.json");descriptor=os.open(campaign,os.O_RDONLY);os.fsync(descriptor);os.close(descriptor)
        record={"status":"confirmation_prepared","nonce":payload["nonce"],"chain_key":payload["chain_key"],"commit":commit,"rows_digest":rows_digest,"rows":locked,"files":hashes,"rounds":rounds,"completed_unix_s":int(time.time())};atomic_json(receipt,record);pending.unlink();descriptor=os.open(transitions,os.O_RDONLY);os.fsync(descriptor);os.close(descriptor)
    finally:
        fcntl.flock(lock_fd,fcntl.LOCK_UN);os.close(lock_fd)
    print(json.dumps({"lifecycle":"confirmation_prepared","rounds":rounds,"rows":rows,"branch":branch,"receipt":record}))
if __name__=="__main__":main()
