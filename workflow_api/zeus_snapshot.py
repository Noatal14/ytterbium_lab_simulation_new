"""Narrow read-only Zeus snapshot boundary.

This module intentionally exposes one operation only: obtain a bounded snapshot
using an existing SSH key or agent.  It cannot accept commands, SSH options, a
host name, credentials, or scheduler mutations from callers.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


ZEUS_HOST = "zeus.technion.ac.il"
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,31}$")
JOB_ID_RE = re.compile(r"^\d+(?:\[\d+\]|\[\])?(?:\.zeus-master)?$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
RAW_STATES = frozenset("QRHFXEBSWTU")
MAX_JOBS = 500
MAX_STDOUT = 2 * 1024 * 1024
MAX_STDERR = 64 * 1024


class ZeusSnapshotError(RuntimeError):
    """A sanitized, user-actionable read-only connection failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ZeusProfile:
    username: str
    project_directory: str

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> "ZeusProfile":
        if set(payload) != {"username", "project_directory"}:
            raise ValueError("Connection profile fields are invalid.")
        username = payload.get("username")
        project = payload.get("project_directory")
        if not isinstance(username, str) or not USERNAME_RE.fullmatch(username):
            raise ValueError("Technion username is invalid.")
        if not isinstance(project, str) or len(project) > 192 or any(ord(char) < 32 for char in project):
            raise ValueError("Remote project directory is invalid.")
        candidate = PurePosixPath(project)
        expected = PurePosixPath("/home") / username / "ytterbium_lab_simulation_new"
        if candidate != expected:
            raise ValueError("Remote project directory does not match the supported Zeus checkout.")
        return cls(username=username, project_directory=str(candidate))


_REMOTE_SCRIPT = r'''import json, os, pathlib, re, subprocess, sys, tempfile
username = sys.argv[1]
requested = pathlib.Path(sys.argv[2])
try:
    resolved = requested.resolve(strict=True)
except (OSError, RuntimeError):
    print(json.dumps({"error": "remote_project_missing"})); raise SystemExit(20)
home = pathlib.Path("/home") / username
if not resolved.is_dir() or (resolved != home and home not in resolved.parents):
    print(json.dumps({"error": "remote_project_missing"})); raise SystemExit(20)
def run(argv, cwd=None, cap=1048576):
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=output, stderr=errors, env={"PATH": "/opt/pbs/bin:/usr/local/bin:/usr/bin:/bin", "HOME": str(home), "LC_ALL": "C"}, shell=False, close_fds=True)
        try: code = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(); raise RuntimeError("timeout")
        output.seek(0, os.SEEK_END); size = output.tell()
        errors.seek(0, os.SEEK_END); error_size = errors.tell()
        if size > cap or error_size > 65536: raise RuntimeError("oversized")
        output.seek(0); errors.seek(0)
        return code, output.read().decode("utf-8", "strict"), errors.read().decode("utf-8", "replace")
try:
    head_code, head, _ = run(["git", "rev-parse", "--verify", "HEAD^{commit}"], resolved, 128)
    branch_code, branch, _ = run(["git", "branch", "--show-current"], resolved, 256)
    dirty_code, dirty, _ = run(["git", "status", "--porcelain=v1", "--untracked-files=no"], resolved, 262144)
    select_code, selected, _ = run(["qselect", "-u", username], resolved, 65536)
    if select_code:
        print(json.dumps({"error": "scheduler_unavailable"})); raise SystemExit(22)
    job_ids = [line.strip() for line in selected.splitlines() if line.strip()]
    valid_id = re.compile(r"^\d+(?:\[\d+\]|\[\])?(?:\.zeus-master)?$")
    if len(job_ids) > 500 or len(job_ids) != len(set(job_ids)) or any(not valid_id.match(identifier) for identifier in job_ids):
        raise RuntimeError("invalid job selection")
    if job_ids:
        qstat_code, qstat, _ = run(["qstat", "-f"] + job_ids, resolved, 1048576)
    else:
        qstat_code, qstat = 0, ""
except (OSError, RuntimeError, UnicodeError):
    print(json.dumps({"error": "remote_check_failed"})); raise SystemExit(21)
if head_code or branch_code or dirty_code:
    print(json.dumps({"error": "remote_project_missing"})); raise SystemExit(20)
if qstat_code:
    print(json.dumps({"error": "scheduler_unavailable"})); raise SystemExit(22)
print(json.dumps({"project_directory": str(resolved), "git_commit": head.strip(), "branch": branch.strip(), "dirty": bool(dirty), "qstat": qstat}))
'''


