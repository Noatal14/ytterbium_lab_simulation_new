import numpy as np

from studies.estimate_oven_flux import estimate_oven_flux
from studies.full_thermal_zeeman_flux import clopper_pearson_interval


def test_oven_flux_matches_design_scale():
    result = estimate_oven_flux()

    assert np.isclose(result["vapor_pressure_pa"], 0.099876, rtol=1e-4)
    assert np.isclose(result["yb171_total_flux_s"], 7.386e13, rtol=1e-3)


def test_exact_binomial_interval_contains_observed_fraction():
    low, high = clopper_pearson_interval(70, 10_000)
    assert low < 0.007 < high
