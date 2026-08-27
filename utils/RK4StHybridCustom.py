"""Stochastic RK4 recoil with exact low-count photon sampling."""

from __future__ import annotations

import numpy as np
import scipy.constants as csts
from atomsmltr.simulation.simulator.simbase import get_force_vec

from utils.RK4StCustom import RK4StCustom


DEFAULT_POISSON_THRESHOLD = 15.0


def sample_isotropic_recoil_sum(rng, photon_count):
    """Return the vector sum of ``photon_count`` isotropic unit vectors."""
    photon_count = int(photon_count)
    if photon_count <= 0:
        return np.zeros(3)
    cos_theta = rng.uniform(-1.0, 1.0, size=photon_count)
    phi = rng.uniform(0.0, 2.0 * np.pi, size=photon_count)
    sin_theta = np.sqrt(1.0 - cos_theta**2)
    return np.array(
        [
            np.sum(sin_theta * np.cos(phi)),
            np.sum(sin_theta * np.sin(phi)),
            np.sum(cos_theta),
        ]
    )


def sample_hybrid_recoil_counts(rng, expected_photons, threshold):
    """Sample absorption fluctuation and emission recoil in photon units.

    Below ``threshold``, the absorption event count is sampled exactly from a
    Poisson distribution. The same event count is used for the isotropic
    spontaneous-emission recoil. At high count, both contributions use the
    library's Gaussian approximation.
    """
    expected = np.asarray(expected_photons, dtype=float)
    expected = np.maximum(expected, 0.0)
    absorption = np.empty_like(expected)
    emission = np.empty(expected.shape + (3,), dtype=float)
    low_count = expected < threshold
    high_count = ~low_count

    if np.any(high_count):
        high_expected = expected[high_count]
        absorption[high_count] = rng.normal(
            loc=0.0,
            scale=np.sqrt(high_expected),
        )
        emission[high_count] = rng.normal(
            loc=0.0,
            scale=np.sqrt(high_expected / 3.0)[..., np.newaxis],
            size=(len(high_expected), 3),
        )

    for index in zip(*np.where(low_count)):
        mean = float(expected[index])
        photon_count = int(rng.poisson(mean))
        absorption[index] = photon_count - mean
        emission[index] = sample_isotropic_recoil_sum(rng, photon_count)

    return absorption, emission


class RK4StHybridCustom(RK4StCustom):
    """Use exact Poisson recoil below a configurable expected photon count."""

    poisson_threshold = DEFAULT_POISSON_THRESHOLD

    def du_fluct(self, t, state, dt):
        _, scattering = get_force_vec(state, self.config, return_list=True)
        velocity_change = np.zeros_like(state[..., :3])
        mass = self.config.atom.mass

        for row in scattering:
            expected = np.atleast_1d(np.asarray(row["rate"] * dt, dtype=float))
            absorption, emission = sample_hybrid_recoil_counts(
                self.rng,
                expected,
                self.poisson_threshold,
            )
            recoil_velocity = csts.hbar * row["k"] / mass
            velocity_change += (
                recoil_velocity * absorption[..., np.newaxis] * row["unit_vector"]
            ).reshape(velocity_change.shape)
            velocity_change += (recoil_velocity * emission).reshape(
                velocity_change.shape
            )

        dx, dy, dz = np.zeros_like(velocity_change.T)
        dvx, dvy, dvz = velocity_change.T
        return np.array([dx, dy, dz, dvx, dvy, dvz]).T