def _remote_command(profile: ZeusProfile) -> str:
    script = base64.urlsafe_b64encode(_REMOTE_SCRIPT.encode("utf-8")).decode("ascii")
    wrapper = "import base64,sys;payload=sys.argv[1];sys.argv=sys.argv[1:];exec(base64.urlsafe_b64decode(payload).decode('utf-8'))"
    return shlex.join(("python3", "-c", wrapper, script, profile.username, profile.project_directory))


def _parse_qstat(text: str) -> list[dict[str, Any]]:
    if "\x00" in text or any(ord(char) < 9 or 13 < ord(char) < 32 for char in text):
        raise ZeusSnapshotError("malformed_remote_response")
    records: list[tuple[str, dict[str, str]]] = []
    job_id: str | None = None
    attributes: dict[str, str] = {}
    last_key: str | None = None
    for line in text.splitlines():
        if line.startswith("Job Id:"):
            if job_id is not None:
                records.append((job_id, attributes))
            job_id = line.split(":", 1)[1].strip(); attributes = {}; last_key = None
        elif job_id is not None and " = " in line:
            key, value = line.strip().split(" = ", 1)
            if len(key) > 128 or len(value) > 4096:
                raise ZeusSnapshotError("malformed_remote_response")
            if key in attributes:
                raise ZeusSnapshotError("malformed_remote_response")
            attributes[key] = value; last_key = key
        elif job_id is not None and last_key is not None and line[:1].isspace() and line.strip():
            combined = f"{attributes[last_key]} {line.strip()}"
            if len(combined) > 4096:
                raise ZeusSnapshotError("malformed_remote_response")
            attributes[last_key] = combined
    if job_id is not None:
        records.append((job_id, attributes))
    if text.strip() and not records:
        raise ZeusSnapshotError("malformed_remote_response")
    if len(records) > MAX_JOBS:
        raise ZeusSnapshotError("malformed_remote_response")
    jobs = []
    seen: set[str] = set()
    for identifier, row in records:
        if not JOB_ID_RE.fullmatch(identifier) or identifier in seen:
            raise ZeusSnapshotError("malformed_remote_response")
        seen.add(identifier)
        raw = row.get("job_state", "?")
        if raw not in RAW_STATES:
            raw = "?"
        exit_status: int | None = None
        if "Exit_status" in row:
            try: exit_status = int(row["Exit_status"])
            except ValueError: raise ZeusSnapshotError("malformed_remote_response") from None
            if not -(2**31) <= exit_status < 2**31:
                raise ZeusSnapshotError("malformed_remote_response")
        dependency = row.get("depend", "")
        dependencies = re.findall(r"\d+(?:\[\d+\]|\[\])?(?:\.zeus-master)?", dependency)
        if raw == "Q": state = "queued"
        elif raw in {"R", "E", "B"}: state = "running"
        elif raw == "H": state = "held_attention"
        elif raw in {"F", "X"} and exit_status == 0: state = "completed_success"
        elif raw in {"F", "X"} and exit_status is not None: state = "completed_failed"
        else: state = "unknown"
        def bounded(key: str, limit: int = 512) -> str | None:
            value = row.get(key)
            return value[:limit] if value else None
        jobs.append({
            "id": identifier, "name": bounded("Job_Name", 128) or "Unnamed job",
            "raw_state": raw, "state": state, "exit_status": exit_status,
            "walltime": bounded("resources_used.walltime", 32),
            "start_time": bounded("stime", 128), "comment": bounded("comment"),
            "dependencies": dependencies,
        })
    return jobs


