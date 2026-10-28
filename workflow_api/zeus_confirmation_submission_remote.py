"""Pinned receiver: submit only the prepared canonical Confirmation PBS."""
from __future__ import annotations
from workflow_api.campaign_deployment import campaign_checkout_paths
import base64, hashlib, json, os, re, stat, subprocess, sys, tempfile, time
from pathlib import Path, PurePosixPath

JOB_FILE="jobs/04_confirmation.pbs"; JOB_RE=re.compile(r"^\d+\[\]\.zeus-master$")
def fail(code,status=20): print(json.dumps({"error":code})); raise SystemExit(status)
def timestamp(value): return isinstance(value,int) and not isinstance(value,bool) and 0<=value<=253402300799
def no_links(root,path):
    current=root
    for part in path.relative_to(root).parts:
        current/=part
        if current.exists() and current.is_symlink(): fail("confirmation_submission_outcome_unknown")
def bounded(path,limit=8*1024*1024):
    try: row=path.lstat()
    except OSError: fail("confirmation_preparation_invalid")
    if not stat.S_ISREG(row.st_mode) or path.is_symlink() or row.st_size<=0 or row.st_size>limit: fail("confirmation_preparation_invalid")
    with path.open("rb") as stream: data=stream.read(limit+1)
    if len(data)!=row.st_size: fail("confirmation_preparation_invalid")
    return data
def read_json(path,keys,limit=1024*1024):
    try: value=json.loads(bounded(path,limit))
    except Exception: fail("confirmation_submission_outcome_unknown")
    if not isinstance(value,dict) or set(value)!=set(keys): fail("confirmation_submission_outcome_unknown")
    return value
