import json

import matplotlib
import pytest

from graphs_scripts.plot_3d_mot_tau import generate_profile_plots


matplotlib.use("Agg")


def _summary():
    return {
        "time_points_s": [0.0, 0.001, 0.002, 0.003, 0.004],
        "results": {
            "accepted": {
                "capture_eligible_counts": [0, 3, 5, 4, 3],
                "peak_time_s": 0.002,
                "peak_count": 5,
                "retained_counts": [5, 4, 3],
                "elapsed_post_peak_s": [0.0, 0.001, 0.002],
                "fit": {"accepted": True, "tau_s": 0.002, "plateau_count": 1.0},
            },
            "rejected": {
                "capture_eligible_counts": [0, 1, 1, 1, 1],
                "peak_time_s": 0.001,
                "peak_count": 1,
                "retained_counts": [1, 1, 1, 1],
                "elapsed_post_peak_s": [0.0, 0.001, 0.002, 0.003],
                "fit": {"accepted": False, "reason": "insufficient loss"},
            },
        },
    }


def test_generates_two_separate_graphs_per_profile(tmp_path):
    source = tmp_path / "retention_summary.json"
    source.write_text(json.dumps(_summary()))

    paths = generate_profile_plots(source, tmp_path / "graphs", data_label="historical run")

    assert {path.name for path in paths} == {
        "accepted_population.png",
        "accepted_retention.png",
        "rejected_population.png",
        "rejected_retention.png",
    }
    assert all(path.exists() and path.stat().st_size > 0 for path in paths)


def test_rejects_profile_missing_from_summary(tmp_path):
    source = tmp_path / "retention_summary.json"
    source.write_text(json.dumps(_summary()))

    with pytest.raises(ValueError, match="not present"):
        generate_profile_plots(source, tmp_path / "graphs", profiles=["missing"])
