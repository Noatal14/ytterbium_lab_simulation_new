"""Pinned receiver for validated Production-to-Production preparation."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

JOB_FILE = "jobs/06_production.pbs"
OUTPUT_FILES = {"sensitivity_summary.json", "production/tasks.json", JOB_FILE, "campaign.json"}


def fail(code: str, status: int = 20) -> None:
    print(json.dumps({"error": code}))
    raise SystemExit(status)


def canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def bounded(path: Path, limit: int = 64 * 1024 * 1024) -> bytes:
    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        row = os.fstat(fd)
        if not stat.S_ISREG(row.st_mode) or row.st_size <= 0 or row.st_size > limit:
            raise ValueError()
        remaining = row.st_size
        chunks = []
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError()
                chunks.append(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                raise ValueError()
        data = b"".join(chunks)
        if len(data) != row.st_size:
            raise ValueError()
        return data
    except Exception:
        fail("transition_conflict")
    finally:
        if fd >= 0: os.close(fd)


def read_json(path: Path, limit: int = 8 * 1024 * 1024):
    try:
        return json.loads(bounded(path, limit))
    except SystemExit:
        raise
    except Exception:
        fail("transition_conflict")


def no_links(root: Path, path: Path) -> None:
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if current.exists() and current.is_symlink():
            fail("transition_conflict")


def safe_status(raw: bytes, root: Path) -> bool:
    try:
        for record in raw.split(b"\0"):
            if not record: continue
            if record[:3] != b"?? ": return False
            relative = PurePosixPath(record[3:].decode("utf-8", "strict"))
            path = root.joinpath(*relative.parts)
            if (relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts)
                    or relative.parts[0] not in {"data", "graphs"}
                    or relative.suffix.lower() not in {".json", ".npy", ".csv", ".db",
                                                       ".sqlite", ".pbs", ".out", ".err",
                                                       ".txt", ".sh", ".lock"}
                    or path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode)):
                return False
        return True
    except Exception:
        return False


def publish(path: Path, data: bytes, mode: int = 0o600) -> None:
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(tmp, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or bounded(path) != data:
                fail("transition_outcome_unknown")
    finally:
        try: tmp.unlink()
        except FileNotFoundError: pass
    descriptor = os.open(path.parent, os.O_RDONLY)
    os.fsync(descriptor); os.close(descriptor)


def atomic_json(path: Path, value: object) -> None:
    publish(path, (json.dumps(value, sort_keys=True) + "\n").encode("utf-8"))


def timestamp(value: object) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and 0 <= value <= 253402300799)


def run_captured(argv: list[str], *, cwd: Path, limit: int, timeout: int) -> tuple[int, bytes, bytes]:
    """Run a fixed argv without allowing unbounded child output in receiver memory."""
    with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as stdout, \
            tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as stderr:
        result = subprocess.run(argv, cwd=cwd, stdout=stdout, stderr=stderr,
                                timeout=timeout, check=False)
        stdout.seek(0, os.SEEK_END); stdout_size = stdout.tell()
        stderr.seek(0, os.SEEK_END); stderr_size = stderr.tell()
        if stdout_size > limit or stderr_size > limit:
            raise ValueError("bounded process output")
        stdout.seek(0); stderr.seek(0)
        return result.returncode, stdout.read(limit + 1), stderr.read(limit + 1)


def scheduler_snapshot(output: bytes, job_id: str, task_count: int) -> dict[str, object]:
    if not isinstance(output, bytes) or len(output) > 4 * 1024 * 1024:
        raise ValueError("scheduler output")
    try: text = output.decode("utf-8", "strict")
    except UnicodeDecodeError: raise ValueError("scheduler encoding") from None
    chunks = re.split(r"(?m)^Job Id:\s*", text)
    if chunks[0].strip(): raise ValueError("scheduler preamble")
    for chunk in chunks[1:]:
        lines = chunk.splitlines(); last_key = None
        if not lines or not lines[0].strip(): raise ValueError("scheduler record")
        for line in lines[1:]:
            if not line.strip(): continue
            match = re.match(r"\s*([A-Za-z_.]+)\s*=\s*(.*?)\s*$", line)
            if match: last_key = match.group(1)
            elif line.startswith("\t") and last_key is not None: continue
            else: raise ValueError("scheduler grammar")
    from workflow_api.zeus_snapshot import _parse_qstat
    try: jobs = _parse_qstat(text)
    except Exception: raise ValueError("scheduler records") from None
    prefix = job_id.replace("[].zeus-master", "")
    children = {f"{prefix}[{index}].zeus-master" for index in range(task_count)}
    by_id = {row.get("id"): row for row in jobs}
    if (len(by_id) != len(jobs) or not children.issubset(by_id)
            or set(by_id) not in (children, children | {job_id})):
        raise ValueError("scheduler records")
    counts = {"queued": 0, "running": 0, "held": 0, "succeeded": 0, "failed": 0}
    for child in children:
        row = by_id[child]
        state = row.get("state")
        key = {"queued": "queued", "running": "running", "held_attention": "held",
               "completed_success": "succeeded", "completed_failed": "failed"}.get(state)
        if key is None or key == "succeeded" and row.get("exit_status") != 0:
            raise ValueError("scheduler state")
        counts[key] += 1
    state = ("completed_success" if counts["succeeded"] == task_count
             else "completed_failed" if counts["failed"]
             else "held" if counts["held"] else "running" if counts["running"]
             else "queued" if counts["queued"] else "unknown")
    return {"state": state, "task_count": task_count, "counts": counts,
            "job_id": job_id}


def response(lifecycle: str, scheduler: dict[str, object], rows: list[dict],
             branch: str, receipt: dict | None) -> None:
    print(json.dumps({"lifecycle": lifecycle, "scheduler": scheduler,
                      "rows": rows, "branch": branch, "receipt": receipt}))


def validate_static(payload: dict, root: Path):
    exact = {"campaign", "commit", "sensitivity_files",
             "sensitivity_transition_nonce", "sensitivity_transition_digest",
             "sensitivity_submission_key"}
    if not exact.issubset(payload) or set(payload) - exact - {
            "rows_digest", "production_files", "transition_key", "nonce"}:
        fail("invalid_request")
    relative = PurePosixPath(str(payload.get("campaign", "")))
    if (relative.is_absolute() or len(relative.parts) != 4
            or relative.parts[:3] != ("data", "optimization", "mot_2d")
            or any(part in {"", ".", ".."} for part in relative.parts)):
        fail("invalid_request")
    campaign = root.joinpath(*relative.parts)
    no_links(root, campaign)
    if not campaign.is_dir(): fail("campaign_not_found")
    commit = payload.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        fail("invalid_request")
    try:
        head_code, head_stdout, head_stderr = run_captured(
            ["/usr/bin/git", "rev-parse", "HEAD"], cwd=root, limit=4096, timeout=10)
        branch_code, branch_stdout, branch_stderr = run_captured(
            ["/usr/bin/git", "branch", "--show-current"], cwd=root,
            limit=4096, timeout=10)
    except Exception: fail("local_checkout_mismatch")
    try: head_revision = head_stdout.decode("ascii", "strict").strip()
    except UnicodeDecodeError: fail("local_checkout_mismatch")
    if head_code or head_stderr or head_revision != commit:
        fail("local_checkout_mismatch")
    try: branch = branch_stdout.decode("utf-8", "strict").strip()
    except UnicodeDecodeError: fail("remote_response_invalid")
    if branch_code or branch_stderr or not branch or len(branch) > 256 or not branch.isprintable():
        fail("remote_response_invalid")
    try:
        status_code, status_stdout, status_stderr = run_captured(
            ["/usr/bin/git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root, limit=4 * 1024 * 1024, timeout=20)
    except Exception: fail("local_checkout_mismatch")
    if status_code or status_stderr or not safe_status(status_stdout, root):
        fail("local_checkout_mismatch")
    manifest = read_json(campaign / "campaign.json")
    if (not isinstance(manifest, dict) or manifest.get("stage") not in {"sensitivity", "production", "complete"}
            or manifest.get("provenance", {}).get("git_commit") != commit):
        fail("sensitivity_preparation_invalid")
    files = payload.get("sensitivity_files")
    expected_sensitivity = {"winners.json", "sensitivity/tasks.json",
                            "jobs/05_sensitivity.pbs", "campaign.json"}
    if (not isinstance(files, dict) or set(files) != expected_sensitivity
            or any(not re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in files.values())):
        fail("sensitivity_preparation_invalid")
    transition = read_json(campaign / ".mot_ui/transitions/sensitivity.json")
    transition_exact = {"status", "nonce", "transition_key", "commit",
                        "confirmation_submission_key", "confirmation_submission_nonce",
                        "confirmation_job_id", "rows_digest", "rows", "files",
                        "scheduler", "completed_unix_s"}
    if (not isinstance(transition, dict) or set(transition) != transition_exact
            or transition.get("status") != "sensitivity_prepared"
            or transition.get("nonce") != payload["sensitivity_transition_nonce"]
            or transition.get("commit") != commit or transition.get("files") != files
            or not timestamp(transition.get("completed_unix_s"))
            or hashlib.sha256(json.dumps(
                transition, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest() != payload["sensitivity_transition_digest"]):
        fail("sensitivity_preparation_invalid")
    for name, expected_digest in files.items():
        if manifest.get("stage") in {"production", "complete"} and name == "campaign.json": continue
        path = campaign / name; no_links(campaign, path)
        if hashlib.sha256(bounded(path)).hexdigest() != expected_digest:
            fail("sensitivity_preparation_invalid")
    submission = read_json(campaign / ".mot_ui/submissions/sensitivity.json")
    submission_exact = {"version", "status", "submission_key", "transition_nonce",
                        "transition_digest", "pbs_sha256", "nonce", "job_file",
                        "commit", "created_unix_s", "job_id", "completed_unix_s"}
    if (not isinstance(submission, dict) or set(submission) != submission_exact
            or submission.get("version") != 1 or submission.get("status") != "submitted"
            or submission.get("submission_key") != payload["sensitivity_submission_key"]
            or submission.get("transition_nonce") != payload["sensitivity_transition_nonce"]
            or submission.get("transition_digest") != payload["sensitivity_transition_digest"]
            or submission.get("pbs_sha256") != files["jobs/05_sensitivity.pbs"]
            or submission.get("job_file") != f"{relative.as_posix()}/jobs/05_sensitivity.pbs"
            or submission.get("commit") != commit
            or not re.fullmatch(r"\d+\[\]\.zeus-master", str(submission.get("job_id")))
            or not re.fullmatch(r"[0-9a-f]{32}", str(submission.get("nonce")))
            or not timestamp(submission.get("created_unix_s"))
            or not timestamp(submission.get("completed_unix_s"))
            or submission["completed_unix_s"] < submission["created_unix_s"]):
        fail("sensitivity_submission_invalid")
    return campaign, manifest, branch, submission, transition


def inspect_scheduler(root: Path, submission: dict, manifest: dict) -> dict[str, object]:
    count = len(manifest["s0_values"]) * 17
    try:
        returncode, stdout, stderr = run_captured(
            ["/usr/local/bin/qstat", "-x", "-t", "-f", submission["job_id"]],
            cwd=root, limit=4 * 1024 * 1024, timeout=20)
    except Exception:
        returncode, stdout, stderr = 1, b"", b""
    if returncode or stderr:
        return {"state": "unknown", "task_count": count,
                "counts": {"queued": 0, "running": 0, "held": 0,
                           "succeeded": 0, "failed": 0},
                "job_id": submission["job_id"], "submission_nonce": submission["nonce"]}
    try:
        row = scheduler_snapshot(stdout, submission["job_id"], count)
    except Exception:
        row = {"state": "unknown", "task_count": count,
               "counts": {"queued": 0, "running": 0, "held": 0,
                          "succeeded": 0, "failed": 0},
               "job_id": submission["job_id"]}
    row["submission_nonce"] = submission["nonce"]
    return row


def lifecycle_for(scheduler: dict[str, object]) -> str:
    return {"queued": "queued", "running": "running", "held": "held",
            "completed_failed": "failed", "unknown": "status_unknown",
            "completed_success": "complete"}.get(str(scheduler["state"]), "status_unknown")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"inspect", "prepare"}:
        fail("invalid_request")
    operation = sys.argv[1]
    try:
        raw_payload = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(raw_payload) > 8 * 1024 * 1024: raise ValueError()
        payload = json.loads(raw_payload)
    except Exception: fail("invalid_request")
    if not isinstance(payload, dict): fail("invalid_request")
    root = Path.cwd().resolve(strict=True)
    campaign, manifest, branch, submission, sensitivity_transition = validate_static(payload, root)
    state = campaign / ".mot_ui"; transitions = state / "transitions"
    no_links(campaign, state); no_links(campaign, transitions)
    receipt_path = transitions / "production.json"
    pending_path = transitions / "production.pending.json"
    lock_path = transitions / "production.lock"
    for path in (receipt_path, pending_path, lock_path): no_links(campaign, path)

    scheduler = inspect_scheduler(root, submission, manifest)
    if manifest.get("stage") in {"production", "complete"} or receipt_path.exists():
        prior = json.loads(json.dumps(manifest)); prior["stage"] = "sensitivity"
        prior.get("stages", {}).pop("production", None)
        prior.get("stages", {}).pop("final_report", None)
        from workflow_api.mot_2d_validation import validated_evaluation_outputs
        from workflow_api.mot_2d_plan import render_production_transition
        try:
            rows = validated_evaluation_outputs(campaign, prior, "sensitivity")
            rendered = render_production_transition(
                prior, campaign, root, sensitivity_transition["rows"], rows,
            )
            hashes = {name: hashlib.sha256(data).hexdigest() for name, data in rendered.items()}
            expected_key = canonical_digest({
                "campaign": payload["campaign"], "commit": payload["commit"],
                "sensitivity_submission_key": payload["sensitivity_submission_key"],
                "sensitivity_submission_nonce": submission["nonce"],
                "sensitivity_job_id": submission["job_id"],
                "rows_digest": canonical_digest(rows), "files": hashes,
            })
            if not receipt_path.exists():
                pending = read_json(pending_path)
                pending_exact = {"status", "nonce", "transition_key",
                                 "sensitivity_submission_key",
                                 "sensitivity_submission_nonce", "sensitivity_job_id",
                                 "rows_digest", "files", "scheduler", "created_unix_s"}
                if (not isinstance(pending, dict) or set(pending) != pending_exact
                        or pending.get("status") != "production_pending"
                        or pending.get("sensitivity_submission_key") != payload["sensitivity_submission_key"]
                        or pending.get("sensitivity_submission_nonce") != submission["nonce"]
                        or pending.get("sensitivity_job_id") != submission["job_id"]
                        or pending.get("transition_key") != expected_key
                        or pending.get("rows_digest") != canonical_digest(rows)
                        or pending.get("files") != hashes
                        or not isinstance(pending.get("scheduler"), dict)
                        or pending["scheduler"].get("state") != "completed_success"
                        or pending["scheduler"].get("job_id") != submission["job_id"]
                        or pending["scheduler"].get("submission_nonce") != submission["nonce"]
                        or not re.fullmatch(r"[0-9a-f]{32}", str(pending.get("nonce", "")))
                        or not timestamp(pending.get("created_unix_s"))
                        or any(not (campaign / name).is_file()
                               or hashlib.sha256(bounded(campaign / name)).hexdigest() != digest
                               for name, digest in hashes.items())):
                    raise ValueError()
                scheduler = pending["scheduler"]
                receipt = {"status": "production_prepared", "nonce": pending["nonce"],
                           "transition_key": pending["transition_key"], "commit": payload["commit"],
                           "sensitivity_submission_key": payload["sensitivity_submission_key"],
                           "sensitivity_submission_nonce": submission["nonce"],
                           "sensitivity_job_id": submission["job_id"],
                           "rows_digest": canonical_digest(rows), "rows": rows,
                           "files": hashes, "scheduler": scheduler,
                           "completed_unix_s": int(time.time())}
                atomic_json(receipt_path, receipt); pending_path.unlink()
                descriptor = os.open(transitions, os.O_RDONLY)
                os.fsync(descriptor); os.close(descriptor)
            else:
                receipt = read_json(receipt_path)
                scheduler = receipt.get("scheduler")
            receipt_exact = {"status", "nonce", "transition_key", "commit",
                             "sensitivity_submission_key", "sensitivity_submission_nonce",
                             "sensitivity_job_id", "rows_digest", "rows", "files",
                             "scheduler", "completed_unix_s"}
            if (not isinstance(receipt, dict) or set(receipt) != receipt_exact
                    or receipt.get("status") != "production_prepared"
                    or receipt.get("transition_key") != expected_key
                    or receipt.get("commit") != payload["commit"]
                    or receipt.get("sensitivity_submission_key") != payload["sensitivity_submission_key"]
                    or receipt.get("sensitivity_submission_nonce") != submission["nonce"]
                    or receipt.get("sensitivity_job_id") != submission["job_id"]
                    or receipt.get("rows_digest") != canonical_digest(rows)
                    or receipt.get("rows") != rows or receipt.get("files") != hashes
                    or receipt.get("scheduler") != scheduler
                    or not isinstance(scheduler, dict)
                    or scheduler.get("state") != "completed_success"
                    or scheduler.get("job_id") != submission["job_id"]
                    or scheduler.get("submission_nonce") != submission["nonce"]
                    or not re.fullmatch(r"[0-9a-f]{32}", str(receipt.get("nonce")))
                    or not timestamp(receipt.get("completed_unix_s"))
                    or any(not (campaign / name).is_file()
                           or hashlib.sha256(bounded(campaign / name)).hexdigest() != digest
                           for name, digest in hashes.items())):
                raise ValueError()
        except Exception:
            fail("transition_outcome_unknown")
        response("production_prepared", scheduler, rows, branch, receipt); return

    if manifest.get("stage") != "sensitivity": fail("campaign_not_sensitivity")
    for path in (pending_path, campaign / "sensitivity_summary.json", campaign / "production",
                 campaign / JOB_FILE):
        no_links(campaign, path)
        if path.exists(): fail("transition_outcome_unknown")
    lifecycle = lifecycle_for(scheduler)
    rows: list[dict] = []
    if lifecycle == "complete":
        from workflow_api.mot_2d_validation import validated_evaluation_outputs
        try: rows = validated_evaluation_outputs(campaign, manifest, "sensitivity")
        except FileNotFoundError: lifecycle = "awaiting_outputs"
        except Exception: lifecycle = "outputs_invalid"
        else: lifecycle = "ready_to_prepare_production"
    if operation == "inspect" or lifecycle != "ready_to_prepare_production":
        response(lifecycle, scheduler, rows, branch, None); return

    rows_digest = canonical_digest(rows)
    from workflow_api.mot_2d_plan import render_production_transition
    rendered = render_production_transition(
        manifest, campaign, root, sensitivity_transition["rows"], rows,
    )
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in rendered.items()}
    transition_key = canonical_digest({
        "campaign": payload["campaign"], "commit": payload["commit"],
        "sensitivity_submission_key": payload["sensitivity_submission_key"],
        "sensitivity_submission_nonce": submission["nonce"],
        "sensitivity_job_id": submission["job_id"],
        "rows_digest": rows_digest, "files": hashes,
    })
    if (payload.get("rows_digest") != rows_digest
            or payload.get("production_files") != hashes
            or payload.get("transition_key") != transition_key
            or not re.fullmatch(r"[0-9a-f]{32}", str(payload.get("nonce", "")))):
        fail("transition_conflict")

    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd); fail("transition_busy")
    try:
        locked_manifest = read_json(campaign / "campaign.json")
        if locked_manifest != manifest: fail("transition_conflict")
        if read_json(campaign / ".mot_ui/submissions/sensitivity.json") != submission:
            fail("transition_conflict")
        locked_transition = read_json(campaign / ".mot_ui/transitions/sensitivity.json")
        if hashlib.sha256(json.dumps(
                locked_transition, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest() != payload["sensitivity_transition_digest"]:
            fail("transition_conflict")
        for name, expected_digest in payload["sensitivity_files"].items():
            if hashlib.sha256(bounded(campaign / name)).hexdigest() != expected_digest:
                fail("transition_conflict")
        locked_scheduler = inspect_scheduler(root, submission, manifest)
        if locked_scheduler["state"] != "completed_success" or locked_scheduler != scheduler:
            fail("sensitivity_status_unknown")
        locked_rows = validated_evaluation_outputs(campaign, manifest, "sensitivity")
        if canonical_digest(locked_rows) != rows_digest: fail("transition_conflict")
        locked_rendered = render_production_transition(
            manifest, campaign, root, locked_transition["rows"], locked_rows,
        )
        if {name: hashlib.sha256(data).hexdigest() for name, data in locked_rendered.items()} != hashes:
            fail("transition_conflict")
        for path in (receipt_path, pending_path, campaign / "sensitivity_summary.json",
                     campaign / "production", campaign / JOB_FILE): no_links(campaign, path)
        if receipt_path.exists() or pending_path.exists(): fail("transition_outcome_unknown")
        pending = {"status": "production_pending", "nonce": payload["nonce"],
                   "transition_key": transition_key,
                   "sensitivity_submission_key": payload["sensitivity_submission_key"],
                   "sensitivity_submission_nonce": submission["nonce"],
                   "sensitivity_job_id": submission["job_id"],
                   "rows_digest": rows_digest, "files": hashes,
                   "scheduler": scheduler, "created_unix_s": int(time.time())}
        atomic_json(pending_path, pending)
        for name, data in locked_rendered.items():
            if name == "campaign.json": continue
            target = campaign / name; target.parent.mkdir(parents=True, exist_ok=True)
            publish(target, data, 0o755 if target.suffix == ".pbs" else 0o644)
        temporary = campaign / f".campaign.{payload['nonce']}.tmp"
        with temporary.open("xb") as stream:
            stream.write(locked_rendered["campaign.json"]); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, campaign / "campaign.json")
        descriptor = os.open(campaign, os.O_RDONLY); os.fsync(descriptor); os.close(descriptor)
        receipt = {"status": "production_prepared", "nonce": payload["nonce"],
                   "transition_key": transition_key, "commit": payload["commit"],
                   "sensitivity_submission_key": payload["sensitivity_submission_key"],
                   "sensitivity_submission_nonce": submission["nonce"],
                   "sensitivity_job_id": submission["job_id"],
                   "rows_digest": rows_digest, "rows": locked_rows, "files": hashes,
                   "scheduler": scheduler, "completed_unix_s": int(time.time())}
        atomic_json(receipt_path, receipt); pending_path.unlink()
        descriptor = os.open(transitions, os.O_RDONLY); os.fsync(descriptor); os.close(descriptor)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN); os.close(lock_fd)
    response("production_prepared", scheduler, rows, branch, receipt)


if __name__ == "__main__": main()
