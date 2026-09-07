from types import SimpleNamespace

import numpy as np

from studies.compare_3d_mot_retention import (
    capture_eligible_masks,
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


def test_capture_eligibility_rejects_fast_transit_and_requires_residence_time():
    time_points = np.arange(7, dtype=float) * 1.0e-3
    slow = SimpleNamespace(
        t=time_points,
        y=np.vstack(
            [
                np.zeros((3, len(time_points))),
                np.zeros((3, len(time_points))),
            ]
        ),
    )
    fast = SimpleNamespace(
        t=time_points,
        y=np.vstack(
            [
                np.zeros((3, len(time_points))),
                np.full((1, len(time_points)), 2.0),
                np.zeros((2, len(time_points))),
            ]
        ),
    )
    inside = np.ones((2, len(time_points)), dtype=bool)
    eligible = capture_eligible_masks(
        [slow, fast],
        time_points,
        inside,
        minimum_residence_time_s=5.0e-3,
        maximum_speed_m_s=1.0,
    )

    assert eligible[0].tolist() == [False, False, False, False, False, True, True]
    assert not eligible[1].any()


def test_peak_cohort_uses_eligibility_but_retention_uses_spatial_presence():
    eligible = np.array(
        [
            [False, True, False, False],
            [False, True, False, False],
        ]
    )
    inside = np.array(
        [
            [True, True, True, False],
            [True, True, True, True],
        ]
    )
    counts, peak_index, retained, _ = retention_from_masks(
        eligible, continuation_masks=inside
    )
    assert counts.tolist() == [0, 2, 0, 0]
    assert peak_index == 1
    assert retained.tolist() == [2, 2, 1]


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


def test_exponential_fit_reports_an_empty_capture_cohort_explicitly():
    fit = fit_retention_lifetime(np.linspace(0.0, 0.01, 11), np.zeros(11))
    assert not fit["accepted"]
    assert fit["reason"] == "no capture-eligible atoms"
