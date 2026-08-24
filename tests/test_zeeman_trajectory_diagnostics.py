from types import SimpleNamespace

import numpy as np

from config import ZEEMAN_BEAM_DIRECTION, ZEEMAN_SIM_CONFIG
from studies.diagnose_zeeman_trajectories import (
    make_on_axis_initial_states,
    summarize_trajectories,
)


def test_on_axis_initial_states_point_toward_mot():
    states = make_on_axis_initial_states([250.0, 310.0])
    atom_direction = -ZEEMAN_BEAM_DIRECTION
    for state, speed in zip(states, [250.0, 310.0]):
        assert np.isclose(state[:3] @ ZEEMAN_BEAM_DIRECTION, 0.45)
        assert np.isclose(state[3:] @ atom_direction, speed)
        assert np.allclose(np.cross(state[3:], atom_direction), 0.0)


def test_summary_detects_cutoff_crossing():
    beam_direction = np.asarray(ZEEMAN_BEAM_DIRECTION)
    atom_direction = -beam_direction
    distances = np.array([0.45, 0.25, ZEEMAN_SIM_CONFIG["cutoff_distance_m"]])
    positions = distances[:, None] * beam_direction
    velocities = np.array([300.0, 180.0, 80.0])[:, None] * atom_direction
    result = SimpleNamespace(
        y=np.vstack((positions.T, velocities.T)), success=True, message="ok"
    )

    row = summarize_trajectories([result], [300.0])[0]

    assert row["reached_cutoff_plane"] is True
    assert np.isclose(row["axial_speed_at_exit_or_closest_point_m_s"], 80.0)
    assert np.isclose(row["maximum_radial_displacement_mm"], 0.0)
