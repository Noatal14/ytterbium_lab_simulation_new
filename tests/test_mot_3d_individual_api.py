from workflow_api.mot_3d_individual_api import IndividualMot3DApi
import pytest


class Creation:
    def __init__(self):
        self.calls = []

    def preview(self, payload, session):
        self.calls.append(("preview", payload, session))
        return {"ok": True}

    def confirm(self, token, session):
        self.calls.append(("confirm", token, session))
        return {"ok": True}


@pytest.mark.parametrize("explicit_workers", [False, True])
def test_api_is_exact_and_session_bound(tmp_path, explicit_workers):
    creation = Creation()
    api = IndividualMot3DApi(tmp_path, creation)
    request = {
        "source_id": "mot3d-source-" + "a" * 32,
        "geometry_family": "angled_donut",
        "particle_count": 1,
        "selection_seed": 1,
        "simulation_seed": 2,
        "parameters": {},
        "retain_particle_states": False,
        "execution_mode": "local",
    }
    if explicit_workers:
        request["npools"] = 2
    assert api.preview(request, session_id="session") == {"ok": True}
    assert api.confirm({"preview_token": "token"}, session_id="session") == {"ok": True}
    assert creation.calls == [
        ("preview", request, "session"),
        ("confirm", "token", "session"),
    ]
    for invalid in (
        {**request, "command": "qsub"},
        {key: value for key, value in request.items() if key != "parameters"},
    ):
        try:
            api.preview(invalid, session_id="session")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid request accepted")


def test_zeus_recovery_is_exact_and_session_bound(tmp_path):
    class Zeus:
        def recover(self, **kwargs):
            return kwargs

    api = IndividualMot3DApi(tmp_path, Creation(), zeus=Zeus())
    profile = {
        "username": "tal.noa",
        "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
    }
    result = api.recover_zeus(
        {
            "run_id": "mot3d-one",
            "profile": profile,
        },
        session_id="fresh",
    )
    assert result["session"] == "fresh"
    assert "expected_job_id" not in result
    assert "submission_key" not in result
