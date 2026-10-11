"""Bounded, read-only discovery for canonical individual runs."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

from workflow_api.run_records import RunRecordError
from workflow_api.run_results import PublicationPlan, inspect_run_package
from workflow_api.run_specification import INDIVIDUAL_RUN_SPECIFICATION


_SPEC = INDIVIDUAL_RUN_SPECIFICATION
_MAX_RUNS = 4096
_RUN_ID = re.compile(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?")


@dataclass(frozen=True)
class DiscoveredRun:
    family: str
    run_id: str
    path: str
    state: str
    integrity: str
    diagnostic: str | None


@dataclass(frozen=True)
class InspectedRun:
    """One fully checked, immutable point-in-time view of a run package."""

    family: str
    run_id: str
    path: str
    state: str
    integrity: str
    run: Mapping[str, Any]
    configuration: Mapping[str, Any]
    inputs: Mapping[str, Any]
    status: Mapping[str, Any]
    results: Mapping[str, Any] | None
    publication: PublicationPlan | None


@dataclass(frozen=True)
class DiscoverySnapshot:
    records: tuple[DiscoveredRun, ...]
    truncated: bool


def _regular_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def inspect_run(repository_root: Path, family: str, run_id: str) -> InspectedRun:
    """Return the sole D3 trust decision and verified evidence for one run."""

    root = Path(repository_root).resolve(strict=True)
    if family not in _SPEC["layout"]["families"]:
        raise RunRecordError("Run family is invalid.")
    if (
        not isinstance(run_id, str)
        or len(run_id) > _SPEC["limits"]["run_id_max_characters"]
        or _RUN_ID.fullmatch(run_id) is None
    ):
        raise RunRecordError("Run id is invalid.")
    family_root = root / _SPEC["layout"]["root"] / family
    directory = family_root / run_id
    if not _regular_directory(family_root) or not _regular_directory(directory):
        raise RunRecordError("Run path is untrusted.")
    relative = directory.relative_to(root).as_posix()
    package = inspect_run_package(root, family, run_id)
    run = package.run
    configuration = package.configuration
    inputs = package.inputs
    status = package.status
    results = package.results
    publication = package.publication
    if publication is not None:
        if status["state"] == "succeeded":
            integrity = "complete_verified"
        elif status["state"] == "running":
            integrity = "incomplete_publication"
        else:
            raise RunRecordError("Unexpected result registry for the run state.")
    elif status["state"] == "succeeded":
        raise RunRecordError("Succeeded run has no durable result registry.")
    elif status["state"] in _SPEC["lifecycle"]["terminal"]:
        integrity = "terminal_without_results"
    else:
        integrity = "active"
    return InspectedRun(
        family=family,
        run_id=run_id,
        path=relative,
        state=status["state"],
        integrity=integrity,
        run=run,
        configuration=configuration,
        inputs=inputs,
        status=status,
        results=results,
        publication=publication,
    )


def _inspect(root: Path, family: str, directory: Path) -> DiscoveredRun:
    relative = directory.relative_to(root).as_posix()
    run_id = directory.name
    try:
        inspected = inspect_run(root, family, run_id)
        return DiscoveredRun(
            family,
            run_id,
            relative,
            inspected.state,
            inspected.integrity,
            None,
        )
    except (OSError, RunRecordError, KeyError, TypeError, ValueError):
        return DiscoveredRun(
            family, run_id, relative, "unknown", "invalid", "invalid_run"
        )


def discover_run_snapshot(
    repository_root: Path, *, maximum_runs: int = _MAX_RUNS
) -> DiscoverySnapshot:
    if (
        isinstance(maximum_runs, bool)
        or not isinstance(maximum_runs, int)
        or not 1 <= maximum_runs <= _MAX_RUNS
    ):
        raise ValueError("Run discovery limit is invalid.")
    root = Path(repository_root).resolve(strict=True)
    runs_root = root / _SPEC["layout"]["root"]
    if not runs_root.exists():
        return DiscoverySnapshot((), False)
    if not _regular_directory(runs_root):
        raise RunRecordError("Canonical run root is untrusted.")
    # Bound directory iteration before sorting or filtering. Hidden and
    # untrusted entries consume the same budget as valid runs, so an attacker
    # cannot force an unbounded allocation with names that are later ignored.
    raw_entries: list[tuple[int, str, str, bool]] = []
    truncated = False
    for family in _SPEC["layout"]["families"]:
        family_root = runs_root / family
        if not family_root.exists():
            continue
        if not _regular_directory(family_root):
            raise RunRecordError("Canonical run family directory is untrusted.")
        descriptor: int | None = None
        try:
            descriptor = os.open(
                family_root,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            with os.scandir(descriptor) as entries:
                for entry in entries:
                    raw_entries.append(
                        (
                            _SPEC["layout"]["families"].index(family),
                            family,
                            entry.name,
                            entry.is_dir(follow_symlinks=False),
                        )
                    )
                    if len(raw_entries) > maximum_runs:
                        truncated = True
                        break
        except OSError as error:
            raise RunRecordError("Canonical runs cannot be inspected.") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if truncated:
            break

    records: list[DiscoveredRun] = []
    for _family_index, family, name, was_directory in sorted(
        raw_entries[:maximum_runs], key=lambda item: (item[0], item[2])
    ):
        if name.startswith("."):
            continue
        child = runs_root / family / name
        if not was_directory or not _regular_directory(child):
            records.append(
                DiscoveredRun(
                    family,
                    name,
                    child.relative_to(root).as_posix(),
                    "unknown",
                    "invalid",
                    "untrusted_run_path",
                )
            )
        else:
            records.append(_inspect(root, family, child))
    return DiscoverySnapshot(tuple(records), truncated)


def discover_runs(
    repository_root: Path, *, maximum_runs: int = _MAX_RUNS
) -> tuple[DiscoveredRun, ...]:
    """Compatibility tuple view; overflow is bounded and never fails the list."""

    return discover_run_snapshot(repository_root, maximum_runs=maximum_runs).records
