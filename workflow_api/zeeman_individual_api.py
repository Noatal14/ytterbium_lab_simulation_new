"""Thin application boundary for one reviewed individual Zeeman run.

This module owns no scientific defaults and performs no physics itself.  It
only adapts the already reviewed E1--E5 services to small, session-bound UI
operations.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from workflow_api.zeus_snapshot import ZeusProfile


class CreationBoundary(Protocol):
    def preview(self, request: Mapping[str, Any], session: str) -> dict[str, Any]: ...
    def confirm(self, token: str, session: str) -> dict[str, Any]: ...


class LocalBoundary(Protocol):
    def submit(self, family: str, run_id: str): ...


class ZeusBoundary(Protocol):
    def preview(
        self, *, run_id: str, profile: ZeusProfile, session: str
    ) -> dict[str, Any]: ...
    def confirm(self, *, preview_token: str, session: str) -> dict[str, Any]: ...
    def refresh(self, *, run_id: str, profile: ZeusProfile) -> dict[str, Any]: ...
    def recover(
        self,
        *,
        run_id: str,
        profile: ZeusProfile,
        session: str,
    ) -> dict[str, Any]: ...


def _exact(payload: Mapping[str, Any], keys: set[str]) -> None:
    if set(payload) != keys:
        raise ValueError("Individual-run request fields are invalid.")


class IndividualZeemanApi:
    """Closed DTO adapter; all state-changing calls remain explicit."""

    def __init__(
        self, creation: CreationBoundary, local: LocalBoundary, zeus: ZeusBoundary
    ):
        self.creation = creation
        self.local = local
        self.zeus = zeus

    def preview(self, payload: Mapping[str, Any], *, session_id: str) -> dict[str, Any]:
        _exact(
            payload,
            {
                "particle_count",
                "seed",
                "mot_2d_s0",
                "mot_2d_detuning_gamma",
                "mot_2d_magnet_radius_m",
                "npools",
                "retain_particle_states",
                "execution_mode",
            },
        )
        return self.creation.preview(payload, session_id)

    def confirm(self, payload: Mapping[str, Any], *, session_id: str) -> dict[str, Any]:
        _exact(payload, {"preview_token"})
        token = payload["preview_token"]
        if not isinstance(token, str):
            raise ValueError("Preview token is invalid.")
        return self.creation.confirm(token, session_id)

    def start_local(
        self, payload: Mapping[str, Any], *, session_id: str
    ) -> dict[str, Any]:
        del session_id
        _exact(payload, {"run_id"})
        run_id = payload["run_id"]
        if not isinstance(run_id, str):
            raise ValueError("Run identifier is invalid.")
        handle = self.local.submit("zeeman", run_id)
        return {"status": "queued", "run_id": handle.run_id, "execution_mode": "local"}

    @staticmethod
    def _profile(payload: Mapping[str, Any]) -> ZeusProfile:
        value = payload.get("profile")
        if not isinstance(value, dict):
            raise ValueError("Zeus connection profile is invalid.")
        return ZeusProfile.parse(value)

    def preview_zeus(
        self, payload: Mapping[str, Any], *, session_id: str
    ) -> dict[str, Any]:
        _exact(payload, {"run_id", "profile"})
        run_id = payload["run_id"]
        if not isinstance(run_id, str):
            raise ValueError("Run identifier is invalid.")
        return self.zeus.preview(
            run_id=run_id, profile=self._profile(payload), session=session_id
        )

    def confirm_zeus(
        self, payload: Mapping[str, Any], *, session_id: str
    ) -> dict[str, Any]:
        _exact(payload, {"preview_token"})
        token = payload["preview_token"]
        if not isinstance(token, str):
            raise ValueError("Preview token is invalid.")
        return self.zeus.confirm(preview_token=token, session=session_id)

    def refresh_zeus(
        self, payload: Mapping[str, Any], *, session_id: str
    ) -> dict[str, Any]:
        del session_id
        _exact(payload, {"run_id", "profile"})
        run_id = payload["run_id"]
        if not isinstance(run_id, str):
            raise ValueError("Run identifier is invalid.")
        return self.zeus.refresh(run_id=run_id, profile=self._profile(payload))

    def recover_zeus(
        self, payload: Mapping[str, Any], *, session_id: str
    ) -> dict[str, Any]:
        _exact(payload, {"run_id", "profile"})
        run_id = payload["run_id"]
        if not isinstance(run_id, str):
            raise ValueError("Zeus recovery evidence is invalid.")
        return self.zeus.recover(
            run_id=run_id,
            profile=self._profile(payload),
            session=session_id,
        )
