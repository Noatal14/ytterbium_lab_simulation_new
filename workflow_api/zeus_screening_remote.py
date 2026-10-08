"""Pinned Zeus-side receiver for smoke inspection and screening preparation.

Not a public CLI.  The local API invokes it through fixed SSH arguments.  It
has deliberately no scheduler-submission capability.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

def fail(code: str, status: int = 20) -> None:
    print(json.dumps({"error": code})); raise SystemExit(status)


def atomic_json_no_replace(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded=(json.dumps(payload,sort_keys=True)+"\n").encode()
    temporary=path.parent/f".{path.name}.{os.getpid()}.tmp"
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        with os.fdopen(descriptor,"wb") as stream:stream.write(encoded);stream.flush();os.fsync(stream.fileno())
        try:os.link(temporary,path,follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes()!=encoded:fail("transition_conflict")
    finally:
        try:temporary.unlink()
        except FileNotFoundError:pass
    parent=os.open(path.parent,os.O_RDONLY);os.fsync(parent);os.close(parent)


def require_no_symlink(root: Path, path: Path) -> None:
    relative=path.relative_to(root)
    current=root
    for part in relative.parts:
        current=current/part
        if current.exists() and current.is_symlink(): fail("transition_conflict")


def main() -> None:
    if len(sys.argv) != 5 or sys.argv[1] not in {"inspect", "prepare"}: fail("invalid_request")
    operation, username, requested, encoded = sys.argv[1:]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,31}", username): fail("invalid_request")
    expected_root = Path("/home") / username / "ytterbium_lab_simulation_new"
    try: root = Path(requested).resolve(strict=True)
    except OSError: fail("remote_project_missing")
    if root != expected_root or not root.is_dir(): fail("remote_project_missing")
    try: payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except Exception: fail("invalid_request")
    if not isinstance(payload, dict): fail("invalid_request")
    allowed = {"campaign", "commit", "prepared_files", "submission_key", "transition_files"} if operation == "inspect" else {"campaign", "commit", "prepared_files", "submission_key", "transition_files", "smoke_digest", "nonce"}
    if set(payload) != allowed: fail("invalid_request")
    commit = payload.get("commit"); relative = payload.get("campaign")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit) or not isinstance(relative, str): fail("invalid_request")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or len(pure.parts) < 4 or pure.parts[:3] != ("data", "optimization", "mot_2d") or any(part in {"", ".", ".."} for part in pure.parts): fail("invalid_request")
    campaign = root.joinpath(*pure.parts)
    try:
        if campaign.resolve(strict=True) != campaign or campaign.is_symlink(): fail("remote_preparation_invalid")
        head = subprocess.run(["/usr/bin/git","rev-parse","--verify","HEAD^{commit}"],cwd=root,text=True,capture_output=True,timeout=10,check=True).stdout.strip()
        dirty = subprocess.run(["/usr/bin/git","status","--porcelain=v1","--untracked-files=no","--","workflow_api","studies","simulations","utils","config.py","lab_setup"],cwd=root,text=True,capture_output=True,timeout=10,check=True).stdout
    except (OSError,subprocess.SubprocessError): fail("remote_checkout_mismatch")
    if head != commit or dirty: fail("remote_checkout_mismatch")
    # Import repository code only after the exact clean commit is established.
    from workflow_api.mot_2d_plan import render_screen_transition
    from workflow_api.mot_2d_smoke import SmokeValidationError, validate_smoke_outputs
    from workflow_api.zeus_snapshot import _parse_qstat
    prepared = payload.get("prepared_files"); submission_key = payload.get("submission_key")
    if not isinstance(prepared,dict) or len(prepared)!=72 or not isinstance(submission_key,str) or not re.fullmatch(r"[0-9a-f]{64}",submission_key): fail("invalid_request")
    total=0
    for name,digest in prepared.items():
        if not isinstance(name,str) or not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest): fail("invalid_request")
        item=PurePosixPath(name)
        if item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts): fail("invalid_request")
        path=root.joinpath(*item.parts)
        try:
            metadata=path.lstat(); resolved=path.resolve(strict=True)
            if path.is_symlink() or not path.is_file() or root not in resolved.parents: fail("remote_preparation_invalid")
            total+=metadata.st_size
            if total>128*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=digest: fail("remote_preparation_invalid")
        except OSError: fail("remote_preparation_invalid")
    manifest_path = campaign / "campaign.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except Exception: fail("remote_preparation_invalid")
    transition = render_screen_transition(manifest, campaign, root) if manifest.get("stage") == "smoke" else None
    hashes = payload.get("transition_files")
    if not isinstance(hashes, dict) or transition is not None and hashes != {name:hashlib.sha256(data).hexdigest() for name,data in transition.items()}: fail("transition_conflict")
    state_dir = campaign / ".mot_ui" / "transitions"; receipt = state_dir / "screen.json"; pending = state_dir / "screen.pending.json"
    submission = campaign / ".mot_ui" / "submissions" / "smoke.json"
    for protected in (campaign/".mot_ui",state_dir,campaign/"jobs",campaign/"screen"):
        require_no_symlink(campaign,protected)
    def read_submission():
        try:
            if submission.is_symlink() or submission.stat().st_size>16384: raise ValueError()
            row=json.loads(submission.read_text(encoding="utf-8")); identifier=row["job_id"]
            if set(row)!={"version","submission_key","nonce","job_file","commit","created_unix_s","status","job_id","completed_unix_s"} or row.get("version")!=1 or row.get("status")!="submitted" or row.get("submission_key")!=submission_key or row.get("commit")!=commit or row.get("job_file")!=f"{relative}/jobs/01_smoke.pbs" or not isinstance(identifier,str) or not re.fullmatch(r"\d+(?:\[\])?\.zeus-master",identifier) or not isinstance(row.get("nonce"),str) or not re.fullmatch(r"[0-9a-f]{32}",row["nonce"]): raise ValueError()
            return row
        except FileNotFoundError: fail("smoke_not_submitted")
        except Exception: fail("submission_record_invalid")
    if manifest.get("stage") == "screen":
        try:
            submitted=read_submission()
            if receipt.exists():
                record=json.loads(receipt.read_text())
            elif operation == "prepare" and pending.exists():
                record=json.loads(pending.read_text())
                if set(record)!={"nonce","job_id","smoke_digest","points","artifact_count"} or record.get("nonce") != payload.get("nonce") or record.get("smoke_digest") != payload.get("smoke_digest") or record.get("job_id")!=submitted["job_id"] or not isinstance(record.get("points"),list) or record.get("artifact_count")!=3*len(record["points"]): fail("transition_outcome_unknown")
                record={**record,"status":"screening_prepared","commit":commit,"submission_key":submission_key,"transition_files":hashes,"completed_unix_s":int(__import__('time').time())}
                atomic_json_no_replace(receipt,record);pending.unlink()
            else: fail("transition_outcome_unknown")
            job_id=str(record["job_id"])
            expected_receipt={"status","nonce","job_id","smoke_digest","points","artifact_count","commit","submission_key","transition_files","completed_unix_s"}
            if set(record)!=expected_receipt or record.get("status")!="screening_prepared" or record.get("commit")!=commit or record.get("submission_key")!=submission_key or record.get("transition_files")!=hashes or record.get("job_id")!=submitted["job_id"] or not re.fullmatch(r"[0-9a-f]{32}",str(record.get("nonce",""))) or not re.fullmatch(r"\d+(?:\[\])?\.zeus-master",job_id) or not isinstance(record.get("points"),list) or record.get("artifact_count")!=3*len(record["points"]) or not isinstance(record.get("completed_unix_s"),int) or hashlib.sha256(json.dumps(record["points"],sort_keys=True).encode()).hexdigest()!=record.get("smoke_digest"): fail("transition_outcome_unknown")
            for name,digest in hashes.items():
                path=campaign/name
                if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest: fail("transition_conflict")
        except Exception: fail("transition_outcome_unknown")
        print(json.dumps({"lifecycle":"screen_prepared","job_id":job_id,"raw_state":"F","exit_status":0,"points":record.get("points",[]),"artifact_count":record.get("artifact_count",0)})); return
    if manifest.get("stage") != "smoke": fail("campaign_not_smoke")
    resume_record=None
    if pending.exists():
        try: resume_record=json.loads(pending.read_text())
        except Exception: fail("transition_outcome_unknown")
        if operation!="prepare" or resume_record.get("nonce")!=payload.get("nonce") or resume_record.get("smoke_digest")!=payload.get("smoke_digest"): fail("transition_outcome_unknown")
    submitted=read_submission();job_id=submitted["job_id"]
    try:
        result=subprocess.run(["/usr/local/bin/qstat","-x","-t","-f",job_id],cwd=root,text=True,capture_output=True,timeout=20,check=False)
        if result.returncode or result.stderr: fail("scheduler_unavailable")
        jobs=_parse_qstat(result.stdout)
    except Exception: fail("scheduler_unavailable")
    identifiers={row["id"] for row in jobs}
    if "[]" in job_id:
        prefix=job_id.replace("[].zeus-master","")
        allowed={job_id}|{f"{prefix}[{index}].zeus-master" for index in range(len(manifest.get("s0_values",[])))}
        children=allowed-{job_id}
        if not identifiers or not identifiers<=allowed or not children<=identifiers: fail("scheduler_unavailable")
    elif identifiers!={job_id}: fail("scheduler_unavailable")
    if not jobs: lifecycle="unknown"; raw="?"; exit_status=None
    elif any(row["state"]=="held_attention" for row in jobs): lifecycle="held_attention"; raw="H"; exit_status=None
    elif any(row["state"]=="running" for row in jobs): lifecycle="running"; raw="R"; exit_status=None
    elif any(row["state"]=="queued" for row in jobs): lifecycle="queued"; raw="Q"; exit_status=None
    elif any(row["state"]!="completed_success" for row in jobs): lifecycle="failed"; raw=str(jobs[0]["raw_state"]); exit_status=next((row["exit_status"] for row in jobs if row["exit_status"] not in {None,0}),None)
    else:
        raw="F";exit_status=0
        required=[]
        for value in manifest.get("s0_values",[]):
            key=f"s0_{float(value):.6f}".replace(".","p")
            required.extend((campaign/"smoke"/key/"summary.json",campaign/"smoke"/key/"trials"/"trial_0000.json",campaign/"smoke"/key/"joint_screening.db"))
        if not required or any(not path.exists() for path in required): lifecycle="awaiting_outputs";points=[]
        else:
            try: points=validate_smoke_outputs(campaign,manifest)
            except SmokeValidationError: lifecycle="outputs_invalid";points=[]
            else: lifecycle="ready_to_prepare_screen"
        artifact_count=3*len(points) if points else 0
        if operation=="inspect":
            print(json.dumps({"lifecycle":lifecycle,"job_id":job_id,"raw_state":raw,"exit_status":exit_status,"points":points,"artifact_count":artifact_count}));return
        if lifecycle!="ready_to_prepare_screen": fail("smoke_outputs_invalid")
        digest=hashlib.sha256(json.dumps(points,sort_keys=True).encode()).hexdigest()
        if digest!=payload.get("smoke_digest"): fail("transition_conflict")
        nonce=payload.get("nonce")
        if not isinstance(nonce,str) or not re.fullmatch(r"[0-9a-f]{32}",nonce): fail("invalid_request")
        state_dir.mkdir(parents=True,exist_ok=True)
        lock=state_dir/"screen.lock"
        try: lock.mkdir()
        except FileExistsError: fail("transition_busy")
        try:
            if resume_record is None:
                atomic_json_no_replace(pending,{"nonce":nonce,"job_id":job_id,"smoke_digest":digest,"points":points,"artifact_count":artifact_count})
            assert transition is not None
            for name in ("screen/tasks.json","jobs/02_screen.pbs"):
                target=campaign/name;target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():
                    if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest()!=hashes[name]: fail("transition_conflict")
                    continue
                temporary=target.parent/f".{target.name}.{nonce}.tmp"
                descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o755 if target.suffix==".pbs" else 0o644)
                with os.fdopen(descriptor,"wb") as stream:stream.write(transition[name]);stream.flush();os.fsync(stream.fileno())
                try:os.link(temporary,target,follow_symlinks=False)
                except FileExistsError:fail("transition_conflict")
                finally:
                    try:temporary.unlink()
                    except FileNotFoundError:pass
                parent=os.open(target.parent,os.O_RDONLY);os.fsync(parent);os.close(parent)
            # Manifest is the commit marker and is published last.
            temporary=campaign/f".campaign.{nonce}.tmp"
            with temporary.open("xb") as stream:stream.write(transition["campaign.json"]);stream.flush();os.fsync(stream.fileno())
            if manifest_path.read_bytes()!=manifest_bytes: fail("transition_conflict")
            os.replace(temporary,manifest_path)
            record={"status":"screening_prepared","nonce":nonce,"job_id":job_id,"smoke_digest":digest,"points":points,"artifact_count":artifact_count,"commit":commit,"submission_key":submission_key,"transition_files":hashes,"completed_unix_s":int(__import__('time').time())}
            atomic_json_no_replace(receipt,record);pending.unlink()
        finally:
            try:lock.rmdir()
            except OSError:pass
        print(json.dumps({"lifecycle":"screen_prepared","job_id":job_id,"raw_state":raw,"exit_status":0,"points":points,"artifact_count":artifact_count}));return
    if operation=="prepare": fail("smoke_status_unknown")
    print(json.dumps({"lifecycle":lifecycle,"job_id":job_id,"raw_state":raw,"exit_status":exit_status,"points":[],"artifact_count":0}))


if __name__ == "__main__": main()
