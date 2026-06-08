from atomsmltr.simulation.simulator.stochastic import random_unit_vector
import numpy as np
from scipy import constants as csts
from atomsmltr.simulation.simulator.simbase import get_force_vec, SimRes
from utils.RK4StCustom import RK4StCustom

def smooth_weight(Ni, N0=5.0, p=2):
    """
    Smooth transition between Poisson (Ni small) and Gaussian (Ni large)
    """
    return 1.0 / (1.0 + (N0 / (Ni + 1e-12))**p)

class RK4StCustomDt(RK4StCustom):
    """
    A subclass of RK4St that intercepts the du_fluct call to track
    the expected number of scattering events (Ni) at every timestep.
    """
    def __init__(self, config=None):
        super().__init__(config)
        self.tracked_Ni_vals = []
    
    def du_fluct(self, t, u, dt):
        _, scatt_list = get_force_vec(u, self.config, return_list=True)
        dv_tot = np.zeros_like(u[..., :3])

        Ni_vals = []

        for scatt in scatt_list:
            # 0 - get scattering rate, laser wavenumber and unit vector for each laser
            rate = scatt["rate"]  # scattering rate
            k = scatt["k"]  # laser wavenumber
            u = scatt["unit_vector"]  # laser unit vector
            Ni = rate * dt  # number of scattered photons
            Ni_vals.append(Ni)
            m = self.config.atom.mass
            # 1 - absorption fluctuation
            # large number of photon approximation
            #   > fluctuation are Gaussian with std = np.sqrt(Ni)
            # note that dN has the same shape as Ni, and can be an array !!
            dN = np.asanyarray(self.rng.normal(loc=0, scale=np.sqrt(Ni)))
            dv_abs = (csts.hbar * k / m) * dN[..., np.newaxis] * u
            dv_tot = dv_tot + dv_abs
            # 2 - emission fluctuation
            # Gaussian approx for random walk, with std = sqrt(Ni/3) for x, y, z
            dNx = np.asanyarray(self.rng.normal(loc=0, scale=np.sqrt(Ni / 3)))
            dNy = np.asanyarray(self.rng.normal(loc=0, scale=np.sqrt(Ni / 3)))
            dNz = np.asanyarray(self.rng.normal(loc=0, scale=np.sqrt(Ni / 3)))
            dN = np.array([dNx.T, dNy.T, dNz.T]).T
            dv_em = (csts.hbar * k / m) * dN
            dv_tot = dv_tot + dv_em

        self.tracked_Ni_vals.append(Ni_vals)
        dx, dy, dz = np.zeros_like(dv_tot.T)
        dvx, dvy, dvz = dv_tot.T
        res = np.array([dx, dy, dz, dvx, dvy, dvz]).T
        return res