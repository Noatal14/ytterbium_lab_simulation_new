"""Small bounded JSON reader for untrusted campaign artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_JSON_BYTES = 8 * 1024 * 1024


def read_json(path: Path, *, maximum_bytes: int = MAX_JSON_BYTES) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError("JSON artifact is not a trusted regular file")
    if path.stat().st_size > maximum_bytes:
        raise ValueError("JSON artifact exceeds the inspection size limit")
    with path.open("rb") as stream:
        raw = stream.read(maximum_bytes + 1)
    if len(raw) > maximum_bytes:
        raise ValueError("JSON artifact exceeds the inspection size limit")
    return json.loads(raw.decode("utf-8"))
