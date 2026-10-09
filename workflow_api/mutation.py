"""Session-bound preview/confirm service for local 2D campaign creation."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workflow_api.mot_2d_plan import CampaignPlan, build_plan, materialize
from workflow_api.mot_2d_sources import list_sources
from workflow_api.repository_snapshot import RepositorySnapshotProvider
from workflow_api.safe_json import read_json
from workflow_api.discovery import list_campaigns
from workflow_api.mot_2d_validation import modern_contract
from workflow_api.preview_registry import PreviewRegistry


@dataclass
class Pending:
    expires: float; session: str; request: dict[str, Any]; plan: CampaignPlan
    consumed: bool = False; result: dict[str, Any] | None = None


class CreationService:
    def __init__(
        self,
        repository_root: Path,
        snapshot_provider: RepositorySnapshotProvider,
        *,
        clock=time.monotonic,
        token_factory=None,
    ):
        self.root = repository_root.resolve(); self.snapshots = snapshot_provider
        self.clock = clock
        self._previews = PreviewRegistry[Pending](
            clock=clock,
            token_factory=token_factory,
        )
        self._lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._requests: dict[str, list[float]] = {}

    def _rate_limit(self, session: str) -> None:
        with self._rate_lock:
            now = self.clock()
            recent = [stamp for stamp in self._requests.get(session, []) if now - stamp < 60]
            if len(recent) >= 12:
                raise BlockingIOError("Too many local creation requests.")
            recent.append(now); self._requests[session] = recent

    def _duplicate(self, plan: CampaignPlan) -> dict[str, Any] | None:
        root = self.root / "data/optimization/mot_2d"
        for directory in root.iterdir() if root.is_dir() else ():
            if directory.name.startswith("."):
                continue
            manifest_path = directory / "campaign.json"
            if directory.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink(): continue
            try:
                manifest = read_json(manifest_path)
                portable, _ = modern_contract(manifest, self.root)
                if not portable:
                    continue
                records = [row for values in manifest["input_ensembles"].values() for row in values]
                identities = [
                    f'{int(row["zeeman_seed"])}:{row["sha256"]}:{row["metadata_sha256"]}'
                    for row in sorted(records, key=lambda row: int(row["zeeman_seed"]))
                ]
                if len(identities) != 35 or len(set(int(row["zeeman_seed"]) for row in records)) != 35: continue
                source_fingerprint = hashlib.sha256("\n".join(identities).encode()).hexdigest()
                model = manifest["provenance"]["physical_model_sha256"]
                same = (
                    set(map(float, manifest["s0_values"])) == set(plan.s0_values)
                    and source_fingerprint == plan.source_fingerprint
                    and model == plan.manifest["provenance"]["physical_model_sha256"]
                    and manifest["fixed_design"] == plan.manifest["fixed_design"]
                )
            except (OSError, ValueError, TypeError, KeyError):
                continue
            if same:
                record = next((row for row in list_campaigns(self.root)["campaigns"] if row["path"] == directory.relative_to(self.root).as_posix()), None)
                return {"campaign_id": record["id"] if record else None, "path": directory.relative_to(self.root).as_posix(), "stage": manifest.get("stage")}
        return None

    def new_session(self) -> tuple[str, str]:
        return secrets.token_urlsafe(32), secrets.token_urlsafe(32)

    def preview(self, request: dict[str, Any], session: str) -> dict[str, Any]:
        self._rate_limit(session)
        if set(request) != {"name", "slug", "s0_values", "source_id"}:
            raise ValueError("Preview fields are invalid.")
        if not isinstance(request["name"], str) or not isinstance(request["slug"], str) or not isinstance(request["source_id"], str) or not isinstance(request["s0_values"], list):
            raise ValueError("Preview fields are invalid.")
        sources = {row["id"]: row for row in list_sources(self.root)["sources"]}
        source = sources.get(request["source_id"])
        if source is None: raise ValueError("The selected Zeeman source is unavailable.")
        before = self.snapshots.capture()
        plan = build_plan(self.root, name=request["name"], slug=request["slug"], s0_values=request["s0_values"], source=source, snapshot=before)
        after = self.snapshots.capture()
        if before != after: raise RuntimeError("Repository changed during preview.")
        duplicate = self._duplicate(plan)
        if duplicate:
            return {"preview_token": None, "expires_in_seconds": 0, "plan": None, "scientific_design": plan.manifest["fixed_design"], "provenance": {"commit": plan.snapshot.commit, "input_count": 35}, "duplicate": duplicate}
        with self._lock:
            now = self.clock()
            try:
                raw = self._previews.add_factory_keyed(
                    lambda _token: Pending(
                        now + 300, session, dict(request), plan,
                    ),
                    key_factory=lambda token: hashlib.sha256(token.encode()).hexdigest(),
                    expires_at=now + 300,
                    capacity=64,
                    retain_at_expiry=False,
                )
            except OverflowError as error:
                raise RuntimeError("Too many pending previews.") from error
        return {
            "preview_token": raw, "expires_in_seconds": 300,
            "plan": {"name": plan.name, "path": plan.destination.relative_to(self.root).as_posix(), "s0_values": list(plan.s0_values), "source_id": plan.source_id, "files": sorted(plan.files), "stage": "smoke"},
            "scientific_design": plan.manifest["fixed_design"],
            "provenance": {"commit": plan.snapshot.commit, "input_count": 35},
            "duplicate": None,
        }

    def confirm(self, token: str, session: str) -> dict[str, Any]:
        self._rate_limit(session)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            record = self._previews.get(digest)
            pending = record.value if record is not None else None
            if pending is None or pending.session != session or pending.expires <= self.clock():
                raise PermissionError("Preview token is invalid or expired.")
            if pending.consumed:
                if pending.result is not None: return pending.result
                raise RuntimeError("Preview token can no longer be used.")
            pending.consumed = True
            sources = {row["id"]: row for row in list_sources(self.root)["sources"]}
            source = sources.get(pending.request["source_id"])
            if source is None: raise RuntimeError("Zeeman source changed after preview.")
            snapshot = self.snapshots.capture()
            refreshed = build_plan(self.root, name=pending.request["name"], slug=pending.request["slug"], s0_values=pending.request["s0_values"], source=source, snapshot=snapshot)
            if refreshed.plan_digest != pending.plan.plan_digest or refreshed.source_fingerprint != pending.plan.source_fingerprint or refreshed.snapshot != pending.plan.snapshot:
                raise RuntimeError("Preview is stale; review the campaign again.")
            if self.snapshots.capture() != snapshot: raise RuntimeError("Repository changed before creation.")
            def final_check(staged: Path) -> None:
                if self._duplicate(refreshed): raise FileExistsError("An equivalent campaign already exists.")
                if self.snapshots.capture() != snapshot: raise RuntimeError("Repository changed before creation.")
                if any((staged / relative).read_bytes() != content for relative, content in refreshed.files.items()):
                    raise RuntimeError("Staged campaign files changed before publication.")
                contract_ok, _ = modern_contract(refreshed.manifest, self.root)
                if not contract_ok:
                    raise RuntimeError("Staged campaign provenance could not be validated.")
            materialize(refreshed, final_check)
            relative = refreshed.destination.relative_to(self.root).as_posix()
            try:
                record = next((row for row in list_campaigns(self.root)["campaigns"] if row["path"] == relative), None)
            except Exception:
                record = None
            if not record:
                # The manifest was fully validated before atomic publication.
                # A transient inspection failure must not turn a successful
                # publication into an uncertain failure.
                identifier = "mot_2d-" + hashlib.sha256(f"mot_2d:{relative}".encode()).hexdigest()[:20]
            else:
                identifier = record["id"]
            result = {
                "status": "created", "campaign_id": identifier, "path": relative,
                "stage": "smoke", "submitted_to_zeus": False,
            }
            pending.result = result
            return result
