"""Campaign-kind dispatcher for application clients."""

from __future__ import annotations

import json
from pathlib import Path

from workflow_api.mot_2d import read_campaign as read_2d_campaign
from workflow_api.mot_3d import read_campaign as read_3d_campaign


def read_campaign(path: str | Path):
    candidate = Path(path)
    manifest_path = candidate / "campaign.json" if candidate.is_dir() else candidate
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    kind = manifest.get("kind")
    if kind == "mot_2d_s0_campaign":
        return read_2d_campaign(manifest_path)
    if kind == "mot_3d_campaign_v2":
        return read_3d_campaign(manifest_path)
    raise ValueError(f"Unsupported campaign kind {kind!r}.")
