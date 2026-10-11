"""Read-only source catalog for one individual 2D-MOT simulation.

The public contract deliberately contains opaque identifiers rather than
paths.  Canonical campaign folders are admitted by the existing strict 2D
source attestation; retained individual Zeeman results are admitted only by
the D3 package inspector.  This module does not write, sample, or execute.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from workflow_api.mot_2d_sources import MAX_SOURCES, SourceScanLimits, list_sources
from workflow_api.run_discovery import discover_run_snapshot, inspect_run
from workflow_api.run_records import RunRecordError


CATALOG_VERSION = "mot-2d-individual-source-catalog-v1"
MAX_INDIVIDUAL_RUNS = 500
MAX_CATALOG_SOURCES = MAX_SOURCES + MAX_INDIVIDUAL_RUNS
_LABEL_LIMIT = 80
_UNSAFE_LABEL = re.compile(r"[^A-Za-z0-9._ -]+")
_INTERACTIVE_LIMITS = SourceScanLimits(
    maximum_file_bytes=512 * 1024 * 1024,
    maximum_total_bytes=8 * 1024 * 1024 * 1024,
    maximum_rows_per_file=2_000_000,
    maximum_total_rows=70_000_000,
    maximum_npy_header_bytes=64 * 1024,
)


def _opaque_id(kind: str, evidence: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"kind": kind, "evidence": evidence},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "mot2d-source-" + hashlib.sha256(encoded).hexdigest()[:32]


def _folder_label(path: str) -> str:
    raw = Path(path).name
    cleaned = " ".join(_UNSAFE_LABEL.sub(" ", raw).split()).strip(" ._-")
    if not cleaned:
        return "Validated Zeeman ensembles"
    return cleaned[:_LABEL_LIMIT].rstrip()


def _canonical_options(repository_root: Path) -> tuple[list[dict[str, Any]], int, bool]:
    listing = list_sources(
        repository_root,
        include_pool_counts=True,
        scan_limits=_INTERACTIVE_LIMITS,
    )
    options: list[dict[str, Any]] = []
    for row in listing["sources"]:
        evidence = {
            "fingerprint": row["fingerprint"],
            "profile": row["profile"],
            "ensemble_count": row["ensemble_count"],
            "minimum_survivors": row["minimum_survivors"],
            "maximum_survivors": row["maximum_survivors"],
            "pooled_survivor_count": row["pooled_survivor_count"],
            # The relative location is private binding evidence.  It is never
            # returned in the public catalog.
            "location": row["path"],
        }
        if row["pooled_survivor_count"] <= 0:
            listing["invalid_count"] += 1
            continue
        options.append(
            {
                "id": _opaque_id("canonical_folder", evidence),
                "source_kind": "canonical_folder",
                "label": _folder_label(row["path"]),
                "ensemble_count": row["ensemble_count"],
                "available_particle_count": {
                    "pooled": row["pooled_survivor_count"],
                    "minimum_per_ensemble": row["minimum_survivors"],
                    "maximum_per_ensemble": row["maximum_survivors"],
                },
                "source_qualification": "canonical_campaign_source",
                "result_suitability": "individual_only",
                "provenance": {
                    "validation": "canonical_zeeman_folder",
                    "profile": row["profile"],
                    "fingerprint": row["fingerprint"],
                },
            }
        )
    # list_sources explicitly marks a bounded overflow as invalid.  Preserve
    # that signal and make truncation explicit in this newer contract.
    return options, listing["invalid_count"], listing["truncated"]


def _retained_options(repository_root: Path) -> tuple[list[dict[str, Any]], int, bool]:
    snapshot = discover_run_snapshot(
        repository_root, maximum_runs=MAX_INDIVIDUAL_RUNS
    )
    options: list[dict[str, Any]] = []
    invalid = 0
    for discovered in snapshot.records:
        if discovered.family != "zeeman":
            continue
        if discovered.integrity == "invalid":
            invalid += 1
            continue
        try:
            inspected = inspect_run(
                repository_root, discovered.family, discovered.run_id
            )
            result = inspected.results
            publication = inspected.publication
            state = publication.state_array if publication is not None else None
            if (
                inspected.state != "succeeded"
                or inspected.integrity != "complete_verified"
                or result is None
                or result["states_retained"] is not True
                or result["suitability"] != "individual_only"
                or inspected.run["retention"]["particle_states"] is not True
                or state is None
                or state.dtype != "float64"
                or state.shape != (state.survivor_count, 6)
                or result["metrics"].get("n_survivors")
                != state.survivor_count
            ):
                continue
            if (
                state.survivor_count <= 0
                or state.survivor_count > _INTERACTIVE_LIMITS.maximum_rows_per_file
                or state.size_bytes > _INTERACTIVE_LIMITS.maximum_file_bytes
            ):
                invalid += 1
                continue
            public_run_id = "individual-run-" + hashlib.sha256(
                f"{inspected.family}:{inspected.run_id}".encode("utf-8")
            ).hexdigest()[:24]
            resolved = inspected.configuration["resolved"]
            zeeman = resolved.get("zeeman", {})
            laser = zeeman.get("laser", {})
            profile = zeeman.get("magnet_profile_name")
            summary = {
                "profile": profile if isinstance(profile, str) else "verified",
                "laser_s0": laser.get("s0") if isinstance(laser, Mapping) else None,
                "laser_detuning_gamma": (
                    laser.get("detuning_gamma")
                    if isinstance(laser, Mapping)
                    else None
                ),
            }
            evidence = {
                "family": inspected.family,
                "run_id": inspected.run_id,
                "configuration_sha256": inspected.run["configuration_sha256"],
                "inputs_sha256": inspected.run["inputs_sha256"],
                "results_sha256": publication.results_sha256,
                "states_sha256": state.sha256,
                "states_shape": list(state.shape),
            }
            options.append(
                {
                    "id": _opaque_id("retained_individual_zeeman", evidence),
                    "source_kind": "retained_individual_zeeman",
                    "label": (
                        "Saved Zeeman run "
                        f"{public_run_id.removeprefix('individual-run-')[:8]} · "
                        f"{result['completed_utc'][:10]}"
                    ),
                    "ensemble_count": 1,
                    "available_particle_count": {
                        "pooled": state.survivor_count,
                        "minimum_per_ensemble": state.survivor_count,
                        "maximum_per_ensemble": state.survivor_count,
                    },
                    "source_qualification": "verified_individual_result",
                    "result_suitability": "individual_only",
                    "provenance": {
                        "validation": "verified_retained_individual_result",
                        "completed_at": result["completed_utc"],
                        "public_run_id": public_run_id,
                        "scientific_summary": summary,
                        "fingerprint": hashlib.sha256(
                            json.dumps(
                                evidence, sort_keys=True, separators=(",", ":")
                            ).encode("utf-8")
                        ).hexdigest(),
                    },
                }
            )
        except (OSError, RunRecordError, KeyError, TypeError, ValueError):
            invalid += 1
    return options, invalid, snapshot.truncated


def list_individual_mot_2d_sources(repository_root: Path) -> dict[str, Any]:
    """Return a bounded, deterministic catalog without exposing locations."""

    root = Path(repository_root).resolve(strict=True)
    canonical, canonical_invalid, canonical_truncated = _canonical_options(root)
    retained, retained_invalid, retained_truncated = _retained_options(root)
    sources = canonical + retained
    sources.sort(key=lambda row: (row["source_kind"], row["label"], row["id"]))
    if len(sources) > MAX_CATALOG_SOURCES:
        # Defensive only: both component scanners are already bounded.
        sources = sources[:MAX_CATALOG_SOURCES]
        retained_truncated = True
    identifiers = [row["id"] for row in sources]
    if len(identifiers) != len(set(identifiers)):
        raise RuntimeError("Source catalog contains duplicate identities.")
    return {
        "contract_version": CATALOG_VERSION,
        "sources": sources,
        "invalid_count": canonical_invalid + retained_invalid,
        "total": len(sources),
        "truncated": canonical_truncated or retained_truncated,
    }
