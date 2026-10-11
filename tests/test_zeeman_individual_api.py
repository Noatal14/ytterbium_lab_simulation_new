from dataclasses import dataclass

import pytest

from workflow_api.zeeman_individual_api import IndividualZeemanApi
from workflow_api.zeus_snapshot import ZeusProfile
from workflow_api.server import POST_ROUTES, _invoke_post_route


@dataclass
class Handle:
    run_id: str


class Creation:
    def preview(self, request, session):
        return {"request": dict(request), "session": session}
    def confirm(self, token, session):
        return {"token": token, "session": session}


class Local:
    calls = []
    def submit(self, family, run_id):
        self.calls.append((family, run_id)); return Handle(run_id)


class Zeus:
    calls = []
    def preview(self, **kwargs): self.calls.append(("preview", kwargs)); return {"preview_token": "p"}
    def confirm(self, **kwargs): self.calls.append(("confirm", kwargs)); return {"status": "submitted"}
    def refresh(self, **kwargs): self.calls.append(("refresh", kwargs)); return {"state": "running"}


@pytest.fixture
def api():
    return IndividualZeemanApi(Creation(), Local(), Zeus())


def test_only_four_scientific_request_controls_are_accepted(api):
    request = {"particle_count": 12, "seed": 4, "retain_particle_states": True, "execution_mode": "local"}
    assert api.preview(request, session_id="session") == {"request": request, "session": "session"}
    with pytest.raises(ValueError, match="fields"):
        api.preview({**request, "magnet_profile": "caller-controlled"}, session_id="session")


def test_creation_and_local_execution_are_distinct_explicit_actions(api):
    assert api.confirm({"preview_token": "reviewed"}, session_id="s")["token"] == "reviewed"
    assert api.start_local({"run_id": "run-1"}, session_id="s") == {
        "status": "queued", "run_id": "run-1", "execution_mode": "local"
    }


def test_zeus_profile_is_derived_and_every_remote_action_is_explicit(api):
    profile = {"username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"}
    assert api.preview_zeus({"run_id": "run-1", "profile": profile}, session_id="s") == {"preview_token": "p"}
    assert api.confirm_zeus({"preview_token": "p"}, session_id="s") == {"status": "submitted"}
    assert api.refresh_zeus({"run_id": "run-1", "profile": profile}, session_id="s") == {"state": "running"}
    first = api.zeus.calls[-3][1]
    assert first["profile"] == ZeusProfile("tal.noa", profile["project_directory"])
    assert first["session"] == "s"
    with pytest.raises(ValueError):
        api.preview_zeus({"run_id": "run-1", "profile": {**profile, "host": "evil"}}, session_id="s")


def test_facade_has_no_generic_command_or_cancellation_surface(api):
    assert not hasattr(api, "command")
    assert not hasattr(api, "cancel")


def test_server_exposes_only_the_six_reviewed_session_bound_operations(api):
    expected = {
        "/api/v1/individual-runs/zeeman/preview": "preview",
        "/api/v1/individual-runs/zeeman/confirm": "confirm",
        "/api/v1/individual-runs/zeeman/local/start": "start_local",
        "/api/v1/individual-runs/zeeman/zeus/preview": "preview_zeus",
        "/api/v1/individual-runs/zeeman/zeus/confirm": "confirm_zeus",
        "/api/v1/individual-runs/zeeman/zeus/refresh": "refresh_zeus",
    }
    for path, operation in expected.items():
        route = POST_ROUTES[path]
        assert route.service_attr == "individual_zeeman_api"
        assert route.operation == operation
        assert route.call_style == "session_kw"
    assert not any("cancel" in path or "command" in path for path in expected)

    request = {"particle_count": 2, "seed": 1, "retain_particle_states": False, "execution_mode": "local"}
    assert _invoke_post_route(POST_ROUTES["/api/v1/individual-runs/zeeman/preview"], api, request, "bound-session")["session"] == "bound-session"
