"""Trusted fixed worker for one staged individual 3D-MOT Zeus package."""

from __future__ import annotations

import argparse
import base64
from io import BytesIO
import hashlib
import json
from workflow_api.platform_io import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import re

import numpy as np

from workflow_api.mot_3d_local_execution import Mot3DLocalWorker
from workflow_api.run_execution import WorkerRequest
from workflow_api.run_records import decode_record


MAX_PACKAGE = 8 * 1024 * 1024
MAX_PRODUCT = 4 * 1024 * 1024
JOB = re.compile(r"^[1-9][0-9]*\.zeus-master$")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _read_existing_product(path: Path) -> object:
    """Read a prior durable product once, descriptor-bound and size-bounded."""
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size > MAX_PRODUCT
    ):
        raise ValueError("Existing worker product is invalid.")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        raw = os.read(descriptor, MAX_PRODUCT + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns
    )
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or identity(opened) != identity(after)
        or len(raw) != opened.st_size
        or len(raw) > MAX_PRODUCT
    ):
        raise ValueError("Existing worker product changed while reading.")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Existing worker product is invalid.") from error


def _read_package(path: Path, expected_hash: str):
    relative = PurePosixPath(path.as_posix())
    if path.is_absolute() or ".." in relative.parts or len(expected_hash) != 64:
        raise ValueError("Invalid staged package path.")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_PACKAGE:
        raise ValueError("Invalid staged package.")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor); raw = os.read(descriptor, MAX_PACKAGE + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if ((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) !=
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or len(raw) != opened.st_size):
        raise ValueError("Staged package changed while reading.")
    value = json.loads(raw)
    exact = {"version", "family", "run_id", "commit", "username", "project_directory",
             "package_sha256", "pbs_sha256", "submission_key", "records",
             "selected_states", "selected_states_sha256", "selection_sha256", "pbs"}
    if not isinstance(value, dict) or set(value) != exact or value["family"] != "mot_3d":
        raise ValueError("Invalid staged package schema.")
    decoded = {name: base64.b64decode(content, validate=True)
               for name, content in value["records"].items()}
    selected_bytes = base64.b64decode(value["selected_states"], validate=True)
    pbs = base64.b64decode(value["pbs"], validate=True)
    if set(decoded) != {"run", "configuration", "inputs", "status"}:
        raise ValueError("Invalid staged records.")
    manifest = {
        "version": 1, "family": "mot_3d", "run_id": value["run_id"],
        "commit": value["commit"], "username": value["username"],
        "project_directory": value["project_directory"],
        "records": {name: hashlib.sha256(content).hexdigest() for name, content in decoded.items()},
        "selected_states_sha256": hashlib.sha256(selected_bytes).hexdigest(),
        "selected_states_size": len(selected_bytes), "selection_sha256": value["selection_sha256"],
    }
    if (
        hashlib.sha256(_canonical(manifest)).hexdigest() != expected_hash
        or value["package_sha256"] != expected_hash
        or manifest["selected_states_sha256"] != value["selected_states_sha256"]
        or hashlib.sha256(pbs).hexdigest() != value["pbs_sha256"]
    ):
        raise ValueError("Staged package digest mismatch.")
    records = {name: decode_record(name, content) for name, content in decoded.items()}
    run = records["run"]
    if (
        run["family"] != "mot_3d" or run["run_id"] != value["run_id"]
        or run["git_revision"] != value["commit"] or run["execution_mode"] != "zeus"
        or records["status"]["state"] != "configured"
        or records["configuration"]["resolved"]["sampling"]["selected_identities_sha256"] != value["selection_sha256"]
    ):
        raise ValueError("Staged package identity mismatch.")
    selected = np.load(BytesIO(selected_bytes), allow_pickle=False)
    if selected.dtype != np.float64 or selected.shape != (run["particle_count"], 6):
        raise ValueError("Invalid selected-state payload.")
    return value, records, np.ascontiguousarray(selected)


def execute_package(path: Path, expected_hash: str, *, worker_factory=None):
    value, records, selected = _read_package(path, expected_hash)
    job_id = os.environ.get("PBS_JOBID")
    if not isinstance(job_id, str) or not JOB.fullmatch(job_id):
        raise ValueError("Canonical scalar Zeus job identity is unavailable.")
    destination = path.parent / "worker_product.json"
    if destination.exists():
        existing = _read_existing_product(destination)
        if (not isinstance(existing, dict)
            or set(existing) != {"version", "run_id", "job_id", "package_sha256", "submission_key",
                                 "results", "receipt", "artifacts"}
            or existing.get("version") != 1
            or existing.get("run_id") != value["run_id"]
            or existing.get("job_id") != job_id
            or existing.get("package_sha256") != expected_hash
            or existing.get("submission_key") != value["submission_key"]
            or not isinstance(existing.get("artifacts"), dict)):
            raise ValueError("Existing worker product is not identity-bound.")
        return existing
    worker = worker_factory() if worker_factory else Mot3DLocalWorker(Path.cwd())
    product = worker.run_materialized(
        WorkerRequest(records["run"], records["configuration"], records["inputs"]), selected
    )
    payload = {
        "version": 1, "run_id": value["run_id"], "job_id": job_id,
        "package_sha256": expected_hash,
        "submission_key": value["submission_key"], "results": dict(product.results),
        "receipt": dict(product.receipt) if product.receipt is not None else None,
        "artifacts": {name: base64.b64encode(content).decode("ascii")
                      for name, content in product.artifacts.items()},
    }
    encoded = _canonical(payload)
    if len(encoded) > MAX_PRODUCT:
        raise ValueError("Worker product exceeds retrieval bound.")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name); stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
    try:
        os.chmod(temporary, 0o600); os.replace(temporary, destination)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True); parser.add_argument("--package-sha256", required=True)
    arguments = parser.parse_args(argv)
    execute_package(Path(arguments.package), arguments.package_sha256)


if __name__ == "__main__":
    main()
