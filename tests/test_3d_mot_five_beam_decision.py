import numpy as np

from config import (
    MOT_3D_FIVE_BEAM_DECISION_SCREEN_CONFIG,
    MOT_3D_FIVE_BEAM_REFINED_SCREEN_CONFIG,
)
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from studies import submit_3d_mot_five_beam_decision as submitter
from studies.scan_3d_mot_five_beam_decision import candidate_points, profile_for_point


def test_decision_screen_has_donut_control_and_twelve_five_beam_anchors():
    points = candidate_points()
    assert len(points) == 13
    assert sum(point["kind"] == "full_donut" for point in points) == 1
    assert sum(point["kind"] == "five_beam_gravity" for point in points) == 12
    assert len({point["label"] for point in points}) == len(points)


def test_refined_screen_has_fourteen_nonduplicate_five_beam_anchors():
    points = candidate_points(MOT_3D_FIVE_BEAM_REFINED_SCREEN_CONFIG)
    assert len(points) == 15
    candidates = [point for point in points if point["kind"] == "five_beam_gravity"]
    assert len(candidates) == 14
    assert len({point["label"] for point in candidates}) == 14
    assert {point["gradient_G_cm"] for point in candidates} >= {
        0.5,
        0.75,
        1.0,
        1.25,
        1.5,
    }


def test_five_beam_anchor_changes_only_configured_operating_parameters():
    point = next(point for point in candidate_points() if point["label"] == "baseline_lower_6")
    profile = profile_for_point(point)
    assert profile["magnetic_gradient_G_cm"] == 2.5
    assert profile["399"]["s0"] == 1.0
    assert profile["399"]["detuning_gamma"] == -2.0
    assert profile["556"]["s0"] == 10.0
    assert profile["556"]["s0_by_axis"] == {"+X": 6.0}
    assert profile["556"]["detuning_gamma"] == -20.0
    blue = [beam for beam in setup_3dmot_lasers(profile) if "399" in beam.tag]
    center = np.asarray(profile["center_position_m"])[None, :]
    assert len(blue) == 4
    assert all(float(beam.get_value(center)[0]) == 0.0 for beam in blue)


def test_decision_submission_uses_three_full_nodes(tmp_path, monkeypatch):
    submitted = []

    def fake_submit(path, dependency=None):
        submitted.append((path, dependency))
        return f"job{len(submitted)}"

    monkeypatch.setattr(submitter, "_submit", fake_submit)
    assert submitter.submit(tmp_path) == "job2"
    generated = submitted[0][0].read_text()
    assert "#PBS -l select=1:ncpus=200:mem=64gb" in generated
    assert "--max-atoms 600" in generated
    assert "--num-shards 3" in generated
    assert "--npools 200" in generated
    assert MOT_3D_FIVE_BEAM_REFINED_SCREEN_CONFIG["pbs_walltime"] in generated
    assert "--refined" in generated
