import json

import numpy as np

from utils.mot_2d_study import (
    load_production_ensembles,
    student_mean_interval,
    summarize_replicates,
)


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
    for seed, size in [(3001, 5), (3000, 4)]:
        path = tmp_path / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
        np.save(path, np.full((size, 6), seed, dtype=float))
        path.with_suffix(".json").write_text(
            json.dumps(
                {
                    "parameters": {"seed": seed, "n_initial_atoms": 50000},
                    "survival_fraction": size / 50000,
                }
            ),
            encoding="utf-8",
        )
    ensembles = load_production_ensembles(2, 3, directory=tmp_path)
    assert [row["zeeman_seed"] for row in ensembles] == [3000, 3001]
    assert [len(row["states"]) for row in ensembles] == [3, 3]
