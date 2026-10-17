"""Trusted scalar Zeus worker for one staged individual Zeeman package."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from workflow_api.platform_io import os
from pathlib import Path, PurePosixPath
import stat
import tempfile

from workflow_api.run_execution import WorkerRequest
from workflow_api.run_records import decode_record
from workflow_api.zeeman_local_execution import ZeemanLocalWorker


MAX_PACKAGE = 2 * 1024 * 1024
MAX_PRODUCT = 4 * 1024 * 1024


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _read_package(path: Path, expected_hash: str):
    relative = PurePosixPath(path.as_posix())
    if path.is_absolute() or ".." in relative.parts or not expected_hash or len(expected_hash) != 64:
        raise ValueError("Invalid staged package path.")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_PACKAGE:
        raise ValueError("Invalid staged package.")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        raw = os.read(descriptor, MAX_PACKAGE + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if ((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) !=
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or
        len(raw) != opened.st_size):
        raise ValueError("Staged package changed while reading.")
    value = json.loads(raw)
    exact = {"version", "run_id", "commit", "username", "project_directory",
             "package_sha256", "pbs_sha256", "submission_key", "records", "pbs"}
    if not isinstance(value, dict) or set(value) != exact or value["package_sha256"] != expected_hash:
        raise ValueError("Invalid staged package schema.")
    if set(value["records"]) != {"run", "configuration", "inputs", "status"}:
        raise ValueError("Invalid staged records.")
    decoded_bytes = {
        name: base64.b64decode(content, validate=True)
        for name, content in value["records"].items()
    }
    records = {name: decode_record(name, content) for name, content in decoded_bytes.items()}
    manifest = {
        "version": 1, "run_id": value["run_id"], "commit": value["commit"],
        "username": value["username"], "project_directory": value["project_directory"],
        "records": {name: hashlib.sha256(content).hexdigest()
                    for name, content in decoded_bytes.items()},
    }
    if hashlib.sha256(_canonical(manifest)).hexdigest() != expected_hash:
        raise ValueError("Staged package digest mismatch.")
    pbs = base64.b64decode(value["pbs"], validate=True)
    if hashlib.sha256(pbs).hexdigest() != value["pbs_sha256"]:
        raise ValueError("Staged PBS digest mismatch.")
    run = records["run"]
    if (run["run_id"] != value["run_id"] or run["git_revision"] != value["commit"] or
        run["execution_mode"] != "zeus" or records["status"]["state"] != "configured"):
        raise ValueError("Staged package identity mismatch.")
    return value, records


def execute_package(path: Path, expected_hash: str, *, worker_factory=ZeemanLocalWorker):
    value, records = _read_package(path, expected_hash)
    destination = path.parent / "worker_product.json"
    if destination.exists():
        existing = json.loads(destination.read_bytes())
        if (
            not isinstance(existing, dict)
            or set(existing) != {"version", "run_id", "package_sha256", "submission_key",
                                 "results", "receipt", "artifacts"}
            or existing["version"] != 1
            or existing["run_id"] != value["run_id"]
            or existing["package_sha256"] != expected_hash
            or existing["submission_key"] != value["submission_key"]
            or not isinstance(existing["artifacts"], dict)
        ):
            raise ValueError("Existing worker product is not identity-bound.")
        return existing
    product = worker_factory().run(WorkerRequest(
        records["run"], records["configuration"], records["inputs"]
    ))
    payload = {
        "version": 1,
        "run_id": value["run_id"],
        "package_sha256": expected_hash,
        "submission_key": value["submission_key"],
        "results": dict(product.results),
        "receipt": dict(product.receipt) if product.receipt is not None else None,
        "artifacts": {name: base64.b64encode(content).decode("ascii")
                      for name, content in product.artifacts.items()},
    }
    encoded = _canonical(payload)
    if len(encoded) > MAX_PRODUCT:
        raise ValueError("Worker product exceeds the retrieval bound.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
    try:
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--package-sha256", required=True)
    arguments = parser.parse_args(argv)
    execute_package(Path(arguments.package), arguments.package_sha256)


if __name__ == "__main__":
    main()
