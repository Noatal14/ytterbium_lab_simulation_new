"""Local preview/confirm boundary for a Discovery-ready 3D-MOT campaign."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import errno
import hashlib
import json
import math
from workflow_api.platform_io import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import threading
import time
from typing import Any, Callable, Mapping

from studies import mot_3d_campaign
from workflow_api.mot_3d_plan import (
    canonical_digest,
    load_timestep_policy,
    render_discovery_bootstrap,
)
from workflow_api.preview_registry import PreviewRegistry


PREVIEW_LIFETIME_SECONDS = 300
PREVIEW_CAPACITY = 32


class Mot3DBootstrapError(ValueError):
    """A safe failure at the local 3D campaign preparation boundary."""


@dataclass
class _Pending:
    expires_at: float
    session_sha256: str
    request: dict[str, Any]
    source_identity: dict[str, str]
    files: dict[str, str]
    nonce: str
    bootstrap_key: str
    consumed: bool = False
    result: dict[str, Any] | None = None


def _digest_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or not value.isprintable():
        raise PermissionError(f"{label} is invalid.")
    encoded = value.encode("utf-8")
    if len(encoded) > 512:
        raise PermissionError(f"{label} is invalid.")
    return hashlib.sha256(encoded).hexdigest()


def _write_durable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _identity(row: os.stat_result) -> tuple[int, int, int, int, int]:
    return (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns)


def _rename_no_replace(
    parent_descriptor: int, source_name: str, destination_name: str
) -> None:
    """Atomically publish sibling directories without replacing an entry."""
    if os.name == "nt":
        os.rename(source_name, destination_name, src_dir_fd=parent_descriptor, dst_dir_fd=parent_descriptor)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_name)
    destination = os.fsencode(destination_name)
    if hasattr(libc, "renameatx_np"):
        result = libc.renameatx_np(
            parent_descriptor, source, parent_descriptor, destination, 0x00000004
        )
    elif hasattr(libc, "renameat2"):
        result = libc.renameat2(
            parent_descriptor, source, parent_descriptor, destination, 1
        )
    else:
        raise RuntimeError("Atomic no-replace publication is unavailable.")
    if result:
        number = ctypes.get_errno()
        if number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError("3D campaign destination already exists.")
        raise OSError(number, os.strerror(number))


def _bounded_json(
    root: Path, path: Path, *, limit: int = 2 * 1024 * 1024
) -> dict[str, Any]:
    path.relative_to(root)
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if current.is_symlink():
            raise Mot3DBootstrapError("Campaign evidence contains a symbolic link.")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise Mot3DBootstrapError(
                "Campaign evidence is not a bounded regular file."
            )
        raw = bytearray()
        while len(raw) <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
        identity = lambda row: (
            row.st_dev,
            row.st_ino,
            row.st_size,
            row.st_mtime_ns,
            row.st_ctime_ns,
        )
        if len(raw) != before.st_size or identity(before) != identity(after):
            raise Mot3DBootstrapError("Campaign evidence changed while reading.")
    finally:
        os.close(descriptor)

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise Mot3DBootstrapError("Campaign evidence contains a duplicate key.")
            result[key] = item
        return result

    value = json.loads(
        raw.decode("utf-8", "strict"), object_pairs_hook=reject_duplicates
    )
    if not isinstance(value, dict):
        raise Mot3DBootstrapError("Campaign evidence is invalid.")
    return value


class Mot3DDiscoveryBootstrapService:
    """Prepare, but never submit, a canonical 3D Discovery campaign."""

    def __init__(
        self,
        repository_root: Path,
        *,
        acceptance_profile_id: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] | None = None,
        revision_provider: Callable[[], str] = mot_3d_campaign._revision,
        physical_hash_provider: Callable[[], str] = mot_3d_campaign._relevant_hash,
        dirty_provider: Callable[
            [], tuple[str, ...]
        ] = mot_3d_campaign._dirty_relevant_files,
    ) -> None:
        self.root = Path(repository_root).resolve(strict=True)
        self.acceptance_profile_id = acceptance_profile_id
        if acceptance_profile_id is not None:
            from workflow_api.acceptance_profile import load_acceptance_profile
            load_acceptance_profile(acceptance_profile_id)
        self.clock = clock
        self.revision_provider = revision_provider
        self.physical_hash_provider = physical_hash_provider
        self.dirty_provider = dirty_provider
        self._previews = PreviewRegistry[_Pending](
            clock=clock, token_factory=token_factory
        )
        self._lock = threading.RLock()

    def _sources(self) -> list[tuple[dict[str, Any], Path, Path]]:
        root = self.root / "data/optimization/mot_2d"
        if self.acceptance_profile_id is not None:
            root = root / "ui_acceptance"
        rows: list[tuple[dict[str, Any], Path, Path]] = []
        if not root.is_dir() or root.is_symlink():
            return rows
        for campaign in sorted(root.iterdir())[:250]:
            if (campaign.is_symlink() or not campaign.is_dir()
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", campaign.name) is None):
                continue
            try:
                manifest = _bounded_json(self.root, campaign / "campaign.json")
                report = _bounded_json(self.root, campaign / "final_report.json")
            except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if (
                manifest.get("kind") != ("mot_2d_ui_acceptance_v1" if self.acceptance_profile_id else "mot_2d_s0_campaign")
                or manifest.get("stage") != "complete"
            ):
                continue
            for result in report.get("results", []):
                if not isinstance(result, dict):
                    continue
                campaign_name = manifest.get("name", campaign.name)
                s0 = result.get("s0")
                if (
                    not isinstance(campaign_name, str)
                    or not campaign_name.strip()
                    or campaign_name != campaign_name.strip()
                    or not campaign_name.isprintable()
                    or len(campaign_name) > 120
                    or isinstance(s0, bool)
                    or not isinstance(s0, (int, float))
                    or not math.isfinite(float(s0))
                    or float(s0) <= 0
                ):
                    continue
                survivor_value = Path(str(result.get("survivor_states_directory", "")))
                survivor = (
                    survivor_value
                    if survivor_value.is_absolute()
                    else self.root / survivor_value
                ).resolve()
                survivor_root = (
                    campaign if self.acceptance_profile_id else self.root / "data/particle_states/after_2d_mot"
                ).resolve()
                try:
                    survivor.relative_to(survivor_root)
                except ValueError:
                    continue
                current = self.root
                try:
                    for part in survivor.relative_to(self.root).parts:
                        current /= part
                        if current.is_symlink():
                            raise ValueError
                except ValueError:
                    continue
                try:
                    upstream = mot_3d_campaign.validate_upstream_2d_campaign(
                        campaign, survivor, acceptance_profile_id=self.acceptance_profile_id, repository_root=self.root
                    )
                    pairs = {
                        row["zeeman_seed"]: row["mot_seed"]
                        for row in upstream["sealed_seed_pairs"]
                    }
                    mot_3d_campaign.freeze_inputs(
                        survivor,
                        expected_seed_pairs=pairs,
                        expected_design=upstream["expected_survivor_design"],
                        expected_parameters=upstream["expected_survivor_parameters"],
                        acceptance_profile_id=self.acceptance_profile_id,
                        acceptance_upstream=upstream,
                        repository_root=self.root,
                    )
                except (OSError, ValueError, KeyError):
                    continue
                identity = {
                    "source_id": canonical_digest(
                        {
                            "campaign": upstream["campaign_sha256"],
                            "report": upstream["final_report_sha256"],
                            "s0": s0,
                        }
                    ),
                    "campaign_sha256": upstream["campaign_sha256"],
                    "final_report_sha256": upstream["final_report_sha256"],
                }
                public = {
                    "source_id": identity["source_id"],
                    "campaign_name": campaign_name,
                    "s0": s0,
                    "sealed_ensemble_count": 20,
                    "completion": "complete",
                    "provenance_fingerprint": identity["final_report_sha256"],
                }
                rows.append((public | identity, campaign, survivor))
        return rows

    def status(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping) or set(request):
            raise Mot3DBootstrapError("3D bootstrap status request is invalid.")
        sources = [row[0] for row in self._sources()]
        public = [
            {
                key: row[key]
                for key in (
                    "source_id",
                    "campaign_name",
                    "s0",
                    "sealed_ensemble_count",
                    "completion",
                    "provenance_fingerprint",
                )
            }
            for row in sources
        ]
        policy, policy_sha256 = load_timestep_policy()
        return {
            "lifecycle": "ready",
            "sources": public,
            "reason": None,
            "evidence_requirement": None,
            "timestep_policy": {
                "status": policy["status"],
                "convergence_claim": policy["convergence_claim"],
                "sha256": policy_sha256,
            },
        }

    def _destination(self, name: str) -> Path:
        """Single reviewed namespace authority for rendering and publication."""
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", name) is None:
            raise Mot3DBootstrapError("3D campaign name is invalid.")
        parent = self.root / "data/optimization/mot_3d"
        if self.acceptance_profile_id is not None:
            parent /= "ui_acceptance"
        return parent / name

    def _render(
        self, request: Mapping[str, Any]
    ) -> tuple[dict[str, bytes], dict[str, Any], dict[str, str]]:
        if set(request) != {"source_id", "campaign_name"}:
            raise Mot3DBootstrapError("3D bootstrap request is invalid.")
        matches = [
            row
            for row in self._sources()
            if row[0]["source_id"] == request["source_id"]
        ]
        if len(matches) != 1:
            raise Mot3DBootstrapError(
                "The selected completed 2D campaign is unavailable."
            )
        source, upstream, survivor = matches[0]
        name = request["campaign_name"]
        destination = self._destination(name)
        dirty = self.dirty_provider()
        if dirty:
            raise Mot3DBootstrapError(
                "Relevant simulation code has uncommitted changes."
            )
        files, manifest = render_discovery_bootstrap(
            repository_root=self.root,
            destination=destination,
            name=name,
            upstream_campaign=upstream,
            survivor_directory=survivor,
            revision=self.revision_provider(),
            physical_model_sha256=self.physical_hash_provider(),
            acceptance_profile_id=self.acceptance_profile_id,
        )
        return files, manifest, source

    def preview(self, request: Mapping[str, Any], session_id: str) -> dict[str, Any]:
        session_sha256 = _digest_text(session_id, "Session")
        detached = dict(request)
        files, manifest, source = self._render(detached)
        hashes = {
            name: hashlib.sha256(payload).hexdigest() for name, payload in files.items()
        }
        nonce = secrets.token_hex(16)
        timestep_evidence = manifest["design"]["timestep_evidence"]
        key = canonical_digest(
            {
                "campaign_name": manifest["name"],
                "commit": manifest["provenance"]["git_commit"],
                "physical_model_sha256": manifest["provenance"][
                    "physical_model_sha256"
                ],
                "source_2d_campaign_sha256": source["campaign_sha256"],
                "source_2d_final_report_sha256": source["final_report_sha256"],
                "input_registry_sha256": timestep_evidence["source_handoff"][
                    "input_registry_sha256"
                ],
                "timestep_policy_sha256": timestep_evidence["policy_sha256"],
                "files": hashes,
                "nonce": nonce,
            }
        )
        expires_at = self.clock() + PREVIEW_LIFETIME_SECONDS
        try:
            token = self._previews.add_factory_keyed(
                lambda _token: _Pending(
                    expires_at,
                    session_sha256,
                    detached,
                    {
                        "campaign_sha256": source["campaign_sha256"],
                        "final_report_sha256": source["final_report_sha256"],
                    },
                    hashes,
                    nonce,
                    key,
                ),
                key_factory=lambda raw: _digest_text(raw, "Preview token"),
                expires_at=expires_at,
                capacity=PREVIEW_CAPACITY,
                retain_at_expiry=False,
            )
        except OverflowError as error:
            raise Mot3DBootstrapError(
                "Too many pending 3D bootstrap previews."
            ) from error
        return {
            "preview_token": token,
            "expires_in_seconds": PREVIEW_LIFETIME_SECONDS,
            "campaign": {"name": manifest["name"], "stage": "discovery"},
            "source": {
                key: source[key]
                for key in (
                    "source_id",
                    "campaign_name",
                    "s0",
                    "sealed_ensemble_count",
                    "completion",
                    "provenance_fingerprint",
                )
            },
            "discovery": {
                "families": list(manifest["design"]["families"]),
                "solver": manifest["design"]["solver"],
                "screening_dt_s": manifest["design"]["screening_dt_s"],
                "production_dt_s": manifest["design"]["production_dt_s"],
                "timestep_policy_status": timestep_evidence["policy_status"],
                "convergence_claim": timestep_evidence["convergence_claim"],
                "input_role_counts": {
                    key: len(value) for key, value in manifest["input_roles"].items()
                },
            },
            "artifacts": {"create": sorted(files)},
            "effects": {
                "create_campaign": True,
                "submit_job": False,
                "start_simulation": False,
                "prepare_dt_validation": False,
            },
        }

    def confirm(self, request: Mapping[str, Any], session_id: str) -> dict[str, Any]:
        if set(request) != {"preview_token"}:
            raise Mot3DBootstrapError("3D bootstrap confirmation is invalid.")
        token_key = _digest_text(request["preview_token"], "Preview token")
        session_sha256 = _digest_text(session_id, "Session")
        with self._lock:
            record = self._previews.get(token_key)
            pending = record.value if record else None
            if (
                pending is None
                or pending.session_sha256 != session_sha256
                or pending.expires_at <= self.clock()
            ):
                raise PermissionError("Preview token is invalid or expired.")
            if pending.result is not None:
                return dict(pending.result)
            pending.consumed = True
            files, manifest, source = self._render(pending.request)
            hashes = {
                name: hashlib.sha256(payload).hexdigest()
                for name, payload in files.items()
            }
            if (
                hashes != pending.files
                or {
                    "campaign_sha256": source["campaign_sha256"],
                    "final_report_sha256": source["final_report_sha256"],
                }
                != pending.source_identity
            ):
                raise Mot3DBootstrapError(
                    "3D bootstrap evidence changed after preview."
                )
            destination = self._destination(manifest["name"])
            from workflow_api.acceptance_profile import policy_for_manifest
            profile = policy_for_manifest(manifest)
            expected_kind = "mot_3d_ui_acceptance_v1" if self.acceptance_profile_id else "mot_3d_campaign_v2"
            if ((profile.profile_id if profile else None) != self.acceptance_profile_id
                    or manifest.get("kind") != expected_kind):
                raise Mot3DBootstrapError("3D publication policy differs from its reviewed namespace.")
            receipt = {
                "status": "discovery_prepared",
                "nonce": pending.nonce,
                "bootstrap_key": pending.bootstrap_key,
                "commit": manifest["provenance"]["git_commit"],
                "physical_model_sha256": manifest["provenance"][
                    "physical_model_sha256"
                ],
                "source_2d_campaign_sha256": source["campaign_sha256"],
                "source_2d_final_report_sha256": source["final_report_sha256"],
                "input_registry_sha256": (
                    manifest["design"]["timestep_evidence"]["source_handoff"][
                        "input_registry_sha256"
                    ]
                    if "source_handoff"
                    in manifest["design"].get("timestep_evidence", {})
                    else None
                ),
                "timestep_policy_sha256": manifest["design"]["timestep_evidence"][
                    "policy_sha256"
                ],
                "files": hashes,
                "completed_unix_s": time.time(),
            }
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging = (
                destination.parent / f".{destination.name}.tmp-{secrets.token_hex(8)}"
            )
            parent_descriptor = os.open(
                destination.parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            os.mkdir(staging.name, mode=0o700, dir_fd=parent_descriptor)
            parent_before = os.fstat(parent_descriptor)
            try:
                for relative, payload in files.items():
                    target = staging / relative
                    _write_durable(target, payload)
                receipt_path = staging / ".mot_ui/transitions/discovery_bootstrap.json"
                _write_durable(
                    receipt_path,
                    (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode(
                        "utf-8"
                    ),
                )
                directories = sorted(
                    {path.parent for path in staging.rglob("*")},
                    key=lambda path: len(path.parts),
                    reverse=True,
                )
                for directory in (*directories, staging):
                    descriptor = os.open(directory, os.O_RDONLY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                staging_descriptor = os.open(
                    staging,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                )
                staging_identity = _identity(os.fstat(staging_descriptor))
                if (
                    _identity(os.fstat(parent_descriptor)) != _identity(parent_before)
                    or _identity(os.stat(destination.parent, follow_symlinks=False))
                    != _identity(parent_before)
                    or _identity(os.stat(staging, follow_symlinks=False))
                    != staging_identity
                ):
                    os.close(staging_descriptor)
                    raise Mot3DBootstrapError(
                        "3D campaign destination changed during publication."
                    )
                try:
                    _rename_no_replace(
                        parent_descriptor, staging.name, destination.name
                    )
                finally:
                    os.close(staging_descriptor)
                os.fsync(parent_descriptor)
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            finally:
                os.close(parent_descriptor)
            result = {
                "lifecycle": "discovery_prepared",
                "campaign_name": manifest["name"],
                "stage": "discovery",
                "submitted_to_zeus": False,
                "bootstrap_key": pending.bootstrap_key,
            }
            pending.result = result
            return dict(result)
