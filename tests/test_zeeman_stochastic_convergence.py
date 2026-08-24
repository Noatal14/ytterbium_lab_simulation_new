import numpy as np

from studies.zeeman_stochastic_convergence import (
    paired_differences,
    summarize_records,
    wilson_interval,
)


def _record(dt_s, seed, fraction, n_atoms=5000):
    return {
        "configuration": {"n_atoms": n_atoms, "dt_s": dt_s, "seed": seed},
        "result": {"survival_fraction": fraction},
    }


def test_wilson_interval_contains_observed_fraction():
    low, high = wilson_interval(50, 100)
    assert low < 0.5 < high


def test_summary_reports_across_seed_uncertainty():
    rows = [_record(4e-5, 1, 0.50), _record(4e-5, 2, 0.54), _record(4e-5, 3, 0.52)]
    summary = summarize_records(rows)[0]
    assert np.isclose(summary["mean_survival_fraction"], 0.52)
    assert summary["n_seeds"] == 3
    assert summary["student_t_95_ci_fraction"][0] < 0.52


def test_paired_difference_matches_common_seed_runs():
    rows = [
        _record(2e-5, 1, 0.50),
        _record(2e-5, 2, 0.52),
        _record(4e-5, 1, 0.51),
        _record(4e-5, 2, 0.55),
    ]
    comparison = paired_differences(rows)[0]
    assert comparison["shared_seeds"] == [1, 2]
    assert np.isclose(comparison["mean_paired_difference_fraction"], 0.02)
