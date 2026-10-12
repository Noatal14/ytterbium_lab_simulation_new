import json

from tests.test_zeeman_individual_http import _headers
from tests.test_workflow_api_contracts import _request, _server
from workflow_api.mot_3d_individual_api import IndividualMot3DApi


class Creation:
    def __init__(self): self.calls = []
    def preview(self, payload, session): self.calls.append(("preview", payload, session)); return {"ok": True}
    def confirm(self, token, session): self.calls.append(("confirm", token, session)); return {"ok": True}


def test_mot3d_http_preview_and_confirm_are_same_origin_session_bound_and_exact(tmp_path):
    creation = Creation(); api = IndividualMot3DApi(tmp_path, creation)
    valid = {"source_id": "mot3d-source-" + "a" * 32, "geometry_family": "angled_donut", "particle_count": 1, "selection_seed": 1, "simulation_seed": 2, "parameters": {}, "retain_particle_states": False, "execution_mode": "local"}
    with _server(7, services=False, individual_mot_3d_api=api) as (base, _):
        _, headers, session = _request(base, "GET", "/api/v1/session", {"Sec-Fetch-Site": "same-origin"})
        cookie = headers["set-cookie"].split(";", 1)[0]; csrf = session["data"]["csrf_token"]
        assert _request(base, "POST", "/api/v1/individual-runs/mot-3d/preview", _headers(base, cookie, "wrong"), json.dumps(valid))[0] == 403
        assert _request(base, "POST", "/api/v1/individual-runs/mot-3d/preview", _headers(base, cookie, csrf, "text/plain"), json.dumps(valid))[0] == 400
        assert _request(base, "POST", "/api/v1/individual-runs/mot-3d/preview", _headers(base, cookie, csrf), json.dumps({**valid, "command": "qsub"}))[0] == 412
        assert _request(base, "POST", "/api/v1/individual-runs/mot-3d/preview", _headers(base, cookie, csrf), json.dumps(valid))[0] == 200
        assert _request(base, "POST", "/api/v1/individual-runs/mot-3d/confirm", _headers(base, cookie, csrf), json.dumps({"preview_token": "token", "command": "run"}))[0] == 412
        assert _request(base, "POST", "/api/v1/individual-runs/mot-3d/confirm", _headers(base, cookie, csrf), json.dumps({"preview_token": "token"}))[0] == 201
    assert [call[0] for call in creation.calls] == ["preview", "confirm"]


def test_mot3d_source_get_is_read_only_and_service_guarded(tmp_path):
    class Api(IndividualMot3DApi):
        def sources(self): return {"contract_version": "v", "sources": [], "invalid_count": 0, "total": 0, "truncated": False}
    with _server(1, services=False, individual_mot_3d_api=Api(tmp_path, Creation())) as (base, _):
        status, _, body = _request(base, "GET", "/api/v1/individual-runs/mot-3d/sources")
    assert status == 200 and body["data"]["sources"] == []
