"""Pinned Zeus receiver for exactly one screening-array submission."""
from __future__ import annotations
import base64,hashlib,json,os,re,subprocess,sys,time,stat
import math
from pathlib import Path,PurePosixPath

def fail(code,status=20):print(json.dumps({"error":code}));raise SystemExit(status)
def digest(path):
    value=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):value.update(chunk)
    return value.hexdigest()
def no_symlinks(root,path):
    current=root
    for part in path.relative_to(root).parts:
        current/=part
        if current.exists() and current.is_symlink():fail("remote_preparation_invalid")
def read_json(path,limit=65536):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:fail("remote_preparation_invalid")
    try:return json.loads(path.read_text("utf-8"))
    except Exception:fail("remote_preparation_invalid")
def write_no_replace(path,payload):
    encoded=(json.dumps(payload,sort_keys=True)+"\n").encode();temporary=path.parent/f".{path.name}.{os.getpid()}.tmp"
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        with os.fdopen(descriptor,"wb") as stream:stream.write(encoded);stream.flush();os.fsync(stream.fileno())
        try:os.link(temporary,path,follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes()!=encoded:fail("screening_submission_record_invalid")
    finally:
        try:temporary.unlink()
        except FileNotFoundError:pass
    parent=os.open(path.parent,os.O_RDONLY);os.fsync(parent);os.close(parent)

def timestamp(value):
    return isinstance(value,int) and not isinstance(value,bool) and 0<=value<=253402300799
def valid_points(points,expected_s0):
    if not isinstance(points,list) or len(points)!=len(expected_s0):return False
    for row,s0 in zip(points,expected_s0):
        if not isinstance(row,dict) or set(row)!={"s0","captured","input","efficiency","artifacts"}:return False
        if isinstance(row["s0"],bool) or not isinstance(row["s0"],(int,float)) or not math.isfinite(row["s0"]) or float(row["s0"])!=float(s0):return False
        if not isinstance(row["captured"],int) or isinstance(row["captured"],bool) or not isinstance(row["input"],int) or isinstance(row["input"],bool) or row["input"]!=2 or not 0<=row["captured"]<=2:return False
        if isinstance(row["efficiency"],bool) or not isinstance(row["efficiency"],(int,float)) or not math.isfinite(row["efficiency"]) or float(row["efficiency"])!=row["captured"]/row["input"]:return False
        artifacts=row["artifacts"]
        if not isinstance(artifacts,dict) or set(artifacts)!={"summary_sha256","trial_sha256","database_sha256"} or not all(isinstance(value,str) and re.fullmatch(r"[0-9a-f]{64}",value) for value in artifacts.values()):return False
    return True
def safe_worktree_status(raw,root):
    safe_suffixes={'.json','.npy','.csv','.db','.sqlite','.png','.pdf','.pbs','.out','.err','.txt'}
    try:
        for record in raw.split(b'\0'):
            if not record:continue
            if len(record)<4 or record[:2]!=b'??' or record[2:3]!=b' ':return False
            text=record[3:].decode('utf-8','strict');pure=PurePosixPath(text)
            if pure.is_absolute() or pure.as_posix()!=text or any(part in {'','.','..'} for part in pure.parts):return False
            if not pure.parts or pure.parts[0] not in {'data','graphs'} or pure.suffix.lower() not in safe_suffixes:return False
            if not stat.S_ISREG(root.joinpath(*pure.parts).lstat().st_mode):return False
        return True
    except Exception:return False

def main():
    if len(sys.argv)!=5 or sys.argv[1] not in {"inspect","submit"}:fail("invalid_request")
    operation,username,requested,encoded=sys.argv[1:]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,31}",username):fail("invalid_request")
    root=Path(requested)
    try:resolved=root.resolve(strict=True)
    except OSError:fail("remote_project_missing")
    if resolved!=Path("/home")/username/"ytterbium_lab_simulation_new":fail("remote_project_missing")
    root=resolved
    try:payload=json.loads(base64.urlsafe_b64decode(encoded).decode())
    except Exception:fail("invalid_request")
    required={"campaign","commit","prepared_files","transition_files","transition_digest","submission_key","nonce"}
    if not isinstance(payload,dict) or set(payload)!=required:fail("invalid_request")
    relative=payload["campaign"];commit=payload["commit"]
    if not isinstance(relative,str) or not isinstance(commit,str) or not re.fullmatch(r"[0-9a-f]{40}",commit):fail("invalid_request")
    pure=PurePosixPath(relative)
    if pure.is_absolute() or len(pure.parts)<4 or pure.parts[:3]!=("data","optimization","mot_2d") or any(part in {"",".",".."} for part in pure.parts):fail("invalid_request")
    campaign=root.joinpath(*pure.parts);no_symlinks(root,campaign)
    try:
        head=subprocess.run(["/usr/bin/git","rev-parse","--verify","HEAD^{commit}"],cwd=root,text=True,capture_output=True,timeout=10,check=True).stdout.strip()
        dirty=subprocess.run(["/usr/bin/git","status","--porcelain=v1","-z","--untracked-files=all"],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=True).stdout
    except Exception:fail("remote_checkout_mismatch")
    if head!=commit or not safe_worktree_status(dirty,root):fail("remote_checkout_mismatch")
    prepared=payload["prepared_files"];transition=payload["transition_files"];transition_digest=payload["transition_digest"];key=payload["submission_key"]
    if not isinstance(prepared,dict) or len(prepared)!=72 or not isinstance(transition,dict) or set(transition)!={"campaign.json","screen/tasks.json","jobs/02_screen.pbs"} or not all(isinstance(v,str) and re.fullmatch(r"[0-9a-f]{64}",v) for v in [*prepared.values(),*transition.values(),transition_digest,key]):fail("invalid_request")
    if hashlib.sha256(json.dumps(transition,sort_keys=True).encode()).hexdigest()!=transition_digest:fail("invalid_request")
    # The remote manifest is the transitioned manifest, while all other frozen
    # prepared artifacts must still match their original exact bytes.
    total=0
    for name,expected in prepared.items():
        if name==f"{relative}/campaign.json":continue
        item=PurePosixPath(name)
        if item.is_absolute() or any(part in {"",".",".."} for part in item.parts):fail("invalid_request")
        path=root.joinpath(*item.parts);no_symlinks(root,path)
        try:total+=path.stat().st_size
        except OSError:fail("remote_preparation_invalid")
        if total>128*1024*1024 or not path.is_file() or digest(path)!=expected:fail("remote_preparation_invalid")
    for name,expected in transition.items():
        path=campaign/name;no_symlinks(campaign,path)
        if not path.is_file() or digest(path)!=expected:fail("screening_not_prepared")
    metadata=campaign/".mot_ui";transitions=metadata/"transitions";submissions=metadata/"submissions"
    for parent in (metadata,transitions,submissions):no_symlinks(campaign,parent)
    transition_receipt=read_json(transitions/"screen.json")
    smoke_receipt=read_json(submissions/"smoke.json")
    smoke_key=hashlib.sha256(json.dumps({"campaign":relative,"commit":commit,"manifest":prepared[f"{relative}/campaign.json"],"pbs":prepared[f"{relative}/jobs/01_smoke.pbs"]},sort_keys=True,separators=(",",":")).encode()).hexdigest()
    smoke_exact={"version","submission_key","nonce","job_file","commit","created_unix_s","status","job_id","completed_unix_s"}
    if set(smoke_receipt)!=smoke_exact or smoke_receipt.get("version")!=1 or smoke_receipt.get("status")!="submitted" or smoke_receipt.get("submission_key")!=smoke_key or smoke_receipt.get("commit")!=commit or smoke_receipt.get("job_file")!=f"{relative}/jobs/01_smoke.pbs" or not re.fullmatch(r"[0-9a-f]{32}",str(smoke_receipt.get("nonce",""))) or not re.fullmatch(r"\d+(?:\[\])?\.zeus-master",str(smoke_receipt.get("job_id",""))) or not timestamp(smoke_receipt.get("created_unix_s")) or not timestamp(smoke_receipt.get("completed_unix_s")) or smoke_receipt["completed_unix_s"]<smoke_receipt["created_unix_s"]:fail("screening_not_prepared")
    manifest=read_json(campaign/"campaign.json",1024*1024);expected_s0=manifest.get("s0_values") if isinstance(manifest,dict) else None
    transition_exact={"status","nonce","job_id","smoke_digest","points","artifact_count","commit","submission_key","transition_files","completed_unix_s"}
    if set(transition_receipt)!=transition_exact or transition_receipt.get("status")!="screening_prepared" or transition_receipt.get("commit")!=commit or transition_receipt.get("submission_key")!=smoke_key or transition_receipt.get("job_id")!=smoke_receipt.get("job_id") or not re.fullmatch(r"[0-9a-f]{32}",str(transition_receipt.get("nonce",""))) or transition_receipt.get("transition_files")!=transition or not isinstance(expected_s0,list) or not valid_points(transition_receipt.get("points"),expected_s0) or transition_receipt.get("artifact_count")!=3*len(transition_receipt["points"]) or not isinstance(transition_receipt.get("smoke_digest"),str) or not re.fullmatch(r"[0-9a-f]{64}",transition_receipt["smoke_digest"]) or hashlib.sha256(json.dumps(transition_receipt["points"],sort_keys=True).encode()).hexdigest()!=transition_receipt["smoke_digest"] or not timestamp(transition_receipt.get("completed_unix_s")) or transition_receipt["completed_unix_s"]<smoke_receipt["completed_unix_s"]:fail("screening_not_prepared")
    state_dir=submissions;no_symlinks(campaign,state_dir);state_dir.mkdir(parents=True,exist_ok=True)
    receipt=state_dir/"screening.json";pending=state_dir/"screening.pending.json";lock=state_dir/"screening.lock"
    def current():
        if receipt.exists():
            row=read_json(receipt)
            exact={"version","status","submission_key","transition_digest","nonce","job_file","commit","job_id","created_unix_s","completed_unix_s"}
            if set(row)!=exact or row.get("version")!=1 or row.get("status")!="submitted" or row.get("submission_key")!=key or row.get("transition_digest")!=transition_digest or row.get("job_file")!=f"{relative}/jobs/02_screen.pbs" or row.get("commit")!=commit or not re.fullmatch(r"\d+\[\]\.zeus-master",str(row.get("job_id",""))) or not re.fullmatch(r"[0-9a-f]{32}",str(row.get("nonce",""))) or not timestamp(row.get("created_unix_s")) or not timestamp(row.get("completed_unix_s")) or row["completed_unix_s"]<row["created_unix_s"]:fail("screening_submission_record_invalid")
            return row
        if pending.exists():
            row=read_json(pending)
            exact={"version","submission_key","transition_digest","nonce","job_file","commit","created_unix_s"}
            if set(row)!=exact or row.get("version")!=1 or row.get("submission_key")!=key or row.get("transition_digest")!=transition_digest or row.get("job_file")!=f"{relative}/jobs/02_screen.pbs" or row.get("commit")!=commit or not re.fullmatch(r"[0-9a-f]{32}",str(row.get("nonce",""))) or not timestamp(row.get("created_unix_s")):fail("screening_submission_record_invalid")
            return {"status":"ambiguous","nonce":row.get("nonce")}
        return {"status":"eligible"}
    state=current()
    branch=subprocess.run(["/usr/bin/git","branch","--show-current"],cwd=root,text=True,capture_output=True,timeout=10,check=True).stdout.strip()
    if operation=="inspect":
        if any(path.name!="tasks.json" for path in (campaign/"screen").iterdir()):fail("screening_already_started")
        print(json.dumps({**state,"branch":branch,"validated_smoke_job_id":smoke_receipt["job_id"]}));return
    if state["status"]=="submitted":print(json.dumps(state));return
    if state["status"]=="ambiguous":fail("screening_submission_outcome_unknown")
    if any(path.name!="tasks.json" for path in (campaign/"screen").iterdir()):fail("screening_already_started")
    nonce=payload["nonce"]
    if not isinstance(nonce,str) or not re.fullmatch(r"[0-9a-f]{32}",nonce):fail("invalid_request")
    try:lock.mkdir()
    except FileExistsError:fail("screening_submission_busy")
    try:
        if current()["status"]!="eligible":fail("screening_submission_outcome_unknown")
        if any(path.name!="tasks.json" for path in (campaign/"screen").iterdir()):fail("screening_already_started")
        job=(campaign/"jobs/02_screen.pbs").read_bytes()
        if hashlib.sha256(job).hexdigest()!=transition["jobs/02_screen.pbs"]:fail("screening_not_prepared")
        created=int(time.time());record={"version":1,"submission_key":key,"transition_digest":transition_digest,"nonce":nonce,"job_file":f"{relative}/jobs/02_screen.pbs","commit":commit,"created_unix_s":created}
        write_no_replace(pending,record)
        try:result=subprocess.run(["/usr/local/bin/qsub","-v","MOT_UI_SUBMISSION_ID="+nonce],input=job,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,check=False)
        except Exception:fail("screening_submission_outcome_unknown")
        try:stdout=result.stdout.decode("ascii","strict");stderr=result.stderr.decode("utf-8","replace")
        except Exception:fail("screening_submission_outcome_unknown")
        if result.returncode or stderr or not re.fullmatch(r"\d+\[\]\.zeus-master\n?",stdout):fail("screening_submission_outcome_unknown")
        job_id=stdout.rstrip("\n");final={**record,"status":"submitted","job_id":job_id,"completed_unix_s":int(time.time())};write_no_replace(receipt,final);pending.unlink();parent=os.open(state_dir,os.O_RDONLY);os.fsync(parent);os.close(parent);print(json.dumps(final))
    finally:
        try:lock.rmdir()
        except OSError:pass
if __name__=="__main__":main()
