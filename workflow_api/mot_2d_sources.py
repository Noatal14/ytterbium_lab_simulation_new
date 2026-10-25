"""Read-only registry for canonical Zeeman inputs offered by campaign setup."""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

import numpy as np
from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
    attest_canonical_zeeman_metadata,
)
from workflow_api.repository_paths import canonical_repo_relative

SOURCE_ROOT = Path("data/particle_states/after_zeeman")
EXPECTED_SEEDS = tuple(range(3000, 3035))
MAX_METADATA_BYTES = 128 * 1024
MAX_SOURCES = 128


class SourceScanLimits:
    """Optional resource bounds for interactive source discovery."""

    def __init__(
        self,
        *,
        maximum_file_bytes: int,
        maximum_total_bytes: int,
        maximum_rows_per_file: int,
        maximum_total_rows: int,
        maximum_npy_header_bytes: int,
    ):
        self.maximum_file_bytes = maximum_file_bytes
        self.maximum_total_bytes = maximum_total_bytes
        self.maximum_rows_per_file = maximum_rows_per_file
        self.maximum_total_rows = maximum_total_rows
        self.maximum_npy_header_bytes = maximum_npy_header_bytes


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_file(path: Path, root: Path) -> bool:
    resolved_root = root.resolve(); resolved = path.resolve()
    if not _within(resolved, resolved_root) or not path.is_file() or path.is_symlink():
        return False
    current = root
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    return True


def _metadata(path: Path, root: Path) -> dict[str, Any]:
    if not _safe_file(path, root) or path.stat().st_size > MAX_METADATA_BYTES:
        raise ValueError("untrusted metadata")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("invalid metadata")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_id(relative: Path) -> str:
    return "zeeman-" + hashlib.sha256(relative.as_posix().encode()).hexdigest()[:20]


def inspect_source(
    directory: Path,
    repository_root: Path,
    *,
    include_records: bool = False,
    scan_limits: SourceScanLimits | None = None,
    expected_seeds: tuple[int, ...] = EXPECTED_SEEDS,
    acceptance_profile_id: str | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    source_root = (repository_root / SOURCE_ROOT).resolve()
    if directory.is_symlink() or not directory.is_dir() or not _within(directory.resolve(), source_root):
        raise ValueError("invalid source")
    from workflow_api.acceptance_profile import (
        assert_acceptance_path, assert_scientific_source, load_acceptance_profile,
    )
    profile = load_acceptance_profile(acceptance_profile_id) if acceptance_profile_id is not None else None
    if profile is not None:
        assert_acceptance_path(directory, repository_root)
    elif "ui_acceptance" in directory.relative_to(source_root).parts:
        raise ValueError("TEST ONLY sources cannot be used by scientific campaigns.")
    profiles: set[str] = set(); commits: set[str] = set(); survivor_counts: list[int] = []
    identities: list[str] = []; records: list[dict[str, Any]] = []
    total_bytes = 0
    total_rows = 0
    if (
        not expected_seeds
        or len(expected_seeds) != len(set(expected_seeds))
        or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in expected_seeds)
    ):
        raise ValueError("invalid expected seeds")
    for seed in expected_seeds:
        matches = list(directory.glob(f"production_zeeman_n*_dt*_seed{seed}.npy"))
        if len(matches) != 1:
            raise ValueError("missing or duplicate canonical seed")
        state = matches[0]; metadata_path = state.with_suffix(".json")
        if not _safe_file(state, source_root):
            raise ValueError("untrusted state")
        state_bytes = state.stat().st_size
        total_bytes += state_bytes
        if scan_limits is not None and (
            state_bytes > scan_limits.maximum_file_bytes
            or total_bytes > scan_limits.maximum_total_bytes
        ):
            raise ValueError("state source exceeds interactive byte limits")
        metadata = _metadata(metadata_path, source_root)
        if profile is None:
            assert_scientific_source(metadata)
        elif metadata.get("acceptance") != profile.provenance():
            raise ValueError("Acceptance source provenance does not match its profile.")
        metadata_bytes = metadata_path.stat().st_size
        parameters = metadata.get("parameters") if isinstance(metadata.get("parameters"), dict) else {}
        software = metadata.get("software") if isinstance(metadata.get("software"), dict) else {}
        required_generation = ("n_initial_atoms", "dt_s")
        if (
            parameters.get("seed") != seed
            or not all(parameters.get(key) is not None for key in required_generation)
            or parameters.get("resolved_zeeman_magnet_profile") is None
            or software.get("git_commit") is None
            or parameters.get("resolved_zeeman_magnet_profile")
            != CANONICAL_ZEEMAN_PROFILE_NAME
        ):
            raise ValueError("incomplete provenance")
        provenance = attest_canonical_zeeman_metadata(metadata, allow_legacy=True)
        array = np.load(
            state,
            mmap_mode="r",
            allow_pickle=False,
            max_header_size=(
                scan_limits.maximum_npy_header_bytes
                if scan_limits is not None
                else 10_000
            ),
        )
        rows = int(array.shape[0]) if array.ndim >= 1 else 0
        total_rows += rows
        if scan_limits is not None and (
            rows > scan_limits.maximum_rows_per_file
            or total_rows > scan_limits.maximum_total_rows
        ):
            raise ValueError("state source exceeds interactive row limits")
        digest = _sha256(state)
        metadata_digest = _sha256(metadata_path)
        if (
            array.ndim != 2 or array.shape[1] != 6 or not np.all(np.isfinite(array))
            or metadata.get("shape") != list(array.shape)
            or metadata.get("dtype") != str(array.dtype)
            or metadata.get("n_survivors") != len(array)
            or metadata.get("output_sha256") != digest
        ):
            raise ValueError("state and metadata mismatch")
        if len(array) == 0:
            raise ValueError("Campaign input ensembles must contain survivors for a defined conditional efficiency.")
        profiles.add(str(parameters["resolved_zeeman_magnet_profile"]))
        commits.add(str(software["git_commit"]))
        survivor_counts.append(len(array)); identities.append(f"{seed}:{digest}:{metadata_digest}")
        record = {
            "zeeman_seed": seed,
            "path": canonical_repo_relative(repository_root, state, allowed_root=SOURCE_ROOT, require="file"),
            "metadata_path": canonical_repo_relative(repository_root, metadata_path, allowed_root=SOURCE_ROOT, require="file"),
            "sha256": digest,
            "size_bytes": state_bytes,
            "metadata_sha256": metadata_digest,
            "metadata_size_bytes": metadata_bytes,
            "shape": list(array.shape), "dtype": str(array.dtype),
            "survivor_count": len(array),
            "zeeman_profile": str(parameters["resolved_zeeman_magnet_profile"]),
            "source_git_commit": str(software["git_commit"]),
            "zeeman_profile_sha256": provenance["zeeman_profile_sha256"],
            "legacy_attested_profile": provenance["legacy_attested_profile"],
            "generation": {key: parameters.get(key) for key in ("n_initial_atoms", "dt_s", "stochastic", "collimation_angle_deg")},
        }
        if not provenance["legacy_attested_profile"]:
            record.update({
                "laboratory_spec_version": provenance["laboratory_spec_version"],
                "laboratory_spec_sha256": provenance["laboratory_spec_sha256"],
            })
        records.append(record)
    if len(profiles) != 1 or len(commits) != 1:
        raise ValueError("mixed source provenance")
    relative = directory.resolve().relative_to(repository_root)
    fingerprint = hashlib.sha256("\n".join(identities).encode()).hexdigest()
    result = {
        "id": _source_id(relative),
        "path": relative.as_posix(),
        "profile": next(iter(profiles)),
        "ensemble_count": len(expected_seeds),
        "minimum_survivors": min(survivor_counts),
        "maximum_survivors": max(survivor_counts),
        "fingerprint": fingerprint,
    }
    if include_records:
        result["records"] = records
    return result


