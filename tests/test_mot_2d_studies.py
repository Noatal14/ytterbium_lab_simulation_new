import json

import numpy as np

from utils.mot_2d_study import (
    load_production_ensembles,
    student_mean_interval,
    summarize_replicates,
)


def test_joint_followup_uses_updated_experimental_bounds():
    from studies.optimize_2d_mot_joint import (
        BOUNDS_DETUNING,
        BOUNDS_MAGNET_RADIUS_M,
        BOUNDS_S0,
    )

    assert BOUNDS_S0 == (1.4, 1.5)
    assert BOUNDS_DETUNING == (-1.55, -0.85)
    assert BOUNDS_MAGNET_RADIUS_M == (0.045, 0.051)


def test_student_interval_requires_replicates():
    mean, low, high, half_width = student_mean_interval([0.25])
    assert mean == 0.25
    assert low is high is half_width is None


def test_replicate_summary_reports_conditional_and_total_uncertainty():
    result = summarize_replicates(
        [
            {"conditional_efficiency": 0.20, "estimated_total_efficiency": 0.10},
            {"conditional_efficiency": 0.22, "estimated_total_efficiency": 0.11},
            {"conditional_efficiency": 0.21, "estimated_total_efficiency": 0.105},
        ]
    )
    assert result["n_replicates"] == 3
    assert np.isclose(result["mean_conditional_efficiency"], 0.21)
    assert np.isclose(result["mean_estimated_total_efficiency"], 0.105)
    assert result["conditional_95_ci_half_width"] > 0


def test_load_production_ensembles_uses_ordered_fixed_subsets(tmp_path):
    for seed, size in [(3001, 20), (3000, 20)]:
        path = tmp_path / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
        states = np.column_stack(
            (np.arange(size), np.full((size, 5), seed, dtype=float))
        )
        np.save(path, states)
        path.with_suffix(".json").write_text(
            json.dumps(
                {
                    "parameters": {"seed": seed, "n_initial_atoms": 50000},
                    "survival_fraction": size / 50000,
                }
            ),
            encoding="utf-8",
        )
    ensembles = load_production_ensembles(2, 5, directory=tmp_path)
    repeated = load_production_ensembles(2, 5, directory=tmp_path)
    assert [row["zeeman_seed"] for row in ensembles] == [3000, 3001]
    assert [len(row["states"]) for row in ensembles] == [5, 5]
    assert all(
        row["selection_method"] == "deterministic_random_without_replacement"
        for row in ensembles
    )
    assert all(
        np.array_equal(first["states"], second["states"])
        for first, second in zip(ensembles, repeated)
    )
    assert not np.array_equal(ensembles[0]["states"][:, 0], np.arange(5))
