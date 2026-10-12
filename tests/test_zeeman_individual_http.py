import json

from workflow_api.zeeman_individual_api import IndividualZeemanApi
from workflow_api.repository_snapshot import RepositoryFilesChangedError
from workflow_api.zeeman_zeus_execution import ZeemanZeusError
from tests.test_workflow_api_contracts import _request, _server


class Creation:
    def __init__(self): self.preview_session = None; self.mutations = 0
    def preview(self, request, session): self.preview_session = session; return {"preview_token":"token","plan":{}}
    def confirm(self, token, session):
        if token != "token" or session != self.preview_session: raise PermissionError
        self.mutations += 1; return {"status":"created"}
class Local:
    def submit(self, family, run_id): raise AssertionError("execution must not occur")
class Zeus:
    def preview(self, **kwargs): raise ZeemanZeusError("secret_unreviewed_code")
    def confirm(self, **kwargs): raise AssertionError("submission must not occur")
    def refresh(self, **kwargs): raise AssertionError("network must not occur")


class ChangedFilesCreation(Creation):
    def preview(self, request, session):
        raise RepositoryFilesChangedError("secret local path")


def _session(base):
    status, headers, body = _request(base,"GET","/api/v1/session",{"Sec-Fetch-Site":"same-origin"})
    assert status == 200
    return headers["set-cookie"].split(";",1)[0], body["data"]["csrf_token"]


def _headers(base,cookie,csrf,content="application/json"):
    return {"Content-Type":content,"Origin":base,"Sec-Fetch-Site":"same-origin","Cookie":cookie,"X-CSRF-Token":csrf}


def test_real_handler_requires_same_origin_json_cookie_and_csrf_before_fake_service():
    creation=Creation(); api=IndividualZeemanApi(creation,Local(),Zeus())
    with _server(5,services=False,individual_api=api) as (base,_):
        cookie,csrf=_session(base)
        body=json.dumps({
            "particle_count": 1,
            "seed": 0,
            "mot_2d_s0": 1.3,
            "mot_2d_detuning_gamma": -0.9196610026631429,
            "mot_2d_magnet_radius_m": 0.04676406447474441,
            "npools": 8,
            "retain_particle_states": False,
            "execution_mode": "local",
        })
        assert _request(base,"POST","/api/v1/individual-runs/zeeman/preview",_headers(base,cookie,"wrong"),body)[0] == 403
        assert _request(base,"POST","/api/v1/individual-runs/zeeman/preview",_headers(base,cookie,csrf,"text/plain"),body)[0] == 400
        assert _request(base,"POST","/api/v1/individual-runs/zeeman/preview",{"Content-Type":"application/json"},body)[0] == 403
        status,_,_=_request(base,"POST","/api/v1/individual-runs/zeeman/preview",_headers(base,cookie,csrf),body)
        assert status == 200
    assert creation.mutations == 0


def test_wrong_session_unknown_fields_and_command_fields_cannot_confirm_or_execute():
    creation=Creation(); api=IndividualZeemanApi(creation,Local(),Zeus())
    with _server(5,services=False,individual_api=api) as (base,_):
        cookie,csrf=_session(base)
        valid={"particle_count":1,"seed":0,"retain_particle_states":False,"execution_mode":"local"}
        assert _request(base,"POST","/api/v1/individual-runs/zeeman/preview",_headers(base,cookie,csrf),json.dumps({**valid,"command":"qsub evil"}))[0] == 412
        assert _request(base,"POST","/api/v1/individual-runs/zeeman/preview",_headers(base,cookie,csrf),json.dumps({**valid,"secret":"password"}))[0] == 412
        _request(base,"POST","/api/v1/individual-runs/zeeman/preview",_headers(base,cookie,csrf),json.dumps(valid))
        bad_cookie="mot_ui_session=" + "x"*43
        assert _request(base,"POST","/api/v1/individual-runs/zeeman/confirm",_headers(base,bad_cookie,csrf),json.dumps({"preview_token":"token"}))[0] == 403
    assert creation.mutations == 0


def test_unknown_zeus_error_is_sanitized_and_not_reflected():
    api=IndividualZeemanApi(Creation(),Local(),Zeus())
    with _server(2,services=False,individual_api=api) as (base,_):
        cookie,csrf=_session(base)
        payload={"run_id":"zeeman-one","profile":{"username":"tal.noa","project_directory":"/home/tal.noa/ytterbium_lab_simulation_new"}}
        status,_,body=_request(base,"POST","/api/v1/individual-runs/zeeman/zeus/preview",_headers(base,cookie,csrf),json.dumps(payload))
    assert status == 500
    assert body == {"error":{"code":"individual_zeus_failed","message":"The individual Zeus operation stopped safely."}}
    assert "secret" not in repr(body)


def test_changed_reviewed_files_return_actionable_sanitized_error():
    api = IndividualZeemanApi(ChangedFilesCreation(), Local(), Zeus())
    with _server(2, services=False, individual_api=api) as (base, _):
        cookie, csrf = _session(base)
        payload = {
            "particle_count": 200,
            "seed": 42,
            "mot_2d_s0": 1.3,
            "mot_2d_detuning_gamma": -0.9196610026631429,
            "mot_2d_magnet_radius_m": 0.04676406447474441,
            "npools": 8,
            "retain_particle_states": True,
            "execution_mode": "local",
        }
        status, _, body = _request(
            base,
            "POST",
            "/api/v1/individual-runs/zeeman/preview",
            _headers(base, cookie, csrf),
            json.dumps(payload),
        )
    assert status == 412
    assert body == {
        "error": {
            "code": "local_files_changed",
            "message": "Reviewed simulation files have uncommitted changes. Commit or stash them, then validate again.",
        }
    }
    assert "secret" not in repr(body)
