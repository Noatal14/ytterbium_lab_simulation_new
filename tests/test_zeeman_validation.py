import numpy as np

from studies.validate_zeeman_configuration import analyze_zeeman_configuration


def test_active_zeeman_configuration_has_consistent_structure_and_directions():
    summary, profiles = analyze_zeeman_configuration(num_points=201)

    assert summary["checks"]["magnet_arrays_have_equal_length"]
    assert summary["checks"]["magnet_profile_has_20_rings"]
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
