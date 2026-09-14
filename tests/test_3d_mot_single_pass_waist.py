import numpy as np

from config import MOT_3D_SINGLE_PASS_WAIST_SCREEN_CONFIG
from studies import submit_3d_mot_single_pass_waist as submitter
from studies.scan_3d_mot_single_pass_waist import waist_screen_points


def test_waist_screen_has_five_controlled_points():
    points = waist_screen_points()

    assert len(points) == 5
    assert [point["waist_m"] for point in points] == [
        15e-3,
        20e-3,
        25e-3,
        20e-3,
        25e-3,
    ]
    assert [point["s0"] for point in points[:3]] == [0.75, 0.75, 0.75]


def test_matched_points_preserve_intensity_at_cutoff():
    settings = MOT_3D_SINGLE_PASS_WAIST_SCREEN_CONFIG
    radius = settings["cutoff_radius_m"]
    points = waist_screen_points()
    intensities = [
        point["s0"] * np.exp(-2.0 * (radius / point["waist_m"]) ** 2)
        for point in points
    ]

    assert np.allclose(intensities[3:], intensities[0], rtol=1e-12, atol=0.0)
    assert points[3]["s0"] < points[0]["s0"]
    assert points[4]["s0"] < points[3]["s0"]


def test_waist_submission_uses_three_full_nodes(tmp_path, monkeypatch):
    submitted = []

    def fake_submit(path, dependency=None):
        submitted.append((path, dependency))
        return f"job{len(submitted)}"

    monkeypatch.setattr(submitter, "_submit", fake_submit)
    assert submitter.submit(tmp_path) == "job2"
    assert submitted[1][1] == "job1"
    generated = submitted[0][0].read_text()
    assert "#PBS -l select=1:ncpus=200:mem=64gb" in generated
    assert "--max-atoms 600" in generated
    assert "--num-shards 3" in generated
    assert "--npools 200" in generated
