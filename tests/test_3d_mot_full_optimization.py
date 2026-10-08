import math
from types import SimpleNamespace

import optuna
import pytest

from config import MOT_3D_OPTIMIZATION_CONFIG
from studies.mot_3d.discovery.optimize import (
    _seed_parameters,
    _single_pass_reference_field_G,
    build_trial_profile,
    resolve_single_pass_detuning,
    remaining_complete_trials,
    lock_study_design,
    fail_stale_running_trials,
    acquire_worker_lock,
    _design_identity,
)


def test_reference_single_pass_seed_has_no_zeeman_delta():
    detuning, z_slow_m, field_G = resolve_single_pass_detuning(
        anchor_gamma=-2.75,
        gradient_G_cm=2.5,
        crossing_z_m=-0.050,
        waist_m=0.0075,
    )
    assert math.isclose(detuning, -2.75)
    assert math.isclose(z_slow_m, -0.05825)
    assert math.isclose(field_G, _single_pass_reference_field_G())


def test_larger_slowing_field_makes_blue_detuning_less_red():
    reference, _, _ = resolve_single_pass_detuning(-2.75, 2.5, -0.050, 0.0075)
    shifted, _, _ = resolve_single_pass_detuning(-2.75, 3.0, -0.050, 0.0075)
    assert shifted > reference


def test_seed_profiles_respect_confirmed_search_bounds():
    common = MOT_3D_OPTIMIZATION_CONFIG["common"]
    for family in ("angled_donut", "single_pass"):
        parameters = _seed_parameters(family, 0)
        profile, _, _ = build_trial_profile(
            family, optuna.trial.FixedTrial(parameters)
        )
        assert common["green_waist_m_bounds"][0] <= profile["556"]["waist_m"] <= common["green_waist_m_bounds"][1]
        assert common["blue_waist_m_bounds"][0] <= profile["399"]["waist_m"] <= common["blue_waist_m_bounds"][1]
        assert profile["399"]["s0"] <= 1.5
        if family == "angled_donut":
            split = profile["399"]["inner_cutoff_radius_m"]
            assert profile["556"]["outer_cutoff_radius_m"] == split
            assert profile["399"]["outer_cutoff_radius_m"] == 0.005


def test_resume_budget_counts_only_complete_trials():
    states = [
        optuna.trial.TrialState.COMPLETE,
        optuna.trial.TrialState.FAIL,
        optuna.trial.TrialState.RUNNING,
    ]
    assert remaining_complete_trials(3, states) == 2
    with pytest.raises(RuntimeError, match="exceeding target"):
        remaining_complete_trials(0, states)


def test_optuna_design_lock_rejects_incompatible_resume(tmp_path):
    study = optuna.create_study(
        storage=f"sqlite:///{tmp_path / 'study.db'}",
        study_name="locked",
        load_if_exists=True,
    )
    lock_study_design(study, {"family": "angled_donut"}, "design-a")
    lock_study_design(study, {"family": "angled_donut"}, "design-a")
    with pytest.raises(RuntimeError, match="incompatible scientific design"):
        lock_study_design(study, {"family": "single_pass"}, "design-b")


def test_interrupted_running_trial_is_failed_deterministically(tmp_path):
    study = optuna.create_study(
        storage=f"sqlite:///{tmp_path / 'study.db'}",
        study_name="interrupted",
        load_if_exists=True,
    )
    study.ask()
    assert study.trials[0].state == optuna.trial.TrialState.RUNNING
    assert fail_stale_running_trials(study) == 1
    assert study.trials[0].state == optuna.trial.TrialState.FAIL
    assert fail_stale_running_trials(study) == 0


def test_worker_lock_rejects_concurrent_owner(tmp_path):
    first = acquire_worker_lock(tmp_path)
    with pytest.raises(RuntimeError, match="Another process owns worker lock"):
        acquire_worker_lock(tmp_path)
    first.close()
    recovered = acquire_worker_lock(tmp_path)
    recovered.close()


def test_design_identity_changes_with_frozen_input_sha():
    args = SimpleNamespace(
        family="angled_donut", worker_index=0, sampler_seed=1,
        startup_trials=2, selection_seed=3, simulation_seed=4,
        particles_per_ensemble=5, dt=1e-6, t_max=0.1,
        input_role="discovery",
    )
    manifest = {
        "provenance": {"git_commit": "abc", "physical_model_sha256": "model"},
        "upstream_2d_campaign": {
            "campaign_sha256": "campaign", "final_report_sha256": "report"
        },
        "input_roles": {"discovery": [{"path": "same.npy", "sha256": "a"}]},
    }
    _, first = _design_identity(args, [], manifest)
    manifest["input_roles"]["discovery"][0]["sha256"] = "b"
    _, second = _design_identity(args, [], manifest)
    assert first != second
