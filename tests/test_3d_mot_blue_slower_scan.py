import copy
from types import SimpleNamespace

import numpy as np

from config import MOT_3D_CONFIGURATIONS
import simulations.mot_3d as mot_3d
from studies.scan_3d_mot_blue_slower import (
    _matrix,
    blue_exposure_diagnostics,
    slowing_rank_key,
)


def _record(detuning, s0, slow, eligible, residence, speed):
    return {
        "profile": "profile",
        "detuning_gamma": detuning,
        "s0": s0,
        "entered_capture_region_count": 10,
        "slow_inside_count": slow,
        "minimum_residence_met_count": residence,
        "capture_eligible_ever_count": eligible,
        "median_minimum_speed_inside_m_s": speed,
    }


def test_slowing_rank_prioritizes_capture_then_slow_count_then_speed():
    records = [
        _record(-1.0, 0.3, slow=8, eligible=0, residence=0, speed=4.0),
        _record(-2.0, 0.3, slow=1, eligible=1, residence=1, speed=8.0),
    ]
    assert max(records, key=slowing_rank_key) is records[1]


def test_scan_matrix_maps_sorted_physical_axes_to_rows_and_columns():
    records = [
        _record(-2.0, 0.3, slow=1, eligible=0, residence=0, speed=8.0),
        _record(-1.0, 0.3, slow=2, eligible=0, residence=0, speed=7.0),
        _record(-2.0, 1.0, slow=3, eligible=0, residence=0, speed=6.0),
        _record(-1.0, 1.0, slow=4, eligible=0, residence=0, speed=5.0),
    ]
    matrix = _matrix(
        records,
        "profile",
        (-2.0, -1.0),
        (0.3, 1.0),
        "slow_inside_count",
    )
    assert matrix.tolist() == [[1.0, 2.0], [3.0, 4.0]]


def test_blue_exposure_diagnostics_uses_actual_beams_and_lab_trajectory():
    profile = copy.deepcopy(MOT_3D_CONFIGURATIONS["angled_sequential"])
    crossing = np.asarray(profile["center_position_m"], dtype=float)
    crossing += np.asarray(profile["399"]["center_offset_m"], dtype=float)
    times = np.array([0.0, 1.0e-3, 2.0e-3])
    positions = np.column_stack(
        [
            np.zeros(3),
            np.zeros(3),
            crossing[2] + np.array([-1.0e-3, 0.0, 1.0e-3]),
        ]
    )
    velocities = np.column_stack(
        [np.zeros(3), np.zeros(3), np.array([10.0, 9.0, 8.0])]
    )
    trajectory = SimpleNamespace(t=times, y=np.vstack([positions.T, velocities.T]))

    diagnostics = blue_exposure_diagnostics(
        [trajectory], profile, exposure_threshold_fraction=0.01
    )

    assert diagnostics["exposed_particle_count"] == 1
    assert diagnostics["maximum_relative_intensity"]["max"] == 1.0
    assert diagnostics["exposure_time_s"]["median"] == 2.0e-3
    assert diagnostics["delta_vz_during_exposure_m_s"]["median"] == -2.0


def test_3d_integrator_limits_internal_step_to_resolve_narrow_beams(monkeypatch):
    class FakeIntegrator:
        def __init__(self, config, **kwargs):
            self.config = config
            self.solve_ivp_args = kwargs

    monkeypatch.setattr(mot_3d, "ScipyIVP_3DCustom", FakeIntegrator)
    marker_config = object()
    integrator = mot_3d._make_3d_integrator(
        marker_config, maximum_step_s=1.0e-5
    )

    assert integrator.config is marker_config
    assert integrator.solve_ivp_args["max_step"] == 1.0e-5
