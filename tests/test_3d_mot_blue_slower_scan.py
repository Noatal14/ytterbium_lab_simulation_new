import copy
from types import SimpleNamespace

import numpy as np

from config import MOT_3D_CONFIGURATIONS, MOT_3D_SIM_CONFIG
import simulations.mot_3d as mot_3d
from utils.RK4StHybridCustom import RK4StHybridCustom
from studies.scan_3d_mot_blue_slower import (
    _matrix,
    blue_exposure_diagnostics,
    parse_parameter_pairs,
    select_particle_shard,
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


def test_particle_shards_are_disjoint_and_reconstruct_selected_ensemble():
    states = np.arange(60).reshape(10, 6)
    shards = [select_particle_shard(states, 3, index) for index in range(3)]
    all_indices = np.concatenate([indices for _, indices in shards])

    assert sorted(all_indices.tolist()) == list(range(10))
    assert len(set(all_indices.tolist())) == len(states)
    for shard_states, indices in shards:
        np.testing.assert_array_equal(shard_states, states[indices])


def test_explicit_parameter_pairs_preserve_only_requested_unique_points():
    pairs = parse_parameter_pairs(["0.8:-1.75", "1.5:-2.5", "0.8:-1.75"])

    assert pairs == ((0.8, -1.75), (1.5, -2.5))


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


def test_blue_exposure_diagnostics_normalizes_center_blocked_donut_at_ring():
    profile = copy.deepcopy(MOT_3D_CONFIGURATIONS["angled_donut"])
    center = np.asarray(profile["center_position_m"], dtype=float)
    cutoff = profile["399"]["inner_cutoff_radius_m"]
    position = center + np.array([0.0, 1.01 * cutoff, 0.0])
    trajectory = SimpleNamespace(
        t=np.array([0.0]),
        y=np.concatenate([position, np.zeros(3)]).reshape(6, 1),
    )

    diagnostics = blue_exposure_diagnostics(
        [trajectory], profile, exposure_threshold_fraction=0.001
    )

    assert diagnostics["maximum_relative_intensity"]["max"] > 0.0
    assert diagnostics["exposed_particle_count"] == 1


def test_3d_solver_and_timestep_come_from_central_configuration():
    assert MOT_3D_SIM_CONFIG["dt_s"] == 1.0e-5
    assert MOT_3D_SIM_CONFIG["t_max_s"] == 25.0e-3
    assert MOT_3D_SIM_CONFIG["solver"] == "RK4StHybridCustom"
    assert mot_3d._configured_3d_solver() is RK4StHybridCustom
