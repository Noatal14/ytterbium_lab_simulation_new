import numpy as np

from graphs_scripts.plot_donut_capture_phase_space import (
    binned_capture_fraction,
    derived_input_features,
)


def test_derived_input_features_use_transverse_components():
    states = np.array([[3e-3, 4e-3, 0.2, 3.0, 4.0, 12.0]])
    features = derived_input_features(states)

    np.testing.assert_allclose(features["r_perp_mm"], [5.0])
    np.testing.assert_allclose(features["v_perp_m_s"], [5.0])
    np.testing.assert_allclose(features["speed_m_s"], [13.0])
    np.testing.assert_allclose(
        features["angle_deg"], [np.degrees(np.arctan2(5.0, 12.0))]
    )


def test_binned_capture_fraction_reports_counts_and_uncertainty():
    centers, fraction, counts, error = binned_capture_fraction(
        [0.1, 0.2, 0.6, 0.8],
        [True, False, True, True],
        [0.0, 0.5, 1.0],
    )

    np.testing.assert_allclose(centers, [0.25, 0.75])
    np.testing.assert_allclose(fraction, [0.5, 1.0])
    np.testing.assert_array_equal(counts, [2, 2])
    np.testing.assert_allclose(error, [np.sqrt(0.125), 0.0])
