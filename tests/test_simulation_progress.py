import types

import numpy as np

from utils.RK4StCustom import RK4StCustom
from utils.ScipyIVP_3DCustom import ScipyIVP_3DCustom


def test_scipy_runner_reports_completed_trajectories_serially():
    simulator = object.__new__(ScipyIVP_3DCustom)
    simulator.u0_list = [np.zeros(6), np.ones(6), np.full(6, 2.0)]
    simulator.integrate = types.MethodType(lambda _self, state, _time: state, simulator)
    progress = []

    result = simulator.run(
        np.array([0.0, 1.0]),
        verbose=False,
        progress_callback=lambda completed, total: progress.append((completed, total)),
    )

    assert len(result) == 3
    assert progress == [(0, 3), (1, 3), (2, 3), (3, 3)]


def test_stochastic_runner_reports_completed_trajectories_serially():
    simulator = object.__new__(RK4StCustom)
    simulator.u0_list = [np.zeros(6), np.ones(6)]
    simulator.seed_idx = 42
    simulator.trajectory_seed_sequences = None
    simulator._integrate_with_seed = types.MethodType(
        lambda _self, task, _time: task[0], simulator
    )
    progress = []

    result = simulator.run(
        np.array([0.0, 1.0]),
        verbose=False,
        progress_callback=lambda completed, total: progress.append((completed, total)),
    )

    assert len(result) == 2
    assert progress == [(0, 2), (1, 2), (2, 2)]
