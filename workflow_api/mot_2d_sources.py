"""Read-only registry for canonical Zeeman inputs offered by campaign setup."""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

import numpy as np
from workflow_api.repository_paths import canonical_repo_relative

SOURCE_ROOT = Path("data/particle_states/after_zeeman")
EXPECTED_SEEDS = tuple(range(3000, 3035))
MAX_METADATA_BYTES = 128 * 1024
MAX_SOURCES = 128


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


def inspect_source(directory: Path, repository_root: Path, *, include_records: bool = False) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    source_root = (repository_root / SOURCE_ROOT).resolve()
    if directory.is_symlink() or not directory.is_dir() or not _within(directory.resolve(), source_root):
        raise ValueError("invalid source")
    profiles: set[str] = set(); commits: set[str] = set(); survivor_counts: list[int] = []
    identities: list[str] = []; records: list[dict[str, Any]] = []
    for seed in EXPECTED_SEEDS:
        matches = list(directory.glob(f"production_zeeman_n*_dt*_seed{seed}.npy"))
        if len(matches) != 1:
            raise ValueError("missing or duplicate canonical seed")
        state = matches[0]; metadata_path = state.with_suffix(".json")
        if not _safe_file(state, source_root):
            raise ValueError("untrusted state")
        metadata = _metadata(metadata_path, source_root)
        parameters = metadata.get("parameters") if isinstance(metadata.get("parameters"), dict) else {}
        software = metadata.get("software") if isinstance(metadata.get("software"), dict) else {}
        required_generation = ("n_initial_atoms", "dt_s")
        if (
            parameters.get("seed") != seed
            or not all(parameters.get(key) is not None for key in required_generation)
            or parameters.get("resolved_zeeman_magnet_profile") is None
            or software.get("git_commit") is None
        ):
            raise ValueError("incomplete provenance")
        array = np.load(state, mmap_mode="r", allow_pickle=False)
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
        profiles.add(str(parameters["resolved_zeeman_magnet_profile"]))
        commits.add(str(software["git_commit"]))
        survivor_counts.append(len(array)); identities.append(f"{seed}:{digest}:{metadata_digest}")
        records.append({
            "zeeman_seed": seed,
            "path": canonical_repo_relative(repository_root, state, allowed_root=SOURCE_ROOT, require="file"),
            "metadata_path": canonical_repo_relative(repository_root, metadata_path, allowed_root=SOURCE_ROOT, require="file"),
            "sha256": digest,
            "metadata_sha256": metadata_digest,
            "shape": list(array.shape), "dtype": str(array.dtype),
            "survivor_count": len(array),
            "zeeman_profile": str(parameters["resolved_zeeman_magnet_profile"]),
            "source_git_commit": str(software["git_commit"]),
            "generation": {key: parameters.get(key) for key in ("n_initial_atoms", "dt_s", "stochastic", "collimation_angle_deg")},
        })
    if len(profiles) != 1 or len(commits) != 1:
        raise ValueError("mixed source provenance")
    relative = directory.resolve().relative_to(repository_root)
    fingerprint = hashlib.sha256("\n".join(identities).encode()).hexdigest()
    result = {
        "id": _source_id(relative),
        "path": relative.as_posix(),
        "profile": next(iter(profiles)),
        "ensemble_count": len(EXPECTED_SEEDS),
        "minimum_survivors": min(survivor_counts),
        "maximum_survivors": max(survivor_counts),
        "fingerprint": fingerprint,
    }
    if include_records:
        result["records"] = records
    return result


def list_sources(repository_root: Path) -> dict[str, Any]:
    source_root = (repository_root.resolve() / SOURCE_ROOT).resolve()
    if not source_root.is_dir():
        return {"sources": [], "invalid_count": 0, "total": 0}
    sources: list[dict[str, Any]] = []; invalid = 0
    for directory in itertools.islice(source_root.iterdir(), MAX_SOURCES + 1):
        if len(sources) + invalid >= MAX_SOURCES:
            invalid += 1
            break
        if directory.is_symlink() or not directory.is_dir() or directory.name.startswith("."):
            continue
        try:
            sources.append(inspect_source(directory, repository_root))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            invalid += 1
    sources.sort(key=lambda row: row["path"])
    return {"sources": sources, "invalid_count": invalid, "total": len(sources)}