class ZeusSnapshotProvider:
    """Execute the single pinned read-only SSH operation."""

    def __init__(self, repository_root: Path, ssh_executable: Path, *, timeout: float = 25):
        self.root = repository_root.resolve()
        self.ssh = ssh_executable.resolve()
        self.timeout = timeout
        if not self.ssh.is_file() or not os.access(self.ssh, os.X_OK) or self.root in self.ssh.parents:
            raise ValueError("The trusted SSH executable is unavailable.")
        from workflow_api.pinned_ssh import PinnedSshPolicy, PinnedSshRunner

        self.runner = PinnedSshRunner(
            PinnedSshPolicy.snapshot(self.root, self.ssh, timeout=self.timeout)
        )

    def _run(self, profile: ZeusProfile) -> tuple[int, bytes, bytes]:
        return self.runner.snapshot(profile)

    def snapshot(self, profile: ZeusProfile) -> dict[str, Any]:
        returncode, output, errors = self._run(profile)
        stderr = errors.decode("utf-8", "replace").lower()
        if returncode != 0:
            if "host key verification failed" in stderr or "remote host identification has changed" in stderr:
                raise ZeusSnapshotError("zeus_host_key_untrusted")
            if "permission denied" in stderr or "authentication" in stderr:
                raise ZeusSnapshotError("zeus_authentication_required")
            if "timed out" in stderr: raise ZeusSnapshotError("zeus_timeout")
            if "could not resolve hostname" in stderr or "connection refused" in stderr or "no route to host" in stderr:
                raise ZeusSnapshotError("zeus_unreachable")
        try:
            payload = json.loads(output.decode("utf-8", "strict"))
        except (UnicodeError, json.JSONDecodeError):
            raise ZeusSnapshotError("malformed_remote_response") from None
        if not isinstance(payload, dict):
            raise ZeusSnapshotError("malformed_remote_response")
        remote_error = payload.get("error")
        if remote_error == "remote_project_missing": raise ZeusSnapshotError("remote_project_missing")
        if remote_error == "scheduler_unavailable": raise ZeusSnapshotError("scheduler_unavailable")
        if remote_error is not None or returncode != 0: raise ZeusSnapshotError("zeus_check_failed")
        expected = {"project_directory", "git_commit", "branch", "dirty", "qstat"}
        branch = payload.get("branch")
        if set(payload) != expected or payload["project_directory"] != profile.project_directory or not COMMIT_RE.fullmatch(str(payload["git_commit"])) or not isinstance(branch, str) or len(branch) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in branch) or not isinstance(payload["dirty"], bool) or not isinstance(payload["qstat"], str):
            raise ZeusSnapshotError("malformed_remote_response")
        jobs = _parse_qstat(payload["qstat"])
        return {
            "connection_status": "connected",
            "profile": {"host": ZEUS_HOST, "username": profile.username, "project_directory": profile.project_directory, "authentication": "ssh-key-or-agent"},
            "remote": {"project_directory": payload["project_directory"], "git_commit": payload["git_commit"], "branch": payload["branch"], "dirty": payload["dirty"]},
            "scheduler": {"status": "available", "queried_at": datetime.now(timezone.utc).isoformat(), "jobs": jobs},
        }


class ZeusSnapshotService:
    """Bound refresh concurrency and request frequency without persistence."""

    def __init__(self, provider: ZeusSnapshotProvider):
        self.provider = provider
        self._lock = threading.Lock()
        self._last_attempt = 0.0

    def snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = ZeusProfile.parse(payload)
        if not self._lock.acquire(blocking=False):
            raise ZeusSnapshotError("rate_limited")
        try:
            now = time.monotonic()
            if now - self._last_attempt < 0.5:
                raise ZeusSnapshotError("rate_limited")
            self._last_attempt = now
            return self.provider.snapshot(profile)
        finally:
            self._lock.release()
