import copy

import numpy as np

from config import MOT_3D_CONFIGURATIONS, MOT_3D_SCREENING_CONFIG
from studies.screen_3d_mot_configurations import (
    apply_anchor,
    screening_rank_key,
    static_force_diagnostics,
)
from studies import submit_3d_mot_screening as submitter
from studies.merge_3d_mot_screening_shards import screening_verdict


def test_screening_anchors_include_six_probes_and_donut_positive_control():
    anchors = MOT_3D_SCREENING_CONFIG["anchors"]
    assert len(anchors) == 7
    assert all(point["blue_s0"] > 0 for point in anchors)
    assert all(point["blue_detuning_gamma"] < 0 for point in anchors)
    assert all(point["green_s0"] > 0 for point in anchors)
    assert all(point["green_detuning_gamma"] < 0 for point in anchors)
    assert all(point["gradient_G_cm"] > 0 for point in anchors)


def test_anchor_changes_parameters_without_mutating_configuration():
    original = MOT_3D_CONFIGURATIONS["angled_sequential"]
    profile = copy.deepcopy(original)
    anchor = MOT_3D_SCREENING_CONFIG["anchors"][0]
    apply_anchor(profile, anchor)
    assert profile["399"]["s0"] == anchor["blue_s0"]
    assert profile["556"]["detuning_gamma"] == anchor["green_detuning_gamma"]
    assert original["399"]["s0"] != anchor["blue_s0"]


def test_four_beam_candidate_splits_nominal_blue_intensity_between_two_pairs():
    profile = copy.deepcopy(MOT_3D_CONFIGURATIONS["dual_plane_four_blue"])
    anchor = MOT_3D_SCREENING_CONFIG["anchors"][1]
    apply_anchor(profile, anchor)
    assert profile["399"]["s0"] == 0.5 * anchor["blue_s0"]


def test_screening_rank_rejects_nonrestoring_candidate_first():
    base = {
        "capture_eligible_ever_count": 0,
        "slow_inside_count": 2,
        "minimum_residence_met_count": 0,
        "median_minimum_speed_inside_m_s": 5.0,
        "median_delta_vz_during_blue_exposure_m_s": -10.0,
        "blue_exposed_particle_count": 10,
    }
    restoring = {**base, "green_restoring_all_axes": True}
    nonrestoring = {**base, "green_restoring_all_axes": False, "capture_eligible_ever_count": 20}
    assert screening_rank_key(restoring) > screening_rank_key(nonrestoring)


def test_submission_uses_three_full_nodes_and_dependent_merge(tmp_path, monkeypatch):
    submitted = []

    def fake_submit(path, dependency=None):
        submitted.append((path, dependency))
        return f"job{len(submitted)}"

    monkeypatch.setattr(submitter, "_submit", fake_submit)
    assert submitter.submit_screening(tmp_path, ["angled_sequential"], 600) == "job2"
    assert submitted[1][1] == "job1"
    generated = "\n".join(path.read_text() for path, _ in submitted)
    assert "--max-atoms 600" in generated
    assert "--num-shards 3" in generated
    assert "#PBS -l select=1:ncpus=200:mem=64gb" in generated
    assert "--npools 200" in generated
    assert "merge_3d_mot_screening_shards" in generated


def test_static_screen_finds_restoring_equilibrium_for_every_current_profile():
    sample_states = np.zeros((2, 6))
    sample_states[:, 5] = 10.0
    anchor = MOT_3D_SCREENING_CONFIG["anchors"][0]
    for base in MOT_3D_CONFIGURATIONS.values():
        profile = apply_anchor(copy.deepcopy(base), anchor)
        diagnostics = static_force_diagnostics(
            profile,
            sample_states,
            anchor["gradient_G_cm"],
            MOT_3D_SCREENING_CONFIG["force_displacement_m"],
        )
        assert diagnostics["green_equilibrium_found"]
        assert diagnostics["green_restoring_all_axes"]


def test_verdict_can_pass_without_observing_a_rare_full_capture():
    row = {
        "green_restoring_all_axes": True,
        "blue_center_intensity_W_m2": 0.0,
        "input_particle_count": 100,
        "blue_exposed_particle_count": 80,
        "weighted_mean_of_shard_medians_delta_vz_during_blue_exposure_m_s": -2.0,
        "capture_eligible_ever_count": 0,
    }
    assert screening_verdict([row])["verdict"] == "promising_for_confirmation"
