import json

import matplotlib
import pytest

from graphs_scripts.plot_donut_vs_five_beam_retention import create_comparison_plot


matplotlib.use("Agg")


def _result(counts, peak_time, peak_count, fit):
    return {
        "capture_eligible_counts": counts,
        "peak_time_s": peak_time,
        "peak_count": peak_count,
        "retained_counts": counts[1:],
        "elapsed_post_peak_s": [0.05 * index for index in range(len(counts) - 1)],
        "fit": fit,
    }


def test_creates_stitched_comparison_with_accepted_five_beam_fit(tmp_path):
    initial = {
        "time_points_s": [0.0, 0.05, 0.1],
        "results": {
            "angled_donut": _result([0, 80, 80], 0.05, 80, {"accepted": False}),
            "five_beam_gravity": _result(
                [0, 30, 10],
                0.05,
                30,
                {"accepted": True, "tau_s": 0.02, "plateau_count": 5.0},
            ),
        },
    }
    continuation = {
        "time_points_s": [0.0, 0.15, 0.3],
        "results": {
            "angled_donut": _result([79, 79, 78], 0.0, 79, {"accepted": False}),
        },
    }
    initial_path = tmp_path / "initial.json"
    continuation_path = tmp_path / "continuation.json"
    initial_path.write_text(json.dumps(initial))
    continuation_path.write_text(json.dumps(continuation))
    output = tmp_path / "comparison.png"

    assert create_comparison_plot(initial_path, continuation_path, output) == output
    assert output.exists() and output.stat().st_size > 0


def test_rejects_discontinuous_donut_checkpoint(tmp_path):
    initial = {
        "time_points_s": [0.0, 0.1],
        "results": {
            "angled_donut": _result([0, 80], 0.1, 80, {"accepted": False}),
            "five_beam_gravity": _result(
                [0, 10], 0.1, 10,
                {"accepted": True, "tau_s": 0.02, "plateau_count": 1.0},
            ),
        },
    }
    continuation = {
        "time_points_s": [0.0, 0.3],
        "results": {"angled_donut": _result([70, 69], 0.0, 70, {"accepted": False})},
    }
    initial_path = tmp_path / "initial.json"
    continuation_path = tmp_path / "continuation.json"
    initial_path.write_text(json.dumps(initial))
    continuation_path.write_text(json.dumps(continuation))

    with pytest.raises(ValueError, match="inconsistent"):
        create_comparison_plot(initial_path, continuation_path, tmp_path / "bad.png")
