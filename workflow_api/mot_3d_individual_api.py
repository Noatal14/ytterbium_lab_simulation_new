"""Closed HTTP-facing adapter for reviewed individual 3D-MOT creation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

from workflow_api.mot_3d_individual_sources import list_individual_mot_3d_sources


class CreationBoundary(Protocol):
    def preview(self, request: Mapping[str, Any], session: str) -> dict[str, Any]: ...
    def confirm(self, token: str, session: str) -> dict[str, Any]: ...


_FIELDS = {"source_id", "geometry_family", "particle_count", "selection_seed", "simulation_seed", "parameters", "retain_particle_states", "execution_mode"}


def _exact(payload: Mapping[str, Any], keys: set[str]) -> None:
    if type(payload) is not dict or set(payload) != keys:
        raise ValueError("Individual 3D-MOT request fields are invalid.")


class IndividualMot3DApi:
    def __init__(self, root: Path, creation: CreationBoundary):
        self.root = root; self.creation = creation

    def sources(self) -> dict[str, Any]:
        return list_individual_mot_3d_sources(self.root)

    def preview(self, payload: Mapping[str, Any], *, session_id: str) -> dict[str, Any]:
        _exact(payload, _FIELDS)
        return self.creation.preview(payload, session_id)

    def confirm(self, payload: Mapping[str, Any], *, session_id: str) -> dict[str, Any]:
        _exact(payload, {"preview_token"}); token = payload["preview_token"]
        if not isinstance(token, str): raise ValueError("Preview token is invalid.")
        return self.creation.confirm(token, session_id)
