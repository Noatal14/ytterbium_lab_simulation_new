import copy

import numpy as np
from atomsmltr.simulation.simulator.simbase import get_force_vec

from config import MOT_3D_BLUE_GATE_SEQUENCE_CONFIG
from lab_setup.config_builder import build_base_config
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from studies import submit_3d_mot_blue_gate_sequence as submitter
from studies.scan_3d_mot_blue_gate_sequence import build_gate_profiles


def _blue(profile):
    return [beam for beam in setup_3dmot_lasers(profile) if "399" in beam.tag]


def _blue_force(profile, z_offset_m, vz_m_s, x_offset_m=12e-3):
    isolated = copy.deepcopy(profile)
    isolated["556"]["enabled"] = False
    _, simulation_config = build_base_config(
        include_2d_mot=False,
        include_zeeman=False,
        include_3dmot=True,
        _3d_mot_config=isolated,
        gravity_enabled=False,
        zones=[],
    )
    center = np.asarray(profile["center_position_m"], dtype=float)
    state = np.array(
        [[*(center + np.array([x_offset_m, 0.0, z_offset_m])), 0.0, 0.0, vz_m_s]]
    )
    return np.asarray(get_force_vec(state, simulation_config)[0], dtype=float)


def test_gate_variants_have_expected_blue_beam_counts_and_dark_center():
    profiles = build_gate_profiles()
    assert [len(_blue(profiles[name])) for name in profiles] == [6, 2, 4, 4, 6]
    center = np.asarray(profiles["single_minus_z_gate"]["center_position_m"])[None, :]
    for name, profile in profiles.items():
        if name == "full_donut_control":
            continue
        assert all(float(beam.get_value(center)[0]) == 0.0 for beam in _blue(profile))


def test_each_gate_force_points_against_the_selected_atomic_motion():
    settings = MOT_3D_BLUE_GATE_SEQUENCE_CONFIG
    profiles = build_gate_profiles()
    first_force = _blue_force(
        profiles["single_minus_z_gate"],
        settings["first_slowing_crossing_offset_m"],
        12.0,
    )
    assert first_force[2] < 0.0

    return_only = copy.deepcopy(profiles["minus_z_plus_return_gate"])
    return_only["399"]["beam_groups"] = [
        return_only["399"]["beam_groups"][1]
    ]
    return_force = _blue_force(
        return_only, settings["return_crossing_offset_m"], -12.0
    )
    assert return_force[2] > 0.0


def test_gate_submission_uses_three_full_nodes(tmp_path, monkeypatch):
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
