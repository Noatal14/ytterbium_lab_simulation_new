import numpy as np
import pytest

import studies.validate_zeeman_configuration as zeeman_validation
from studies.validate_zeeman_configuration import analyze_zeeman_configuration


def test_active_zeeman_configuration_has_consistent_structure_and_directions():
    summary, profiles = analyze_zeeman_configuration(
        num_points=201,
        magnet_profile="active",
        expected_ring_count=20,
    )

    assert summary["checks"]["magnet_arrays_have_equal_length"]
    assert summary["checks"]["magnet_ring_count_matches_expected"]
    assert summary["evaluated_magnet_profile"] == "active"
    assert summary["checks"]["magnet_positions_are_strictly_increasing"]
    assert summary["checks"]["laser_is_antiparallel_to_atoms"]
    assert summary["checks"]["laser_detuning_is_red"]
    assert summary["checks"]["sampled_field_is_finite"]
    assert summary["checks"]["polarization_is_normalized"]
    assert np.all(np.isfinite(profiles["dominant_resonant_speed_m_s"]))
    assert summary["diagnostics"]["median_dominant_polarization_weight"] > 0.99


def test_active_zeeman_entry_resonance_is_near_design_capture_speed():
    summary, _ = analyze_zeeman_configuration(num_points=401)
    assert summary["checks"]["entry_resonance_matches_target"]


def test_corrected_zeeman_profile_validates_as_19_rings():
    summary, _ = analyze_zeeman_configuration(
        num_points=201,
        magnet_profile="corrected_projectant_19ring_20261005",
        expected_ring_count=19,
    )

    assert summary["checks"]["magnet_ring_count_matches_expected"]
    assert summary["evaluated_magnet_profile"] == (
        "corrected_projectant_19ring_20261005"
    )
    assert summary["configuration"]["magnet_ring_count"] == 19


def test_corrected_profile_rejects_wrong_external_ring_expectation():
    summary, _ = analyze_zeeman_configuration(
        num_points=201,
        magnet_profile="corrected_projectant_19ring_20261005",
        expected_ring_count=20,
    )

    assert not summary["checks"]["magnet_ring_count_matches_expected"]
    assert summary["status"] == "FAIL"


def test_default_ring_expectation_is_independent_of_profile_array_length(monkeypatch):
    radii, positions, tilts = zeeman_validation.ZEEMAN_MAGNET_PROFILES["active"]
    monkeypatch.setitem(
        zeeman_validation.ZEEMAN_MAGNET_PROFILES,
        "active",
        (radii[:-1], positions[:-1], tilts[:-1]),
    )

    summary, _ = analyze_zeeman_configuration(
        num_points=201,
        magnet_profile="active",
    )

    assert summary["configuration"]["expected_magnet_ring_count"] == 20
    assert summary["configuration"]["magnet_ring_count"] == 19
    assert not summary["checks"]["magnet_ring_count_matches_expected"]
    assert summary["status"] == "FAIL"


@pytest.mark.parametrize("expected", [0, -1, 19.5, True])
def test_expected_ring_count_must_be_a_positive_integer(expected):
    with pytest.raises(ValueError, match="positive integer"):
        analyze_zeeman_configuration(
            num_points=201,
            expected_ring_count=expected,
        )


def test_unknown_zeeman_profile_is_rejected():
    with pytest.raises(ValueError, match="Unknown Zeeman magnet profile"):
        analyze_zeeman_configuration(num_points=201, magnet_profile="missing")
