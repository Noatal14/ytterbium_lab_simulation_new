"""Repository-owned Zeus receiver for scalar individual Zeeman jobs.

Executed only by :mod:`workflow_api.pinned_ssh`; all subprocess argument
vectors are fixed here and no caller-provided command or path is executed.
"""

import base64
try:
    import fcntl
except ImportError:  # Only imported on Windows; remote execution remains POSIX.
    from workflow_api.platform_io import locking as fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


MAX_REQUEST = 3 * 1024 * 1024
MAX_PRODUCT = 4 * 1024 * 1024
HEX = re.compile(r"^[0-9a-f]{64}$")
NONCE = re.compile(r"^[0-9a-f]{32}$")
JOB = re.compile(r"^[1-9][0-9]*\.zeus-master$")


def fail(code, status=20):
    print(json.dumps({"error": code}, separators=(",", ":")))
    raise SystemExit(status)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name); stream.write(content); stream.flush(); os.fsync(stream.fileno())
    try:
        os.chmod(temporary, 0o600); os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def validate_identity(value, username, project):
    expected = {"version", "run_id", "commit", "username", "project_directory",
                "package_sha256", "pbs_sha256", "submission_key", "records", "pbs"}
    if not isinstance(value, dict) or set(value) != expected or value["version"] != 1:
        fail("remote_package_invalid")
    if value["username"] != username or value["project_directory"] != str(project):
        fail("remote_package_invalid")
    if not all(HEX.fullmatch(str(value[key])) for key in ("package_sha256", "pbs_sha256", "submission_key")):
        fail("remote_package_invalid")
    if not isinstance(value["records"], dict) or set(value["records"]) != {"run", "configuration", "inputs", "status"}:
        fail("remote_package_invalid")
    try:
        records = {name: base64.b64decode(content, validate=True)
                   for name, content in value["records"].items()}
        pbs = base64.b64decode(value["pbs"], validate=True)
    except Exception:
        fail("remote_package_invalid")
    manifest = {"version": 1, "run_id": value["run_id"], "commit": value["commit"],
                "username": username, "project_directory": str(project),
                "records": {name: hashlib.sha256(content).hexdigest()
                            for name, content in records.items()}}
    package_hash = hashlib.sha256(canonical(manifest)).hexdigest()
    pbs_hash = hashlib.sha256(pbs).hexdigest()
    key = hashlib.sha256(canonical({"package_sha256": package_hash,
        "pbs_sha256": pbs_hash, "run_id": value["run_id"], "commit": value["commit"],
        "username": username, "project_directory": str(project)})).hexdigest()
    if (package_hash, pbs_hash, key) != (value["package_sha256"], value["pbs_sha256"], value["submission_key"]):
        fail("remote_package_invalid")
    return pbs


def load(path):
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_PRODUCT: raise ValueError
        return json.loads(raw)
    except Exception:
        fail("remote_package_invalid")


def verify_commit(expected):
    try:
        result = subprocess.run(
            ["/usr/bin/git", "rev-parse", "--verify", "HEAD^{commit}"],
            cwd=project, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            shell=False, close_fds=True, timeout=10, check=False,
        )
        observed = result.stdout.decode("ascii").strip()
    except Exception:
        fail("remote_package_invalid")
    if result.returncode or observed != expected:
        fail("remote_package_invalid")


operation, username, requested, encoded = sys.argv[1:5]
try:
    project = Path(requested).resolve(strict=True)
    expected_project = (Path("/home") / username / "ytterbium_lab_simulation_new").resolve(strict=True)
    if project != expected_project or not project.is_dir(): raise ValueError
    request_raw = base64.urlsafe_b64decode(encoded)
    if len(request_raw) > MAX_REQUEST: raise ValueError
    request = json.loads(request_raw)
except Exception:
    fail("remote_project_missing")

root = project / ".workflow" / "individual-zeeman"
submissions = root / "submissions"
submissions.mkdir(parents=True, exist_ok=True)

