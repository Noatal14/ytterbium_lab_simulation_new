"""Server-side separation of scientific and acceptance campaign authorities."""
from pathlib import Path
from typing import Any, Mapping
from workflow_api.acceptance_profile import ACCEPTANCE_KINDS, policy_for_manifest


def campaign_visible(campaign: Mapping[str, Any], profile_id: str | None) -> bool:
    acceptance = campaign.get('kind') in ACCEPTANCE_KINDS.values()
    return acceptance if profile_id is not None else not acceptance


def authorize_campaign_request(root: Path, payload: Mapping[str, Any], profile_id: str | None) -> None:
    campaign_id = payload.get('campaign_id')
    if campaign_id is None:
        return  # Creation catalogs and session-bound confirmations have their own authority.
    from workflow_api.discovery import build_registry
    from workflow_api.manifest_codec import read_manifest
    entry = build_registry(root).get(campaign_id) if isinstance(campaign_id, str) else None
    if entry is None:
        if profile_id is not None:
            raise ValueError('Acceptance campaign is unavailable.')
        return  # Preserve the canonical service's typed not-found handling.
    manifest = read_manifest(entry.manifest).model
    policy = policy_for_manifest(manifest)
    if (policy is None) != (profile_id is None) or (policy is not None and policy.profile_id != profile_id):
        raise ValueError('Campaign policy does not match this server mode.')
