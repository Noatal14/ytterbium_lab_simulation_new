"""Pinned receiver: submit only four verified refinement PBS byte streams."""
from __future__ import annotations
import base64,hashlib,json,os,re,subprocess,sys,time
from pathlib import Path,PurePosixPath
FILES=tuple(f"jobs/03_refine_round_{i:02d}.pbs" for i in range(1,5));JOB_RE=re.compile(r"^\d+\[\]\.zeus-master$")
def fail(code,status=20):print(json.dumps({"error":code}));raise SystemExit(status)
def digest_bytes(value):return hashlib.sha256(value).hexdigest()
def no_symlinks(root,path):
    current=root
    for part in path.relative_to(root).parts:
        current/=part
        if current.exists() and current.is_symlink():fail("remote_preparation_invalid")
def write_record(path,value):
    data=(json.dumps(value,sort_keys=True)+"\n").encode();tmp=path.parent/f".{path.name}.{os.getpid()}.tmp";fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        with os.fdopen(fd,"wb") as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        try:os.link(tmp,path,follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes()!=data:fail("refinement_submission_outcome_unknown")
    finally:
        try:tmp.unlink()
        except FileNotFoundError:pass
    parent=os.open(path.parent,os.O_RDONLY);os.fsync(parent);os.close(parent)
def response(status,branch,ids=(),nonce=None,stamp=None):print(json.dumps({"status":status,"branch":branch,"job_ids":list(ids),"nonce":nonce,"completed_unix_s":stamp}))
def read_record(path,keys,limit=262144):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:fail("refinement_submission_outcome_unknown")
    try:value=json.loads(path.read_text("utf-8"))
    except Exception:fail("refinement_submission_outcome_unknown")
    if not isinstance(value,dict) or set(value)!=set(keys):fail("refinement_submission_outcome_unknown")
    return value
def timestamp(value):return isinstance(value,int) and not isinstance(value,bool) and 0<=value<=253402300799
def main():
    if len(sys.argv)!=5 or sys.argv[1] not in {"inspect","submit"}:fail("invalid_request")
    operation,username,project,encoded=sys.argv[1:5]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,31}",username) or project!=f"/home/{username}/ytterbium_lab_simulation_new":fail("invalid_request")
    try:payload=json.loads(base64.urlsafe_b64decode(encoded));root=Path(project).resolve(strict=True);relative=PurePosixPath(payload["campaign"])
    except Exception:fail("invalid_request")
    exact_payload={"campaign","commit","refine_files","chain_key","screen_digest","screening_submission_key","nonce"}
    if not isinstance(payload,dict) or set(payload)!=exact_payload or not re.fullmatch(r"[0-9a-f]{40}",str(payload.get("commit",""))) or not re.fullmatch(r"[0-9a-f]{64}",str(payload.get("screen_digest",""))) or not re.fullmatch(r"[0-9a-f]{64}",str(payload.get("screening_submission_key",""))):fail("invalid_request")
    if relative.is_absolute() or len(relative.parts)!=4 or relative.parts[:3]!=("data","optimization","mot_2d") or any(part in {"",".",".."} for part in relative.parts):fail("invalid_request")
    campaign=root/relative;no_symlinks(root,campaign);state_dir=campaign/".mot_ui/transitions";no_symlinks(root,state_dir);state_dir.mkdir(parents=True,exist_ok=True)
    files=payload.get("refine_files");nonce=payload.get("nonce");key=payload.get("chain_key")
    exact_files={*FILES,"campaign.json","screening_candidates.json","refine/tasks.json","jobs/03_submit_refinement_chain.sh"}
    if not isinstance(files,dict) or set(files)!=exact_files or any(not re.fullmatch(r"[0-9a-f]{64}",str(x)) for x in files.values()) or not re.fullmatch(r"[0-9a-f]{64}",str(key)):fail("invalid_request")
    status=subprocess.run(["/usr/bin/git","status","--porcelain=v1","-z","--untracked-files=all"],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if status.returncode or status.stderr:fail("remote_checkout_mismatch")
    for item in status.stdout.split(b"\0"):
        if not item:continue
        if item[:3]!=b"?? ":fail("remote_checkout_mismatch")
        try:path=PurePosixPath(item[3:].decode("utf-8","strict"))
        except Exception:fail("remote_checkout_mismatch")
        if path.is_absolute() or not path.parts or path.parts[0]!="data" or path.suffix.lower() not in {".json",".pbs",".sh",".db",".npy",".csv",".out",".err"}:fail("remote_checkout_mismatch")
        disk=root/Path(*path.parts)
        try:info=disk.lstat()
        except OSError:fail("remote_checkout_mismatch")
        if disk.is_symlink() or not disk.is_file():fail("remote_checkout_mismatch")
    branch_result=subprocess.run(["/usr/bin/git","branch","--show-current"],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    revision_result=subprocess.run(["/usr/bin/git","rev-parse","HEAD"],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    try:branch=branch_result.stdout.decode("utf-8","strict").strip();revision=revision_result.stdout.decode("ascii","strict").strip()
    except Exception:fail("remote_checkout_mismatch")
    if branch_result.returncode or branch_result.stderr or not branch or len(branch)>256 or not branch.isprintable() or revision_result.returncode or revision_result.stderr or revision!=payload.get("commit"):fail("remote_checkout_mismatch")
    receipt=state_dir/"refinement_chain.json";chain_pending=state_dir/"refinement_chain.pending.json";lock=state_dir/"refinement_chain.lock"
    step_receipts=[state_dir/f"refinement_round_{i:02d}.json" for i in range(1,5)];step_pending=[state_dir/f"refinement_round_{i:02d}.pending.json" for i in range(1,5)]
    for path in (receipt,chain_pending,*step_receipts,*step_pending):
        no_symlinks(root,path)
        if path.is_symlink():fail("refinement_submission_outcome_unknown")
    def verify():
        transition=state_dir/"refine.json";no_symlinks(root,transition)
        record=read_record(transition,{"status","nonce","job_id","rows_digest","rows","refine_files","commit","screening_submission_key","screen_digest","completed_unix_s"},4*1024*1024)
        if record["status"]!="refinement_prepared" or record["commit"]!=payload["commit"] or record["screening_submission_key"]!=payload["screening_submission_key"] or record["screen_digest"]!=payload["screen_digest"] or record["refine_files"]!=files or not timestamp(record["completed_unix_s"]):fail("refinement_not_prepared")
        manifest_path=campaign/"campaign.json";no_symlinks(root,manifest_path)
        try:manifest=json.loads(manifest_path.read_text("utf-8"))
        except Exception:fail("refinement_not_prepared")
        if not isinstance(manifest,dict) or manifest.get("stage")!="refine" or manifest.get("provenance",{}).get("git_commit")!=payload["commit"]:fail("refinement_not_prepared")
        for name,want in files.items():
            path=campaign/name;no_symlinks(root,path)
            if not path.is_file() or digest_bytes(path.read_bytes())!=want:fail("refinement_not_prepared")
        refine=campaign/"refine";no_symlinks(root,refine)
        if not refine.is_dir() or any(path.name!="tasks.json" for path in refine.iterdir()):fail("refinement_already_started")
        return [ (campaign/name).read_bytes() for name in FILES ]
    ids=[]
    receipt_nonce=None
    step_created=[];step_completed=[]
    missing_receipt=False
    for index,path in enumerate(step_receipts,1):
        if path.exists():
            if missing_receipt:fail("refinement_submission_outcome_unknown")
            record=read_record(path,{"status","chain_key","nonce","round","pbs_sha256","depends_on","created_unix_s","job_id","completed_unix_s"});job=record["job_id"]
            if record["status"]!="submitted" or record["chain_key"]!=key or record["round"]!=index or record["pbs_sha256"]!=files[FILES[index-1]] or record["depends_on"]!=(ids[index-2] if index>1 else None) or not re.fullmatch(r"[0-9a-f]{32}",str(record["nonce"])) or receipt_nonce not in {None,record["nonce"]} or not JOB_RE.fullmatch(str(job)) or job in ids or not timestamp(record["created_unix_s"]) or not timestamp(record["completed_unix_s"]) or record["completed_unix_s"]<record["created_unix_s"]:fail("refinement_submission_outcome_unknown")
            receipt_nonce=record["nonce"]
            ids.append(job)
            step_created.append(record["created_unix_s"]);step_completed.append(record["completed_unix_s"])
        else:missing_receipt=True
    if receipt.exists():
        record=read_record(receipt,{"status","chain_key","nonce","commit","job_ids","created_unix_s","completed_unix_s"})
        causal=bool(step_created) and all(record["created_unix_s"]<=value for value in step_created) and all(step_completed[index]<=step_created[index+1] for index in range(len(step_completed)-1)) and record["completed_unix_s"]>=max(step_completed)
        if record["status"]!="submitted" or record["chain_key"]!=key or record["commit"]!=payload["commit"] or record["job_ids"]!=ids or len(ids)!=4 or record["nonce"]!=receipt_nonce or not re.fullmatch(r"[0-9a-f]{32}",str(record["nonce"])) or not timestamp(record["created_unix_s"]) or not timestamp(record["completed_unix_s"]) or record["completed_unix_s"]<record["created_unix_s"] or not causal:fail("refinement_submission_outcome_unknown")
        verify()
        response("submitted",branch,ids,record.get("nonce"),record.get("completed_unix_s"));return
    if chain_pending.exists() or any(path.exists() or path.is_symlink() for path in step_pending):response("ambiguous",branch,ids,nonce,None);return
    if ids:response("partial",branch,ids,None,None);return
    verify()
    if operation=="inspect":response("eligible",branch);return
    if not isinstance(nonce,str) or not re.fullmatch(r"[0-9a-f]{32}",nonce):fail("invalid_request")
    try:lock.mkdir()
    except FileExistsError:fail("refinement_submission_busy")
    try:
        pbs=verify();created=int(time.time());write_record(chain_pending,{"status":"pending","chain_key":key,"nonce":nonce,"commit":payload["commit"],"created_unix_s":created})
        previous=None
        for index,data in enumerate(pbs,1):
            # Revalidate the whole frozen plan and pristine output tree immediately before each qsub.
            current=verify()[index-1]
            if current!=data:fail("refinement_submission_outcome_unknown")
            intent={"status":"pending","chain_key":key,"nonce":nonce,"round":index,"pbs_sha256":digest_bytes(data),"depends_on":previous,"created_unix_s":int(time.time())};write_record(step_pending[index-1],intent)
            argv=["/usr/local/bin/qsub"] if previous is None else ["/usr/local/bin/qsub","-W","depend=afterok:"+previous]
            try:result=subprocess.run(argv,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,check=False)
            except Exception:fail("refinement_submission_outcome_unknown")
            try:stdout=result.stdout.decode("ascii","strict");stderr=result.stderr.decode("utf-8","replace")
            except Exception:fail("refinement_submission_outcome_unknown")
            if result.returncode or stderr or not re.fullmatch(r"\d+\[\]\.zeus-master\n?",stdout):fail("refinement_submission_outcome_unknown")
            job=stdout.rstrip("\n");final={**intent,"status":"submitted","job_id":job,"completed_unix_s":int(time.time())};write_record(step_receipts[index-1],final);step_pending[index-1].unlink();d=os.open(state_dir,os.O_RDONLY);os.fsync(d);os.close(d);ids.append(job);previous=job
        completed=int(time.time());write_record(receipt,{"status":"submitted","chain_key":key,"nonce":nonce,"commit":payload["commit"],"job_ids":ids,"created_unix_s":created,"completed_unix_s":completed});chain_pending.unlink();d=os.open(state_dir,os.O_RDONLY);os.fsync(d);os.close(d);response("submitted",branch,ids,nonce,completed)
    finally:
        try:lock.rmdir()
        except OSError:pass
if __name__=="__main__":main()
