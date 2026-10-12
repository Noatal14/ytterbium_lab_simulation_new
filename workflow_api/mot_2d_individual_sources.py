"""Read-only source catalog for one individual 2D-MOT simulation.

The public contract deliberately contains opaque identifiers rather than
paths.  Canonical campaign folders are admitted by the existing strict 2D
source attestation; retained individual Zeeman results are admitted only by
the D3 package inspector.  This module does not write, sample, or execute.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

from workflow_api import mot_2d_sources as campaign_sources
from workflow_api.mot_2d_sources import (
    MAX_SOURCES,
    SourceScanLimits,
    inspect_source,
    list_sources,
)
from workflow_api.run_discovery import discover_run_snapshot, inspect_run
from workflow_api.run_records import RunRecordError


CATALOG_VERSION = "mot-2d-individual-source-catalog-v1"
MAX_INDIVIDUAL_RUNS = 500
MAX_CATALOG_SOURCES = MAX_SOURCES + MAX_INDIVIDUAL_RUNS
_LABEL_LIMIT = 80
_UNSAFE_LABEL = re.compile(r"[^A-Za-z0-9._ -]+")
_ENSEMBLE_NAME = re.compile(r"production_zeeman_n\d+_dt[^/]+_seed(\d+)\.npy")
INDIVIDUAL_MOT_2D_SOURCE_SCAN_LIMITS = SourceScanLimits(
    maximum_file_bytes=512 * 1024 * 1024,
    maximum_total_bytes=8 * 1024 * 1024 * 1024,
    maximum_rows_per_file=2_000_000,
    maximum_total_rows=70_000_000,
    maximum_npy_header_bytes=64 * 1024,
)
# Backward-compatible private name retained for the focused bounded-scan tests.
_INTERACTIVE_LIMITS = INDIVIDUAL_MOT_2D_SOURCE_SCAN_LIMITS


def individual_mot_2d_source_scan_limits() -> SourceScanLimits:
    """Return the one authoritative admission/execution source-size policy."""

    return _INTERACTIVE_LIMITS


@dataclass(frozen=True)
class ResolvedMot2DSource:
    source_id: str
    source_kind: str
    source_qualification: str
    pooled_particle_count: int
    fingerprint: str
    records: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class _RetainedEvidence:
    source_id: str
    public_run_id: str
    label: str
    count: int
    fingerprint: str
    completed_at: str
    scientific_summary: Mapping[str, Any]
    record: Mapping[str, Any]


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _retained_evidence(inspected: Any, discovered_path: str) -> _RetainedEvidence | None:
    """One shared admission decision for listing and later resolution."""

    result = inspected.results
    publication = inspected.publication
    state = publication.state_array if publication is not None else None
    if (
        inspected.family != "zeeman"
        or inspected.state != "succeeded"
        or inspected.integrity != "complete_verified"
        or result is None
        or result["states_retained"] is not True
        or result["suitability"] != "individual_only"
        or inspected.run["retention"]["particle_states"] is not True
        or state is None
        or state.dtype != "float64"
        or state.shape != (state.survivor_count, 6)
        or result["metrics"].get("n_survivors") != state.survivor_count
        or state.survivor_count <= 0
        or state.survivor_count > individual_mot_2d_source_scan_limits().maximum_rows_per_file
        or state.size_bytes > individual_mot_2d_source_scan_limits().maximum_file_bytes
    ):
        return None
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
            laser.get("detuning_gamma") if isinstance(laser, Mapping) else None
        ),
    }
    identity = {
        "family": inspected.family,
        "run_id": inspected.run_id,
        "configuration_sha256": inspected.run["configuration_sha256"],
        "inputs_sha256": inspected.run["inputs_sha256"],
        "results_sha256": publication.results_sha256,
        "states_sha256": state.sha256,
        "states_size_bytes": state.size_bytes,
        "states_shape": list(state.shape),
        "survivor_count": state.survivor_count,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    record = {
        "source_index": 0,
        "path": f"{discovered_path}/{state.path}",
        "sha256": state.sha256,
        "size_bytes": state.size_bytes,
        "shape": list(state.shape),
        "dtype": state.dtype,
        "survivor_count": state.survivor_count,
        "source_run_public_id": public_run_id,
    }
    return _RetainedEvidence(
        _opaque_id("retained_individual_zeeman", identity),
        public_run_id,
        "Saved Zeeman run "
        f"{public_run_id.removeprefix('individual-run-')[:8]} · "
        f"{result['completed_utc'][:10]}",
        state.survivor_count,
        fingerprint,
        result["completed_utc"],
        _freeze(summary),
        _freeze(record),
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
    # "corrected" described a one-time historical mistake, not a scientific
    # source category.  Keep the on-disk path stable while avoiding that stale
    # distinction in the operator-facing catalog.
    raw = raw.removeprefix("corrected_")
    cleaned = " ".join(_UNSAFE_LABEL.sub(" ", raw).split()).strip(" ._-")
    if not cleaned:
        return "Validated Zeeman ensembles"
    return cleaned[:_LABEL_LIMIT].rstrip()


def _individual_folder_rows(repository_root: Path) -> tuple[list[dict[str, Any]], int, bool]:
    """Admit verified folders for individual runs, including partial seed sets.

    Campaign setup deliberately continues to require the complete canonical
    3000--3034 set.  This catalog may also expose a smaller, fully attested
    folder, but marks it individual-only and revalidates it on resolution.
    """

    source_root = (repository_root / "data/particle_states/after_zeeman").resolve()
    if not source_root.is_dir():
        return [], 0, False
    rows: list[dict[str, Any]] = []
    invalid = 0
    truncated = False
    candidates = 0
    for directory in sorted(source_root.iterdir(), key=lambda item: item.name):
        if directory.is_symlink() or not directory.is_dir() or directory.name.startswith("."):
            continue
        if candidates >= campaign_sources.MAX_SOURCES:
            truncated = True
            break
        candidates += 1
        try:
            state_files = sorted(directory.glob("production_zeeman_n*_dt*_seed*.npy"))
            matches = [_ENSEMBLE_NAME.fullmatch(path.name) for path in state_files]
            if not state_files or any(match is None for match in matches):
                raise ValueError("invalid ensemble filenames")
            seeds = tuple(sorted(int(match.group(1)) for match in matches if match is not None))
            if len(seeds) != len(set(seeds)):
                raise ValueError("duplicate ensemble seeds")
            if seeds not in (tuple(range(3000, 3020)), tuple(range(3000, 3035))):
                raise ValueError("unsupported individual ensemble seed set")
            row = inspect_source(
                directory,
                repository_root,
                include_records=True,
                scan_limits=individual_mot_2d_source_scan_limits(),
                expected_seeds=seeds,
            )
            row["pooled_survivor_count"] = sum(
                record["survivor_count"] for record in row.pop("records")
            )
            row["seed_set"] = list(seeds)
            rows.append(row)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            invalid += 1
    return rows, invalid, truncated


def _canonical_options(repository_root: Path) -> tuple[list[dict[str, Any]], int, bool]:
    rows, invalid_count, truncated = _individual_folder_rows(repository_root)
    options: list[dict[str, Any]] = []
    for row in rows:
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
            "seed_set": row["seed_set"],
        }
        if row["pooled_survivor_count"] <= 0:
            invalid_count += 1
            continue
        complete_campaign_source = tuple(row["seed_set"]) == tuple(range(3000, 3035))
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
                "source_qualification": (
                    "canonical_campaign_source"
                    if complete_campaign_source
                    else "verified_individual_folder"
                ),
                "result_suitability": "individual_only",
                "provenance": {
                    "validation": (
                        "canonical_zeeman_folder"
                        if complete_campaign_source
                        else "verified_individual_zeeman_folder"
                    ),
                    "profile": row["profile"],
                    "fingerprint": row["fingerprint"],
                },
            }
        )
    # list_sources explicitly marks a bounded overflow as invalid.  Preserve
    # that signal and make truncation explicit in this newer contract.
    return options, invalid_count, truncated


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
            evidence = _retained_evidence(inspected, discovered.path)
            if evidence is None:
                invalid += 1
                continue
            options.append(
                {
                    "id": evidence.source_id,
                    "source_kind": "retained_individual_zeeman",
                    "label": evidence.label,
                    "ensemble_count": 1,
                    "available_particle_count": {
                        "pooled": evidence.count,
                        "minimum_per_ensemble": evidence.count,
                        "maximum_per_ensemble": evidence.count,
                    },
                    "source_qualification": "verified_individual_result",
                    "result_suitability": "individual_only",
                    "provenance": {
                        "validation": "verified_retained_individual_result",
                        "completed_at": evidence.completed_at,
                        "public_run_id": evidence.public_run_id,
                        "scientific_summary": dict(evidence.scientific_summary),
                        "fingerprint": evidence.fingerprint,
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


def resolve_individual_mot_2d_source(
    repository_root: Path, source_id: str
) -> ResolvedMot2DSource:
    """Resolve one opaque catalog choice to freshly verified frozen evidence."""

    if (
        not isinstance(source_id, str)
        or not re.fullmatch(r"mot2d-source-[0-9a-f]{32}", source_id)
    ):
        raise ValueError("Individual 2D-MOT source identifier is invalid.")
    root = Path(repository_root).resolve(strict=True)
    rows, _, _ = _individual_folder_rows(root)
    for row in rows:
        evidence = {
            "fingerprint": row["fingerprint"],
            "profile": row["profile"],
            "ensemble_count": row["ensemble_count"],
            "minimum_survivors": row["minimum_survivors"],
            "maximum_survivors": row["maximum_survivors"],
            "pooled_survivor_count": row["pooled_survivor_count"],
            "location": row["path"],
            "seed_set": row["seed_set"],
        }
        if _opaque_id("canonical_folder", evidence) != source_id:
            continue
        inspected = inspect_source(
            root / row["path"], root, include_records=True,
            scan_limits=individual_mot_2d_source_scan_limits(),
            expected_seeds=tuple(row["seed_set"]),
        )
        records = sorted(inspected["records"], key=lambda item: item["zeeman_seed"])
        pooled = sum(item["survivor_count"] for item in records)
        refreshed_evidence = {
            "fingerprint": inspected["fingerprint"],
            "profile": inspected["profile"],
            "ensemble_count": inspected["ensemble_count"],
            "minimum_survivors": inspected["minimum_survivors"],
            "maximum_survivors": inspected["maximum_survivors"],
            "pooled_survivor_count": pooled,
            "location": inspected["path"],
            "seed_set": row["seed_set"],
        }
        if (
            pooled <= 0
            or _opaque_id("canonical_folder", refreshed_evidence) != source_id
        ):
            raise ValueError("Individual 2D-MOT source is unavailable or changed.")
        return ResolvedMot2DSource(
            source_id,
            "canonical_folder",
            (
                "canonical_campaign_source"
                if tuple(row["seed_set"]) == tuple(range(3000, 3035))
                else "verified_individual_folder"
            ),
            pooled, inspected["fingerprint"],
            tuple(_freeze(item) for item in records),
        )

    snapshot = discover_run_snapshot(root, maximum_runs=MAX_INDIVIDUAL_RUNS)
    for discovered in snapshot.records:
        if discovered.family != "zeeman" or discovered.integrity == "invalid":
            continue
        try:
            inspected = inspect_run(root, "zeeman", discovered.run_id)
            evidence = _retained_evidence(inspected, discovered.path)
            if evidence is None:
                continue
            if evidence.source_id != source_id:
                continue
            return ResolvedMot2DSource(
                source_id, "retained_individual_zeeman",
                "verified_individual_result", evidence.count,
                evidence.fingerprint, (evidence.record,),
            )
        except (OSError, RunRecordError, KeyError, TypeError, ValueError):
            continue
    raise ValueError("Individual 2D-MOT source is unavailable or changed.")
