import copy

import numpy as np

from config import MOT_3D_POSITIVE_Z_PAIR_SCREEN_CONFIG
from lab_setup.config_builder import build_base_config
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from studies import submit_3d_mot_positive_z_pair as submitter
from studies.scan_3d_mot_positive_z_pair import (
    candidate_points,
    positive_z_pair_profiles,
)
from atomsmltr.simulation.simulator.simbase import get_force_vec


def _blue_beams(profile):
    return [beam for beam in setup_3dmot_lasers(profile) if "3DMOT_399_" in beam.tag]


def test_positive_z_pair_profiles_keep_only_requested_blue_and_all_green():
    for profile in positive_z_pair_profiles().values():
        beams = setup_3dmot_lasers(profile)
        blue_tags = {beam.tag.removeprefix("3DMOT_399_") for beam in beams if "399" in beam.tag}
        green_tags = {beam.tag.removeprefix("3DMOT_556_") for beam in beams if "556" in beam.tag}

        assert blue_tags == {"+XZ_1", "+XZ_2"}
        assert green_tags == {"+XZ_1", "-XZ_1", "+XZ_2", "-XZ_2", "+Y", "-Y"}


def test_positive_z_single_pass_is_exactly_blue_dark_at_mot_center():
    profile = positive_z_pair_profiles()["positive_z_pair_single_pass"]
    center = np.asarray(profile["center_position_m"], dtype=float)[None, :]

    assert all(float(beam.get_value(center)[0]) == 0.0 for beam in _blue_beams(profile))


def test_positive_z_pair_pushes_forward_and_cancels_transverse_force_on_axis():
    profile = copy.deepcopy(positive_z_pair_profiles()["positive_z_pair_single_pass"])
    profile["556"]["enabled"] = False
    _, simulation_config = build_base_config(
        include_2d_mot=False,
        include_zeeman=False,
        include_3dmot=True,
        _3d_mot_config=profile,
        gravity_enabled=False,
        zones=[],
    )
    center = np.asarray(profile["center_position_m"], dtype=float)
    state = np.array([[*(center + np.array([0.0, 0.0, -25e-3])), 0.0, 0.0, 12.0]])
    force = np.asarray(get_force_vec(state, simulation_config)[0], dtype=float)

    assert force[2] > 0.0
    assert abs(force[0]) <= 1e-12 * abs(force[2]) + 1e-30
    assert abs(force[1]) <= 1e-12 * abs(force[2]) + 1e-30


def test_positive_z_screen_contains_shell_control_and_twelve_single_pass_points():
    points = candidate_points()

    assert len(points) == 13
    assert points[0] == {
        "kind": "shell_control",
        "label": "positive_z_pair_shell",
        "detuning_gamma": -3.0,
        "s0": 1.5,
    }
    assert sum(point["kind"] == "single_pass" for point in points) == 12


def test_positive_z_submission_uses_three_full_nodes(tmp_path, monkeypatch):
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
    assert MOT_3D_POSITIVE_Z_PAIR_SCREEN_CONFIG["pbs_walltime"] in generated
