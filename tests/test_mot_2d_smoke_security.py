"""Adversarial contract tests for the Smoke-to-Screening trust boundary."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

import pytest

from workflow_api.mot_2d_smoke import SmokeValidationError, validate_smoke_outputs
from workflow_api.zeus_screening import (
    RemoteSmokeState,
    ZeusScreeningCoordinator,
    ZeusScreeningError,
)


def _manifest(*, values=(1.3,)):
    return {
        "kind": "mot_2d_s0_campaign",
        "name": "Smoke fixture",
        "stage": "smoke",
        "s0_values": list(values),
        "fixed_design": {
            "working_dt_s": 1.25e-6,
            "solver": "RK4StHybridCustom",
            "detuning_bounds_gamma": [-2.0, -0.5],
            "magnet_radius_bounds_m": [0.04, 0.06],
        },
        "ensemble_source": {"directory": "data/particle_states/after_zeeman/canonical"},
        "seed_roles": {"discovery": [3000, 3001]},
        "mot_seeds": {"discovery": [43000, 43001]},
        "provenance": {
            "git_commit": "a" * 40,
            "physical_model_sha256": "b" * 64,
        },
    }


def _design(manifest, s0):
    fixed = manifest["fixed_design"]
    return {
        "fixed_s0": float(s0),
        "dt_s": fixed["working_dt_s"],
        "solver": fixed["solver"],
        "ensemble_dir": manifest["ensemble_source"]["directory"],
        "zeeman_seeds": [manifest["seed_roles"]["discovery"][0]],
        "mot_seeds": [manifest["mot_seeds"]["discovery"][0]],
        "particles_per_ensemble": 2,
        "sampler_seed": 42,
        "bounds": {
            "s0": [float(s0), float(s0)],
            "detuning_gamma": fixed["detuning_bounds_gamma"],
            "magnet_radius_m": fixed["magnet_radius_bounds_m"],
        },
        "git_commit": manifest["provenance"]["git_commit"],
        "campaign_design_id": manifest["provenance"]["physical_model_sha256"],
    }


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=True), encoding="utf-8")


def _write_database(path, expected):
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE trials (state TEXT);"
        "CREATE TABLE study_user_attributes (key TEXT, value_json TEXT);"
    )
    connection.execute("INSERT INTO trials VALUES ('COMPLETE')")
    design_id = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    connection.executemany(
        "INSERT INTO study_user_attributes VALUES (?, ?)",
        [("scientific_design", json.dumps(expected)), ("design_id", json.dumps(design_id))],
    )
    connection.commit()
    connection.close()


def _valid_smoke(root: Path, manifest, s0, *, captured=0):
    key = f"s0_{float(s0):.6f}".replace(".", "p")
    directory = root / "smoke" / key
    expected = _design(manifest, s0)
    design_id = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    parameters = {"s0": float(s0), "detuning_gamma": -1.0, "magnet_radius": 0.05}
    efficiency = captured / 2
    trial = {
        "kind": "mot_2d_joint_optimization_trial",
        "trial_number": 0,
        "parameters": parameters,
        "design": {
            "dt_s": expected["dt_s"], "n_ensembles": 1,
            "particles_per_ensemble": 2, "mot_seed_start": 4000,
            "stochastic_solver": expected["solver"], "design_id": design_id,
            "git_commit": expected["git_commit"],
            "ensemble_dir": expected["ensemble_dir"],
            "zeeman_seeds": expected["zeeman_seeds"], "mot_seeds": expected["mot_seeds"],
        },
        "replicates": [{
            "zeeman_seed": expected["zeeman_seeds"][0],
            "mot_seed": expected["mot_seeds"][0], "n_input": 2,
            "captured": captured, "conditional_efficiency": efficiency,
        }],
        "statistics": {"mean_conditional_efficiency": efficiency},
    }
    summary = {
        "kind": "mot_2d_joint_optimization_summary",
        "study_name": "smoke", "objectives": ["maximize_mean_conditional_efficiency"],
        "fixed_s0": float(s0), "n_registered_trials": 1, "n_finished_trials": 1,
        "ranked_trials": [{"trial_number": 0, "mean_conditional_efficiency": efficiency,
                           "parameters": parameters}],
        "pareto_front": [],
        "design": {
            "dt_s": expected["dt_s"], "n_ensembles": 1,
            "particles_per_ensemble": 2, "mot_seed_start": 4000,
            "stochastic_solver": expected["solver"], "ensemble_dir": expected["ensemble_dir"],
            "zeeman_seeds": expected["zeeman_seeds"], "sampler_seed": 42,
            "bounds": expected["bounds"],
        },
    }
    _write_json(directory / "summary.json", summary)
    _write_json(directory / "trials/trial_0000.json", trial)
    _write_database(directory / "joint_screening.db", expected)
    return directory, summary, trial


def test_zero_capture_is_a_valid_smoke_result(tmp_path):
    manifest = _manifest()
    _valid_smoke(tmp_path, manifest, 1.3, captured=0)
    report = validate_smoke_outputs(tmp_path, manifest)
    assert report[0]["captured"] == 0
    assert report[0]["efficiency"] == 0.0


def test_every_frozen_s0_must_have_an_independently_valid_result(tmp_path):
    manifest = _manifest(values=(1.1, 1.3))
    _valid_smoke(tmp_path, manifest, 1.1)
    with pytest.raises(SmokeValidationError):
        validate_smoke_outputs(tmp_path, manifest)
    _valid_smoke(tmp_path, manifest, 1.3)
    assert [row["s0"] for row in validate_smoke_outputs(tmp_path, manifest)] == [1.1, 1.3]


@pytest.mark.parametrize(
    ("target", "path", "value"),
    [
        ("trial", ("design", "git_commit"), "c" * 40),
        ("trial", ("design", "dt_s"), 2.5e-6),
        ("trial", ("design", "stochastic_solver"), "RK4StCustom"),
        ("trial", ("design", "zeeman_seeds"), [3001]),
        ("trial", ("design", "mot_seeds"), [43001]),
        ("trial", ("design", "design_id"), "d" * 64),
        ("trial", ("parameters", "detuning_gamma"), float("nan")),
        ("summary", ("ranked_trials", 0, "mean_conditional_efficiency"), float("inf")),
    ],
)
def test_provenance_and_finite_value_tampering_is_rejected(tmp_path, target, path, value):
    manifest = _manifest()
    directory, summary, trial = _valid_smoke(tmp_path, manifest, 1.3)
    row = summary if target == "summary" else trial
    cursor = row
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value
    _write_json(directory / ("summary.json" if target == "summary" else "trials/trial_0000.json"), row)
    with pytest.raises(SmokeValidationError):
        validate_smoke_outputs(tmp_path, manifest)


def test_nonfinite_unranked_statistics_are_rejected(tmp_path):
    manifest = _manifest()
    directory, _, trial = _valid_smoke(tmp_path, manifest, 1.3)
    trial["statistics"]["mean_conditional_efficiency"] = float("nan")
    _write_json(directory / "trials/trial_0000.json", trial)
    with pytest.raises(SmokeValidationError):
        validate_smoke_outputs(tmp_path, manifest)


@pytest.mark.parametrize("artifact", ["summary.json", "trials/trial_0000.json", "joint_screening.db"])
def test_symlinked_artifacts_are_rejected(tmp_path, artifact):
    manifest = _manifest()
    directory, _, _ = _valid_smoke(tmp_path, manifest, 1.3)
    victim = directory / artifact
    outside = tmp_path / ("outside-" + victim.name)
    victim.replace(outside)
    victim.symlink_to(outside)
    with pytest.raises(SmokeValidationError):
        validate_smoke_outputs(tmp_path, manifest)


def test_corrupt_or_incompatible_database_is_rejected(tmp_path):
    manifest = _manifest()
    directory, _, _ = _valid_smoke(tmp_path, manifest, 1.3)
    database = directory / "joint_screening.db"
    database.write_bytes(b"not sqlite")
    with pytest.raises(SmokeValidationError):
        validate_smoke_outputs(tmp_path, manifest)


def test_database_with_extra_or_running_trial_is_rejected(tmp_path):
    manifest = _manifest()
    directory, _, _ = _valid_smoke(tmp_path, manifest, 1.3)
    database = directory / "joint_screening.db"
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO trials VALUES ('RUNNING')")
    connection.commit(); connection.close()
    with pytest.raises(SmokeValidationError):
        validate_smoke_outputs(tmp_path, manifest)


def test_validator_is_read_only(tmp_path):
    manifest = _manifest()
    _valid_smoke(tmp_path, manifest, 1.3)
    before = {p.relative_to(tmp_path): (p.stat().st_mtime_ns, p.read_bytes())
              for p in tmp_path.rglob("*") if p.is_file()}
    validate_smoke_outputs(tmp_path, manifest)
    after = {p.relative_to(tmp_path): (p.stat().st_mtime_ns, p.read_bytes())
             for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


class _ScreeningTransport:
    def __init__(self, lifecycle="ready_to_prepare_screen"):
        self.lifecycle = lifecycle
        self.inspections = []
        self.preparations = []

    def _state(self, lifecycle=None):
        return RemoteSmokeState(
            lifecycle or self.lifecycle, "12345.zeus-master", "F", 0,
            ({"s0": 1.3, "captured": 0, "input": 2, "efficiency": 0.0},), 3, "main",
        )

    def inspect(self, **payload):
        self.inspections.append(payload)
        return self._state()

    def prepare(self, **payload):
        self.preparations.append(payload)
        return self._state("screen_prepared")


def _screening_coordinator(tmp_path, transport, *, clock=lambda: 100.0):
    campaign = tmp_path / "data/optimization/mot_2d/campaign"
    campaign.mkdir(parents=True, exist_ok=True)
    manifest = _manifest()
    transition = {"screen/tasks.json": "1" * 64, "jobs/02_screen.pbs": "2" * 64,
                  "campaign.json": "3" * 64}
    coordinator = ZeusScreeningCoordinator(
        tmp_path, Path("/usr/bin/ssh"), Path("/usr/bin/git"), clock=clock,
        transport_factory=lambda profile: transport,
    )
    prepared = {f"artifact-{index}": f"{index:064x}" for index in range(72)}
    coordinator._plan = lambda campaign_id: (
        campaign, manifest, "a" * 40, dict(prepared), "f" * 64, dict(transition)
    )
    coordinator._revision = lambda: ("a" * 40, True)
    return coordinator, transition


def _screening_request():
    return {"campaign_id": "mot_2d-id", "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"}


def _screening_code(callable_):
    with pytest.raises(ZeusScreeningError) as caught:
        callable_()
    return caught.value.code


@pytest.mark.parametrize("lifecycle,action", [
    ("queued", "wait"), ("running", "wait"), ("awaiting_outputs", "wait"),
    ("held_attention", "inspect_on_zeus"), ("failed", "inspect_on_zeus"),
    ("outputs_invalid", "inspect_on_zeus"), ("unknown", "inspect_on_zeus"),
    ("ready_to_prepare_screen", "review_screening_preparation"),
    ("screen_prepared", "none"),
])
def test_read_only_status_never_prepares_and_maps_lifecycle(tmp_path, lifecycle, action):
    transport = _ScreeningTransport(lifecycle)
    coordinator, _ = _screening_coordinator(tmp_path, transport)
    result = coordinator.status(_screening_request(), session_id="owner")
    assert result["source"] == "zeus" and result["lifecycle"] == lifecycle
    assert result["next_action"] == action
    assert transport.preparations == []


@pytest.mark.parametrize("lifecycle,code", [
    ("queued", "smoke_running"), ("running", "smoke_running"),
    ("awaiting_outputs", "smoke_outputs_pending"),
    ("held_attention", "smoke_held"), ("failed", "smoke_failed"),
    ("outputs_invalid", "smoke_outputs_invalid"),
    ("unknown", "smoke_status_unknown"),
    ("screen_prepared", "screening_already_prepared"),
])
def test_preview_blocks_every_noneligible_lifecycle(tmp_path, lifecycle, code):
    transport = _ScreeningTransport(lifecycle)
    coordinator, _ = _screening_coordinator(tmp_path, transport)
    assert _screening_code(lambda: coordinator.preview(
        _screening_request(), session_id="owner")) == code
    assert transport.preparations == []


def test_preview_is_read_only_and_explicitly_promises_no_submission(tmp_path):
    transport = _ScreeningTransport()
    coordinator, _ = _screening_coordinator(tmp_path, transport)
    preview = coordinator.preview(_screening_request(), session_id="owner")
    assert preview["from_stage"] == "smoke" and preview["to_stage"] == "screen"
    assert preview["smoke"]["points"][0]["captured"] == 0
    assert preview["effects"] == {"prepare_screening": True, "submit_screening": False,
                                  "start_simulation": False, "overwrite_existing": False}
    assert transport.preparations == []


def test_confirmation_is_session_bound_expires_and_rechecks_local_plan(tmp_path):
    now = [100.0]
    transport = _ScreeningTransport()
    coordinator, transition = _screening_coordinator(tmp_path, transport, clock=lambda: now[0])
    token = coordinator.preview(_screening_request(), session_id="owner")["preview_token"]
    assert _screening_code(lambda: coordinator.confirm(
        {"preview_token": token}, session_id="intruder")) == "confirmation_invalid"
    campaign = tmp_path / "data/optimization/mot_2d/campaign"
    coordinator._plan = lambda campaign_id: (
        campaign, _manifest(), "a" * 40,
        {f"artifact-{index}": f"{index:064x}" for index in range(72)}, "f" * 64,
        {**transition, "campaign.json": "9" * 64},
    )
    assert _screening_code(lambda: coordinator.confirm(
        {"preview_token": token}, session_id="owner")) == "local_files_changed"
    assert transport.preparations == []

    coordinator, _ = _screening_coordinator(tmp_path, transport, clock=lambda: now[0])
    token = coordinator.preview(_screening_request(), session_id="owner")["preview_token"]
    now[0] = 401.0
    assert _screening_code(lambda: coordinator.confirm(
        {"preview_token": token}, session_id="owner")) == "confirmation_expired"
    assert transport.preparations == []


def test_successful_confirmation_is_replay_safe_and_does_not_submit(tmp_path):
    transport = _ScreeningTransport()
    coordinator, _ = _screening_coordinator(tmp_path, transport)
    token = coordinator.preview(_screening_request(), session_id="owner")["preview_token"]
    request = {"preview_token": token}
    first = coordinator.confirm(request, session_id="owner")
    second = coordinator.confirm(request, session_id="owner")
    assert first == second
    assert first["submitted_to_zeus"] is False and first["simulation_started"] is False
    assert len(transport.preparations) == 1
    assert set(transport.preparations[0]) == {
        "campaign", "commit", "prepared_files", "submission_key",
        "transition_files", "smoke_digest", "nonce"
    }


def test_concurrent_confirmation_performs_one_remote_transition(tmp_path):
    transport = _ScreeningTransport()
    coordinator, _ = _screening_coordinator(tmp_path, transport)
    token = coordinator.preview(_screening_request(), session_id="owner")["preview_token"]
    results, errors = [], []
    def confirm():
        try: results.append(coordinator.confirm({"preview_token": token}, session_id="owner"))
        except Exception as error: errors.append(error)
    threads = [threading.Thread(target=confirm) for _ in range(8)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=5)
    assert errors == [] and len(results) == 8
    assert len(transport.preparations) == 1


def test_remote_transition_receiver_has_no_submission_or_git_mutation_capability():
    source = (Path(__file__).parents[1] / "workflow_api/zeus_screening_remote.py").read_text()
    lowered = source.lower()
    assert "/usr/local/bin/qstat" in source
    assert all(command not in lowered for command in (
        "/usr/local/bin/qsub", "qdel", "git pull", "git checkout",
        "git switch", "git reset", "git merge", "git commit", "git push",
    ))
