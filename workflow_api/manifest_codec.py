"""Version-dispatched, read-only campaign-manifest decoding.

Campaign manifests predate an explicit ``schema_version`` field.  Their
established ``kind`` values therefore form the V1 discriminator.  Decoding
never normalizes or writes a manifest: callers receive both the exact bytes
that were authenticated and the JSON object parsed from those bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
import copy
from enum import Enum
import json
import os
from pathlib import Path
import stat
from typing import Any, Literal


MAX_MANIFEST_BYTES = 2 * 1024 * 1024
ManifestFamily = Literal["mot_2d", "mot_3d"]


class ManifestFailure(str, Enum):
    NOT_REGULAR = "not_regular"
    UNAVAILABLE = "unavailable"
    OVERSIZED = "oversized"
    INVALID_JSON = "invalid_json"
    NON_OBJECT = "non_object"
    UNSUPPORTED_KIND = "unsupported_kind"
    FAMILY_MISMATCH = "family_mismatch"
    MIXED_SCHEMA = "mixed_schema"
    CHANGED = "changed"


class ManifestCodecError(ValueError):
    """Typed failure safe for translation at an API boundary."""

    def __init__(self, reason: ManifestFailure, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class CampaignManifest:
    family: ManifestFamily
    version: str
    raw_bytes: bytes
    _model: dict[str, Any]

    @property
    def model(self) -> dict[str, Any]:
        """Return a defensive deep copy of the authenticated parsed model."""
        return copy.deepcopy(self._model)


_KINDS: dict[str, tuple[ManifestFamily, str]] = {
    "mot_2d_s0_campaign": ("mot_2d", "mot-2d-manifest-v1"),
    "mot_3d_campaign_v2": ("mot_3d", "mot-3d-manifest-v1"),
}
_TWO_D_MARKERS = frozenset(("s0_values", "ensemble_source", "fixed_design", "seed_roles", "mot_seeds", "input_ensembles"))
_THREE_D_MARKERS = frozenset(("upstream_2d_campaign", "input_roles", "jobs"))


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ManifestCodecError(
                ManifestFailure.INVALID_JSON,
                f"Campaign manifest repeats JSON key {key!r}.",
            )
        value[key] = item
    return value


def classify_manifest(
    payload: dict[str, Any], *, expected_family: ManifestFamily | None = None
) -> tuple[ManifestFamily, str]:
    """Validate and classify an already-parsed manifest object."""
    if not isinstance(payload, dict):
        raise ManifestCodecError(
            ManifestFailure.NON_OBJECT,
            "Campaign manifest must contain a JSON object.",
        )
    identity = _KINDS.get(payload.get("kind"))
    if identity is None:
        raise ManifestCodecError(
            ManifestFailure.UNSUPPORTED_KIND,
            f"Unsupported campaign kind {payload.get('kind')!r}.",
        )
    family, version = identity
    if expected_family is not None and family != expected_family:
        raise ManifestCodecError(
            ManifestFailure.FAMILY_MISMATCH,
            f"Campaign family {family!r} does not match expected family "
            f"{expected_family!r}."
        )
    opposing = _THREE_D_MARKERS if family == "mot_2d" else _TWO_D_MARKERS
    mixed = sorted(opposing.intersection(payload))
    if mixed:
        raise ManifestCodecError(
            ManifestFailure.MIXED_SCHEMA,
            "Campaign manifest mixes incompatible implicit schemas: "
            + ", ".join(mixed)
        )
    return family, version


def decode_manifest(
    raw: bytes, *, expected_family: ManifestFamily | None = None
) -> CampaignManifest:
    """Decode one established implicit V1 schema, rejecting mixed identity."""
    if not isinstance(raw, bytes):
        raise TypeError("Campaign manifest input must be bytes.")
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManifestCodecError(
            ManifestFailure.OVERSIZED,
            "Campaign manifest exceeds the inspection size limit.",
        )
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except ManifestCodecError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ManifestCodecError(
            ManifestFailure.INVALID_JSON,
            "Campaign manifest is not valid UTF-8 JSON.",
        ) from error
    family, version = classify_manifest(payload, expected_family=expected_family)
    return CampaignManifest(family, version, raw, payload)


def read_manifest(
    path: str | Path, *, expected_family: ManifestFamily | None = None
) -> CampaignManifest:
    """Read and decode a regular manifest without following a final symlink."""
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ManifestCodecError(
            ManifestFailure.NOT_REGULAR,
            "Campaign manifest is not a trusted regular file.",
        )
    try:
        before = candidate.stat()
    except OSError as error:
        raise ManifestCodecError(
            ManifestFailure.UNAVAILABLE, "Campaign manifest is unavailable."
        ) from error
    if before.st_size > MAX_MANIFEST_BYTES:
        raise ManifestCodecError(
            ManifestFailure.OVERSIZED,
            "Campaign manifest exceeds the inspection size limit.",
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as error:
        raise ManifestCodecError(
            ManifestFailure.UNAVAILABLE,
            "Campaign manifest could not be opened safely.",
        ) from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns
        ) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
            raise ManifestCodecError(
                ManifestFailure.CHANGED,
                "Campaign manifest changed while it was opened.",
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, MAX_MANIFEST_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_MANIFEST_BYTES:
                raise ManifestCodecError(
                    ManifestFailure.OVERSIZED,
                    "Campaign manifest exceeds the inspection size limit.",
                )
        after = os.fstat(descriptor)
        if (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
            raise ManifestCodecError(
                ManifestFailure.CHANGED,
                "Campaign manifest changed while it was read.",
            )
    finally:
        os.close(descriptor)
    try:
        current = candidate.lstat()
    except OSError as error:
        raise ManifestCodecError(
            ManifestFailure.UNAVAILABLE,
            "Campaign manifest changed while it was read.",
        ) from error
    if not stat.S_ISREG(current.st_mode) or (
        current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns
    ) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
        raise ManifestCodecError(
            ManifestFailure.CHANGED,
            "Campaign manifest changed while it was read.",
        )
    raw = b"".join(chunks)
    if len(raw) != opened.st_size:
        raise ManifestCodecError(
            ManifestFailure.CHANGED,
            "Campaign manifest was truncated while it was read.",
        )
    return decode_manifest(raw, expected_family=expected_family)
