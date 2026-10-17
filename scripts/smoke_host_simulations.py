"""Tiny real seeded integrations, serial vs spawn workers, without saved runs."""
import json
import multiprocessing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import numpy as np
    from simulations.zeeman import zeeman_simulation
    from simulations.mot_2d import mot_simulation
    from simulations.mot_3d import mot_3d_simulation

    states = np.array([[0., 0., 0., 0., 0., .1], [1e-4, 0., 0., 0., 0., .2]])
    cases = {
        'zeeman': lambda workers: zeeman_simulation(N_particles=2, npools=workers, seed=713, dt=4e-5, t_max_s=8e-5)[0],
        'mot_2d': lambda workers: mot_simulation(states.copy(), npools=workers, seed=713, dt=4e-5, t_max_s=8e-5)[0],
        'mot_3d': lambda workers: mot_3d_simulation(states.copy(), npools=workers, seed=713, dt=1e-6, t_max=2e-6)[0],
    }
    summary = {}
    for name, integrate in cases.items():
        serial, parallel = integrate(0), integrate(2)
        assert len(serial) == len(parallel) == 2
        for first, second in zip(serial, parallel):
            assert np.isfinite(first.y).all() and np.isfinite(second.y).all()
            np.testing.assert_allclose(first.y, second.y, rtol=1e-12, atol=1e-15)
        summary[name] = {'trajectories': 2, 'serial_matches_spawn': True,
                         'final_states': [r.y[:, -1].tolist() for r in serial]}
    print('HOST_SIMULATION_SMOKE=' + json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    multiprocessing.freeze_support()
    multiprocessing.set_start_method('spawn', force=True)
    main()
