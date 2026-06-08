import multiprocessing as mp
import numpy as np
from functools import partial
from atomsmltr.simulation.simulator import ScipyIVP_3D, RK4St
from scipy import constants as csts
from atomsmltr.simulation.simulator.simbase import get_force_vec, SimRes


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
