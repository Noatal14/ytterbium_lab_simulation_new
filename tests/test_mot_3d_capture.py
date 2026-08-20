from types import SimpleNamespace

import numpy as np

from simulations.mot_3d import extract_3d_mot_captured


def make_trajectory(positions, velocities, times):
    states = np.vstack((np.asarray(positions).T, np.asarray(velocities).T))
    return SimpleNamespace(t=np.asarray(times), y=states)


def test_capture_requires_final_residence_and_low_speed():
    times = [0.0, 0.005, 0.010]
    inside_positions = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    slow = make_trajectory(inside_positions, [[0, 0, 0.2]] * 3, times)
    fast = make_trajectory(inside_positions, [[0, 0, 2.0]] * 3, times)

    states, indices = extract_3d_mot_captured(
        [slow, fast],
        center_m=(0, 0, 0),
        capture_radius_m=0.01,
        minimum_residence_time_s=0.005,
        maximum_final_speed_m_s=1.0,
    )

    assert indices == [0]
    assert states.shape == (1, 6)


def test_capture_requires_continuous_residence_at_end():
    trajectory = make_trajectory(
        [[0, 0, 0], [0.02, 0, 0], [0, 0, 0]],
        [[0, 0, 0.1]] * 3,
        [0.0, 0.009, 0.010],
    )

    states, indices = extract_3d_mot_captured(
        [trajectory],
        center_m=(0, 0, 0),
        capture_radius_m=0.01,
        minimum_residence_time_s=0.005,
        maximum_final_speed_m_s=1.0,
    )

    assert indices == []
    assert states.shape == (0, 6)
