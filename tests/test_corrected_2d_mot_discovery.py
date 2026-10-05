import json

import numpy as np
import pytest

from studies.generate_corrected_zeeman_ensembles import (
    PROFILE_NAME,
    corrected_field,
    output_path,
)
from studies.merge_2d_mot_corrected_discovery import merge


def test_corrected_production_profile_and_filename_are_unambiguous(tmp_path):
    field = corrected_field()
    assert PROFILE_NAME == "corrected_projectant_19ring_20261005"
    assert [
        len(field[key]) for key in ("radii_m", "positions_m", "tilt_angles_deg")
    ] == [
        19,
        19,
        19,
    ]
    assert np.all(np.diff(field["positions_m"]) > 0.0)
    assert output_path(3007, tmp_path).name == (
        "production_zeeman_n50000_dt40us_seed3007.npy"
    )


def test_corrected_discovery_merge_ranks_all_workers(tmp_path):
    root = tmp_path / "input"
    for worker in range(3):
        worker_dir = root / f"worker_{worker}"
        worker_dir.mkdir(parents=True)
        summary = {
            "fixed_s0": 1.3,
            "design": {
                "bounds": {
                    "s0": [1.3, 1.3],
                    "detuning_gamma": [-3.0, -0.4],
                    "magnet_radius_m": [0.045, 0.051],
                }
            },
            "ranked_trials": [
                {
                    "trial_number": worker,
                    "mean_conditional_efficiency": 0.1 + 0.01 * worker,
                    "parameters": {
                        "s0": 1.3,
                        "detuning_gamma": -1.0 - 0.1 * worker,
                        "magnet_radius": 0.048 + 0.001 * worker,
                    },
                }
            ],
        }
        (worker_dir / "summary.json").write_text(json.dumps(summary))

    payload = merge(root, tmp_path / "merged")
    assert payload["completed_trial_count"] == 3
    assert payload["best"]["worker_index"] == 2
    assert payload["best"]["mean_conditional_efficiency"] == pytest.approx(0.12)
    assert (tmp_path / "merged" / "ranked_trials.csv").exists()
