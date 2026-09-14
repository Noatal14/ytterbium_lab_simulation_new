import numpy as np

from config import MOT_3D_SINGLE_PASS_GATE_FOLLOWUP_CONFIG
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from studies import submit_3d_mot_single_pass_gate_followup as submitter
from studies.scan_3d_mot_single_pass_gate_followup import (
    candidate_points,
    profile_for_point,
)


def _blue(profile):
    return [beam for beam in setup_3dmot_lasers(profile) if "399" in beam.tag]


def test_followup_has_control_location_scan_and_fixed_total_power_two_stage_scan():
    points = candidate_points()
    assert len(points) == 9
    assert sum(point["kind"] == "single_gate" for point in points) == 5
    assert sum(point["kind"] == "two_stage" for point in points) == 3
    for point in points:
        if point["kind"] == "two_stage":
            assert point["front_s0"] + point["rear_s0"] == 0.75


def test_two_stage_windows_do_not_illuminate_outside_their_z_intervals():
    point = next(point for point in candidate_points() if point["kind"] == "two_stage")
    profile = profile_for_point(point)
    beams = _blue(profile)
    assert len(beams) == 4
    center = np.asarray(profile["center_position_m"], dtype=float)
    for beam in beams:
        crossing_z = beam.waist_position[2]
        transverse_point = center + np.array([12e-3, 0.0, crossing_z - center[2]])
        below = transverse_point.copy()
        below[2] = beam.minimum_lab_z_m - 1e-6
        above = transverse_point.copy()
        above[2] = beam.maximum_lab_z_m + 1e-6
        assert float(beam.get_value(transverse_point[None, :])[0]) > 0.0
        assert float(beam.get_value(below[None, :])[0]) == 0.0
        assert float(beam.get_value(above[None, :])[0]) == 0.0


def test_every_followup_gate_geometry_is_blue_dark_at_mot_center():
    for point in candidate_points():
        if point["kind"] == "full_donut":
            continue
        profile = profile_for_point(point)
        center = np.asarray(profile["center_position_m"])[None, :]
        assert all(float(beam.get_value(center)[0]) == 0.0 for beam in _blue(profile))


def test_followup_submission_uses_three_full_nodes(tmp_path, monkeypatch):
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
    assert MOT_3D_SINGLE_PASS_GATE_FOLLOWUP_CONFIG["pbs_walltime"] in generated
