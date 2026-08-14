import multiprocessing as mp
import numpy as np
from functools import partial
from atomsmltr.simulation.simulator import RK4St
from scipy import constants as csts
from atomsmltr.simulation.simulator.simbase import Pool, get_force_vec, SimRes
from tqdm import tqdm


class RK4StCustom(RK4St):
    def _stop_position_event(self, u, stop_position):
        x, y, z, _, _, _ = u.T
        position = np.array([x, y, z]).T
        in_stop = np.logical_or.reduce([zone.get_value(position) for zone in stop_position])
        return np.logical_not(in_stop)

    def _stop_speed_event(self, u, stop_speed):
        _, _, _, vx, vy, vz = u.T
        speed = np.array([vx, vy, vz]).T
        in_stop = np.logical_or.reduce([zone.get_value(speed) for zone in stop_speed])
        return np.logical_not(in_stop)

    def _integrate(self, u0, t):
        u = np.asanyarray(u0)
        stop_position, stop_speed = self.config.get_stop_zones()
        events = []
        if stop_position:
            events.append(partial(self._stop_position_event, stop_position=stop_position))
        if stop_speed:
            events.append(partial(self._stop_speed_event, stop_speed=stop_speed))

        t = np.asanyarray(t)
        t = np.sort(t)
        dt = np.diff(t)

        y = np.empty((*u.shape, len(t)))
        y[..., 0] = u
        stop = False
        u_none = np.full((6,), np.nan)

        for i, (tt, h) in enumerate(zip(t[1:], dt)):
            if events:
                for ev in events:
                    test = ev(u)
                    u[np.logical_not(test), :] = u_none
                    if not np.any(test):
                        stop = True
            if stop:
                break

            u = u + self._iterate(tt, u, h)
            y[..., i + 1] = u

        if stop:
            y = y[..., : i + 1]
            t = t[: i + 1]

        return SimRes(t=t, y=y)

    def _integrate_with_seed(self, task, t):
        """
        Integrate one trajectory using its own independent RNG stream.
        """
        u0, seed = task

        self.rng = np.random.default_rng(seed)

        return self.integrate(u0, t)

    def run(
        self,
        t: np.ndarray,
        u0_list: list = None,
        npools: int = 0,
        verbose: bool = False,
        chunksize: int = 1,
    ) -> list:
        """
        Run a batch of stochastic simulations.

        Each trajectory receives its own deterministic and independent RNG
        stream derived from ``self.seed_idx``. Therefore, for fixed initial
        conditions and seed, the results are independent of ``npools`` and
        ``chunksize``.
        """
        if u0_list is not None:
            self.u0_list = u0_list

        if not isinstance(npools, int):
            raise TypeError("'npools' should be an int")

        N = len(self.u0_list)

        # Generate one reproducible RNG stream per trajectory.
        master_seed = getattr(self, "seed_idx", 42)
        seed_sequence = np.random.SeedSequence(master_seed)
        child_sequences = seed_sequence.spawn(N)

        tasks = list(zip(self.u0_list, child_sequences))

        map_fun = partial(self._integrate_with_seed, t=t)

        # Parallel execution
        if npools:
            if verbose:
                res_list = []

                with Pool(npools) as p, tqdm(total=N) as pbar:
                    for res in p.imap(
                        map_fun,
                        tasks,
                        chunksize=chunksize,
                    ):
                        res_list.append(res)
                        pbar.update()
            else:
                with Pool(npools) as p:
                    res_list = p.map(
                        map_fun,
                        tasks,
                        chunksize=chunksize,
                    )

        # Serial execution
        else:
            res_list = []
            iterable = tqdm(tasks) if verbose else tasks

            for task in iterable:
                res_list.append(map_fun(task))

        return res_list
