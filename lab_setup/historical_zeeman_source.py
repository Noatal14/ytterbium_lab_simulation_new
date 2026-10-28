"""Reviewed artifact identity, not a retroactive laboratory specification.

Only the byte-identical, original 35-ensemble bank is admitted. Callers must
first validate the actual arrays and metadata using the normal source reader.
See docs/HISTORICAL_ZEEMAN_SOURCE_EVIDENCE.md for the original evidence.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from lab_setup.physical_specification import CANONICAL_ZEEMAN_PROFILE_NAME

SOURCE_COMMIT = "f042931070b58f9dac47789212e449f0552be25b"
SOURCE_FINGERPRINT = "a8699ba2f14146c7427cda8118e688cf3b3157792be9c0b7e0d99d832eeab13c"
EVIDENCE_ID = "corrected-19ring-original-35-ensembles-v1"


class HistoricalSourceEvidenceError(ValueError):
    """The original historical bank identity could not be authenticated."""


def historical_source_evidence(records: Sequence[Mapping]) -> dict[str, str]:
    """Authenticate reviewed records without claiming missing original lab IDs."""
    invalid = HistoricalSourceEvidenceError(
        "This source cannot create a new campaign without explicit laboratory "
        "provenance or verified original historical evidence."
    )
    if len(records) != 35:
        raise invalid
    seeds = [row.get("zeeman_seed") for row in records]
    if any(type(seed) is not int for seed in seeds) or sorted(seeds) != list(range(3000, 3035)):
        raise invalid
    ordered = sorted(records, key=lambda row: row["zeeman_seed"])
    for row in ordered:
        if (row.get("source_git_commit") != SOURCE_COMMIT
                or row.get("zeeman_profile") != CANONICAL_ZEEMAN_PROFILE_NAME
                or row.get("legacy_attested_profile") is not True
                or any(key in row for key in ("laboratory_spec_version", "laboratory_spec_sha256"))):
            raise invalid
    counts = [row.get("survivor_count") for row in ordered]
    if any(type(count) is not int or count <= 0 for count in counts) or sum(counts) != 1_110_091:
        raise invalid
    fingerprint = hashlib.sha256("\n".join(
        f"{row['zeeman_seed']}:{row.get('sha256')}:{row.get('metadata_sha256')}"
        for row in ordered
    ).encode()).hexdigest()
    if fingerprint != SOURCE_FINGERPRINT:
        raise invalid
    return {
        "id": EVIDENCE_ID,
        "source_git_commit": SOURCE_COMMIT,
        "source_fingerprint": fingerprint,
    }
