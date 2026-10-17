"""Pinned remote receiver for the canonical five-array 3D Discovery chain."""

from __future__ import annotations

import base64
try:
    import fcntl
except ImportError:  # Only imported on Windows; remote execution remains POSIX.
    from workflow_api.platform_io import locking as fcntl
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any


RENDERED_FILES = {
    "campaign.json",
    "jobs/01_smoke_angled_donut.pbs",
    "jobs/01_smoke_single_pass.pbs",
    "jobs/02_submit_discovery_chain.sh",
    "jobs/angled_donut/round_01.pbs",
    "jobs/angled_donut/round_02.pbs",
    "jobs/single_pass/round_01.pbs",
    "jobs/single_pass/round_02.pbs",
    "jobs/single_pass/round_03.pbs",
}
JOBS = {
    "angled_donut": (
        "jobs/angled_donut/round_01.pbs",
        "jobs/angled_donut/round_02.pbs",
    ),
    "single_pass": (
        "jobs/single_pass/round_01.pbs",
        "jobs/single_pass/round_02.pbs",
        "jobs/single_pass/round_03.pbs",
    ),
}
HEX32 = re.compile(r"[0-9a-f]{32}")
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
JOB_ID = re.compile(r"\d+\[\]\.zeus-master")


def fail(code: str, status: int = 20) -> None:
    print(json.dumps({"error": code}))
    raise SystemExit(status)


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def timestamp(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= 253402300799
    )


def no_links(root: Path, path: Path) -> None:
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if current.exists() and current.is_symlink():
            fail("discovery_submission_outcome_unknown")


