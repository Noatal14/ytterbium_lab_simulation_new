"""Strict codecs and atomic persistence for individual-run v1 records.

This module validates declared storage shape only.  Codec acceptance is not
scientific validation, execution admission, completion evidence, or campaign
input suitability.  Those responsibilities belong to later family services.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from workflow_api.platform_io import locking as fcntl
import hashlib
import json
import math
from workflow_api.platform_io import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
from typing import Any, Iterator, Literal, Mapping

from workflow_api.run_specification import INDIVIDUAL_RUN_SPECIFICATION


RecordKind = Literal[
    "run", "configuration", "inputs", "status", "results", "retention_receipt"
]
_SPEC = INDIVIDUAL_RUN_SPECIFICATION
_VERSIONS = _SPEC["record_versions"]
_LIMITS = _SPEC["limits"]
_FAMILIES = frozenset(_SPEC["layout"]["families"])
_MODES = frozenset(_SPEC["execution_modes"])
_STATES = frozenset(_SPEC["lifecycle"]["transitions"])
_TRANSITIONS = {
    state: frozenset(destinations)
    for state, destinations in _SPEC["lifecycle"]["transitions"].items()
}
_KINDS = frozenset(_SPEC["output_kinds"])
_RUN_ID = re.compile(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_REVISION = re.compile(r"[0-9a-f]{40}")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_UTC_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)"
)
_PATHS: dict[RecordKind, str] = {
    "run": "run.json",
    "configuration": "configuration.json",
    "inputs": "inputs.json",
    "status": "status.json",
    "results": _SPEC["layout"]["result_registry"],
    "retention_receipt": _SPEC["layout"]["retention_receipt"],
}


class RunRecordError(ValueError):
    """A safe validation or persistence failure."""


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise RunRecordError(f"Invalid {label} schema.")
    return value


def _text(value: Any, label: str, *, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not value.isprintable()
        or len(value.encode("utf-8")) > maximum
    ):
        raise RunRecordError(f"Invalid {label}.")
    return value


def _identifier(value: Any, label: str) -> str:
    value = _text(value, label, maximum=_LIMITS["run_id_max_characters"])
    if not _RUN_ID.fullmatch(value):
        raise RunRecordError(f"Invalid {label}.")
    return value


def _timestamp(value: Any, label: str) -> str:
    value = _text(value, label, maximum=64)
    if not _UTC_TIMESTAMP.fullmatch(value):
        raise RunRecordError(f"Invalid {label}.")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as error:
        raise RunRecordError(f"Invalid {label}.") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise RunRecordError(f"Invalid {label}.")
    return value


def _parsed_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(
        value[:-1] + "+00:00" if value.endswith("Z") else value
    )


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise RunRecordError(f"Invalid {label}.")
    return value


def _relative(value: Any, label: str) -> str:
    value = _text(value, label, maximum=_LIMITS["path_max_bytes"])
    if "\\" in value:
        raise RunRecordError(f"Invalid {label}.")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RunRecordError(f"Invalid {label}.")
    return value


def _finite_tree(value: Any, *, depth: int = 0, path: tuple[str, ...] = ()) -> None:
    if depth > 32:
        raise RunRecordError("Record nesting is too deep.")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and (
            not value.isprintable() or len(value.encode("utf-8")) > 16 * 1024
        ):
            raise RunRecordError("Record contains invalid text.")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RunRecordError("Record contains a non-finite number.")
        return
    if isinstance(value, list):
        # Particle identities are bounded independently of artifact metadata.
        # Both MOT planners store one [source_record_index, row_index] per atom.
        selection = path == ("resolved", "sampling", "selected_identities")
        maximum = 50_000 if selection else _LIMITS["artifact_count_maximum"] * 16
        if len(value) > maximum:
            raise RunRecordError("Record list is too large.")
        if selection and any(
            not isinstance(pair, list) or len(pair) != 2
            or any(type(index) is not int or index < 0 for index in pair)
            for pair in value
        ):
            raise RunRecordError("Invalid selected particle identities.")
        for child in value:
            _finite_tree(child, depth=depth + 1, path=path + ("[]",))
        return
    if isinstance(value, dict):
        if len(value) > _LIMITS["artifact_count_maximum"] * 4:
            raise RunRecordError("Record object is too large.")
        for key, child in value.items():
            _text(key, "record key", maximum=128)
            _finite_tree(child, depth=depth + 1, path=path + (key,))
        return
    raise RunRecordError("Record contains a non-JSON value.")


def _artifact(value: Any) -> dict[str, Any]:
    row = _exact(value, {"kind", "path", "required"}, "output artifact")
    if row["kind"] not in _KINDS or not isinstance(row["required"], bool):
        raise RunRecordError("Invalid output artifact.")
    _relative(row["path"], "output path")
    return row


def _validate_run(value: Any) -> None:
    row = _exact(
        value,
        {
            "schema_version",
            "run_id",
            "family",
            "created_utc",
            "execution_mode",
            "git_revision",
            "configuration_sha256",
            "inputs_sha256",
            "particle_count",
            "seed",
            "solver",
            "timestep_s",
            "retention",
            "outputs",
            "suitability",
        },
        "run record",
    )
    if row["schema_version"] != _VERSIONS["run"]:
        raise RunRecordError("Invalid run record version.")
    _identifier(row["run_id"], "run id")
    if row["family"] not in _FAMILIES or row["execution_mode"] not in _MODES:
        raise RunRecordError("Invalid run family or execution mode.")
    _timestamp(row["created_utc"], "creation timestamp")
    if not isinstance(row["git_revision"], str) or not _GIT_REVISION.fullmatch(
        row["git_revision"]
    ):
        raise RunRecordError("Invalid Git revision.")
    _sha(row["configuration_sha256"], "configuration digest")
    _sha(row["inputs_sha256"], "inputs digest")
    if (
        isinstance(row["particle_count"], bool)
        or not isinstance(row["particle_count"], int)
        or row["particle_count"] <= 0
    ):
        raise RunRecordError("Invalid particle count.")
    if (
        isinstance(row["seed"], bool)
        or not isinstance(row["seed"], int)
        or row["seed"] < 0
    ):
        raise RunRecordError("Invalid seed.")
    _text(row["solver"], "solver", maximum=128)
    if (
        isinstance(row["timestep_s"], bool)
        or not isinstance(row["timestep_s"], (int, float))
        or not math.isfinite(row["timestep_s"])
        or row["timestep_s"] <= 0
    ):
        raise RunRecordError("Invalid timestep.")
    retention = _exact(row["retention"], {"particle_states"}, "retention")
    if not isinstance(retention["particle_states"], bool):
        raise RunRecordError("Invalid retention choice.")
    if row["suitability"] != "individual_only":
        raise RunRecordError("D2 records cannot claim campaign suitability.")
    outputs = row["outputs"]
    if (
        not isinstance(outputs, list)
        or not 1 <= len(outputs) <= _LIMITS["artifact_count_maximum"]
    ):
        raise RunRecordError("Invalid output registry.")
    for item in outputs:
        _artifact(item)
    paths = [item["path"] for item in outputs]
    if len(paths) != len(set(paths)):
        raise RunRecordError("Output paths must be unique.")
    required = {_SPEC["layout"]["result_registry"]}
    required.add(
        _SPEC["layout"]["particle_states"]
        if retention["particle_states"]
        else _SPEC["layout"]["retention_receipt"]
    )
    if not required.issubset(paths):
        raise RunRecordError("Output registry does not match retention.")
    forbidden = (
        _SPEC["layout"]["retention_receipt"]
        if retention["particle_states"]
        else _SPEC["layout"]["particle_states"]
    )
    if forbidden in paths:
        raise RunRecordError("Output registry contradicts retention.")
    by_path = {item["path"]: item for item in outputs}
    expected_kinds = {
        _SPEC["layout"]["result_registry"]: "summary",
        (
            _SPEC["layout"]["particle_states"]
            if retention["particle_states"]
            else _SPEC["layout"]["retention_receipt"]
        ): ("particle_states" if retention["particle_states"] else "retention_receipt"),
    }
    if any(
        by_path[path]["kind"] != kind or by_path[path]["required"] is not True
        for path, kind in expected_kinds.items()
    ):
        raise RunRecordError("Canonical outputs must be required and correctly typed.")


def _validate_configuration(value: Any) -> None:
    row = _exact(
        value,
        {
            "schema_version",
            "run_id",
            "family",
            "laboratory_spec",
            "numerical_policy",
            "resolved",
        },
        "configuration record",
    )
    if row["schema_version"] != _VERSIONS["configuration"]:
        raise RunRecordError("Invalid configuration record version.")
    _identifier(row["run_id"], "run id")
    if row["family"] not in _FAMILIES:
        raise RunRecordError("Invalid run family.")
    for label in ("laboratory_spec", "numerical_policy"):
        spec = _exact(row[label], {"version", "sha256"}, label)
        _text(spec["version"], f"{label} version", maximum=128)
        _sha(spec["sha256"], f"{label} digest")
    if not isinstance(row["resolved"], dict):
        raise RunRecordError("Resolved configuration must be an object.")
    _finite_tree(row["resolved"], path=("resolved",))


def _validate_inputs(value: Any) -> None:
    row = _exact(
        value, {"schema_version", "run_id", "family", "artifacts"}, "inputs record"
    )
    if row["schema_version"] != _VERSIONS["inputs"]:
        raise RunRecordError("Invalid inputs record version.")
    _identifier(row["run_id"], "run id")
    if (
        row["family"] not in _FAMILIES
        or not isinstance(row["artifacts"], list)
        or len(row["artifacts"]) > _LIMITS["artifact_count_maximum"]
    ):
        raise RunRecordError("Invalid inputs record.")
    seen: set[str] = set()
    for item in row["artifacts"]:
        artifact = _exact(
            item,
            {"id", "role", "path", "sha256", "size_bytes", "provenance"},
            "input artifact",
        )
        identity = _identifier(artifact["id"], "input id")
        if identity in seen:
            raise RunRecordError("Input identities must be unique.")
        seen.add(identity)
        _text(artifact["role"], "input role", maximum=128)
        _relative(artifact["path"], "input path")
        _sha(artifact["sha256"], "input digest")
        if (
            isinstance(artifact["size_bytes"], bool)
            or not isinstance(artifact["size_bytes"], int)
            or artifact["size_bytes"] < 0
        ):
            raise RunRecordError("Invalid input size.")
        if not isinstance(artifact["provenance"], dict):
            raise RunRecordError("Invalid input provenance.")
        _finite_tree(artifact["provenance"])


def _validate_status(value: Any) -> None:
    row = _exact(
        value,
        {
            "schema_version",
            "run_id",
            "revision",
            "state",
            "updated_utc",
            "execution",
            "error",
        },
        "status record",
    )
    if row["schema_version"] != _VERSIONS["status"]:
        raise RunRecordError("Invalid status record version.")
    _identifier(row["run_id"], "run id")
    if (
        isinstance(row["revision"], bool)
        or not isinstance(row["revision"], int)
        or row["revision"] < 0
        or row["state"] not in _STATES
    ):
        raise RunRecordError("Invalid status revision or state.")
    _timestamp(row["updated_utc"], "status timestamp")
    execution = _exact(
        row["execution"], {"mode", "local_pid", "zeus_job_id"}, "execution evidence"
    )
    if execution["mode"] not in _MODES:
        raise RunRecordError("Invalid execution evidence mode.")
    if execution["local_pid"] is not None and (
        isinstance(execution["local_pid"], bool)
        or not isinstance(execution["local_pid"], int)
        or execution["local_pid"] <= 0
    ):
        raise RunRecordError("Invalid local process id.")
    if execution["zeus_job_id"] is not None:
        _text(execution["zeus_job_id"], "Zeus job id", maximum=128)
    if execution["mode"] == "local" and execution["zeus_job_id"] is not None:
        raise RunRecordError("Local status cannot contain a Zeus job id.")
    if execution["mode"] == "zeus" and execution["local_pid"] is not None:
        raise RunRecordError("Zeus status cannot contain a local process id.")
    if row["error"] is not None:
        error = _exact(row["error"], {"code", "message"}, "status error")
        if not isinstance(error["code"], str) or not _CODE.fullmatch(error["code"]):
            raise RunRecordError("Invalid status error code.")
        _text(error["message"], "status error message", maximum=1024)
        if row["state"] not in {"failed", "outcome_unknown"}:
            raise RunRecordError("Non-error status cannot contain an error.")
    elif row["state"] in {"failed", "outcome_unknown"}:
        raise RunRecordError("Error status requires a safe error.")


def _result_artifact(value: Any) -> None:
    row = _exact(value, {"kind", "path", "sha256", "size_bytes"}, "result artifact")
    if row["kind"] not in _KINDS:
        raise RunRecordError("Invalid result artifact kind.")
    _relative(row["path"], "result path")
    _sha(row["sha256"], "result digest")
    if (
        isinstance(row["size_bytes"], bool)
        or not isinstance(row["size_bytes"], int)
        or row["size_bytes"] < 0
    ):
        raise RunRecordError("Invalid result size.")


def _validate_results(value: Any) -> None:
    row = _exact(
        value,
        {
            "schema_version",
            "run_id",
            "completed_utc",
            "states_retained",
            "suitability",
            "metrics",
            "artifacts",
        },
        "results record",
    )
    if row["schema_version"] != _VERSIONS["results"]:
        raise RunRecordError("Invalid results record version.")
    _identifier(row["run_id"], "run id")
    _timestamp(row["completed_utc"], "completion timestamp")
    if (
        not isinstance(row["states_retained"], bool)
        or row["suitability"] != "individual_only"
        or not isinstance(row["metrics"], dict)
    ):
        raise RunRecordError("Invalid result classification.")
    _finite_tree(row["metrics"])
    artifacts = row["artifacts"]
    if (
        not isinstance(artifacts, list)
        or len(artifacts) > _LIMITS["artifact_count_maximum"]
    ):
        raise RunRecordError("Invalid result registry.")
    for item in artifacts:
        _result_artifact(item)
    paths = [item["path"] for item in artifacts]
    if len(paths) != len(set(paths)):
        raise RunRecordError("Result paths must be unique.")
    expected = (
        _SPEC["layout"]["particle_states"]
        if row["states_retained"]
        else _SPEC["layout"]["retention_receipt"]
    )
    forbidden = (
        _SPEC["layout"]["retention_receipt"]
        if row["states_retained"]
        else _SPEC["layout"]["particle_states"]
    )
    if expected not in paths or forbidden in paths:
        raise RunRecordError("Result registry contradicts retention.")
    expected_kind = "particle_states" if row["states_retained"] else "retention_receipt"
    if (
        next(item for item in artifacts if item["path"] == expected)["kind"]
        != expected_kind
    ):
        raise RunRecordError("Canonical result has the wrong artifact kind.")


def _validate_retention_receipt(value: Any) -> None:
    row = _exact(
        value,
        {"schema_version", "run_id", "created_utc", "reason"},
        "retention receipt",
    )
    if row["schema_version"] != _VERSIONS["retention_receipt"]:
        raise RunRecordError("Invalid retention receipt version.")
    _identifier(row["run_id"], "run id")
    _timestamp(row["created_utc"], "receipt timestamp")
    if row["reason"] != "particle_states_not_retained":
        raise RunRecordError("Invalid retention receipt reason.")


_VALIDATORS = {
    "run": _validate_run,
    "configuration": _validate_configuration,
    "inputs": _validate_inputs,
    "status": _validate_status,
    "results": _validate_results,
    "retention_receipt": _validate_retention_receipt,
}


def validate_record(kind: RecordKind, value: Any) -> dict[str, Any]:
    validator = _VALIDATORS.get(kind)
    if validator is None:
        raise RunRecordError("Unknown run record kind.")
    validator(value)
    _finite_tree(value)
    return json.loads(json.dumps(value))


def encode_record(kind: RecordKind, value: Any) -> bytes:
    validated = validate_record(kind, value)
    encoded = (
        json.dumps(validated, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    if len(encoded) > _LIMITS["json_max_bytes"]:
        raise RunRecordError("Run record exceeds the size limit.")
    return encoded


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise RunRecordError(f"Run record repeats key {key!r}.")
        value[key] = item
    return value


def decode_record(kind: RecordKind, raw: bytes) -> dict[str, Any]:
    if not isinstance(raw, bytes) or len(raw) > _LIMITS["json_max_bytes"]:
        raise RunRecordError("Invalid or oversized run record.")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise RunRecordError("Run record is not valid UTF-8 JSON.") from error
    return validate_record(kind, value)


def record_sha256(kind: RecordKind, value: Any) -> str:
    return hashlib.sha256(encode_record(kind, value)).hexdigest()


def _read_regular(path: Path) -> bytes:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size > _LIMITS["json_max_bytes"]
        ):
            raise RunRecordError("Run record is not a trusted regular file.")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            ) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
                raise RunRecordError("Run record changed while opening.")
            chunks: list[bytes] = []
            remaining = _LIMITS["json_max_bytes"] + 1
            while remaining:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
            raw = b"".join(chunks)
            if (
                len(raw) != opened.st_size
                or len(raw) > _LIMITS["json_max_bytes"]
                or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            ):
                raise RunRecordError("Run record changed while reading.")
        finally:
            os.close(descriptor)
        current = path.lstat()
        if not stat.S_ISREG(current.st_mode) or (
            current.st_dev,
            current.st_ino,
            current.st_size,
            current.st_mtime_ns,
        ) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
            raise RunRecordError("Run record path changed while reading.")
        return raw
    except OSError as error:
        raise RunRecordError("Run record is unavailable.") from error


def read_record(path: Path, kind: RecordKind) -> dict[str, Any]:
    return decode_record(kind, _read_regular(path))


def _read_regular_at(parent: int, name: str) -> bytes:
    try:
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise RunRecordError("Run record is not a trusted regular file.")
        descriptor = os.open(
            name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent
        )
        try:
            opened = os.fstat(descriptor)
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_size > _LIMITS["json_max_bytes"]
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                or (
                    current.st_dev,
                    current.st_ino,
                    current.st_size,
                    current.st_mtime_ns,
                )
                != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            ):
                raise RunRecordError("Run record is not a trusted regular file.")
            chunks: list[bytes] = []
            remaining = _LIMITS["json_max_bytes"] + 1
            while remaining:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
            raw = b"".join(chunks)
            final = os.stat(name, dir_fd=parent, follow_symlinks=False)
            identity = (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            )
            if (
                len(raw) != opened.st_size
                or len(raw) > _LIMITS["json_max_bytes"]
                or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                != identity
                or (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns)
                != identity
            ):
                raise RunRecordError("Run record changed while reading.")
            return raw
        finally:
            os.close(descriptor)
    except OSError as error:
        raise RunRecordError("Run record is unavailable.") from error


def _read_record_at(parent: int, name: str, kind: RecordKind) -> dict[str, Any]:
    return decode_record(kind, _read_regular_at(parent, name))


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_no_replace(path: Path, data: bytes, *, identical_ok: bool = False) -> None:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as error:
            if identical_ok and _read_regular(path) == data:
                return
            raise RunRecordError("Run record already exists.") from error
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _replace_at(parent: int, name: str, data: bytes) -> None:
    temporary = f".{name}.{secrets.token_hex(12)}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
        dir_fd=parent,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass


def _publish_no_replace_at(parent: int, name: str, data: bytes) -> None:
    temporary = f".{name}.{secrets.token_hex(12)}.tmp"
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(
            temporary,
            name,
            src_dir_fd=parent,
            dst_dir_fd=parent,
            follow_symlinks=False,
        )
        os.fsync(parent)
    except FileExistsError as error:
        raise RunRecordError("Run record already exists.") from error
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass


class RunRecordStore:
    """Persist validated run records beneath the canonical repository root."""

    def __init__(self, repository_root: Path):
        self.repository_root = repository_root.resolve(strict=True)
        if not self.repository_root.is_dir():
            raise RunRecordError("Repository root is unavailable.")
        try:
            self._repository_descriptor = os.open(
                self.repository_root,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError as error:
            raise RunRecordError("Repository root is unavailable.") from error
        self.runs_root = self.repository_root / _SPEC["layout"]["root"]

    def close(self) -> None:
        descriptor = getattr(self, "_repository_descriptor", None)
        if descriptor is not None:
            os.close(descriptor)
            self._repository_descriptor = None

    def __del__(self) -> None:
        try:
            self.close()
        except OSError:
            pass

    def _open_repository(self) -> int:
        try:
            if self._repository_descriptor is None:
                raise OSError("closed")
            return os.dup(self._repository_descriptor)
        except (AttributeError, OSError) as error:
            raise RunRecordError("Repository root is unavailable.") from error

    def _verify_family_binding(self, family: str, expected: os.stat_result) -> None:
        current = self._open_family(family, create=False)
        try:
            observed = os.fstat(current)
            if (observed.st_dev, observed.st_ino) != (expected.st_dev, expected.st_ino):
                raise RunRecordError("Run family directory changed during creation.")
        finally:
            os.close(current)

    def _open_beneath(self, parts: tuple[str, ...], *, create: bool) -> int:
        descriptor = self._open_repository()
        try:
            for part in parts:
                if part in {"", ".", ".."} or "/" in part:
                    raise RunRecordError("Run directory contains an invalid component.")
                try:
                    child = os.open(
                        part,
                        os.O_RDONLY
                        | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=descriptor,
                    )
                except FileNotFoundError:
                    if not create:
                        raise RunRecordError("Run directory is unavailable.") from None
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    child = os.open(
                        part,
                        os.O_RDONLY
                        | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=descriptor,
                    )
                os.close(descriptor)
                descriptor = child
            return descriptor
        except (OSError, RunRecordError) as error:
            os.close(descriptor)
            if isinstance(error, RunRecordError):
                raise
            raise RunRecordError(
                "Run directory contains an untrusted component."
            ) from error

    def _open_family(self, family: str, *, create: bool) -> int:
        if family not in _FAMILIES:
            raise RunRecordError("Invalid run family.")
        return self._open_beneath(("data", "runs", family), create=create)

    def _open_run(self, family: str, run_id: str) -> int:
        _identifier(run_id, "run id")
        family_descriptor = self._open_family(family, create=False)
        try:
            return os.open(
                run_id,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=family_descriptor,
            )
        except OSError as error:
            raise RunRecordError("Run directory is unavailable.") from error
        finally:
            os.close(family_descriptor)

    def _trusted_directory(self, path: Path, *, create: bool) -> Path:
        try:
            relative = path.relative_to(self.repository_root)
        except ValueError as error:
            raise RunRecordError("Run directory is outside the repository.") from error
        current = self.repository_root
        for part in relative.parts:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                if not create:
                    raise RunRecordError("Run directory is unavailable.") from None
                try:
                    current.mkdir(mode=0o700)
                except FileExistsError:
                    pass
                metadata = current.lstat()
            if not stat.S_ISDIR(metadata.st_mode):
                raise RunRecordError("Run directory contains an untrusted component.")
        return current

    def _run_directory(self, family: str, run_id: str, *, require: bool) -> Path:
        if family not in _FAMILIES:
            raise RunRecordError("Invalid run family.")
        _identifier(run_id, "run id")
        candidate = self.runs_root / family / run_id
        if require:
            self._trusted_directory(candidate, create=False)
        return candidate

    def create(
        self,
        run: Mapping[str, Any],
        configuration: Mapping[str, Any],
        inputs: Mapping[str, Any],
        status: Mapping[str, Any],
    ) -> Path:
        """Publish declared records; no scientific admission occurs here."""
        records = {
            "run": dict(run),
            "configuration": dict(configuration),
            "inputs": dict(inputs),
            "status": dict(status),
        }
        for kind, value in records.items():
            validate_record(kind, value)
        run_id = records["run"]["run_id"]
        family = records["run"]["family"]
        if (
            any(
                records[k]["run_id"] != run_id
                for k in ("configuration", "inputs", "status")
            )
            or records["configuration"]["family"] != family
            or records["inputs"]["family"] != family
        ):
            raise RunRecordError("Run records do not share one identity.")
        if (
            records["status"]["revision"] != 0
            or records["status"]["state"] != _SPEC["lifecycle"]["initial"]
            or records["status"]["execution"]["mode"]
            != records["run"]["execution_mode"]
        ):
            raise RunRecordError("Initial status is invalid.")
        if records["run"]["configuration_sha256"] != record_sha256(
            "configuration", records["configuration"]
        ) or records["run"]["inputs_sha256"] != record_sha256(
            "inputs", records["inputs"]
        ):
            raise RunRecordError("Run record digests do not match.")
        family_descriptor = self._open_family(family, create=True)
        family_identity = os.fstat(family_descriptor)
        target = self._run_directory(family, run_id, require=False)
        try:
            os.stat(run_id, dir_fd=family_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            os.close(family_descriptor)
            raise RunRecordError("Run already exists.")
        staging_name = f".{run_id}.{secrets.token_hex(12)}.staging"
        try:
            os.mkdir(staging_name, mode=0o700, dir_fd=family_descriptor)
        except FileExistsError as error:
            os.close(family_descriptor)
            raise RunRecordError("Run staging directory already exists.") from error
        except OSError:
            os.close(family_descriptor)
            raise
        try:
            staging_descriptor = os.open(
                staging_name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=family_descriptor,
            )
        except BaseException:
            os.close(family_descriptor)
            raise
        try:
            os.mkdir("results", mode=0o700, dir_fd=staging_descriptor)
            os.mkdir("logs", mode=0o700, dir_fd=staging_descriptor)
            for kind in ("configuration", "inputs", "status"):
                _publish_no_replace_at(
                    staging_descriptor, _PATHS[kind], encode_record(kind, records[kind])
                )
            _publish_no_replace_at(
                staging_descriptor, _PATHS["run"], encode_record("run", records["run"])
            )
            os.fsync(staging_descriptor)
            with self._locked_at(family_descriptor, ".runs.lock"):
                try:
                    os.stat(run_id, dir_fd=family_descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise RunRecordError("Run already exists.")
                os.rename(
                    staging_name,
                    run_id,
                    src_dir_fd=family_descriptor,
                    dst_dir_fd=family_descriptor,
                )
                published = os.stat(
                    run_id, dir_fd=family_descriptor, follow_symlinks=False
                )
                if not stat.S_ISDIR(published.st_mode):
                    raise RunRecordError("Published run directory is invalid.")
                os.fsync(family_descriptor)
                self._verify_family_binding(family, family_identity)
        except BaseException:
            # Failed bundles remain hidden as forensic evidence.  Readers admit
            # only the exact non-hidden run-id directory.
            raise
        finally:
            os.close(staging_descriptor)
            os.close(family_descriptor)
        return target

    @contextmanager
    def _locked_at(self, parent: int, name: str = ".records.lock") -> Iterator[None]:
        try:
            descriptor = os.open(
                name,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent,
            )
            opened = os.fstat(descriptor)
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(opened.st_mode) or (
                current.st_dev,
                current.st_ino,
            ) != (opened.st_dev, opened.st_ino):
                raise RunRecordError("Run lock is not a trusted regular file.")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (locked.st_dev, locked.st_ino) != (opened.st_dev, opened.st_ino):
                raise RunRecordError("Run lock changed while acquiring it.")
            yield
        except OSError as error:
            raise RunRecordError("Run lock is unavailable or untrusted.") from error
        finally:
            if "descriptor" in locals():
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)

    @contextmanager
    def _locked(self, directory: Path, name: str = ".records.lock") -> Iterator[int]:
        parent: int | None = None
        try:
            parent_before = directory.lstat()
            if not stat.S_ISDIR(parent_before.st_mode):
                raise RunRecordError("Lock parent is not a trusted directory.")
            parent = os.open(
                directory,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            parent_opened = os.fstat(parent)
            if (parent_opened.st_dev, parent_opened.st_ino) != (
                parent_before.st_dev,
                parent_before.st_ino,
            ):
                os.close(parent)
                raise RunRecordError("Lock parent changed while opening.")
            descriptor = os.open(
                name,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent,
            )
        except OSError as error:
            if parent is not None:
                os.close(parent)
            raise RunRecordError("Run lock is unavailable or untrusted.") from error
        try:
            lock_opened = os.fstat(descriptor)
            parent_current = directory.lstat()
            lock_current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISREG(lock_opened.st_mode)
                or not stat.S_ISDIR(parent_current.st_mode)
                or (parent_current.st_dev, parent_current.st_ino)
                != (parent_opened.st_dev, parent_opened.st_ino)
                or (lock_current.st_dev, lock_current.st_ino)
                != (lock_opened.st_dev, lock_opened.st_ino)
            ):
                raise RunRecordError("Run lock is not a trusted regular file.")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                locked_current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                locked_parent = directory.lstat()
            except OSError as error:
                raise RunRecordError("Run lock changed while acquiring it.") from error
            if (
                (locked_current.st_dev, locked_current.st_ino)
                != (lock_opened.st_dev, lock_opened.st_ino)
                or not stat.S_ISDIR(locked_parent.st_mode)
                or (locked_parent.st_dev, locked_parent.st_ino)
                != (parent_opened.st_dev, parent_opened.st_ino)
            ):
                raise RunRecordError("Run lock changed while acquiring it.")
            yield parent
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            os.close(parent)

    def read(self, family: str, run_id: str, kind: RecordKind) -> dict[str, Any]:
        directory_descriptor = self._open_run(family, run_id)
        try:
            return _read_record_at(directory_descriptor, _PATHS[kind], kind)
        finally:
            os.close(directory_descriptor)

    def update_status(
        self, family: str, run_id: str, status: Mapping[str, Any]
    ) -> None:
        """Persist only pre-admission cancellation, never progress or success."""
        proposed = dict(status)
        validate_record("status", proposed)
        directory_descriptor = self._open_run(family, run_id)
        try:
            with self._locked_at(directory_descriptor):
                current = _read_record_at(
                    directory_descriptor, _PATHS["status"], "status"
                )
                if (
                    current["state"] != "configured"
                    or proposed["state"] != "cancelled"
                    or proposed["run_id"] != run_id
                    or proposed["revision"] != current["revision"] + 1
                    or proposed["state"] not in _TRANSITIONS[current["state"]]
                ):
                    raise RunRecordError("Status transition is stale or invalid.")
                if _parsed_timestamp(proposed["updated_utc"]) < _parsed_timestamp(
                    current["updated_utc"]
                ):
                    raise RunRecordError("Status timestamp moved backwards.")
                run = _read_record_at(directory_descriptor, _PATHS["run"], "run")
                if proposed["execution"]["mode"] != run["execution_mode"]:
                    raise RunRecordError("Status execution mode changed.")
                _replace_at(
                    directory_descriptor,
                    _PATHS["status"],
                    encode_record("status", proposed),
                )
        finally:
            os.close(directory_descriptor)
