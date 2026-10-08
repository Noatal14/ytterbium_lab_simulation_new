"""Strict repository-relative path identities for portable workflow records."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Literal


MAX_REPOSITORY_PATH_BYTES = 512
PathKind = Literal["file", "dir"]


def _relative_identity(value: str | os.PathLike[str]) -> PurePosixPath:
    text = os.fspath(value)
    if not isinstance(text, str):
        raise ValueError("Repository path must be text.")
    if (
        not text
        or len(text.encode("utf-8")) > MAX_REPOSITORY_PATH_BYTES
        or not text.isprintable()
        or "\\" in text
    ):
        raise ValueError("Repository path is not a canonical portable path.")
    candidate = PurePosixPath(text)
    if (
        candidate.is_absolute()
        or text != candidate.as_posix()
        or candidate.as_posix() == "."
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError("Repository path is not a canonical portable path.")
    return candidate


def _allowed_directory(repository_root: Path, allowed_root: str | os.PathLike[str]) -> Path:
    identity = _relative_identity(allowed_root)
    candidate = repository_root.joinpath(*identity.parts)
    _reject_symlink_components(repository_root, candidate)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError("Allowed repository directory is unavailable.") from error
    if not resolved.is_dir():
        raise ValueError("Allowed repository path is not a directory.")
    return resolved


def _reject_symlink_components(repository_root: Path, candidate: Path) -> None:
    try:
        relative = candidate.relative_to(repository_root)
    except ValueError as error:
        raise ValueError("Repository path is outside the repository.") from error
    current = repository_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Repository path contains a symbolic link.")


def _require_kind(path: Path, kind: PathKind) -> None:
    if kind == "file":
        valid = path.is_file()
    elif kind == "dir":
        valid = path.is_dir()
    else:
        raise ValueError("Repository path kind is invalid.")
    if not valid:
        raise ValueError(f"Repository path is not a {kind}.")


def resolve_repo_relative(
    repository_root: str | os.PathLike[str],
    value: str | os.PathLike[str],
    *,
    allowed_root: str | os.PathLike[str],
    require: PathKind,
) -> Path:
    """Resolve a stored portable identity beneath one allowlisted repository root."""

    root = Path(repository_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Repository root is not a directory.")
    identity = _relative_identity(value)
    allowed = _allowed_directory(root, allowed_root)
    candidate = root.joinpath(*identity.parts)
    _reject_symlink_components(root, candidate)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(allowed)
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError("Repository path is outside the allowed directory.") from error
    _require_kind(resolved, require)
    return resolved


def canonical_repo_relative(
    repository_root: str | os.PathLike[str],
    path: str | os.PathLike[str],
    *,
    allowed_root: str | os.PathLike[str],
    require: PathKind,
) -> str:
    """Return a portable identity for an existing trusted repository path."""

    root = Path(repository_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Repository root is not a directory.")
    raw = Path(path)
    if raw.is_absolute():
        candidate = raw
    else:
        identity = _relative_identity(path)
        candidate = root.joinpath(*identity.parts)
    allowed = _allowed_directory(root, allowed_root)
    _reject_symlink_components(root, candidate)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(allowed)
        relative = resolved.relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError("Repository path is outside the allowed directory.") from error
    _require_kind(resolved, require)
    _relative_identity(relative)
    return relative