def bounded(path: Path, limit: int = 8 * 1024 * 1024) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            fail("discovery_preparation_invalid")
        raw = bytearray()
        while len(raw) <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
        identity = lambda row: (
            row.st_dev,
            row.st_ino,
            row.st_size,
            row.st_mtime_ns,
            row.st_ctime_ns,
        )
        if len(raw) != before.st_size or identity(before) != identity(after):
            fail("discovery_preparation_invalid")
        return bytes(raw)
    except SystemExit:
        raise
    except OSError:
        fail("discovery_preparation_invalid")
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def read_json(path: Path, keys: set[str], limit: int = 1024 * 1024) -> dict[str, Any]:
    try:
        value = json.loads(
            bounded(path, limit),
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except SystemExit:
        raise
    except Exception:
        fail("discovery_preparation_invalid")
    if not isinstance(value, dict) or set(value) != keys:
        fail("discovery_preparation_invalid")
    return value


def write_record(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
    except FileExistsError:
        fail("discovery_submission_outcome_unknown")
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    parent = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def run_captured(
    argv: list[str], *, input_data: bytes | None = None, limit: int = 4 * 1024 * 1024
) -> tuple[int, bytes, bytes]:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(
            argv,
            input=input_data,
            stdout=stdout,
            stderr=stderr,
            timeout=30,
            check=False,
        )
        stdout.seek(0, os.SEEK_END)
        stdout_size = stdout.tell()
        stderr.seek(0, os.SEEK_END)
        stderr_size = stderr.tell()
        if stdout_size > limit or stderr_size > limit:
            fail("discovery_submission_outcome_unknown")
        stdout.seek(0)
        stderr.seek(0)
        return result.returncode, stdout.read(limit + 1), stderr.read(limit + 1)


def response(
    lifecycle: str,
    branch: str,
    chain: dict[str, list[str]],
    nonce: str | None = None,
    stamp: int | None = None,
) -> None:
    print(
        json.dumps(
            {
                "lifecycle": lifecycle,
                "branch": branch,
                "chain": chain,
                "submission_nonce": nonce,
                "submitted_unix_s": stamp,
            }
        )
    )


def _empty_chain() -> dict[str, list[str]]:
    return {"angled_donut": [], "single_pass": []}


def scheduler_state(raw: bytes, job_id: str) -> str:
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return "status_unknown"
    chunks = re.split(r"(?m)^Job Id:\s*", text)
    if chunks[0].strip():
        return "status_unknown"
    prefix = job_id.split("[]", 1)[0]
    expected = {f"{prefix}[{index}].zeus-master" for index in range(3)}
    states: list[str] = []
    seen: set[str] = set()
    for chunk in chunks[1:]:
        lines = chunk.splitlines()
        identifier = lines[0].strip() if lines else ""
        if identifier not in expected | {job_id} or identifier in seen:
            return "status_unknown"
        seen.add(identifier)
        fields: dict[str, str] = {}
        for line in lines[1:]:
            match = re.fullmatch(r"\s*([A-Za-z_]+)\s*=\s*(.*?)\s*", line)
            if not match or match.group(1) in fields:
                return "status_unknown"
            fields[match.group(1)] = match.group(2)
        if identifier == job_id:
            continue
        state = fields.get("job_state")
        if state in {"Q", "W"}:
            states.append("queued")
        elif state in {"R", "E"}:
            states.append("running")
        elif state in {"H", "S"}:
            states.append("held")
        elif state in {"F", "X"} and fields.get("Exit_status") == "0":
            states.append("completed_success")
        elif state in {"F", "X"} and "Exit_status" in fields:
            states.append("completed_failed")
        else:
            states.append("status_unknown")
    if not expected.issubset(seen) or seen - expected not in (set(), {job_id}):
        return "status_unknown"
    for state in ("completed_failed", "held", "status_unknown", "running", "queued"):
        if state in states:
            return state
    return "completed_success"


def main() -> None:
    if len(sys.argv) != 5 or sys.argv[1] not in {"inspect", "submit", "status"}:
        fail("invalid_request")
    operation, username, project, encoded = sys.argv[1:]
    if (
        re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,31}", username) is None
        or project != f"/home/{username}/ytterbium_lab_simulation_new"
    ):
        fail("invalid_request")
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded))
        requested_root = Path(project)
        root = requested_root.resolve(strict=True)
        if root != requested_root:
            fail("invalid_request")
        relative = PurePosixPath(payload["campaign"])
    except Exception:
        fail("invalid_request")
    base_keys = {
        "campaign",
        "commit",
        "bootstrap_digest",
        "bootstrap_key",
        "bootstrap_nonce",
        "files",
        "submission_key",
    }
    if not isinstance(payload, dict) or set(payload) != base_keys | (
        {"nonce"} if operation == "submit" else set()
    ):
        fail("invalid_request")
    if (
        relative.is_absolute()
        or len(relative.parts) != 4
        or relative.parts[:3] != ("data", "optimization", "mot_3d")
        or any(part in {"", ".", ".."} for part in relative.parts)
        or HEX40.fullmatch(str(payload["commit"])) is None
        or HEX64.fullmatch(str(payload["bootstrap_digest"])) is None
        or HEX64.fullmatch(str(payload["bootstrap_key"])) is None
        or HEX32.fullmatch(str(payload["bootstrap_nonce"])) is None
        or HEX64.fullmatch(str(payload["submission_key"])) is None
    ):
        fail("invalid_request")
    files = payload["files"]
    if (
        not isinstance(files, dict)
        or set(files) != RENDERED_FILES
        or any(HEX64.fullmatch(str(value)) is None for value in files.values())
    ):
        fail("invalid_request")
    campaign = root.joinpath(*relative.parts)
    no_links(root, campaign)
    try:
        git_code, git_stdout, git_stderr = run_captured(
            ["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"], limit=4096
        )
        branch_code, branch_stdout, branch_stderr = run_captured(
            ["/usr/bin/git", "-C", str(root), "branch", "--show-current"],
            limit=4096,
        )
    except Exception:
        fail("remote_checkout_mismatch")
    try:
        revision = git_stdout.decode("ascii", "strict").strip()
        branch = branch_stdout.decode("utf-8", "strict").strip()
    except UnicodeDecodeError:
        fail("remote_checkout_mismatch")
    if (
        git_code
        or git_stderr
        or revision != payload["commit"]
        or branch_code
        or branch_stderr
        or not branch
        or len(branch) > 256
        or not branch.isprintable()
    ):
        fail("remote_checkout_mismatch")
    transition = campaign / ".mot_ui/transitions/discovery_bootstrap.json"
    receipt_keys = {
        "status",
        "nonce",
        "bootstrap_key",
        "commit",
        "physical_model_sha256",
        "source_2d_campaign_sha256",
        "source_2d_final_report_sha256",
        "input_registry_sha256",
        "timestep_policy_sha256",
        "files",
        "completed_unix_s",
    }
    no_links(campaign, transition)
    receipt = read_json(transition, receipt_keys, 8 * 1024 * 1024)
    if (
        canonical_digest(receipt) != payload["bootstrap_digest"]
        or receipt["status"] != "discovery_prepared"
        or receipt["nonce"] != payload["bootstrap_nonce"]
        or receipt["commit"] != payload["commit"]
        or receipt["files"] != files
        or not timestamp(receipt["completed_unix_s"])
        or any(
            HEX64.fullmatch(str(receipt[key])) is None
            for key in (
                "physical_model_sha256",
                "source_2d_campaign_sha256",
                "source_2d_final_report_sha256",
                "input_registry_sha256",
                "timestep_policy_sha256",
            )
        )
    ):
        fail("discovery_preparation_invalid")
    expected_bootstrap_key = canonical_digest(
        {
            "campaign_name": relative.name,
            "commit": receipt["commit"],
            "physical_model_sha256": receipt["physical_model_sha256"],
            "source_2d_campaign_sha256": receipt["source_2d_campaign_sha256"],
            "source_2d_final_report_sha256": receipt["source_2d_final_report_sha256"],
            "input_registry_sha256": receipt["input_registry_sha256"],
            "timestep_policy_sha256": receipt["timestep_policy_sha256"],
            "files": files,
            "nonce": receipt["nonce"],
        }
    )
    if (
        receipt["bootstrap_key"] != expected_bootstrap_key
        or receipt["bootstrap_key"] != payload["bootstrap_key"]
    ):
        fail("discovery_preparation_invalid")
    manifest = read_json(
        campaign / "campaign.json",
        {
            "kind",
            "name",
            "stage",
            "provenance",
            "input_directory",
            "upstream_2d_campaign",
            "input_roles",
            "design",
            "jobs",
        },
        8 * 1024 * 1024,
    )
    if (
        manifest.get("stage") != "discovery"
        or manifest.get("name") != relative.name
        or manifest.get("provenance", {}).get("git_commit") != payload["commit"]
    ):
        fail("discovery_preparation_invalid")
    frozen: dict[str, bytes] = {}
    for name, digest in files.items():
        path = campaign.joinpath(*PurePosixPath(name).parts)
        no_links(campaign, path)
        raw = bounded(path)
        if hashlib.sha256(raw).hexdigest() != digest:
            fail("discovery_preparation_invalid")
        frozen[name] = raw
    expected_submission_key = canonical_digest(
        {
            "campaign": relative.as_posix(),
            "commit": payload["commit"],
            "bootstrap_digest": payload["bootstrap_digest"],
            "bootstrap_key": payload["bootstrap_key"],
            "bootstrap_nonce": payload["bootstrap_nonce"],
            "files": files,
        }
    )
    if expected_submission_key != payload["submission_key"]:
        fail("discovery_preparation_invalid")
    submissions = campaign / ".mot_ui/submissions"
    no_links(campaign, submissions)
    lock_descriptor = -1
    if operation == "submit":
        try:
            submissions.mkdir(parents=True, exist_ok=True)
            no_links(campaign, submissions)
            lock_descriptor = os.open(
                submissions / "discovery.lock",
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            lock_stat = os.fstat(lock_descriptor)
            if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1:
                fail("discovery_submission_outcome_unknown")
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if lock_descriptor >= 0:
                os.close(lock_descriptor)
            fail("discovery_submission_outcome_unknown")
    final_path = submissions / "discovery.json"
    pending_path = submissions / "discovery.pending.json"
    chain = _empty_chain()
    if final_path.exists():
        final = read_json(
            final_path,
            {
                "version",
                "status",
                "submission_key",
                "bootstrap_digest",
                "bootstrap_key",
                "bootstrap_nonce",
                "nonce",
                "commit",
                "chain",
                "created_unix_s",
                "submitted_unix_s",
            },
        )
        if (
            final.get("version") != 1
            or final.get("status") != "submitted"
            or final.get("submission_key") != payload["submission_key"]
            or final.get("bootstrap_digest") != payload["bootstrap_digest"]
            or final.get("bootstrap_key") != payload["bootstrap_key"]
            or final.get("bootstrap_nonce") != payload["bootstrap_nonce"]
            or final.get("commit") != payload["commit"]
            or HEX32.fullmatch(str(final.get("nonce", ""))) is None
            or not timestamp(final.get("created_unix_s"))
            or not timestamp(final.get("submitted_unix_s"))
            or final["submitted_unix_s"] < final["created_unix_s"]
            or not isinstance(final.get("chain"), dict)
            or set(final["chain"]) != set(JOBS)
            or any(
                not isinstance(final["chain"][family], list)
                or len(final["chain"][family]) != len(JOBS[family])
                or any(
                    JOB_ID.fullmatch(str(item)) is None
                    for item in final["chain"][family]
                )
                for family in JOBS
            )
        ):
            fail("discovery_submission_outcome_unknown")
        chain = final["chain"]
        if operation == "status":
            states = []
            for family in JOBS:
                for job in chain[family]:
                    try:
                        code, stdout, stderr = run_captured(
                            ["/usr/local/bin/qstat", "-x", "-t", "-f", job]
                        )
                    except Exception:
                        states.append("status_unknown")
                    else:
                        states.append(
                            "status_unknown"
                            if code or stderr
                            else scheduler_state(stdout, job)
                        )
            lifecycle = "completed_success"
            for candidate in (
                "completed_failed",
                "held",
                "status_unknown",
                "running",
                "queued",
            ):
                if candidate in states:
                    lifecycle = candidate
                    break
            response(
                lifecycle, branch, chain, final["nonce"], final["submitted_unix_s"]
            )
            return
        response("submitted", branch, chain, final["nonce"], final["submitted_unix_s"])
        return
    if pending_path.exists():
        response("outcome_unknown", branch, chain)
        return
    if operation in {"inspect", "status"}:
        response("eligible", branch, chain)
        return
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or HEX32.fullmatch(nonce) is None:
        fail("invalid_request")
    created = int(time.time())
    write_record(
        pending_path,
        {
            "version": 1,
            "status": "pending",
            "submission_key": payload["submission_key"],
            "bootstrap_digest": payload["bootstrap_digest"],
            "bootstrap_key": payload["bootstrap_key"],
            "bootstrap_nonce": payload["bootstrap_nonce"],
            "nonce": nonce,
            "commit": payload["commit"],
            "created_unix_s": created,
        },
    )
    for family, job_files in JOBS.items():
        previous: str | None = None
        for index, job_file in enumerate(job_files, 1):
            step_pending = submissions / f"discovery_{family}_{index}.pending.json"
            step_done = submissions / f"discovery_{family}_{index}.json"
            write_record(
                step_pending,
                {
                    "status": "pending",
                    "nonce": nonce,
                    "family": family,
                    "round": index,
                    "pbs_sha256": files[job_file],
                    "depends_on": previous,
                    "created_unix_s": int(time.time()),
                },
            )
            argv = ["/usr/local/bin/qsub", "-J", "0-2:1"]
            if previous is not None:
                argv += ["-W", f"depend=afterok:{previous}"]
            try:
                code, stdout, stderr = run_captured(
                    argv, input_data=frozen[job_file], limit=1024 * 1024
                )
            except Exception:
                fail("discovery_submission_outcome_unknown")
            try:
                job_id = stdout.decode("ascii", "strict").strip()
            except UnicodeDecodeError:
                fail("discovery_submission_outcome_unknown")
            if code or stderr or JOB_ID.fullmatch(job_id) is None:
                fail("discovery_submission_outcome_unknown")
            write_record(
                step_done,
                {
                    "status": "submitted",
                    "nonce": nonce,
                    "family": family,
                    "round": index,
                    "pbs_sha256": files[job_file],
                    "depends_on": previous,
                    "job_id": job_id,
                    "completed_unix_s": int(time.time()),
                },
            )
            step_pending.unlink()
            directory = os.open(submissions, os.O_RDONLY)
            os.fsync(directory)
            os.close(directory)
            chain[family].append(job_id)
            previous = job_id
    submitted = int(time.time())
    write_record(
        final_path,
        {
            "version": 1,
            "status": "submitted",
            "submission_key": payload["submission_key"],
            "bootstrap_digest": payload["bootstrap_digest"],
            "bootstrap_key": payload["bootstrap_key"],
            "bootstrap_nonce": payload["bootstrap_nonce"],
            "nonce": nonce,
            "commit": payload["commit"],
            "chain": chain,
            "created_unix_s": created,
            "submitted_unix_s": submitted,
        },
    )
    pending_path.unlink()
    directory = os.open(submissions, os.O_RDONLY)
    os.fsync(directory)
    os.close(directory)
    response("submitted", branch, chain, nonce, submitted)


if __name__ == "__main__":
    main()
