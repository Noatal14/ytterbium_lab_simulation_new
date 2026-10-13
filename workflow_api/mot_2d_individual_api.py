"""Closed HTTP-facing adapter for reviewed individual 2D-MOT runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

from workflow_api.mot_2d_individual_sources import list_individual_mot_2d_sources
from workflow_api.run_discovery import inspect_run
from workflow_api.run_records import RunRecordError
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
    if type(payload) is not dict or set(payload) != keys:
        raise ValueError("Individual 2D-MOT request fields are invalid.")


class IndividualMot2DApi:
    def __init__(
        self,
        root: Path,
        creation: CreationBoundary,
        local: LocalBoundary,
        zeus: ZeusBoundary,
    ):
        self.root = root
        self.creation = creation
        self.local = local
        self.zeus = zeus

    def sources(self) -> dict[str, Any]:
        return list_individual_mot_2d_sources(self.root)

    def preview(self, payload: Mapping[str, Any], *, session_id: str) -> dict[str, Any]:
        _exact(
            payload,
            {
                "source_id",
                "particle_count",
                "selection_seed",
                "mot_seed",
                "s0",
                "detuning_gamma",
                "magnet_radius_m",
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
        try:
            inspected = inspect_run(self.root, "mot_2d", run_id)
        except (OSError, RunRecordError, KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "The reviewed 2D-MOT run could not be verified."
            ) from error
        if (
            inspected.family != "mot_2d"
            or inspected.run.get("family") != "mot_2d"
            or inspected.run.get("execution_mode") != "local"
            or inspected.state != "configured"
            or inspected.integrity != "active"
        ):
            raise ValueError(
                "The reviewed 2D-MOT run is not ready for local execution."
            )
        handle = self.local.submit("mot_2d", run_id)
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
