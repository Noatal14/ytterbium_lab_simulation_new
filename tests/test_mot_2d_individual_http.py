import json

from tests.test_zeeman_individual_http import _headers
from tests.test_workflow_api_contracts import _request, _server
from workflow_api.mot_2d_individual_api import IndividualMot2DApi


class Creation:
    calls=[]
    def preview(self,payload,session): self.calls.append(("preview",payload,session)); return {"ok":True}
    def confirm(self,token,session): self.calls.append(("confirm",token,session)); return {"ok":True}
class Local:
    def submit(self,family,run_id): raise AssertionError("not used")
class Zeus: pass


def test_mot2d_http_preview_is_same_origin_session_bound_and_exact(tmp_path):
    creation=Creation(); creation.calls=[]
    api=IndividualMot2DApi(tmp_path,creation,Local(),Zeus())
    valid={"source_id":"mot2d-source-"+"a"*32,"particle_count":20,"selection_seed":1,"mot_seed":2,"s0":1.3,"detuning_gamma":-0.92,"magnet_radius_m":0.046,"npools":8,"retain_particle_states":False,"execution_mode":"local"}
    with _server(4,services=False,individual_mot_2d_api=api) as (base,_):
        _,headers,session=_request(base,"GET","/api/v1/session",{"Sec-Fetch-Site":"same-origin"})
        cookie=headers["set-cookie"].split(";",1)[0]; csrf=session["data"]["csrf_token"]
        assert _request(base,"POST","/api/v1/individual-runs/mot-2d/preview",_headers(base,cookie,"wrong"),json.dumps(valid))[0]==403
        assert _request(base,"POST","/api/v1/individual-runs/mot-2d/preview",_headers(base,cookie,csrf,"text/plain"),json.dumps(valid))[0]==400
        assert _request(base,"POST","/api/v1/individual-runs/mot-2d/preview",_headers(base,cookie,csrf),json.dumps({**valid,"command":"qsub"}))[0]==412
    assert creation.calls == []
    assert api.preview(valid, session_id="session-a") == {"ok": True}
    assert len(creation.calls) == 1
    assert creation.calls[0][:2] == ("preview", valid)
