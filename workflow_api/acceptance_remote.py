"""Fail-closed separation between scientific and UI-acceptance Zeus checkouts."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from workflow_api.acceptance_profile import assert_acceptance_path, policy_for_manifest

from workflow_api.campaign_deployment import ACCEPTANCE_CHECKOUT, SCIENTIFIC_CHECKOUT, normal_checkout


def assert_campaign_target(manifest: Mapping[str, Any], username: str, project_directory: str | Path,
                           campaign_path: str | Path | None = None) -> None:
    """Authenticate the manifest before permitting a remote campaign mutation.

    Call both locally before review and remotely before locks, files or qsub.
    Never infer a test profile from a path or environment variable.
    """
    from workflow_api.zeus_snapshot import USERNAME_RE
    if not isinstance(username, str) or not USERNAME_RE.fullmatch(username):
        raise ValueError('Invalid campaign account.')
    profile = policy_for_manifest(manifest)
    if profile is not None and 'execution_checkout' in manifest:
        raise ValueError('TEST ONLY policy cannot override its deployment.')
    expected = PurePosixPath('/home') / username / (ACCEPTANCE_CHECKOUT if profile else normal_checkout(manifest))
    if str(project_directory) != str(expected):
        raise ValueError('Campaign policy does not match the isolated Zeus checkout.')
    if campaign_path is not None:
        campaign = PurePosixPath(str(campaign_path))
        if not campaign.is_absolute():
            if '..' in campaign.parts or str(campaign) != str(campaign_path):
                raise ValueError('Invalid campaign path.')
            campaign = expected / campaign
        if profile is not None:
            assert_acceptance_path(Path(str(campaign)), Path(str(expected)))
        elif 'ui_acceptance' in campaign.parts:
            raise ValueError('TEST ONLY paths cannot host scientific campaigns.')


def campaign_path_parts(value: str, family: str) -> tuple[str, ...]:
    """Validate syntax only; assert_campaign_target must authenticate contents."""
    path = PurePosixPath(value)
    parts = path.parts
    if family not in ('mot_2d', 'mot_3d') or path.is_absolute() or str(path) != value or any(x in ('.', '..') for x in parts):
        raise ValueError('Invalid campaign path.')
    if parts[:3] != ('data', 'optimization', family):
        raise ValueError('Invalid campaign path.')
    if len(parts) == 4 and parts[3] != 'ui_acceptance':
        return parts
    if len(parts) == 5 and parts[3] == 'ui_acceptance':
        return parts
    raise ValueError('Invalid campaign path.')