def write_record(path,value):
    data=(json.dumps(value,sort_keys=True)+"\n").encode();tmp=path.parent/f".{path.name}.{os.getpid()}.tmp";fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        with os.fdopen(fd,"wb") as stream: stream.write(data);stream.flush();os.fsync(stream.fileno())
        try: os.link(tmp,path,follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or bounded(path)!=data: fail("confirmation_submission_outcome_unknown")
    finally:
        try: tmp.unlink()
        except FileNotFoundError: pass
    parent=os.open(path.parent,os.O_RDONLY);os.fsync(parent);os.close(parent)
def respond(status,branch,job=None,nonce=None,stamp=None): print(json.dumps({"status":status,"branch":branch,"job_id":job,"nonce":nonce,"completed_unix_s":stamp}))
def run_captured(argv,*,input_data=None,limit=4*1024*1024):
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result=subprocess.run(argv,input=input_data,stdout=stdout,stderr=stderr,timeout=30,check=False)
        stdout.seek(0,os.SEEK_END);stdout_size=stdout.tell();stderr.seek(0,os.SEEK_END);stderr_size=stderr.tell()
        if stdout_size>limit or stderr_size>limit: fail("confirmation_submission_outcome_unknown")
        stdout.seek(0);stderr.seek(0)
        return result.returncode,stdout.read(limit+1),stderr.read(limit+1)
def scheduler_state(output,job_id,task_count):
    if not isinstance(output,bytes) or len(output)>4*1024*1024: return "status_unknown"
    try: text=output.decode("utf-8","strict")
    except Exception: return "status_unknown"
    chunks=re.split(r"(?m)^Job Id:\s*",text)
    if chunks[0].strip():return "status_unknown"
    blocks=[];seen=set()
    for chunk in chunks[1:]:
        lines=chunk.splitlines();identifier=lines[0].strip();values={};last_key=None
        if not identifier:return "status_unknown"
        if identifier in seen:return "status_unknown"
        seen.add(identifier)
        for line in lines[1:]:
            if not line.strip():continue
            match=re.match(r"\s*([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(.*?)\s*$",line)
            if match:
                key=match.group(1)
                if key in {"job_state","Exit_status"} and key in values:return "status_unknown"
                values[key]=match.group(2);last_key=key
            elif (line.startswith(("\t", "        ")) and last_key is not None
                  and last_key not in {"job_state", "Exit_status"} and line.strip()):
                values[last_key]+=line.strip()
            else:return "status_unknown"
        blocks.append((identifier,values))
    prefix=job_id.split("[]",1)[0];expected={f"{prefix}[{index}].zeus-master" for index in range(task_count)}
    allowed=expected|{job_id}
    if any(identifier not in allowed for identifier,_ in blocks): return "status_unknown"
    children=[(identifier,tuple(values.items())) for identifier,values in blocks if identifier in expected]
    ids={identifier for identifier,_ in children}
    if ids!=expected or len(children)!=task_count: return "status_unknown"
    states=[]
    for _,items in children:
        values=dict(items);state=values.get("job_state")
        if state in {"Q","W"}: states.append("queued")
        elif state in {"R","E"}: states.append("running")
        elif state in {"H","S"}: states.append("held")
        elif state in {"F","X"}:
            exit_status=values.get("Exit_status")
            states.append("completed_success" if exit_status=="0" else "completed_failed" if exit_status is not None else "status_unknown")
        else: states.append("status_unknown")
    for candidate in ("completed_failed","held","status_unknown","running","queued"):
        if candidate in states:return candidate
    return "completed_success"

def main():
    if len(sys.argv)!=5 or sys.argv[1] not in {"inspect","submit","status"}: fail("invalid_request")
    operation,username,project,encoded=sys.argv[1:]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,31}",username) or PurePosixPath(project) not in campaign_checkout_paths(username): fail("invalid_request")
    try: payload=json.loads(base64.urlsafe_b64decode(encoded));root=Path(project).resolve(strict=True);relative=PurePosixPath(payload["campaign"])
    except Exception: fail("invalid_request")
    if set(payload)!={"campaign","commit","confirmation_files","transition_nonce","transition_digest","submission_key","nonce"} or relative.is_absolute() or ((len(relative.parts) != 4 and not (len(relative.parts) == 5 and relative.parts[3] == "ui_acceptance")) and not (len(relative.parts) == 5 and relative.parts[3] == "ui_acceptance")) or relative.parts[:3]!=("data","optimization","mot_2d") or any(part in {"",".",".."} for part in relative.parts): fail("invalid_request")
    if not re.fullmatch(r"[0-9a-f]{40}",str(payload["commit"])) or not re.fullmatch(r"[0-9a-f]{64}",str(payload["submission_key"])) or not re.fullmatch(r"[0-9a-f]{64}",str(payload["transition_digest"])) or not re.fullmatch(r"[0-9a-f]{32}",str(payload["transition_nonce"])): fail("invalid_request")
    files=payload["confirmation_files"];expected_files={"refined_candidates.json","confirmation/tasks.json",JOB_FILE,"campaign.json"}
    if not isinstance(files,dict) or set(files)!=expected_files or any(not re.fullmatch(r"[0-9a-f]{64}",str(value)) for value in files.values()): fail("invalid_request")
    campaign=root.joinpath(*relative.parts)
    _authorize_acceptance_campaign(campaign, root)
    no_links(root,campaign)
    git=subprocess.run(["/usr/bin/git","rev-parse","HEAD"],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    branch_result=subprocess.run(["/usr/bin/git","branch","--show-current"],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    worktree=subprocess.run(["/usr/bin/git","status","--porcelain=v1","-z","--untracked-files=all"],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    try: revision=git.stdout.decode("ascii","strict").strip();branch=branch_result.stdout.decode("utf-8","strict").strip()
    except Exception: fail("remote_checkout_mismatch")
    if git.returncode or git.stderr or revision!=payload["commit"] or branch_result.returncode or branch_result.stderr or not branch or len(branch)>256 or not branch.isprintable() or worktree.returncode or worktree.stderr: fail("remote_checkout_mismatch")
    for item in worktree.stdout.split(b"\0"):
        if not item: continue
        if item[:3]!=b"?? ": fail("remote_checkout_mismatch")
        try: untracked=PurePosixPath(item[3:].decode("utf-8","strict"))
        except Exception: fail("remote_checkout_mismatch")
        if untracked.is_absolute() or not untracked.parts or untracked.parts[0]!="data" or untracked.suffix.lower() not in {".json",".pbs",".sh",".db",".npy",".csv",".out",".err"}: fail("remote_checkout_mismatch")
        disk=root.joinpath(*untracked.parts)
        try: info=disk.lstat()
        except OSError: fail("remote_checkout_mismatch")
        if not stat.S_ISREG(info.st_mode) or disk.is_symlink(): fail("remote_checkout_mismatch")
    state=campaign/".mot_ui";transitions=state/"transitions";submissions=state/"submissions"
    for path in (state,transitions,submissions): no_links(campaign,path)
    receipt=transitions/"confirmation.json";record=read_json(receipt,{"status","nonce","chain_key","commit","rows_digest","rows","files","rounds","completed_unix_s"},8*1024*1024)
    record_digest=hashlib.sha256(json.dumps(record,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    if record_digest!=payload["transition_digest"] or record["status"]!="confirmation_prepared" or record["nonce"]!=payload["transition_nonce"] or record["commit"]!=payload["commit"] or record["files"]!=files or not timestamp(record["completed_unix_s"]): fail("confirmation_preparation_invalid")
    manifest=json.loads(bounded(campaign/"campaign.json"));
    historical_projection_used = False
    if operation in {"inspect", "status"} and isinstance(manifest, dict) and manifest.get("stage") in {"sensitivity", "production", "complete"}:
        try:
            from workflow_api.mot_2d_spec import project_historical_manifest
            manifest = project_historical_manifest(manifest, "confirmation", files["campaign.json"])
            historical_projection_used = True
        except (ValueError, KeyError): fail("confirmation_preparation_invalid")
    if not isinstance(manifest,dict) or manifest.get("stage")!="confirmation" or manifest.get("provenance",{}).get("git_commit")!=payload["commit"]: fail("confirmation_preparation_invalid")
    for name,want in files.items():
        path=campaign/name;no_links(campaign,path);data=bounded(path,64*1024*1024)
        if name == "campaign.json" and historical_projection_used: data = (json.dumps(manifest, indent=2, sort_keys=True)+"\n").encode()
        if hashlib.sha256(data).hexdigest()!=want: fail("confirmation_preparation_invalid")
    job_bytes=bounded(campaign/JOB_FILE,1024*1024)
    submission=submissions/"confirmation.json";pending=submissions/"confirmation.pending.json";lock=submissions/"confirmation.lock"
    for path in (submission,pending,lock): no_links(campaign,path)
    if submission.exists():
        done=read_json(submission,{"version","status","submission_key","transition_nonce","transition_digest","pbs_sha256","nonce","job_file","commit","created_unix_s","job_id","completed_unix_s"})
        if done["version"]!=1 or done["status"]!="submitted" or done["submission_key"]!=payload["submission_key"] or done["transition_nonce"]!=payload["transition_nonce"] or done["transition_digest"]!=payload["transition_digest"] or done["pbs_sha256"]!=files[JOB_FILE] or done["job_file"]!=f"{relative.as_posix()}/{JOB_FILE}" or done["commit"]!=payload["commit"] or not re.fullmatch(r"[0-9a-f]{32}",str(done["nonce"])) or not JOB_RE.fullmatch(str(done["job_id"])) or not timestamp(done["created_unix_s"]) or not timestamp(done["completed_unix_s"]) or done["completed_unix_s"]<done["created_unix_s"]: fail("confirmation_submission_outcome_unknown")
        if operation=="status":
            task_count=len(manifest["s0_values"])*5
            try: returncode,stdout,stderr=run_captured(["/opt/pbs/bin/qstat","-x","-t","-f",done["job_id"]])
            except Exception: status="status_unknown"
            else: status="status_unknown" if returncode or stderr else scheduler_state(stdout,done["job_id"],task_count)
            respond(status,branch,done["job_id"],done["nonce"],done["completed_unix_s"]);return
        respond("submitted",branch,done["job_id"],done["nonce"],done["completed_unix_s"]);return
    if pending.exists() or lock.exists():
        pending_nonce=None
        if pending.exists():
            intent=read_json(pending,{"version","status","submission_key","transition_nonce","transition_digest","pbs_sha256","nonce","job_file","commit","created_unix_s"})
            if intent["version"]!=1 or intent["status"]!="pending" or intent["submission_key"]!=payload["submission_key"] or intent["transition_nonce"]!=payload["transition_nonce"] or intent["transition_digest"]!=payload["transition_digest"] or intent["pbs_sha256"]!=files[JOB_FILE] or intent["job_file"]!=f"{relative.as_posix()}/{JOB_FILE}" or intent["commit"]!=payload["commit"] or not re.fullmatch(r"[0-9a-f]{32}",str(intent["nonce"])) or not timestamp(intent["created_unix_s"]): fail("confirmation_submission_outcome_unknown")
            pending_nonce=intent["nonce"]
        respond("ambiguous",branch,None,pending_nonce,None);return
    if operation in {"inspect","status"}: respond("eligible",branch);return
    nonce=payload["nonce"]
    if not isinstance(nonce,str) or not re.fullmatch(r"[0-9a-f]{32}",nonce): fail("invalid_request")
    submissions.mkdir(parents=True,exist_ok=True);no_links(campaign,submissions)
    try: lock.mkdir()
    except FileExistsError: fail("confirmation_submission_busy")
    try:
        locked_record=read_json(receipt,{"status","nonce","chain_key","commit","rows_digest","rows","files","rounds","completed_unix_s"},8*1024*1024)
        locked_digest=hashlib.sha256(json.dumps(locked_record,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if locked_digest!=payload["transition_digest"] or locked_record!=record: fail("confirmation_submission_outcome_unknown")
        locked_files={}
        for name,want in files.items():
            data=bounded(campaign/name,64*1024*1024)
            if hashlib.sha256(data).hexdigest()!=want: fail("confirmation_submission_outcome_unknown")
            locked_files[name]=data
        locked_key=hashlib.sha256(json.dumps({"campaign":relative.as_posix(),"commit":payload["commit"],"transition_nonce":payload["transition_nonce"],"transition_digest":payload["transition_digest"],"files":files,"job_file":JOB_FILE},sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if locked_key!=payload["submission_key"]: fail("confirmation_submission_outcome_unknown")
        job_bytes=locked_files[JOB_FILE]
        created=int(time.time());intent={"version":1,"status":"pending","submission_key":payload["submission_key"],"transition_nonce":payload["transition_nonce"],"transition_digest":payload["transition_digest"],"pbs_sha256":files[JOB_FILE],"nonce":nonce,"job_file":f"{relative.as_posix()}/{JOB_FILE}","commit":payload["commit"],"created_unix_s":created};write_record(pending,intent)
        try: returncode,raw_stdout,raw_stderr=run_captured(["/usr/local/bin/qsub"],input_data=job_bytes,limit=1024*1024)
        except Exception: fail("confirmation_submission_outcome_unknown")
        try: stdout=raw_stdout.decode("ascii","strict");stderr=raw_stderr.decode("utf-8","replace")
        except Exception: fail("confirmation_submission_outcome_unknown")
        if returncode or stderr or not re.fullmatch(r"\d+\[\]\.zeus-master\n?",stdout): fail("confirmation_submission_outcome_unknown")
        job=stdout.rstrip("\n");completed=int(time.time());done={**intent,"status":"submitted","job_id":job,"completed_unix_s":completed};write_record(submission,done);pending.unlink();parent=os.open(submissions,os.O_RDONLY);os.fsync(parent);os.close(parent);respond("submitted",branch,job,nonce,completed)
    finally:
        try: lock.rmdir()
        except OSError: pass

def _authorize_acceptance_campaign(campaign, root):
    """Authenticate acceptance before locks, publication, or scheduler mutation."""
    try:
        from workflow_api.campaign_deployment import requires_deployment_attestation
        from workflow_api.acceptance_profile import assert_scientific_source, is_acceptance_manifest
        current = root
        for part in campaign.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError('Unsafe campaign path.')
        manifest_path = campaign / 'campaign.json'
        if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Unsafe campaign manifest.')
        value = json.loads(manifest_path.read_text(encoding='utf-8'))
        if is_acceptance_manifest(value) or 'acceptance' in value or requires_deployment_attestation(value, root) or 'ui_acceptance' in campaign.parts:
            from workflow_api.acceptance_remote import assert_campaign_target
            from workflow_api.mot_2d_spec import validate_campaign_policy
            validate_campaign_policy(value)
            assert_campaign_target(value, root.parent.name, root, campaign)
        else:
            assert_scientific_source(value)
    except (OSError, ValueError, TypeError, KeyError):
        fail('remote_preparation_invalid')

if __name__=="__main__": main()
