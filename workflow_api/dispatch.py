"""Campaign-kind dispatcher for application clients."""

from __future__ import annotations

from pathlib import Path

from workflow_api.manifest_codec import read_manifest
from workflow_api.mot_2d import read_campaign as read_2d_campaign
from workflow_api.mot_3d import read_campaign as read_3d_campaign


def read_campaign(path: str | Path):
    candidate = Path(path)
    manifest_path = candidate / "campaign.json" if candidate.is_dir() else candidate
    document = read_manifest(manifest_path)
    if document.family == "mot_2d":
        return read_2d_campaign(manifest_path, manifest=document.model)
    if document.family == "mot_3d":
        return read_3d_campaign(manifest_path, manifest=document.model)
    raise AssertionError(f"Unreachable campaign family {document.family!r}.")
