"""Allowlisted remote receiver for scalar individual 3D-MOT Zeus jobs."""

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
from io import BytesIO
import stat

MAX_REQUEST = 8 * 1024 * 1024
MAX_PRODUCT = 4 * 1024 * 1024
HEX = re.compile(r"^[0-9a-f]{64}$"); NONCE = re.compile(r"^[0-9a-f]{32}$")
JOB = re.compile(r"^[1-9][0-9]*\.zeus-master$")


def canonical(value): return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
def fail(code, status=20): print(canonical({"error": code}).decode()); raise SystemExit(status)


def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name); stream.write(content); stream.flush(); os.fsync(stream.fileno())
    try:
        os.chmod(temporary, 0o600); os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally: temporary.unlink(missing_ok=True)


def bounded_bytes(path, maximum):
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
        or before.st_size > maximum):
        raise ValueError
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor); raw = os.read(descriptor, maximum + 1)
        after = os.fstat(descriptor)
    finally: os.close(descriptor)
    if (len(raw) != opened.st_size or
        (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) !=
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
        raise ValueError
    return raw


def load(path, maximum=MAX_PRODUCT):
    try:
        return json.loads(bounded_bytes(path, maximum))
    except Exception: fail("remote_package_invalid")


def verify_commit(project, expected):
    result = subprocess.run(
        ["/usr/bin/git", "rev-parse", "--verify", "HEAD^{commit}"], cwd=project,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, shell=False,
        close_fds=True, timeout=10, check=False,
    )
    if result.returncode or result.stdout.decode("ascii").strip() != expected:
        fail("remote_package_invalid")


def validate_identity(value, username, project):
    exact = {"version", "family", "run_id", "commit", "username", "project_directory",
             "package_sha256", "pbs_sha256", "submission_key", "records",
             "selected_states", "selected_states_sha256", "selection_sha256", "pbs"}
    if not isinstance(value, dict) or set(value) != exact or value["version"] != 1 or value["family"] != "mot_3d":
        fail("remote_package_invalid")
    if value["username"] != username or value["project_directory"] != str(project): fail("remote_package_invalid")
    if not all(HEX.fullmatch(str(value[key])) for key in ("package_sha256", "pbs_sha256", "submission_key", "selected_states_sha256", "selection_sha256")):
        fail("remote_package_invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", str(value.get("commit"))): fail("remote_package_invalid")
    verify_commit(project, value["commit"])
    try:
        records = {name: base64.b64decode(content, validate=True) for name, content in value["records"].items()}
        selected = base64.b64decode(value["selected_states"], validate=True)
        pbs = base64.b64decode(value["pbs"], validate=True)
    except Exception: fail("remote_package_invalid")
    if set(records) != {"run", "configuration", "inputs", "status"} or len(selected) > 3 * 1024 * 1024:
        fail("remote_package_invalid")
    try:
        sys.path.insert(0, str(project))
        from workflow_api.run_records import decode_record
        from workflow_api.mot_3d_run_specification import MOT_3D_RUN_SPECIFICATION, MOT_3D_RUN_SPEC_SHA256
        from workflow_api.mot_3d_zeus_execution import _render_pbs
        from lab_setup.physical_specification import LABORATORY_SPEC_VERSION, LABORATORY_SPEC_SHA256, CANONICAL_ZEEMAN_PROFILE_SHA256, validate_laboratory_provenance_identity
        from lab_setup.numerical_policy import NUMERICAL_POLICY_VERSION, NUMERICAL_POLICY_SHA256
        import numpy as np
        decoded = {name: decode_record(name, content) for name, content in records.items()}
        run = decoded["run"]; configuration = decoded["configuration"]
        inputs = decoded["inputs"]; status = decoded["status"]
        resolved = configuration["resolved"]; sampling = resolved["sampling"]
        validate_laboratory_provenance_identity(
            configuration["laboratory_spec"]["version"],
            configuration["laboratory_spec"]["sha256"],
            CANONICAL_ZEEMAN_PROFILE_SHA256,
        )
        fixed = MOT_3D_RUN_SPECIFICATION["fixed_classification"]
        states = np.load(BytesIO(selected), allow_pickle=False)
        expected_selection = hashlib.sha256(canonical(sampling["selected_identities"])).hexdigest()
        if (
            run["run_id"] != value["run_id"] or run["git_revision"] != value["commit"]
            or run["family"] != "mot_3d" or run["execution_mode"] != "zeus"
            or run["particle_count"] > MOT_3D_RUN_SPECIFICATION["particle_count"]["maximum_by_execution_mode"]["zeus"]
            or run["configuration_sha256"] != hashlib.sha256(records["configuration"]).hexdigest()
            or run["inputs_sha256"] != hashlib.sha256(records["inputs"]).hexdigest()
            or configuration["run_id"] != run["run_id"] or configuration["family"] != "mot_3d"
            or inputs["run_id"] != run["run_id"] or inputs["family"] != "mot_3d"
            or status["run_id"] != run["run_id"] or status["revision"] != 0
            or status["state"] != "configured" or status["execution"] != {"mode": "zeus", "local_pid": None, "zeus_job_id": None}
            or configuration["laboratory_spec"] != {"version": LABORATORY_SPEC_VERSION, "sha256": LABORATORY_SPEC_SHA256}
            or configuration["numerical_policy"] != {"version": NUMERICAL_POLICY_VERSION, "sha256": NUMERICAL_POLICY_SHA256}
            or resolved["admission_specification"] != {"version": MOT_3D_RUN_SPECIFICATION["spec_version"], "sha256": MOT_3D_RUN_SPEC_SHA256}
            or resolved["execution"] != {"mode": "zeus", "workers": MOT_3D_RUN_SPECIFICATION["workers_by_execution_mode"]["zeus"]}
            or resolved["numerical_policy"] != {"solver": fixed["solver"], "dt_s": fixed["timestep_s"], "t_max_s": fixed["t_max_s"], "convergence_claim": fixed["convergence_claim"]}
            or resolved["simulation"]["gravity_enabled"] is not fixed["gravity_enabled"]
            or resolved["simulation"]["stochastic"] is not True
            or resolved["mot_3d"]["capture"] != dict(fixed["capture"])
            or sampling["algorithm"] != MOT_3D_RUN_SPECIFICATION["sampling"]["algorithm"]
            or sampling["version"] != MOT_3D_RUN_SPECIFICATION["sampling"]["version"]
            or sampling["canonical_order"] != MOT_3D_RUN_SPECIFICATION["sampling"]["canonical_order"]
            or sampling["selected_count"] != run["particle_count"]
            or sampling["selected_identities_sha256"] != value["selection_sha256"]
            or expected_selection != value["selection_sha256"]
            or states.dtype != np.float64 or states.shape != (run["particle_count"], 6)
            or not np.all(np.isfinite(states))
        ):
            fail("remote_package_invalid")
    except SystemExit:
        raise
    except Exception:
        fail("remote_package_invalid")
    manifest = {"version": 1, "family": "mot_3d", "run_id": value["run_id"],
        "commit": value["commit"], "username": username, "project_directory": str(project),
        "records": {name: hashlib.sha256(content).hexdigest() for name, content in records.items()},
        "selected_states_sha256": hashlib.sha256(selected).hexdigest(),
        "selected_states_size": len(selected), "selection_sha256": value["selection_sha256"]}
    package_hash = hashlib.sha256(canonical(manifest)).hexdigest()
    pbs_hash = hashlib.sha256(pbs).hexdigest()
    key = hashlib.sha256(canonical({"package_sha256": package_hash, "pbs_sha256": pbs_hash,
        "run_id": value["run_id"], "commit": value["commit"], "username": username,
        "project_directory": str(project)})).hexdigest()
    if (package_hash, pbs_hash, key, manifest["selected_states_sha256"]) != (value["package_sha256"], value["pbs_sha256"], value["submission_key"], value["selected_states_sha256"]):
        fail("remote_package_invalid")
    reconstructed = _render_pbs(run, package_hash, str(project))
    if pbs != reconstructed or hashlib.sha256(reconstructed).hexdigest() != value["pbs_sha256"]:
        fail("remote_package_invalid")
    return reconstructed


operation, username, requested, encoded = sys.argv[1:5]
try:
    project = Path(requested).resolve(strict=True)
    allowed = {Path("/home") / username / name for name in ("ytterbium_lab_simulation_new", "ytterbium_lab_simulation_ui_test")}
    request_raw = (
        sys.stdin.buffer.read(MAX_REQUEST + 1)
        if encoded == "-" else base64.urlsafe_b64decode(encoded)
    )
    if Path(requested) not in allowed or project != Path(requested) or not project.is_dir() or len(request_raw) > MAX_REQUEST: raise ValueError
    request = json.loads(request_raw)
except Exception: fail("remote_project_missing")

root = project / ".workflow" / "individual-mot-3d"; submissions = root / "submissions"
submissions.mkdir(parents=True, exist_ok=True)
if operation in {"inspect", "stage", "submit"}:
    if not isinstance(request, dict) or set(request) != {"identity", "nonce"} or not NONCE.fullmatch(str(request["nonce"])): fail("remote_request_invalid")
    identity = request["identity"]; nonce = request["nonce"]
    pbs = validate_identity(identity, username, project)
    key = identity["submission_key"]; package_hash = identity["package_sha256"]
    package_dir = root / package_hash; receipt_path = submissions / (key + ".json")
    pending_path = submissions / (key + ".pending.json"); lock_path = submissions / (key + ".lock")
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try: fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: os.close(lock_fd); fail("submission_busy", 24)
    try:
        if receipt_path.exists():
            receipt = load(receipt_path)
            if receipt.get("submission_key") != key or (operation != "inspect" and receipt.get("nonce") != nonce): fail("remote_package_invalid")
            print(canonical({"state": "submitted", "nonce": receipt["nonce"], "job_id": receipt["job_id"]}).decode()); raise SystemExit
        if pending_path.exists(): fail("submission_outcome_unknown", 25)
        if operation == "inspect": print(canonical({"state": "absent", "nonce": None, "job_id": None}).decode()); raise SystemExit
        staged = canonical(identity); package_path = package_dir / "package.json"
        if package_path.exists():
            try: existing_package = bounded_bytes(package_path, MAX_REQUEST)
            except Exception: fail("remote_package_invalid")
            if existing_package != staged: fail("remote_package_invalid")
        else: package_dir.mkdir(parents=True, exist_ok=False); atomic(package_path, staged)
        if operation == "stage": print(canonical({"state": "absent", "nonce": nonce, "job_id": None}).decode()); raise SystemExit
        atomic(pending_path, canonical({"version": 1, "submission_key": key, "package_sha256": package_hash, "nonce": nonce}))
        try:
            result = subprocess.run(["/usr/local/bin/qsub"], input=pbs, cwd=project,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={"PATH": "/opt/pbs/bin:/usr/local/bin:/usr/bin:/bin", "HOME": str(Path("/home") / username), "LC_ALL": "C"},
                shell=False, close_fds=True, timeout=30, check=False)
            job_id = result.stdout.decode("ascii").strip()
        except Exception: fail("submission_outcome_unknown", 25)
        if result.returncode or not JOB.fullmatch(job_id): fail("submission_outcome_unknown", 25)
        receipt = {"version": 1, "submission_key": key, "package_sha256": package_hash,
            "nonce": nonce, "job_id": job_id, "run_id": identity["run_id"],
            "commit": identity["commit"],
            "username": username, "project_directory": identity["project_directory"]}
        atomic(receipt_path, canonical(receipt)); pending_path.unlink()
        print(canonical({"state": "submitted", "nonce": nonce, "job_id": job_id}).decode())
    finally:
        try: fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally: os.close(lock_fd)
elif operation in {"status", "retrieve"}:
    exact = {"job_id", "submission_key"} if operation == "status" else {"job_id", "submission_key", "package_sha256"}
    if not isinstance(request, dict) or set(request) != exact or not JOB.fullmatch(str(request["job_id"])) or not HEX.fullmatch(str(request["submission_key"])): fail("remote_request_invalid")
    receipt = load(submissions / (request["submission_key"] + ".json"))
    if receipt.get("job_id") != request["job_id"] or receipt.get("username") != username or receipt.get("project_directory") != str(project): fail("remote_package_invalid")
    verify_commit(project, receipt["commit"])
    if operation == "status":
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            result = subprocess.run(["/usr/local/bin/qstat", "-x", "-t", "-f", request["job_id"]], cwd=project,
                stdout=stdout, stderr=stderr, env={"PATH": "/opt/pbs/bin:/usr/local/bin:/usr/bin:/bin", "HOME": str(Path("/home") / username), "LC_ALL": "C"}, shell=False, close_fds=True, timeout=20, check=False)
            if stdout.tell() > 256 * 1024 or stderr.tell() > 64 * 1024: fail("job_status_unavailable")
            stdout.seek(0); text = stdout.read().decode("utf-8", "strict")
        job_match = re.search(r"^Job Id: ([^\s]+)\s*$", text, re.M)
        state_match = re.search(r"^\s*job_state = ([A-Z])\s*$", text, re.M)
        exit_match = re.search(r"^\s*Exit_status = (-?[0-9]+)\s*$", text, re.M)
        states = {"Q": "queued", "H": "queued", "R": "running", "F": "succeeded", "X": "succeeded"}
        if (result.returncode or job_match is None or job_match.group(1) != request["job_id"]
            or state_match is None or state_match.group(1) not in states): fail("job_status_unavailable")
        exit_status = int(exit_match.group(1)) if exit_match else None; state = states[state_match.group(1)]
        if state == "succeeded" and exit_status != 0: state = "failed"
        print(canonical({"job_id": request["job_id"], "state": state, "exit_status": exit_status}).decode())
    else:
        if request["package_sha256"] != receipt.get("package_sha256"): fail("remote_package_invalid")
        product = load(root / receipt["package_sha256"] / "worker_product.json")
        exact_product = {"version", "run_id", "job_id", "package_sha256", "submission_key", "results", "receipt", "artifacts"}
        if (not isinstance(product, dict) or set(product) != exact_product or product.get("version") != 1
            or product.get("run_id") != receipt.get("run_id")
            or product.get("job_id") != request["job_id"]
            or product.get("package_sha256") != request["package_sha256"]
            or product.get("submission_key") != request["submission_key"]
            or not isinstance(product.get("artifacts"), dict)):
            fail("result_unavailable")
        try:
            sys.path.insert(0, str(project))
            from workflow_api.run_records import encode_record, decode_record
            results = product["results"]
            decode_record("results", encode_record("results", results))
            if results["run_id"] != product["run_id"] or results["suitability"] != "individual_only":
                raise ValueError
            registry = {row["path"]: row for row in results["artifacts"]}
            if len(registry) != len(results["artifacts"]) or set(registry) != set(product["artifacts"]):
                raise ValueError
            decoded_artifacts = {}
            total = 0
            for name, encoded_artifact in product["artifacts"].items():
                raw = base64.b64decode(encoded_artifact, validate=True)
                total += len(raw)
                if total > MAX_PRODUCT or len(raw) != registry[name]["size_bytes"] or hashlib.sha256(raw).hexdigest() != registry[name]["sha256"]:
                    raise ValueError
                decoded_artifacts[name] = raw
            retained = results["states_retained"]
            if retained:
                if product["receipt"] is not None or set(registry) != {"results/states.npy"}:
                    raise ValueError
                states = np.load(BytesIO(decoded_artifacts["results/states.npy"]), allow_pickle=False)
                if (states.dtype != np.float64 or states.ndim != 2 or states.shape[1] != 6
                    or len(states) != results["metrics"].get("n_survivors")
                    or not np.all(np.isfinite(states))):
                    raise ValueError
            else:
                if not isinstance(product["receipt"], dict) or set(registry) != {"results/state_retention_receipt.json"}:
                    raise ValueError
                receipt_bytes = encode_record("retention_receipt", product["receipt"])
                if decoded_artifacts["results/state_retention_receipt.json"] != receipt_bytes:
                    raise ValueError
        except Exception:
            fail("result_unavailable")
        print(canonical({"results": product["results"], "receipt": product["receipt"], "artifacts": product["artifacts"]}).decode())
else: fail("remote_request_invalid")
