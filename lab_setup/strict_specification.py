"""Neutral strict-JSON helpers for bundled versioned specifications."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable


def freeze(value: Any) -> Any:
    """Recursively expose JSON containers as immutable Python containers."""
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(freeze(child) for child in value)
    return value


def canonical_digest(value: Any) -> str:
    """Return the SHA-256 of the repository's canonical UTF-8 JSON form."""
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting duplicate member names."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def require_exact_keys(value: Any, keys: set[str], label: str) -> None:
    """Require a JSON object with exactly ``keys`` and no extensions."""
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"Invalid {label} schema.")


def require_finite_number(
    value: Any,
    label: str,
    *,
    lo: float | None = None,
    hi: float | None = None,
    closed: bool = False,
) -> None:
    """Require an exact JSON number satisfying optional finite bounds."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"Invalid {label}.")
    if lo is not None and (value < lo if closed else value <= lo):
        raise ValueError(f"Invalid {label}.")
    if hi is not None and (value > hi if closed else value >= hi):
        raise ValueError(f"Invalid {label}.")


def read_strict_json(
    path: Path,
    validator: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    max_bytes: int,
    error_message: str,
) -> dict[str, Any]:
    """Read one bounded regular file exactly once and validate strict JSON."""
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise ValueError
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            identity = (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            )
            if not stat.S_ISREG(opened.st_mode) or identity != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ):
                raise ValueError
            chunks: list[bytes] = []
            remaining = opened.st_size
            while remaining:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    raise ValueError
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
            if (
                len(raw) != opened.st_size
                or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                != identity
            ):
                raise ValueError
        finally:
            os.close(descriptor)
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
        return validator(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError(error_message) from error
