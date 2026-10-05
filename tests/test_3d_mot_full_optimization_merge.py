import json

import pytest

from studies.merge_3d_mot_full_optimization import merge


def _trial(root, worker, number):
    path = root / f"worker_{worker}" / "trials" / f"trial_{number:04d}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "family": "angled_donut",
                "worker_index": worker,
                "trial_number": number,
                "usable_at_end_count": 120,
                "input_particle_count": 600,
                "usable_at_end_fraction": 0.2,
                "usable_ever_count": 120,
                "entered_capture_region_count": 500,
                "runtime_seconds": 10.0,
                "software_revision": "test",
                "parameters": {},
                "derived_parameters": {},
            }
        )
    )


def test_merge_fails_closed_when_discovery_is_incomplete(tmp_path):
    root = tmp_path / "input"
    _trial(root, 0, 0)
    with pytest.raises(RuntimeError, match="Discovery is incomplete"):
        merge(root, tmp_path / "output", expected_trial_count=2)


def test_merge_accepts_exact_expected_count(tmp_path):
    root = tmp_path / "input"
    _trial(root, 0, 0)
    _trial(root, 1, 0)
    summary, table = merge(root, tmp_path / "output", expected_trial_count=2)
    assert summary.exists()
    assert table.exists()