def list_sources(
    repository_root: Path,
    *,
    include_pool_counts: bool = False,
    scan_limits: SourceScanLimits | None = None,
    acceptance_profile_id: str | None = None,
) -> dict[str, Any]:
    """List strictly attested campaign folders.

    ``include_pool_counts`` is an internal read-only projection for an
    individual-run catalog.  The default campaign API remains byte-for-byte
    compatible and never gains a second, weaker validation path.
    """
    source_root = (repository_root.resolve() / SOURCE_ROOT).resolve()
    if acceptance_profile_id is not None:
        from workflow_api.acceptance_profile import load_acceptance_profile
        load_acceptance_profile(acceptance_profile_id)
        source_root = source_root / "ui_acceptance"
    if not source_root.is_dir():
        result = {"sources": [], "invalid_count": 0, "total": 0}
        if include_pool_counts:
            result["truncated"] = False
        return result
    sources: list[dict[str, Any]] = []; invalid = 0; truncated = False

    def admit(directory: Path) -> None:
        nonlocal invalid
        try:
            profile_options = ({"acceptance_profile_id": acceptance_profile_id}
                               if acceptance_profile_id is not None else {})
            source = inspect_source(
                directory,
                repository_root,
                include_records=include_pool_counts,
                scan_limits=scan_limits,
                **profile_options,
            )
            if include_pool_counts:
                source["pooled_survivor_count"] = sum(
                    record["survivor_count"] for record in source.pop("records")
                )
            sources.append(source)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            invalid += 1

    if not include_pool_counts:
        # Compatibility branch: preserve the original campaign registry scan
        # literally.  The raw-entry islice bound and the pre-filter overflow
        # check are externally characterized legacy behavior.
        for directory in itertools.islice(source_root.iterdir(), MAX_SOURCES + 1):
            if len(sources) + invalid >= MAX_SOURCES:
                invalid += 1
                break
            if (
                directory.is_symlink()
                or not directory.is_dir()
                or directory.name.startswith(".")
            ):
                continue
            admit(directory)
    else:
        candidate_count = 0
        for directory in source_root.iterdir():
            if (
                directory.is_symlink()
                or not directory.is_dir()
                or directory.name.startswith(".")
            ):
                continue
            if candidate_count >= MAX_SOURCES:
                truncated = True
                break
            candidate_count += 1
            admit(directory)
    sources.sort(key=lambda row: row["path"])
    result = {"sources": sources, "invalid_count": invalid, "total": len(sources)}
    if include_pool_counts:
        result["truncated"] = truncated
    return result
