import numpy as np
import json
from types import SimpleNamespace

from config import ZEEMAN_MAGNET_PROFILES
from studies.estimate_oven_flux import estimate_oven_flux
from studies.full_thermal_zeeman_flux import (
    DEFAULT_OUTPUT_DIR,
    clopper_pearson_interval,
    field_config,
    output_dir_for_profile,
    resolve_magnet_profile,
    summarize,
)


def test_oven_flux_matches_design_scale():
    result = estimate_oven_flux()

    assert np.isclose(result["vapor_pressure_pa"], 0.099876, rtol=1e-4)
    assert np.isclose(result["yb171_total_flux_s"], 7.386e13, rtol=1e-3)


def test_exact_binomial_interval_contains_observed_fraction():
    low, high = clopper_pearson_interval(70, 10_000)
    assert low < 0.007 < high


def test_full_thermal_profile_is_resolved_from_recorded_field_arrays():
    radii, positions, tilts = ZEEMAN_MAGNET_PROFILES["active"]
    parameters = {
        "zeeman_field_config": {
            "radii_m": radii,
            "positions_m": positions,
            "tilt_angles_deg": tilts,
        }
    }
    assert resolve_magnet_profile(parameters) == "active"


def test_full_thermal_field_config_selects_corrected_profile():
    parameters = {"zeeman_field_config": field_config(
        "corrected_projectant_19ring_20261005"
    )}
    assert resolve_magnet_profile(parameters) == (
        "corrected_projectant_19ring_20261005"
    )


def test_profile_name_must_match_embedded_field_arrays():
    parameters = {
        "resolved_zeeman_magnet_profile": (
            "corrected_projectant_19ring_20261005"
        ),
        "zeeman_field_config": field_config("active"),
    }
    with np.testing.assert_raises_regex(ValueError, "does not match"):
        resolve_magnet_profile(parameters)


def test_unregistered_field_arrays_are_rejected():
    parameters = {"zeeman_field_config": field_config("active")}
    parameters["zeeman_field_config"]["radii_m"] = list(
        parameters["zeeman_field_config"]["radii_m"]
    )
    parameters["zeeman_field_config"]["radii_m"][0] += 1e-6
    with np.testing.assert_raises_regex(ValueError, "registered profile"):
        resolve_magnet_profile(parameters)


def test_absolute_historical_path_is_isolated_for_corrected_profile():
    profile = "corrected_projectant_19ring_20261005"
    relative = output_dir_for_profile(DEFAULT_OUTPUT_DIR, profile)
    absolute = output_dir_for_profile(DEFAULT_OUTPUT_DIR.resolve(), profile)
    assert relative == absolute
    assert relative != DEFAULT_OUTPUT_DIR


def test_summary_rejects_requested_profile_mismatch(tmp_path):
    metadata = {
        "parameters": {
            "seed": 1,
            "n_initial_atoms": 10,
            "full_angular_distribution": True,
            "angular_broadening_factor": 3.0,
            "zeeman_field_config": field_config("active"),
        },
        "n_survivors": 1,
        "survival_fraction": 0.1,
        "elapsed_seconds": 1.0,
        "output_sha256": "test",
        "software": {"git_commit": "test"},
    }
    (tmp_path / "full_thermal_zeeman_n10_seed1.json").write_text(
        json.dumps(metadata)
    )
    args = SimpleNamespace(
        output_dir=str(tmp_path),
        magnet_profile="corrected_projectant_19ring_20261005",
        temperature_c=400.0,
    )
    with np.testing.assert_raises_regex(ValueError, "Requested profile"):
        summarize(args)
