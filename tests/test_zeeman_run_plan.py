from dataclasses import FrozenInstanceError

import pytest

import workflow_api.zeeman_run_plan as run_plan
from lab_setup.numerical_policy import NUMERICAL_POLICY_SHA256
from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    LABORATORY_SPEC_SHA256,
)
from workflow_api.run_records import record_sha256, validate_record
from workflow_api.zeeman_run_plan import (
    build_zeeman_run_plan,
    validate_zeeman_run_request,
)


REQUEST = {
    "particle_count": 1_000,
    "seed": 123,
    "retain_particle_states": True,
    "execution_mode": "local",
}
CONTEXT = {
    "run_id": "zeeman-test-001",
    "git_revision": "a" * 40,
    "created_utc": "2026-10-11T09:00:00+00:00",
}


def test_request_accepts_only_the_four_approved_editable_fields():
    value = validate_zeeman_run_request(REQUEST)
    assert value.particle_count == 1_000
    assert value.seed == 123
    assert value.retain_particle_states is True
    assert value.execution_mode == "local"


@pytest.mark.parametrize(
    "change",
    [
        {"particle_count": 0},
        {"particle_count": 50_001},
        {"particle_count": True},
        {"seed": -1},
        {"seed": 2**32},
        {"seed": True},
        {"retain_particle_states": 1},
        {"execution_mode": "shell"},
    ],
)
def test_request_rejects_invalid_values(change):
    request = {**REQUEST, **change}
    with pytest.raises(ValueError):
        validate_zeeman_run_request(request)


def test_request_rejects_missing_or_extra_fields():
    with pytest.raises(ValueError):
        validate_zeeman_run_request({key: value for key, value in REQUEST.items() if key != "seed"})
    with pytest.raises(ValueError):
        validate_zeeman_run_request({**REQUEST, "command": "qsub attacker.pbs"})


@pytest.mark.parametrize("mode,workers", [("local", 8), ("zeus", 200)])
@pytest.mark.parametrize("retain", [False, True])
def test_plan_resolves_canonical_configuration_and_valid_d2_records(mode, workers, retain):
    plan = build_zeeman_run_plan(
        {**REQUEST, "execution_mode": mode, "retain_particle_states": retain},
        **CONTEXT,
    )
    records = plan.storage_records()
    for kind in ("run", "configuration", "inputs", "status"):
        validate_record(kind, records[kind])
    assert plan.run["configuration_sha256"] == record_sha256(
        "configuration", records["configuration"]
    )
    assert plan.run["inputs_sha256"] == record_sha256("inputs", records["inputs"])
    assert plan.run["suitability"] == "individual_only"
    assert plan.configuration["laboratory_spec"]["sha256"] == LABORATORY_SPEC_SHA256
    assert plan.configuration["numerical_policy"]["sha256"] == NUMERICAL_POLICY_SHA256
    resolved = plan.configuration["resolved"]
    assert resolved["zeeman"]["magnet_profile_name"] == CANONICAL_ZEEMAN_PROFILE_NAME
    assert resolved["numerical_policy"]["solver"] == "RK4StCustom"
    assert resolved["numerical_policy"]["dt_s"] == pytest.approx(40e-6)
    assert resolved["execution"]["workers"] == workers
    assert plan.review.locked_settings["workers"] == workers
    assert plan.status["state"] == "configured"
    assert plan.status["execution"]["mode"] == mode

    paths = {row["path"]: row["kind"] for row in plan.run["outputs"]}
    if retain:
        assert paths["results/states.npy"] == "particle_states"
        assert "results/state_retention_receipt.json" not in paths
        assert plan.review.output_disposition == "retain_survivor_states"
    else:
        assert paths["results/state_retention_receipt.json"] == "retention_receipt"
        assert "results/states.npy" not in paths
        assert plan.review.output_disposition == "discard_survivor_states_after_summary"


