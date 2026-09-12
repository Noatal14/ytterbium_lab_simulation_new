import numpy as np

from config import MOT_3D_DONUT_ABLATION_CONFIG
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from studies import submit_3d_mot_donut_ablation as submitter
from studies.analyze_3d_mot_donut_ablation import (
    VARIANT_ORDER,
    _exposure_episode_count,
    build_ablation_profiles,
)


def _blue_tags(profile):
    return {
        beam.tag.removeprefix("3DMOT_399_")
        for beam in setup_3dmot_lasers(profile)
        if "3DMOT_399_" in beam.tag
    }


def test_ablation_profiles_isolate_the_intended_blue_functions():
    profiles = build_ablation_profiles()
    assert tuple(profiles) == VARIANT_ORDER
    assert _blue_tags(profiles["full_donut"]) == {
        "+XZ_1", "-XZ_1", "+XZ_2", "-XZ_2", "+Y", "-Y"
    }
    assert _blue_tags(profiles["without_positive_z_blue"]) == {
        "-XZ_1", "-XZ_2", "+Y", "-Y"
    }
    assert _blue_tags(profiles["without_transverse_y_blue"]) == {
        "+XZ_1", "-XZ_1", "+XZ_2", "-XZ_2"
    }
    assert _blue_tags(profiles["counterpropagating_pair_shell"]) == {"-XZ_1", "-XZ_2"}
    assert _blue_tags(profiles["single_pass_counterpropagating_pair"]) == {"-XZ_1", "-XZ_2"}


def test_single_pass_pair_is_dark_after_cutoff_but_shell_pair_is_not():
    profiles = build_ablation_profiles()
    center = np.asarray(profiles["full_donut"]["center_position_m"], dtype=float)
    point = center + np.array([12e-3, 0.0, 1e-3])
    shell = [b for b in setup_3dmot_lasers(profiles["counterpropagating_pair_shell"]) if "399" in b.tag]
    single = [b for b in setup_3dmot_lasers(profiles["single_pass_counterpropagating_pair"]) if "399" in b.tag]
    assert sum(b.get_value(point[None, :])[0] for b in shell) > 0.0
    assert sum(b.get_value(point[None, :])[0] for b in single) == 0.0


def test_exposure_episode_counter_counts_separate_encounters():
    intensities = np.array([[0.0, 2.0, 2.0, 0.0, 0.0, 3.0, 0.0]])
    assert _exposure_episode_count(intensities) == 2


def test_submission_requests_three_full_nodes_and_dependent_merge(tmp_path, monkeypatch):
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
    assert MOT_3D_DONUT_ABLATION_CONFIG["pbs_ncpus_per_shard"] == 200
