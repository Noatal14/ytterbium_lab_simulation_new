"""Read-only validation of realized individual-run results.

This module intentionally does not publish files or transition a run to a
terminal state.  It turns an already staged set of outputs into an immutable
``PublicationPlan`` which a later, atomic publisher may consume.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from workflow_api.platform_io import os
from pathlib import Path, PurePosixPath
import stat
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from workflow_api.run_records import (
    RunRecordError,
    decode_record,
    encode_record,
    record_sha256,
    validate_record,
)
from workflow_api.run_specification import INDIVIDUAL_RUN_SPECIFICATION


_SPEC = INDIVIDUAL_RUN_SPECIFICATION
_SUMMARY_PATH = _SPEC["layout"]["result_registry"]
_STATES_PATH = _SPEC["layout"]["particle_states"]
_RECEIPT_PATH = _SPEC["layout"]["retention_receipt"]
_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024 * 1024
_MAX_NON_STATE_BYTES = 64 * 1024 * 1024
_MAX_NPY_HEADER_BYTES = 64 * 1024
_SCAN_VALUES = 1024 * 1024


@dataclass(frozen=True)
class RealizedArtifact:
    kind: str
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class StateArrayEvidence:
    path: str
    sha256: str
    size_bytes: int
    shape: tuple[int, int]
    dtype: str
    survivor_count: int


@dataclass(frozen=True)
class PublicationPlan:
    run_id: str
    family: str
    expected_status_revision: int
    results_bytes: bytes
    results_sha256: str
    receipt_bytes: bytes | None
    artifacts: tuple[RealizedArtifact, ...]
    state_array: StateArrayEvidence | None


@dataclass(frozen=True)
class InspectedRunPackage:
    """Descriptor-bound, immutable evidence for one canonical run."""

    run: Mapping[str, Any]
    configuration: Mapping[str, Any]
    inputs: Mapping[str, Any]
    status: Mapping[str, Any]
    results: Mapping[str, Any] | None
    publication: PublicationPlan | None


def validate_worker_artifacts(results, receipt, artifacts):
    """Validate the shared worker contract: receipt is separate from state bytes.

    Local publication and Zeus retrieval must agree on this representation.
    The publisher alone materializes the canonical retention receipt on disk.
    """
    results = validate_record("results", dict(results))
    if any(not isinstance(path, str) or not isinstance(data, bytes) for path, data in artifacts.items()):
        raise RunRecordError("Worker artifacts are invalid.")
    registry = {row["path"]: row for row in results["artifacts"]}
    expected = {path for path, row in registry.items() if row["kind"] != "retention_receipt"}
    if len(registry) != len(results["artifacts"]) or set(artifacts) != expected:
        raise RunRecordError("Worker artifacts do not match the result registry.")
    for path, content in artifacts.items():
        row = registry[path]
        if len(content) != row["size_bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise RunRecordError("Worker artifact digest does not match.")
    if results["states_retained"]:
        if receipt is not None:
            raise RunRecordError("Retained states cannot have a retention receipt.")
    else:
        if not isinstance(receipt, Mapping):
            raise RunRecordError("A retention receipt is required.")
        content = encode_record("retention_receipt", dict(receipt))
        row = registry.get(_RECEIPT_PATH)
        if (receipt["run_id"] != results["run_id"] or row is None
            or row["kind"] != "retention_receipt"
            or len(content) != row["size_bytes"]
            or hashlib.sha256(content).hexdigest() != row["sha256"]):
            raise RunRecordError("Retention receipt digest does not match.")
    return results


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _parsed_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(
        value[:-1] + "+00:00" if value.endswith("Z") else value
    )


def _open_repository_root(repository_root: Path) -> tuple[int, os.stat_result]:
    try:
        before = repository_root.lstat()
        if not stat.S_ISDIR(before.st_mode):
            raise RunRecordError("Repository root is not trusted.")
        descriptor = os.open(
            repository_root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            os.close(descriptor)
            raise RunRecordError("Repository root changed while opening.")
        return descriptor, opened
    except OSError as error:
        raise RunRecordError("Repository root is unavailable.") from error


def _open_canonical_run(repository_root: Path, family: str, run_id: str) -> tuple[
    int,
    os.stat_result,
    list[int],
    list[tuple[int, str, int, int]],
    int,
    os.stat_result,
]:
    root_descriptor, root_identity = _open_repository_root(repository_root)
    relative = PurePosixPath(_SPEC["layout"]["root"]) / family / run_id / "_entry_"
    try:
        run_descriptor, _name, descriptors, links = _open_parent(
            root_descriptor, relative.as_posix()
        )
        run_identity = os.fstat(run_descriptor)
        return (
            root_descriptor,
            root_identity,
            descriptors,
            links,
            run_descriptor,
            run_identity,
        )
    except Exception:
        os.close(root_descriptor)
        raise


def _verify_canonical_run(
    repository_root: Path,
    root_descriptor: int,
    root_identity: os.stat_result,
    links: list[tuple[int, str, int, int]],
    run_descriptor: int,
    run_identity: os.stat_result,
) -> None:
    try:
        current_root = repository_root.lstat()
    except OSError as error:
        raise RunRecordError("Repository root changed during inspection.") from error
    expected_root = (root_identity.st_dev, root_identity.st_ino)
    if (
        not stat.S_ISDIR(current_root.st_mode)
        or (current_root.st_dev, current_root.st_ino) != expected_root
        or (os.fstat(root_descriptor).st_dev, os.fstat(root_descriptor).st_ino)
        != expected_root
    ):
        raise RunRecordError("Repository root changed during inspection.")
    _verify_directory_chain(links)
    current_run = os.fstat(run_descriptor)
    if (current_run.st_dev, current_run.st_ino) != (
        run_identity.st_dev,
        run_identity.st_ino,
    ):
        raise RunRecordError("Run directory changed during inspection.")


def _open_parent(
    run_descriptor: int, relative: str
) -> tuple[int, str, list[int], list[tuple[int, str, int, int]]]:
    parts = PurePosixPath(relative).parts
    descriptors = [os.dup(run_descriptor)]
    links: list[tuple[int, str, int, int]] = []
    try:
        for part in parts[:-1]:
            child = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptors[-1],
            )
            metadata = os.fstat(child)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(child)
                raise RunRecordError("Result path contains an untrusted component.")
            links.append((descriptors[-1], part, metadata.st_dev, metadata.st_ino))
            descriptors.append(child)
        return descriptors[-1], parts[-1], descriptors, links
    except (OSError, RunRecordError) as error:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        if isinstance(error, RunRecordError):
            raise
        raise RunRecordError("Result path is unavailable.") from error


def _verify_directory_chain(links: list[tuple[int, str, int, int]]) -> None:
    try:
        for parent, name, device, inode in links:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(current.st_mode) or (
                current.st_dev,
                current.st_ino,
            ) != (device, inode):
                raise RunRecordError("Result path changed while reading.")
    except OSError as error:
        raise RunRecordError("Result path changed while reading.") from error


def _close_descriptors(descriptors: list[int]) -> None:
    for descriptor in reversed(descriptors):
        os.close(descriptor)


def _entry_exists(run_descriptor: int, relative: str) -> bool:
    parent, name, descriptors, links = _open_parent(run_descriptor, relative)
    try:
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
            _verify_directory_chain(links)
            return True
        except FileNotFoundError:
            _verify_directory_chain(links)
            return False
    finally:
        _close_descriptors(descriptors)


def _open_stable_regular(
    run_descriptor: int, relative: str, expected_size: int
) -> tuple[
    int,
    os.stat_result,
    int,
    str,
    list[int],
    list[tuple[int, str, int, int]],
]:
    if expected_size < 0 or expected_size > _MAX_ARTIFACT_BYTES:
        raise RunRecordError("Result artifact exceeds the size limit.")
    try:
        parent, name, descriptors, links = _open_parent(run_descriptor, relative)
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size != expected_size
            or before.st_nlink != 1
        ):
            raise RunRecordError("Result artifact is not a trusted regular file.")
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent,
        )
        opened = os.fstat(descriptor)
        identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or identity
            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        ):
            os.close(descriptor)
            raise RunRecordError("Result artifact changed while opening.")
        return descriptor, opened, parent, name, descriptors, links
    except (OSError, RunRecordError) as error:
        if "descriptors" in locals():
            _close_descriptors(descriptors)
        if isinstance(error, RunRecordError):
            raise
        raise RunRecordError("Result artifact is unavailable.") from error


def _finish_stable_read(
    parent: int,
    name: str,
    descriptor: int,
    opened: os.stat_result,
    links: list[tuple[int, str, int, int]],
) -> None:
    after = os.fstat(descriptor)
    expected = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
    observed = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if observed != expected:
        raise RunRecordError("Result artifact changed while reading.")
    try:
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except OSError as error:
        raise RunRecordError("Result artifact path changed while reading.") from error
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_nlink != 1
        or (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
        != expected
    ):
        raise RunRecordError("Result artifact path changed while reading.")
    _verify_directory_chain(links)


def _hash_artifact(run_descriptor: int, relative: str, expected_size: int) -> str:
    descriptor, opened, parent, name, descriptors, links = _open_stable_regular(
        run_descriptor, relative, expected_size
    )
    digest = hashlib.sha256()
    total = 0
    try:
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
        if total != expected_size:
            raise RunRecordError("Result artifact has an inconsistent size.")
        _finish_stable_read(parent, name, descriptor, opened, links)
    finally:
        os.close(descriptor)
        _close_descriptors(descriptors)
    return digest.hexdigest()


def _read_exact(descriptor: int, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = os.read(descriptor, remaining)
        if not chunk:
            raise RunRecordError("Particle-state array is truncated.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_npy_header(stream) -> tuple[tuple[int, ...], bool, np.dtype, int]:
    try:
        version = np.lib.format.read_magic(stream)
        if version == (1, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_1_0(
                stream, max_header_size=_MAX_NPY_HEADER_BYTES
            )
        elif version in {(2, 0), (3, 0)}:
            shape, fortran, dtype = np.lib.format.read_array_header_2_0(
                stream, max_header_size=_MAX_NPY_HEADER_BYTES
            )
        else:
            raise RunRecordError(
                "Particle-state array uses an unsupported NPY version."
            )
    except (EOFError, ValueError, TypeError) as error:
        raise RunRecordError(
            "Particle-state array has an invalid NPY header."
        ) from error
    return tuple(shape), bool(fortran), np.dtype(dtype), stream.tell()


def _validate_states(
    run_descriptor: int, row: Mapping[str, Any], *, maximum_rows: int
) -> StateArrayEvidence:
    expected_size = int(row["size_bytes"])
    descriptor, opened, parent, name, descriptors, links = _open_stable_regular(
        run_descriptor, row["path"], expected_size
    )
    digest = hashlib.sha256()
    try:
        with os.fdopen(os.dup(descriptor), "rb", closefd=True) as stream:
            shape, _fortran, dtype, data_offset = _read_npy_header(stream)
        if len(shape) != 2 or shape[1] != 6 or shape[0] < 0 or shape[0] > maximum_rows:
            raise RunRecordError("Particle-state array must have shape (N, 6).")
        if dtype.hasobject or dtype.fields is not None or dtype != np.dtype("float64"):
            raise RunRecordError(
                "Particle-state array must contain plain float64 values."
            )
        expected_payload = shape[0] * shape[1] * dtype.itemsize
        if data_offset + expected_payload != expected_size:
            raise RunRecordError("Particle-state array size does not match its header.")
        os.lseek(descriptor, 0, os.SEEK_SET)
        remaining_header = data_offset
        while remaining_header:
            chunk = _read_exact(descriptor, min(1024 * 1024, remaining_header))
            digest.update(chunk)
            remaining_header -= len(chunk)
        remaining_values = shape[0] * shape[1]
        while remaining_values:
            count = min(_SCAN_VALUES, remaining_values)
            raw = _read_exact(descriptor, count * dtype.itemsize)
            digest.update(raw)
            values = np.frombuffer(raw, dtype=dtype, count=count)
            if not bool(np.all(np.isfinite(values))):
                raise RunRecordError("Particle-state array contains non-finite values.")
            remaining_values -= count
        if os.read(descriptor, 1):
            raise RunRecordError("Particle-state array contains trailing data.")
        _finish_stable_read(parent, name, descriptor, opened, links)
    finally:
        os.close(descriptor)
        _close_descriptors(descriptors)
    observed = digest.hexdigest()
    if observed != row["sha256"]:
        raise RunRecordError("Particle-state digest does not match the registry.")
    return StateArrayEvidence(
        path=row["path"],
        sha256=observed,
        size_bytes=expected_size,
        shape=(int(shape[0]), 6),
        dtype="float64",
        survivor_count=int(shape[0]),
    )


def _read_record_at(run_descriptor: int, relative: str, kind: str) -> dict[str, Any]:
    maximum = _SPEC["limits"]["json_max_bytes"]
    parent, name, descriptors, links = _open_parent(run_descriptor, relative)
    descriptor: int | None = None
    try:
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise RunRecordError("Run record is not a trusted regular file.")
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent,
        )
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
            raise RunRecordError("Run record changed while opening.")
        raw = _read_exact(descriptor, opened.st_size)
        _finish_stable_read(parent, name, descriptor, opened, links)
        return decode_record(kind, raw)
    except OSError as error:
        raise RunRecordError("Run record is unavailable.") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        _close_descriptors(descriptors)


def _validate_base_records(
    run: Mapping[str, Any],
    configuration: Mapping[str, Any],
    inputs: Mapping[str, Any],
    status: Mapping[str, Any],
) -> None:
    run_id = run["run_id"]
    family = run["family"]
    if any(record["run_id"] != run_id for record in (configuration, inputs, status)):
        raise RunRecordError("Run package identities do not match.")
    if configuration["family"] != family or inputs["family"] != family:
        raise RunRecordError("Run package families do not match.")
    if run["configuration_sha256"] != record_sha256("configuration", configuration):
        raise RunRecordError("Configuration digest does not match the run.")
    if run["inputs_sha256"] != record_sha256("inputs", inputs):
        raise RunRecordError("Input digest does not match the run.")
    if status["execution"]["mode"] != run["execution_mode"]:
        raise RunRecordError("Status execution mode contradicts the run.")
    if _parsed_timestamp(run["created_utc"]) > _parsed_timestamp(status["updated_utc"]):
        raise RunRecordError("Run timestamps are inconsistent.")


def _validate_publication_plan_at(
    run_descriptor: int,
    run: Mapping[str, Any],
    configuration: Mapping[str, Any],
    inputs: Mapping[str, Any],
    status: Mapping[str, Any],
    results: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
) -> PublicationPlan:
    """Validate publication evidence using one already-held run directory."""

    result = validate_record("results", dict(results))
    _validate_base_records(run, configuration, inputs, status)
    run_id = run["run_id"]
    family = run["family"]
    if result["run_id"] != run_id:
        raise RunRecordError("Results belong to another run.")
    if status["state"] not in {"running", "succeeded"}:
        raise RunRecordError("Results can be validated only for a running run.")
    created = _parsed_timestamp(run["created_utc"])
    completed = _parsed_timestamp(result["completed_utc"])
    status_updated = _parsed_timestamp(status["updated_utc"])
    if created > completed:
        raise RunRecordError("Run timestamps are inconsistent.")
    # Zeus running timestamps record when a poll observes execution, which
    # can occur after the remote worker has already completed.
    if (status["state"] == "running" and run["execution_mode"] == "local"
            and completed < status_updated):
        raise RunRecordError("Results predate the running status.")
    if status["state"] == "succeeded" and completed > status_updated:
        raise RunRecordError("Succeeded status predates durable results.")
    retained = bool(run["retention"]["particle_states"])
    if result["states_retained"] is not retained:
        raise RunRecordError("Results contradict the reviewed retention policy.")

    declared = {
        item["path"]: item for item in run["outputs"] if item["path"] != _SUMMARY_PATH
    }
    required = {path for path, item in declared.items() if item["required"]}
    realized = {item["path"]: item for item in result["artifacts"]}
    if not required.issubset(realized) or not set(realized).issubset(declared):
        raise RunRecordError("Realized outputs do not match the reviewed plan.")
    if any(realized[path]["kind"] != declared[path]["kind"] for path in realized):
        raise RunRecordError("Realized output kinds do not match the reviewed plan.")
    if any(
        path in {"run.json", "configuration.json", "inputs.json", "status.json"}
        or not path.startswith(("results/", "logs/"))
        for path in realized
    ):
        raise RunRecordError("Realized output path is outside the output directories.")

    receipt_bytes: bytes | None = None
    state_evidence: StateArrayEvidence | None = None
    artifacts: list[RealizedArtifact] = []
    for path, row in sorted(realized.items()):
        if row["kind"] == "particle_states":
            state_evidence = _validate_states(
                run_descriptor, row, maximum_rows=run["particle_count"]
            )
            observed = state_evidence.sha256
        elif row["kind"] == "retention_receipt":
            if receipt is None:
                raise RunRecordError("Omitted states require a retention receipt.")
            receipt_value = validate_record("retention_receipt", dict(receipt))
            if receipt_value["run_id"] != run_id:
                raise RunRecordError("Retention receipt belongs to another run.")
            if not (
                created <= _parsed_timestamp(receipt_value["created_utc"]) <= completed
            ):
                raise RunRecordError("Retention receipt timestamp is inconsistent.")
            receipt_bytes = encode_record("retention_receipt", receipt_value)
            if (
                row["size_bytes"] != len(receipt_bytes)
                or row["sha256"] != hashlib.sha256(receipt_bytes).hexdigest()
            ):
                raise RunRecordError("Retention receipt does not match the registry.")
            if _entry_exists(run_descriptor, path):
                observed = _hash_artifact(run_descriptor, path, row["size_bytes"])
                if observed != row["sha256"]:
                    raise RunRecordError("Retention receipt bytes do not match.")
            else:
                observed = row["sha256"]
        else:
            if row["size_bytes"] > _MAX_NON_STATE_BYTES:
                raise RunRecordError(
                    "Non-state result artifact exceeds the size limit."
                )
            observed = _hash_artifact(run_descriptor, path, row["size_bytes"])
            if observed != row["sha256"]:
                raise RunRecordError(
                    "Result artifact digest does not match the registry."
                )
        artifacts.append(
            RealizedArtifact(row["kind"], path, observed, row["size_bytes"])
        )

    if retained:
        if receipt is not None or state_evidence is None:
            raise RunRecordError("Retained states have an invalid disposition.")
        captured_field = (
            "n_survivors" if family == "mot_2d"
            else "residence_qualified_captured_count" if family == "mot_3d"
            else "captured"
        )
        captured = result["metrics"].get(captured_field)
        if (
            isinstance(captured, bool)
            or not isinstance(captured, int)
            or captured != state_evidence.survivor_count
        ):
            raise RunRecordError("Captured count does not match retained states.")
    else:
        if receipt_bytes is None:
            raise RunRecordError("Omitted states require a retention receipt.")
        if _entry_exists(run_descriptor, _STATES_PATH):
            raise RunRecordError("Particle states remain despite the retention policy.")

    results_bytes = encode_record("results", result)
    return PublicationPlan(
        run_id=run_id,
        family=family,
        expected_status_revision=status["revision"],
        results_bytes=results_bytes,
        results_sha256=hashlib.sha256(results_bytes).hexdigest(),
        receipt_bytes=receipt_bytes,
        artifacts=tuple(artifacts),
        state_array=state_evidence,
    )


def inspect_run_package(
    repository_root: Path, family: str, run_id: str
) -> InspectedRunPackage:
    """Read one canonical run without leaving its held descriptor chain."""

    root = Path(repository_root).absolute()
    (
        root_descriptor,
        root_identity,
        directory_descriptors,
        directory_links,
        run_descriptor,
        run_identity,
    ) = _open_canonical_run(root, family, run_id)
    try:
        run = _read_record_at(run_descriptor, "run.json", "run")
        configuration = _read_record_at(
            run_descriptor, "configuration.json", "configuration"
        )
        inputs = _read_record_at(run_descriptor, "inputs.json", "inputs")
        status = _read_record_at(run_descriptor, "status.json", "status")
        _validate_base_records(run, configuration, inputs, status)
        if run["family"] != family or run["run_id"] != run_id:
            raise RunRecordError("Run package identity is inconsistent.")

        results: dict[str, Any] | None = None
        receipt: dict[str, Any] | None = None
        publication: PublicationPlan | None = None
        if _entry_exists(run_descriptor, _SUMMARY_PATH):
            results = _read_record_at(run_descriptor, _SUMMARY_PATH, "results")
            if not results["states_retained"]:
                receipt = _read_record_at(
                    run_descriptor, _RECEIPT_PATH, "retention_receipt"
                )
            # Generic artifact validation remains available separately. Every
            # canonical read/admission also rechecks the publisher's exact family
            # metric contract, including runs that intentionally omitted states.
            from workflow_api.run_metrics import validate_family_metrics
            validate_family_metrics(family, run, results, configuration)
            publication = _validate_publication_plan_at(
                run_descriptor,
                run,
                configuration,
                inputs,
                status,
                results,
                receipt,
            )

        _verify_canonical_run(
            root,
            root_descriptor,
            root_identity,
            directory_links,
            run_descriptor,
            run_identity,
        )
        return InspectedRunPackage(
            run=_freeze(run),
            configuration=_freeze(configuration),
            inputs=_freeze(inputs),
            status=_freeze(status),
            results=_freeze(results) if results is not None else None,
            publication=publication,
        )
    finally:
        _close_descriptors(directory_descriptors)
        os.close(root_descriptor)


def validate_publication_plan(
    run_directory: Path,
    results: Mapping[str, Any],
    receipt: Mapping[str, Any] | None = None,
) -> PublicationPlan:
    """Validate staged realized outputs without publishing or changing status."""

    directory = Path(run_directory).absolute()
    layout_parts = PurePosixPath(_SPEC["layout"]["root"]).parts
    if len(directory.parents) <= len(layout_parts) + 1:
        raise RunRecordError("Run path is not canonical.")
    repository_root = directory.parents[len(layout_parts) + 1]
    family = directory.parent.name
    run_name = directory.name
    if directory != repository_root.joinpath(*layout_parts, family, run_name):
        raise RunRecordError("Run path is not canonical.")
    (
        root_descriptor,
        root_identity,
        directory_descriptors,
        directory_links,
        run_descriptor,
        initial_directory,
    ) = _open_canonical_run(repository_root, family, run_name)
    try:
        run = _read_record_at(run_descriptor, "run.json", "run")
        configuration = _read_record_at(
            run_descriptor, "configuration.json", "configuration"
        )
        inputs = _read_record_at(run_descriptor, "inputs.json", "inputs")
        status = _read_record_at(run_descriptor, "status.json", "status")
        plan = _validate_publication_plan_at(
            run_descriptor,
            run,
            configuration,
            inputs,
            status,
            results,
            receipt,
        )

        _verify_canonical_run(
            repository_root,
            root_descriptor,
            root_identity,
            directory_links,
            run_descriptor,
            initial_directory,
        )
        return plan
    finally:
        _close_descriptors(directory_descriptors)
        os.close(root_descriptor)
