"""Read-only, provenance-bound sources for one individual 3D-MOT run.

Completed canonical 2D campaigns are admitted through the existing strict
3D handoff validators.  Retained individual 2D-MOT results are admitted only
through the canonical D3 package inspector.  Public rows contain opaque IDs,
never repository paths or private run IDs.  This module does not sample,
write, or execute.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any, Mapping

from workflow_api.mot_2d_individual_sources import (
    SourceScanLimits,
    individual_mot_2d_source_scan_limits,
)
from workflow_api.run_discovery import discover_run_snapshot, inspect_run
from workflow_api.run_records import RunRecordError


CATALOG_VERSION = "mot-3d-individual-source-catalog-v1"
MAX_CAMPAIGNS = 250
MAX_INDIVIDUAL_RUNS = 500
MAX_CATALOG_SOURCES = MAX_CAMPAIGNS + MAX_INDIVIDUAL_RUNS
MAX_JSON_BYTES = 2 * 1024 * 1024
_SOURCE_ID = re.compile(r"mot3d-source-[0-9a-f]{32}")
_SAFE_CAMPAIGN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


@dataclass(frozen=True)
class ResolvedMot3DSource:
    source_id: str
    source_kind: str
    source_qualification: str
    pooled_particle_count: int
    fingerprint: str
    records: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class _SourceEvidence:
    source_id: str
    source_kind: str
    source_qualification: str
    label: str
    count: int
    minimum_count: int
    maximum_count: int
    fingerprint: str
    provenance: Mapping[str, Any]
    records: tuple[Mapping[str, Any], ...]


def individual_mot_3d_source_scan_limits() -> SourceScanLimits:
    """Use the established bounded particle-state policy for UI sources."""

    return individual_mot_2d_source_scan_limits()


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain(child) for child in value]
    if isinstance(value, list):
        return [_plain(child) for child in value]
    return value


def _opaque_id(kind: str, evidence: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        {"kind": kind, "evidence": evidence},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "mot3d-source-" + hashlib.sha256(encoded).hexdigest()[:32]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_regular(path: Path, root: Path, *, maximum: int | None = None) -> bool:
    try:
        relative = path.relative_to(root)
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                return False
        metadata = path.lstat()
        return (
            stat.S_ISREG(metadata.st_mode)
            and (maximum is None or metadata.st_size <= maximum)
        )
    except (OSError, ValueError):
        return False


def _safe_directory(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                return False
        return stat.S_ISDIR(path.lstat().st_mode)
    except (OSError, ValueError):
        return False


def _bounded_json(path: Path, root: Path) -> dict[str, Any]:
    if not _safe_regular(path, root, maximum=MAX_JSON_BYTES):
        raise ValueError("Untrusted 2D campaign record.")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        raw = os.read(descriptor, MAX_JSON_BYTES + 1)
        after = os.fstat(descriptor)
        identity = lambda row: (
            row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns,
        )
        if len(raw) != before.st_size or identity(before) != identity(after):
            raise ValueError("2D campaign record changed while reading.")
    finally:
        os.close(descriptor)
    def reject_duplicates(pairs):
        value = {}
        for key, child in pairs:
            if key in value:
                raise ValueError("Duplicate 2D campaign record key.")
            value[key] = child
        return value

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError("Invalid 2D campaign record.")
    return value


def _portable_campaign_records(
    repository_root: Path, roles: Mapping[str, list[Mapping[str, Any]]]
) -> tuple[Mapping[str, Any], ...]:
    records = []
    limits = individual_mot_3d_source_scan_limits()
    total_bytes = 0
    total_rows = 0
    for role in ("discovery", "refinement", "preliminary_check"):
        for source in roles[role]:
            state = Path(source["path"])
            metadata = Path(source["metadata_path"])
            if not state.is_absolute():
                state = repository_root / state
            if not metadata.is_absolute():
                metadata = repository_root / metadata
            state = state.absolute()
            metadata = metadata.absolute()
            if not _safe_regular(state, repository_root) or not _safe_regular(
                metadata, repository_root, maximum=MAX_JSON_BYTES
            ):
                raise ValueError("Untrusted 2D survivor artifact.")
            state_size = state.stat().st_size
            metadata_size = metadata.stat().st_size
            rows = int(source["n_survivors"])
            total_bytes += state_size
            total_rows += rows
            if (
                state_size > limits.maximum_file_bytes
                or total_bytes > limits.maximum_total_bytes
                or rows > limits.maximum_rows_per_file
                or total_rows > limits.maximum_total_rows
            ):
                raise ValueError("2D survivor source exceeds interactive limits.")
            records.append(
                _freeze(
                    {
                        "source_index": len(records),
                        "path": state.relative_to(repository_root).as_posix(),
                        "metadata_path": metadata.relative_to(repository_root).as_posix(),
                        "sha256": source["sha256"],
                        "metadata_sha256": source["metadata_sha256"],
                        "size_bytes": state_size,
                        "metadata_size_bytes": metadata_size,
                        "shape": list(source["shape"]),
                        "dtype": source["dtype"],
                        "survivor_count": rows,
                        "zeeman_seed": int(source["zeeman_seed"]),
                        "mot_seed": int(source["mot_seed"]),
                    }
                )
            )
    return tuple(records)


def _campaign_evidence(
    repository_root: Path, campaign: Path, survivor: Path
) -> _SourceEvidence:
    # Source inspection is invoked on demand; keep importing the HTTP server
    # itself independent of the study/simulation module graph.
    from studies.mot_3d_campaign import freeze_inputs, validate_upstream_2d_campaign

    upstream = validate_upstream_2d_campaign(campaign, survivor)
    pairs = {
        row["zeeman_seed"]: row["mot_seed"] for row in upstream["sealed_seed_pairs"]
    }
    roles = freeze_inputs(
        survivor,
        expected_seed_pairs=pairs,
        expected_design=upstream["expected_survivor_design"],
        expected_parameters=upstream["expected_survivor_parameters"],
    )
    records = _portable_campaign_records(repository_root, roles)
    counts = [record["survivor_count"] for record in records]
    result = upstream["selected_result"]
    manifest = _bounded_json(campaign / "campaign.json", repository_root)
    name = manifest.get("name", campaign.name)
    s0 = result.get("s0")
    if (
        not isinstance(name, str)
        or _SAFE_CAMPAIGN_NAME.fullmatch(name) is None
        or isinstance(s0, bool)
        or not isinstance(s0, (int, float))
    ):
        raise ValueError("Invalid completed 2D campaign identity.")
    identity = {
        "campaign_sha256": upstream["campaign_sha256"],
        "final_report_sha256": upstream["final_report_sha256"],
        "records": [
            {
                "sha256": record["sha256"],
                "metadata_sha256": record["metadata_sha256"],
                "shape": list(record["shape"]),
                "zeeman_seed": record["zeeman_seed"],
                "mot_seed": record["mot_seed"],
            }
            for record in records
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return _SourceEvidence(
        _opaque_id("canonical_2d_campaign", identity),
        "canonical_2d_campaign",
        "canonical_campaign_source",
        f"{name} · s0 {float(s0):g}",
        sum(counts),
        min(counts),
        max(counts),
        fingerprint,
        _freeze(
            {
                "validation": "completed_canonical_2d_campaign",
                "campaign_name": name,
                "s0": float(s0),
                "ensemble_count": len(records),
                "campaign_sha256": upstream["campaign_sha256"],
                "final_report_sha256": upstream["final_report_sha256"],
                "fingerprint": fingerprint,
            }
        ),
        records,
    )


def _retained_evidence(inspected: Any, discovered_path: str) -> _SourceEvidence | None:
    result = inspected.results
    publication = inspected.publication
    state = publication.state_array if publication is not None else None
    if (
        inspected.family != "mot_2d"
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
        or state.survivor_count
        > individual_mot_3d_source_scan_limits().maximum_rows_per_file
        or state.size_bytes > individual_mot_3d_source_scan_limits().maximum_file_bytes
    ):
        return None
    public_run_id = "individual-run-" + hashlib.sha256(
        f"{inspected.family}:{inspected.run_id}".encode("utf-8")
    ).hexdigest()[:24]
    resolved = inspected.configuration["resolved"]
    controls = resolved.get("mot_2d", {})
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
    record = _freeze(
        {
            "source_index": 0,
            "path": f"{discovered_path}/{state.path}",
            "sha256": state.sha256,
            "size_bytes": state.size_bytes,
            "shape": list(state.shape),
            "dtype": state.dtype,
            "survivor_count": state.survivor_count,
            "source_run_public_id": public_run_id,
        }
    )
    return _SourceEvidence(
        _opaque_id("retained_individual_mot_2d", identity),
        "retained_individual_mot_2d",
        "verified_individual_result",
        "Saved 2D-MOT run "
        f"{public_run_id.removeprefix('individual-run-')[:8]} · "
        f"{result['completed_utc'][:10]}",
        state.survivor_count,
        state.survivor_count,
        state.survivor_count,
        fingerprint,
        _freeze(
            {
                "validation": "verified_retained_individual_result",
                "completed_at": result["completed_utc"],
                "public_run_id": public_run_id,
                "scientific_summary": {
                    "s0": controls.get("laser", {}).get("s0")
                    if isinstance(controls, Mapping)
                    and isinstance(controls.get("laser"), Mapping)
                    else None,
                    "detuning_gamma": controls.get("laser", {}).get("detuning_gamma")
                    if isinstance(controls, Mapping)
                    and isinstance(controls.get("laser"), Mapping)
                    else None,
                    "magnet_radius_m": controls.get("magnet_radius_m")
                    if isinstance(controls, Mapping)
                    else None,
                },
                "fingerprint": fingerprint,
            }
        ),
        (record,),
    )


def _campaign_sources(repository_root: Path) -> tuple[list[_SourceEvidence], int, bool]:
    root = repository_root / "data/optimization/mot_2d"
    survivor_root = repository_root / "data/particle_states/after_2d_mot"
    if not root.is_dir() or root.is_symlink():
        return [], 0, False
    entries = []
    truncated = False
    with os.scandir(root) as iterator:
        for entry in iterator:
            entries.append(entry.name)
            if len(entries) > MAX_CAMPAIGNS:
                truncated = True
                break
    # Never publish a filesystem-order-dependent subset.  Once the bounded
    # directory budget is exceeded, fail this source class closed and ask the
    # caller to reduce/archive the excess campaigns.
    if truncated:
        return [], 0, True
    sources = []
    invalid = 0
    for name in sorted(entries):
        campaign = root / name
        if name.startswith(".") or campaign.is_symlink() or not campaign.is_dir():
            continue
        try:
            report = _bounded_json(campaign / "final_report.json", repository_root)
            results = report.get("results")
            if not isinstance(results, list):
                raise ValueError("Invalid 2D final report.")
            for row in results:
                if not isinstance(row, dict):
                    raise ValueError("Invalid 2D result.")
                raw = row.get("survivor_states_directory")
                if not isinstance(raw, str) or not raw:
                    raise ValueError("Invalid survivor directory.")
                survivor = Path(raw)
                if not survivor.is_absolute():
                    survivor = repository_root / survivor
                survivor = survivor.absolute()
                if not _safe_directory(survivor, survivor_root):
                    raise ValueError("Untrusted survivor directory.")
                sources.append(_campaign_evidence(repository_root, campaign, survivor))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            invalid += 1
    return sources, invalid, truncated


def _retained_sources(repository_root: Path) -> tuple[list[_SourceEvidence], int, bool]:
    snapshot = discover_run_snapshot(repository_root, maximum_runs=MAX_INDIVIDUAL_RUNS)
    sources = []
    invalid = 0
    for discovered in snapshot.records:
        if discovered.family != "mot_2d":
            continue
        if discovered.integrity == "invalid":
            invalid += 1
            continue
        try:
            evidence = _retained_evidence(
                inspect_run(repository_root, "mot_2d", discovered.run_id),
                discovered.path,
            )
            if evidence is None:
                invalid += 1
            else:
                sources.append(evidence)
        except (OSError, RunRecordError, KeyError, TypeError, ValueError):
            invalid += 1
    return sources, invalid, snapshot.truncated


def _public(source: _SourceEvidence) -> dict[str, Any]:
    return {
        "id": source.source_id,
        "source_kind": source.source_kind,
        "label": source.label,
        "ensemble_count": len(source.records),
        "available_particle_count": {
            "pooled": source.count,
            "minimum_per_ensemble": source.minimum_count,
            "maximum_per_ensemble": source.maximum_count,
        },
        "source_qualification": source.source_qualification,
        "result_suitability": "individual_only",
        "provenance": _plain(source.provenance),
    }


def _all_sources(repository_root: Path) -> tuple[list[_SourceEvidence], int, bool]:
    canonical, canonical_invalid, canonical_truncated = _campaign_sources(repository_root)
    retained, retained_invalid, retained_truncated = _retained_sources(repository_root)
    sources = canonical + retained
    sources.sort(key=lambda row: (row.source_kind, row.label, row.source_id))
    if len(sources) > MAX_CATALOG_SOURCES:
        sources = sources[:MAX_CATALOG_SOURCES]
        retained_truncated = True
    identifiers = [row.source_id for row in sources]
    if len(identifiers) != len(set(identifiers)):
        raise RuntimeError("3D-MOT source catalog contains duplicate identities.")
    return (
        sources,
        canonical_invalid + retained_invalid,
        canonical_truncated or retained_truncated,
    )


def list_individual_mot_3d_sources(repository_root: Path) -> dict[str, Any]:
    """Return a bounded deterministic catalog without exposing locations."""

    root = Path(repository_root).resolve(strict=True)
    sources, invalid, truncated = _all_sources(root)
    return {
        "contract_version": CATALOG_VERSION,
        "sources": [_public(source) for source in sources],
        "invalid_count": invalid,
        "total": len(sources),
        "truncated": truncated,
    }


def resolve_individual_mot_3d_source(
    repository_root: Path, source_id: str
) -> ResolvedMot3DSource:
    """Freshly re-attest and resolve one opaque source selection."""

    if not isinstance(source_id, str) or _SOURCE_ID.fullmatch(source_id) is None:
        raise ValueError("Individual 3D-MOT source identifier is invalid.")
    root = Path(repository_root).resolve(strict=True)
    sources, _invalid, _truncated = _all_sources(root)
    matches = [source for source in sources if source.source_id == source_id]
    if len(matches) != 1:
        raise ValueError("Individual 3D-MOT source is unavailable or changed.")
    source = matches[0]
    return ResolvedMot3DSource(
        source.source_id,
        source.source_kind,
        source.source_qualification,
        source.count,
        source.fingerprint,
        source.records,
    )
