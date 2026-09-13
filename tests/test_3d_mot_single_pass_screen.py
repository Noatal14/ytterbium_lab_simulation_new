from config import MOT_3D_SINGLE_PASS_SCREEN_CONFIG
from studies import submit_3d_mot_single_pass_screen as submitter
from studies.scan_3d_mot_single_pass_screen import screen_points


def test_single_pass_screen_is_small_and_deterministic():
    settings = MOT_3D_SINGLE_PASS_SCREEN_CONFIG
    points = screen_points(
        settings["blue_detuning_gamma_values"], settings["blue_s0_values"]
    )

    assert len(points) == 12
    assert points[0] == (-2.0, 0.75)
    assert points[-1] == (-5.0, 3.0)
    assert settings["fixed_blue_waist_m"] == 15e-3


def test_single_pass_submission_uses_three_full_nodes(tmp_path, monkeypatch):
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
