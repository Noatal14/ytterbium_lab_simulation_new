import copy

import numpy as np
from atomsmltr.simulation.simulator.simbase import get_force_vec

from config import MOT_3D_SINGLE_PASS_GATE_FOLLOWUP_CONFIG
from lab_setup.config_builder import build_base_config
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from studies import submit_3d_mot_single_pass_gate_followup as submitter
from studies.merge_3d_mot_single_pass_gate_followup import _comparison_counts
from studies.scan_3d_mot_single_pass_gate_followup import candidate_points, profile_for_point


def _blue(profile):
    return [beam for beam in setup_3dmot_lasers(profile) if "399" in beam.tag]


def test_followup_has_controls_and_nine_downstream_backstop_candidates():
    points = candidate_points()
    assert len(points) == 11
    assert sum(point["kind"] == "full_donut" for point in points) == 1
    assert sum(point["kind"] == "entrance_only" for point in points) == 1
    assert sum(point["kind"] == "entrance_plus_backstop" for point in points) == 9
    candidates = [
        point for point in points if point["kind"] == "entrance_plus_backstop"
    ]
    assert {point["backstop_crossing_offset_m"] for point in candidates} == {
        35e-3,
        40e-3,
        45e-3,
    }
    assert {point["backstop_s0"] for point in candidates} == {
        0.5,
        0.75,
        1.0,
    }


def test_backstop_is_strictly_downstream_and_blue_dark_at_mot_center():
    point = next(
        point for point in candidate_points() if point["kind"] == "entrance_plus_backstop"
    )
    profile = profile_for_point(point)
    beams = _blue(profile)
    assert len(beams) == 4
    center = np.asarray(profile["center_position_m"], dtype=float)
    backstop = [beam for beam in beams if "downstream_backstop" in beam.tag]
    assert len(backstop) == 2
    for beam in backstop:
        assert beam.minimum_lab_z_m > center[2]
        upstream = center + np.array([12e-3, 0.0, 5e-3])
        at_crossing = center + np.array(
            [12e-3, 0.0, point["backstop_crossing_offset_m"]]
        )
        assert float(beam.get_value(upstream[None, :])[0]) == 0.0
        assert float(beam.get_value(at_crossing[None, :])[0]) > 0.0
    assert all(float(beam.get_value(center[None, :])[0]) == 0.0 for beam in beams)


def test_downstream_backstop_pushes_overshooting_atoms_toward_center():
    point = next(
        point for point in candidate_points() if point["kind"] == "entrance_plus_backstop"
    )
    profile = profile_for_point(point)
    profile["399"]["beam_groups"] = [profile["399"]["beam_groups"][1]]
    profile["556"]["enabled"] = False
    _, simulation_config = build_base_config(
        include_2d_mot=False,
        include_zeeman=False,
        include_3dmot=True,
        _3d_mot_config=copy.deepcopy(profile),
        gravity_enabled=False,
        zones=[],
    )
    center = np.asarray(profile["center_position_m"], dtype=float)
    position = center + np.array([12e-3, 0.0, point["backstop_crossing_offset_m"]])
    state = np.array([[*position, 0.0, 0.0, 12.0]])
    force = np.asarray(get_force_vec(state, simulation_config)[0], dtype=float)
    assert force[2] < 0.0


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


def test_paired_comparison_distinguishes_rescued_lost_and_retained_atoms():
    indices = np.arange(5)
    entrance = {
        "global_particle_indices": indices,
        "usable_ever": np.array([True, True, False, False, False]),
        "usable_at_end": np.array([True, False, False, True, False]),
    }
    candidate = {
        "global_particle_indices": indices,
        "usable_ever": np.array([True, False, True, True, False]),
        "usable_at_end": np.array([True, True, False, False, False]),
    }

    assert _comparison_counts(candidate, entrance) == {
        "rescued_ever_count": 2,
        "lost_ever_count": 1,
        "retained_from_entrance_ever_count": 1,
        "rescued_at_end_count": 1,
        "lost_at_end_count": 1,
        "retained_from_entrance_at_end_count": 1,
    }