def test_plan_is_deterministic_and_deeply_immutable():
    first = build_zeeman_run_plan(REQUEST, **CONTEXT)
    second = build_zeeman_run_plan(dict(REQUEST), **CONTEXT)
    assert first.plan_sha256 == second.plan_sha256
    assert len(first.plan_sha256) == 64
    with pytest.raises(TypeError):
        first.configuration["resolved"]["simulation"]["seed"] = 9
    with pytest.raises(FrozenInstanceError):
        first.request.seed = 9


def test_context_is_validated_by_the_canonical_record_codec():
    with pytest.raises(ValueError):
        build_zeeman_run_plan(REQUEST, **{**CONTEXT, "run_id": "../escape"})
    with pytest.raises(ValueError):
        build_zeeman_run_plan(REQUEST, **{**CONTEXT, "git_revision": "main"})
    with pytest.raises(ValueError):
        build_zeeman_run_plan(REQUEST, **{**CONTEXT, "created_utc": "tomorrow"})


def test_plan_detects_active_configuration_drift(monkeypatch):
    monkeypatch.setattr(run_plan, "ACTIVE_ZEEMAN_MAGNET_PROFILE", "other")
    with pytest.raises(RuntimeError, match="contradicts bundled policy"):
        build_zeeman_run_plan(REQUEST, **CONTEXT)


def test_plan_detects_canonical_field_array_drift_even_when_name_matches(monkeypatch):
    changed = {key: list(value) for key, value in run_plan.ZEEMAN_FIELD_CONFIG.items()}
    changed["radii_m"][0] += 1e-12
    monkeypatch.setattr(run_plan, "ZEEMAN_FIELD_CONFIG", changed)
    with pytest.raises(RuntimeError, match="contradicts bundled policy"):
        build_zeeman_run_plan(REQUEST, **CONTEXT)


@pytest.mark.parametrize("key", ["dt_s", "t_max_s"])
def test_plan_detects_active_numerical_drift_exactly(monkeypatch, key):
    changed = dict(run_plan.ZEEMAN_SIM_CONFIG)
    changed[key] = float(changed[key]) + 1e-15
    monkeypatch.setattr(run_plan, "ZEEMAN_SIM_CONFIG", changed)
    with pytest.raises(RuntimeError, match="contradicts bundled policy"):
        build_zeeman_run_plan(REQUEST, **CONTEXT)


def test_resolved_laser_and_field_freeze_complete_model_semantics():
    plan = build_zeeman_run_plan(REQUEST, **CONTEXT)
    zeeman = plan.storage_records()["configuration"]["resolved"]["zeeman"]
    assert zeeman["laser"] == run_plan.resolved_zeeman_laser_parameters(
        **run_plan.ZEEMAN_LASER_CONFIG
    )
    assert zeeman["laser"]["waist_m"] == pytest.approx(0.007)
    assert zeeman["laser"]["polarization"] == "CircularRight"
    assert zeeman["laser"]["direction_type"] == "vector"
    assert len(zeeman["laser"]["direction"]) == 3
    assert zeeman["field"]["magnets_per_ring"] == 8
    assert zeeman["field"]["magnet_dimensions_m"] == [0.005, 0.005, 0.005]
    assert zeeman["field"]["magnet_polarization_T"] == pytest.approx(-1.24)
    assert zeeman["field"]["tilt_input_sign"] == -1


def test_local_and_zeus_plans_have_identical_science():
    local = build_zeeman_run_plan(REQUEST, **CONTEXT)
    zeus = build_zeeman_run_plan(
        {**REQUEST, "execution_mode": "zeus"}, **CONTEXT
    )
    local_resolved = local.storage_records()["configuration"]["resolved"]
    zeus_resolved = zeus.storage_records()["configuration"]["resolved"]
    local_execution = local_resolved.pop("execution")
    zeus_execution = zeus_resolved.pop("execution")
    assert local_resolved == zeus_resolved
    assert local_execution == {"mode": "local", "workers": 8}
    assert zeus_execution == {"mode": "zeus", "workers": 200}


def test_planning_has_no_filesystem_process_network_or_zeus_effects(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("planning attempted an external effect")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("pathlib.Path.write_bytes", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    plan = build_zeeman_run_plan(REQUEST, **CONTEXT)
    assert plan.status["state"] == "configured"
