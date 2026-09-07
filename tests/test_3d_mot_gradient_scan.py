from studies.scan_3d_mot_gradient import (
    DEFAULT_GRADIENTS_G_CM,
    DEFAULT_PARAMETER_PAIRS,
)


def test_gradient_scan_defaults_to_five_selected_laser_points():
    assert DEFAULT_PARAMETER_PAIRS == (
        "0.6:-1.65",
        "0.8:-1.85",
        "1.5:-2.5",
        "1.6:-2.6",
        "2.0:-2.7",
    )
    assert 10.0 in DEFAULT_GRADIENTS_G_CM
