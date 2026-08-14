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

    def run(
            self,
            t: np.ndarray,
            u0_list: list = None,
            npools: int = 0,
            verbose: bool = False,
            chunksize: int = 1
        ) -> list:
            """Runs a batch of simulations from a list of initial conditions
    
            Parameters
            ----------
            t : array, shape (n,)
                time steps for the simulation
            u0_list : list, optional
                list of initial conditions, by default None
            npools : int, optional
                number of pools for parallel computing.
                If set to zero, no paralalelisation, by default 0
            verbose : bool, optional
                if set to True, a progress bar is displayed, by default False
    
            Returns
            -------
            res_list : list
                a list of results
    
            Examples
            --------
    
            .. code-block:: python
    
                # ... init a config object with the `Configuration` class
    
                # - import a simulation class
                from atomsmltr.simulation import ScipyIVP_3D
    
                # - init and setup
                sim = ScipyIVP_3D(method="Radau")
                sim.config = config
    
                # - parameters
                # initial conditions
                vz_list = np.linspace(10, 300, 40)
                u0_list = [(0, 0, -0.15, 0, 0, v) for v in vz_list]
                sim.u0_list = u0_list
                # time
                t = np.linspace(0, 0.05, 1000)
    
                # - run a batch in parallel
                res_list = sim.run(t, npools=5, verbose=True)
    
            """
            if u0_list is not None:
                self.u0_list = u0_list
            if not isinstance(npools, int):
                return TypeError("'npools' should be an int")
            if npools:
                map_fun = partial(self.integrate, t=t)
                if verbose:
                    Nmax = len(self.u0_list)
                    res_list = []
                    with Pool(npools) as p, tqdm(total=Nmax) as pbar:
                        for res in p.imap(map_fun, self.u0_list, chunksize=chunksize):
                            pbar.update()
                            pbar.refresh()
                            res_list.append(res)
                else:
                    with Pool(npools) as p:
                        res_list = p.map(map_fun, self.u0_list, chunksize=chunksize)
            else:
                res_list = []
                u0_list = tqdm(self.u0_list) if verbose else self.u0_list
                for u0 in u0_list:
                    res = self.integrate(u0, t)
                    res_list.append(res)
            return res_list
