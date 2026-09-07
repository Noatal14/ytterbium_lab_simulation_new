from types import SimpleNamespace

import numpy as np

from studies.compare_3d_mot_retention import (
    fit_retention_lifetime,
    inside_capture_masks,
    retention_from_masks,
)


def test_inside_capture_masks_aligns_terminated_trajectories_to_shared_grid():
    time_points = np.array([0.0, 1.0, 2.0, 3.0])
    trajectory = SimpleNamespace(
        t=np.array([0.0, 1.0, 2.0]),
        y=np.array(
            [
                [2.0, 0.5, 0.25],
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
            ]
        ),
    )
    masks = inside_capture_masks(
        [trajectory], time_points, center_m=(0.0, 0.0, 0.0), capture_radius_m=1.0
    )
    assert masks.tolist() == [[False, True, True, False]]


def test_retention_cohort_never_readds_atoms_that_leave_and_return():
    masks = np.array(
        [
            [False, True, True, False, True],
            [True, True, True, True, True],
            [False, False, True, True, False],
        ]
    )
    instantaneous, peak_index, retained, cohort_indices = retention_from_masks(masks)
    assert instantaneous.tolist() == [1, 2, 3, 2, 2]
    assert peak_index == 2
    assert cohort_indices.tolist() == [0, 1, 2]
    assert retained.tolist() == [3, 2, 1]


def test_exponential_fit_is_accepted_only_for_a_resolved_decay():
    elapsed = np.linspace(0.0, 0.04, 81)
    expected_tau = 0.012
    counts = 20.0 + 80.0 * np.exp(-elapsed / expected_tau)
    fit = fit_retention_lifetime(elapsed, counts)
    assert fit["accepted"]
    np.testing.assert_allclose(fit["tau_s"], expected_tau, rtol=1e-3)


def test_exponential_fit_rejects_nearly_flat_retention():
    elapsed = np.linspace(0.0, 0.04, 81)
    counts = np.linspace(100.0, 95.0, len(elapsed))
    fit = fit_retention_lifetime(elapsed, counts)
    assert not fit["accepted"]
    assert "loss" in fit["reason"]
