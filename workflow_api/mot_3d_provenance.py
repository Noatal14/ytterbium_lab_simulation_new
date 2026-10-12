"""Path-independent provenance identities shared by 3D planning and readers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def input_registry_digest(roles: Mapping[str, list[dict[str, Any]]]) -> str:
    """Hash the exact portable scientific identity of all frozen 2D inputs."""
    rows = []
    for role in ("discovery", "refinement", "preliminary_check"):
        records = roles.get(role)
        if not isinstance(records, (list, tuple)):
            raise ValueError("Invalid frozen 3D input-role registry.")
        for record in records:
            if not isinstance(record, Mapping):
                raise ValueError("Invalid frozen 3D input record.")
            required = {
                "zeeman_seed",
                "mot_seed",
                "sha256",
                "metadata_sha256",
                "shape",
                "dtype",
                "n_survivors",
                "source_design",
                "source_parameters",
            }
            if not required.issubset(record):
                raise ValueError("Incomplete frozen 3D input record.")
            rows.append(
                {
                    "role": role,
                    **{key: record[key] for key in required},
                }
            )
    payload = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
