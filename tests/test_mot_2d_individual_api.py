from pathlib import Path
from types import SimpleNamespace

import pytest

from workflow_api.mot_2d_individual_api import IndividualMot2DApi
from workflow_api.zeus_snapshot import ZeusProfile


class Creation:
    def preview(self, request, session):
        return {"request": request, "session": session}

    def confirm(self, token, session):
        return {"token": token, "session": session}


class Local:
    def submit(self, family, run_id):
        assert family == "mot_2d"
        return SimpleNamespace(run_id=run_id)


class Zeus:
    def preview(self, **kwargs):
        return kwargs

    def confirm(self, **kwargs):
        return kwargs

    def refresh(self, **kwargs):
        return kwargs

    def recover(self, **kwargs):
        return kwargs


REQUEST = {
    "source_id": "mot2d-source-" + "a" * 32,
    "particle_count": 200,
    "selection_seed": 1,
    "mot_seed": 2,
    "s0": 1.3,
    "detuning_gamma": -0.9196610026631429,
    "magnet_radius_m": 0.04676406447474441,
    "npools": 8,
    "retain_particle_states": False,
    "execution_mode": "local",
}


def api(tmp_path):
    return IndividualMot2DApi(tmp_path, Creation(), Local(), Zeus())


def test_closed_creation_and_execution_boundaries(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "workflow_api.mot_2d_individual_api.inspect_run",
        lambda *_: SimpleNamespace(
            family="mot_2d",
            run={"family": "mot_2d", "execution_mode": "local", "particle_count": 20},
            configuration={"resolved": {"execution": {"mode": "local", "workers": 1}}},
            state="configured",
            integrity="active",
        ),
    )
    boundary = api(tmp_path)
    assert boundary.preview(REQUEST, session_id="owner")["session"] == "owner"
    assert boundary.confirm({"preview_token": "token"}, session_id="owner") == {
        "token": "token",
        "session": "owner",
    }
    assert boundary.start_local({"run_id": "mot2d-one"}, session_id="owner") == {
        "status": "queued",
        "run_id": "mot2d-one",
        "execution_mode": "local",
    }
    profile = {
        "username": "tal.noa",
        "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
    }
    reviewed = boundary.preview_zeus(
        {"run_id": "mot2d-one", "profile": profile}, session_id="owner"
    )
    assert reviewed["profile"] == ZeusProfile.parse(profile)
    assert (
        boundary.confirm_zeus({"preview_token": "ztoken"}, session_id="owner")[
            "session"
        ]
        == "owner"
    )
    assert (
        boundary.refresh_zeus(
            {"run_id": "mot2d-one", "profile": profile}, session_id="owner"
        )["run_id"]
        == "mot2d-one"
    )
    recovered = boundary.recover_zeus(
        {
            "run_id": "mot2d-one",
            "profile": profile,
        },
        session_id="fresh",
    )
    assert recovered["session"] == "fresh"
    assert "expected_job_id" not in recovered
    assert "submission_key" not in recovered


@pytest.mark.parametrize(
    "snapshot",
    [
        SimpleNamespace(
            family="zeeman",
            run={"family": "zeeman", "execution_mode": "local"},
            state="configured",
            integrity="active",
        ),
        SimpleNamespace(
            family="mot_2d",
            run={"family": "mot_2d", "execution_mode": "zeus"},
            state="configured",
            integrity="active",
        ),
        SimpleNamespace(
            family="mot_2d",
            run={"family": "mot_2d", "execution_mode": "local"},
            state="running",
            integrity="active",
        ),
        SimpleNamespace(
            family="mot_2d",
            run={"family": "mot_2d", "execution_mode": "local", "particle_count": 20},
            configuration={"resolved": {"execution": {"mode": "local", "workers": 1}}},
            state="configured",
            integrity="invalid",
        ),
    ],
)
def test_local_start_preflight_rejects_before_scheduling(
    tmp_path, monkeypatch, snapshot
):
    local = Local()
    local.calls = 0

    def submit(*args):
        local.calls += 1
        return SimpleNamespace(run_id=args[-1])

    local.submit = submit
    boundary = IndividualMot2DApi(tmp_path, Creation(), local, Zeus())
    monkeypatch.setattr(
        "workflow_api.mot_2d_individual_api.inspect_run", lambda *_: snapshot
    )
    with pytest.raises(ValueError, match="not ready"):
        boundary.start_local({"run_id": "mot2d-one"}, session_id="owner")
    assert local.calls == 0


def test_local_start_integrity_failure_never_reaches_pool(tmp_path, monkeypatch):
    local = Local()
    local.calls = 0
    local.submit = lambda *_: setattr(local, "calls", local.calls + 1)
    boundary = IndividualMot2DApi(tmp_path, Creation(), local, Zeus())
    monkeypatch.setattr(
        "workflow_api.mot_2d_individual_api.inspect_run",
        lambda *_: (_ for _ in ()).throw(OSError("swapped")),
    )
    with pytest.raises(ValueError, match="could not be verified"):
        boundary.start_local({"run_id": "mot2d-one"}, session_id="owner")
    assert local.calls == 0


@pytest.mark.parametrize("extra", ["command", "secret", "path", "ssh_options"])
def test_preview_rejects_unknown_or_sensitive_fields(tmp_path, extra):
    with pytest.raises(ValueError):
        api(tmp_path).preview({**REQUEST, extra: "bad"}, session_id="owner")
