import json

import pytest

from studies.validate_3d_mot_discovery_preflight import validate


def _summary(tmp_path, *, fraction=0.22, label="donut_core_shell_split_screen_v2_600"):
    path = tmp_path / "summary.json"
    path.write_text(
        json.dumps(
            {
                "run_label": label,
                "input_particle_count": 600,
                "num_shards": 3,
                "best": {
                    "usable_at_end_fraction": fraction,
                    "usable_at_end_count": round(600 * fraction),
                    "usable_ever_count": round(600 * fraction),
                    "core_shell_split_radius_m": 0.004,
                },
            }
        )
    )
    return path


def test_preflight_accepts_correct_stable_screen(tmp_path):
    data = validate(_summary(tmp_path), 0.20)
    assert data["best"]["usable_at_end_fraction"] == pytest.approx(0.22)


def test_preflight_rejects_old_run_label(tmp_path):
    with pytest.raises(ValueError, match="Expected run label"):
        validate(_summary(tmp_path, label="donut_aperture_split_screen_v1_600"), 0.20)


def test_preflight_rejects_capture_below_gate(tmp_path):
    with pytest.raises(RuntimeError, match="Donut gate failed"):
        validate(_summary(tmp_path, fraction=0.19), 0.20)
