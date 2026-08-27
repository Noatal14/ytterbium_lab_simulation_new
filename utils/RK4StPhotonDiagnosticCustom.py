"""Gaussian stochastic RK4 with per-laser photon-count diagnostics."""

from __future__ import annotations

import numpy as np
import scipy.constants as csts
from atomsmltr.simulation.simulator.simbase import get_force_vec

from utils.RK4StCustom import RK4StCustom


PHOTON_COUNT_THRESHOLDS = (1.0, 5.0, 10.0, 15.0)


def _empty_laser_statistics():
    result = {
        "evaluations": 0,
        "sum_expected_photons": 0.0,
        "minimum_expected_photons": None,
        "maximum_expected_photons": None,
    }
    for threshold in PHOTON_COUNT_THRESHOLDS:
        label = f"below_{threshold:g}"
        result[f"{label}_evaluations"] = 0
        result[f"{label}_expected_photons"] = 0.0
    return result


def update_laser_statistics(statistics, expected_photons):
    """Accumulate counts and expected impulse weights for one laser."""
    values = np.asarray(expected_photons, dtype=float).reshape(-1)
    values = values[np.isfinite(values) & (values >= 0.0)]
    if not len(values):
        return
    statistics["evaluations"] += int(len(values))
    statistics["sum_expected_photons"] += float(np.sum(values))
    local_min = float(np.min(values))
    local_max = float(np.max(values))
    current_min = statistics["minimum_expected_photons"]
    current_max = statistics["maximum_expected_photons"]
    statistics["minimum_expected_photons"] = (
        local_min if current_min is None else min(current_min, local_min)
    )
    statistics["maximum_expected_photons"] = (
        local_max if current_max is None else max(current_max, local_max)
    )
    for threshold in PHOTON_COUNT_THRESHOLDS:
        mask = values < threshold
        label = f"below_{threshold:g}"
        statistics[f"{label}_evaluations"] += int(np.count_nonzero(mask))
        statistics[f"{label}_expected_photons"] += float(np.sum(values[mask]))


class RK4StPhotonDiagnosticCustom(RK4StCustom):
    """Preserve Gaussian sampling while recording every per-laser ``Ni``."""

    def _integrate(self, u0, t):
        self._photon_statistics = {}
        result = super()._integrate(u0, t)
        result.photon_statistics = self._photon_statistics
        return result

    def du_fluct(self, t, state, dt):
        _, scattering = get_force_vec(state, self.config, return_list=True)
        velocity_change = np.zeros_like(state[..., :3])
        mass = self.config.atom.mass
        for laser_index, row in enumerate(scattering):
            rate = row["rate"]
            wavenumber = row["k"]
            direction = row["unit_vector"]
            expected = rate * dt
            statistics = self._photon_statistics.setdefault(
                str(laser_index), _empty_laser_statistics()
            )
            update_laser_statistics(statistics, expected)

            absorption = np.asanyarray(self.rng.normal(loc=0, scale=np.sqrt(expected)))
            velocity_change += (
                (csts.hbar * wavenumber / mass)
                * absorption[..., np.newaxis]
                * direction
            )
            emission = np.array(
                [
                    np.asanyarray(self.rng.normal(loc=0, scale=np.sqrt(expected / 3))).T
                    for _ in range(3)
                ]
            ).T
            velocity_change += (csts.hbar * wavenumber / mass) * emission

        dx, dy, dz = np.zeros_like(velocity_change.T)
        dvx, dvy, dvz = velocity_change.T
        return np.array([dx, dy, dz, dvx, dvy, dvz]).T
