import copy
import multiprocessing as mp
import numpy as np

from functools import partial

from atomsmltr.simulation.simulator import RK4St
from atomsmltr.simulation.simulator.simbase import Pool, SimRes
from tqdm import tqdm


# ============================================================
# Worker-local state
# ============================================================

_WORKER_SIM = None
_WORKER_T = None


def _init_worker(sim, t):
    """
    Initialize worker-local simulation state.

    The simulator object and time grid are transferred to each worker once
    when the multiprocessing pool is created, instead of being serialized
    again for every individual trajectory.
    """
    global _WORKER_SIM, _WORKER_T

    _WORKER_SIM = sim
    _WORKER_T = t


def _worker_integrate(task):
    """
    Integrate one stochastic trajectory inside a worker.

    Parameters
    ----------
    task : tuple
        (u0, seed_sequence)

    Returns
    -------
    SimRes
        Simulation result for this trajectory.
    """
    global _WORKER_SIM, _WORKER_T

    u0, seed_sequence = task

    # Each trajectory gets its own deterministic and independent RNG stream.
    _WORKER_SIM.rng = np.random.default_rng(seed_sequence)

    return _WORKER_SIM.integrate(u0, _WORKER_T)


# ============================================================
# Custom stochastic RK4 simulator
# ============================================================

class RK4StCustom(RK4St):

    def _stop_position_event(self, u, stop_position):
        x, y, z, _, _, _ = u.T

        position = np.array([x, y, z]).T

        in_stop = np.logical_or.reduce(
            [
                zone.get_value(position)
                for zone in stop_position
            ]
        )

        return np.logical_not(in_stop)

    def _stop_speed_event(self, u, stop_speed):
        _, _, _, vx, vy, vz = u.T

        speed = np.array([vx, vy, vz]).T

        in_stop = np.logical_or.reduce(
            [
                zone.get_value(speed)
                for zone in stop_speed
            ]
        )

        return np.logical_not(in_stop)

    def _integrate(self, u0, t):
        """
        Integrate one trajectory using the custom stochastic RK4 scheme.
        """

        u = np.asanyarray(u0)

        # ----------------------------------------------------
        # Stop events
        # ----------------------------------------------------

        stop_position, stop_speed = self.config.get_stop_zones()

        events = []

        if stop_position:
            events.append(
                partial(
                    self._stop_position_event,
                    stop_position=stop_position,
                )
            )

        if stop_speed:
            events.append(
                partial(
                    self._stop_speed_event,
                    stop_speed=stop_speed,
                )
            )

        # ----------------------------------------------------
        # Time grid
        # ----------------------------------------------------

        t = np.asanyarray(t)
        t = np.sort(t)

        dt = np.diff(t)

        # ----------------------------------------------------
        # Allocate trajectory storage
        # ----------------------------------------------------

        y = np.empty((*u.shape, len(t)))
        y[..., 0] = u

        stop = False

        u_none = np.full((6,), np.nan)

        # ----------------------------------------------------
        # Integration
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Trim trajectory after stopping
        # ----------------------------------------------------

        if stop:
            y = y[..., : i + 1]
            t = t[: i + 1]

        return SimRes(
            t=t,
            y=y,
        )

    def _integrate_with_seed(self, task, t):
        """
        Serial equivalent of the multiprocessing worker function.

        Used when npools == 0.
        """
        u0, seed_sequence = task

        self.rng = np.random.default_rng(seed_sequence)

        return self.integrate(u0, t)

    def run(
        self,
        t: np.ndarray,
        u0_list: list = None,
        npools: int = 0,
        verbose: bool = False,
    ) -> list:
        """
        Run a batch of stochastic trajectories.

        Each trajectory receives its own deterministic and independent RNG
        stream derived from ``self.seed_idx``.

        The RNG stream assigned to trajectory i therefore does not depend on:

        - the worker that evaluates it,
        - npools,
        - multiprocessing scheduling.

        In the parallel case, the simulator object and time grid are
        initialized once per worker. Individual tasks therefore contain only
        the initial state and the trajectory-specific RNG seed.
        """

        # ----------------------------------------------------
        # Initial conditions
        # ----------------------------------------------------

        if u0_list is not None:
            self.u0_list = u0_list

        if not isinstance(npools, int):
            raise TypeError("'npools' should be an int")

        N = len(self.u0_list)

        # ----------------------------------------------------
        # Generate one independent RNG stream per trajectory
        # ----------------------------------------------------

        master_seed = getattr(
            self,
            "seed_idx",
            42,
        )

        explicit_sequences = getattr(
            self,
            "trajectory_seed_sequences",
            None,
        )

        if explicit_sequences is None:
            seed_sequence = np.random.SeedSequence(
                master_seed
            )
            child_sequences = seed_sequence.spawn(N)
        else:
            child_sequences = list(explicit_sequences)
            if len(child_sequences) != N:
                raise ValueError(
                    "trajectory_seed_sequences must contain one seed "
                    f"sequence per trajectory ({N}), got "
                    f"{len(child_sequences)}."
                )

        tasks = list(
            zip(
                self.u0_list,
                child_sequences,
            )
        )

        # ----------------------------------------------------
        # Parallel execution
        # ----------------------------------------------------

        if npools:

            # The parent simulator owns the full input batch and, for paired
            # studies, one explicit SeedSequence per trajectory.  Neither is
            # needed by the worker-local simulator: each task already carries
            # its own initial state and seed.  Passing ``self`` directly as a
            # Pool initializer argument made Python 3.14 serialize the entire
            # batch once per worker, which could leave a 120-process job using
            # only one CPU for several minutes before integration began.
            worker_sim = copy.copy(self)
            worker_sim.u0_list = []
            worker_sim.trajectory_seed_sequences = None

            if verbose:

                res_list = []

                with tqdm(total=N) as pbar, Pool(
                    npools,
                    initializer=_init_worker,
                    initargs=(worker_sim, t),
                ) as p:

                    for res in p.imap(
                        _worker_integrate,
                        tasks,
                    ):

                        res_list.append(res)

                        pbar.update()

            else:

                with Pool(
                    npools,
                    initializer=_init_worker,
                    initargs=(worker_sim, t),
                ) as p:

                    res_list = list(p.imap(_worker_integrate, tasks))

        # ----------------------------------------------------
        # Serial execution
        # ----------------------------------------------------

        else:

            res_list = []

            iterable = (
                tqdm(tasks)
                if verbose
                else tasks
            )

            for task in iterable:

                res = self._integrate_with_seed(
                    task,
                    t,
                )

                res_list.append(res)

        return res_list
