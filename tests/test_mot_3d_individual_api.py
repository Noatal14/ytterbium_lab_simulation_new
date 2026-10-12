from workflow_api.mot_3d_individual_api import IndividualMot3DApi


class Creation:
    def __init__(self): self.calls = []
    def preview(self, payload, session): self.calls.append(("preview", payload, session)); return {"ok": True}
    def confirm(self, token, session): self.calls.append(("confirm", token, session)); return {"ok": True}


def test_api_is_exact_and_session_bound(tmp_path, monkeypatch):
    creation = Creation(); api = IndividualMot3DApi(tmp_path, creation)
    request = {"source_id": "mot3d-source-" + "a" * 32, "geometry_family": "angled_donut", "particle_count": 1, "selection_seed": 1, "simulation_seed": 2, "parameters": {}, "retain_particle_states": False, "execution_mode": "local"}
    assert api.preview(request, session_id="session") == {"ok": True}
    assert api.confirm({"preview_token": "token"}, session_id="session") == {"ok": True}
    assert creation.calls == [("preview", request, "session"), ("confirm", "token", "session")]
    for invalid in ({**request, "command": "qsub"}, {key: value for key, value in request.items() if key != "parameters"}):
        try: api.preview(invalid, session_id="session")
        except ValueError: pass
        else: raise AssertionError("invalid request accepted")
