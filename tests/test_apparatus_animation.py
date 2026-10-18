"""Trajectory display helpers must not invent states at stage handoffs."""
from types import SimpleNamespace

import numpy as np

from graphs_scripts.animate_full_apparatus import (
    ZEEMAN_BEAM_DIRECTION, compact, crossing_time, zeeman_stage,
)


def test_compact_keeps_exact_handoff_and_drops_later_samples():
    times = np.linspace(0., 1., 10001)
    states = np.tile(times, (6, 1))
    endpoint = np.full(6, .37501)
    t, y = compact(SimpleNamespace(t=times, y=states), endpoint, .37501)
    assert len(t) <= 6001
    assert np.all(np.diff(t) > 0)
    assert t[-1] == .37501
    np.testing.assert_array_equal(y[-1], endpoint)
    assert t[0] == 0.


def test_compact_removes_terminated_nan_samples():
    states = np.ones((6, 3)); states[:, -1] = np.nan
    t, y = compact(SimpleNamespace(t=np.array([0., 1., 2.]), y=states))
    np.testing.assert_array_equal(t, [0., 1.])
    assert np.isfinite(y).all()


def test_zeeman_handoff_time_matches_interpolated_state():
    direction = np.asarray(ZEEMAN_BEAM_DIRECTION)
    cutoff = zeeman_stage.ZEEMAN_SIM_CONFIG['cutoff_distance_m']
    first = np.r_[direction*(cutoff+.02), -direction*10]
    last = np.r_[direction*(cutoff-.01), -direction*10]
    result = SimpleNamespace(t=np.array([.001, .004]), y=np.column_stack([first, last]))
    state = first+(2/3)*(last-first)
    np.testing.assert_allclose(crossing_time(result, state), .003, rtol=0, atol=1e-15)
