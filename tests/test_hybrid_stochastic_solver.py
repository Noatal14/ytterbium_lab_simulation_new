import numpy as np
import pytest

from utils.RK4StHybridCustom import (
    sample_hybrid_recoil_counts,
    sample_isotropic_recoil_sum,
)


def test_zero_expected_photons_produces_zero_recoil():
    absorption, emission = sample_hybrid_recoil_counts(
        np.random.default_rng(1),
        np.array([0.0]),
        threshold=15.0,
    )

    assert absorption.tolist() == [0.0]
    assert np.array_equal(emission, np.zeros((1, 3)))


def test_isotropic_recoil_sum_has_one_unit_of_length_for_one_photon():
    recoil = sample_isotropic_recoil_sum(np.random.default_rng(2), 1)

    assert np.linalg.norm(recoil) == pytest.approx(1.0)


def test_low_count_absorption_has_poisson_mean_and_variance():
    rng = np.random.default_rng(3)
    samples = np.array(
        [
            sample_hybrid_recoil_counts(rng, np.array([2.0]), 15.0)[0][0]
            for _ in range(30_000)
        ]
    )

    assert np.mean(samples) == pytest.approx(0.0, abs=0.04)
    assert np.var(samples) == pytest.approx(2.0, rel=0.05)


def test_high_count_branch_has_gaussian_variance():
    rng = np.random.default_rng(4)
    expected = np.full(30_000, 20.0)
    absorption, emission = sample_hybrid_recoil_counts(
        rng,
        expected,
        threshold=15.0,
    )

    assert np.mean(absorption) == pytest.approx(0.0, abs=0.08)
    assert np.var(absorption) == pytest.approx(20.0, rel=0.05)
    assert np.var(emission[:, 0]) == pytest.approx(20.0 / 3.0, rel=0.05)
