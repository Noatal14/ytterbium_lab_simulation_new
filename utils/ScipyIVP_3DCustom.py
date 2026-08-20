import numpy as np
from functools import partial
from atomsmltr.simulation.simulator import ScipyIVP_3D
from atomsmltr.simulation.simulator.simbase import Pool
from tqdm import tqdm

class ScipyIVP_3DCustom(ScipyIVP_3D):
    def run(
        self,
        t: np.ndarray,
        u0_list: list = None,
        npools: int = 0,
        verbose: bool = False,
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
                    for res in p.imap(map_fun, self.u0_list):
                        pbar.update()
                        pbar.refresh()
                        res_list.append(res)
            else:
                with Pool(npools) as p:
                    res_list = list(p.imap(map_fun, self.u0_list))
        else:
            res_list = []
            u0_list = tqdm(self.u0_list) if verbose else self.u0_list
            for u0 in u0_list:
                res = self.integrate(u0, t)
                res_list.append(res)
        return res_list
