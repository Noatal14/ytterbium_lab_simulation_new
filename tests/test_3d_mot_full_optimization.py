import math

import optuna

from config import MOT_3D_OPTIMIZATION_CONFIG
from studies.optimize_3d_mot_full import (
    _seed_parameters,
    _single_pass_reference_field_G,
    build_trial_profile,
    resolve_single_pass_detuning,
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
            assert "outer_cutoff_radius_m" not in profile["399"]
