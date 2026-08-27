import pytest

from utils.RK4StPhotonDiagnosticCustom import (
    _empty_laser_statistics,
    update_laser_statistics,
)


def test_update_laser_statistics_tracks_frequency_and_photon_weight():
    statistics = _empty_laser_statistics()

    update_laser_statistics(statistics, [0.0, 2.0, 10.0, 20.0])

    assert statistics["evaluations"] == 4
    assert statistics["sum_expected_photons"] == pytest.approx(32.0)
    assert statistics["minimum_expected_photons"] == 0.0
    assert statistics["maximum_expected_photons"] == 20.0
    assert statistics["below_1_evaluations"] == 1
    assert statistics["below_5_evaluations"] == 2
    assert statistics["below_10_evaluations"] == 2
    assert statistics["below_15_evaluations"] == 3
    assert statistics["below_15_expected_photons"] == pytest.approx(12.0)


def test_update_laser_statistics_ignores_invalid_values():
    statistics = _empty_laser_statistics()

    update_laser_statistics(statistics, [-1.0, float("nan"), float("inf")])

    assert statistics == _empty_laser_statistics()