if operation in {"inspect", "stage", "submit"}:
    if not isinstance(request, dict) or set(request) != {"identity", "nonce"} or not NONCE.fullmatch(str(request["nonce"])):
        fail("remote_request_invalid")
    identity = request["identity"]; nonce = request["nonce"]
    pbs = validate_identity(identity, username, project)
    verify_commit(identity["commit"])
    key = identity["submission_key"]; package_hash = identity["package_sha256"]
    package_dir = root / package_hash
    receipt_path = submissions / (key + ".json")
    pending_path = submissions / (key + ".pending.json")
    lock_path = submissions / (key + ".lock")
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(lock_fd); fail("submission_busy", 24)
    try:
        if receipt_path.exists():
            receipt = load(receipt_path)
            if receipt.get("submission_key") != key:
                fail("remote_package_invalid")
            if operation != "inspect" and receipt.get("nonce") != nonce:
                fail("remote_package_invalid")
            print(canonical({"state": "submitted", "nonce": receipt.get("nonce"), "job_id": receipt.get("job_id")}).decode()); raise SystemExit
        if pending_path.exists():
            pending = load(pending_path)
            if pending.get("submission_key") != key:
                fail("remote_package_invalid")
            if operation != "inspect" and pending.get("nonce") != nonce:
                fail("remote_package_invalid")
            fail("submission_outcome_unknown", 25)
        if operation == "inspect":
            print(canonical({"state": "absent", "nonce": None, "job_id": None}).decode()); raise SystemExit
        staged = canonical(identity)
        package_path = package_dir / "package.json"
        if package_path.exists():
            if package_path.read_bytes() != staged: fail("remote_package_invalid")
        else:
            package_dir.mkdir(parents=True, exist_ok=False); atomic(package_path, staged)
        if operation == "stage":
            print(canonical({"state": "absent", "nonce": nonce, "job_id": None}).decode()); raise SystemExit
        atomic(pending_path, canonical({"version": 1, "submission_key": key,
                                       "package_sha256": package_hash, "nonce": nonce}))
        try:
            result = subprocess.run(["/usr/local/bin/qsub"], input=pbs,
                cwd=project, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={"PATH": "/opt/pbs/bin:/usr/local/bin:/usr/bin:/bin",
                     "HOME": str(Path("/home") / username), "LC_ALL": "C"},
                shell=False, close_fds=True, timeout=30, check=False)
            job_id = result.stdout.decode("ascii").strip()
        except Exception:
            fail("submission_outcome_unknown", 25)
        if result.returncode or not JOB.fullmatch(job_id):
            fail("submission_outcome_unknown", 25)
        receipt = {"version": 1, "submission_key": key, "package_sha256": package_hash,
                   "nonce": nonce, "job_id": job_id, "commit": identity["commit"],
                   "username": username, "project_directory": identity["project_directory"]}
        atomic(receipt_path, canonical(receipt)); pending_path.unlink()
        print(canonical({"state": "submitted", "nonce": nonce, "job_id": job_id}).decode())
    finally:
        try: fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally: os.close(lock_fd)
elif operation in {"status", "retrieve"}:
    expected = {"job_id", "submission_key"} if operation == "status" else {"job_id", "submission_key", "package_sha256"}
    if not isinstance(request, dict) or set(request) != expected or not JOB.fullmatch(str(request["job_id"])) or not HEX.fullmatch(str(request["submission_key"])):
        fail("remote_request_invalid")
    receipt = load(submissions / (request["submission_key"] + ".json"))
    if receipt.get("job_id") != request["job_id"] or receipt.get("submission_key") != request["submission_key"]:
        fail("remote_package_invalid")
    if receipt.get("username") != username or receipt.get("project_directory") != str(project):
        fail("remote_package_invalid")
    verify_commit(receipt.get("commit"))
    if operation == "status":
        try:
            result = subprocess.run(["/usr/local/bin/qstat", "-x", "-t", "-f", request["job_id"]],
                cwd=project, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={"PATH": "/opt/pbs/bin:/usr/local/bin:/usr/bin:/bin", "HOME": str(Path("/home") / username), "LC_ALL": "C"},
                shell=False, close_fds=True, timeout=20, check=False)
            text = result.stdout.decode("utf-8", "strict")
        except Exception:
            fail("job_status_unavailable")
        state_match = re.search(r"^\s*job_state = ([A-Z])\s*$", text, re.M)
        exit_match = re.search(r"^\s*Exit_status = (-?[0-9]+)\s*$", text, re.M)
        states = {"Q": "queued", "H": "queued", "R": "running", "F": "succeeded", "X": "succeeded"}
        if result.returncode or state_match is None or state_match.group(1) not in states:
            fail("job_status_unavailable")
        exit_status = int(exit_match.group(1)) if exit_match else None
        state = states[state_match.group(1)]
        if state == "succeeded" and exit_status != 0: state = "failed"
        print(canonical({"job_id": request["job_id"], "state": state, "exit_status": exit_status}).decode())
    else:
        if request["package_sha256"] != receipt.get("package_sha256"):
            fail("remote_package_invalid")
        product = load(root / receipt["package_sha256"] / "worker_product.json")
        if (set(product) != {"version", "run_id", "package_sha256", "submission_key", "results", "receipt", "artifacts"}
            or product["package_sha256"] != request["package_sha256"]
            or product["submission_key"] != request["submission_key"]):
            fail("result_unavailable")
        print(canonical({"results": product["results"], "receipt": product["receipt"], "artifacts": product["artifacts"]}).decode())
else:
    fail("remote_request_invalid")
