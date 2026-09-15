from config import MOT_3D_DECISION_REPEAT_CONFIG
from studies import submit_3d_mot_decision_repeats as submitter
from studies.run_3d_mot_decision_repeats import load_five_beam_point, representatives


def test_repeat_study_has_three_distinct_decision_families():
    items = representatives()
    assert [name for name, _ in items] == [
        "full_donut",
        "finite_four_blue",
        "five_beam_gravity",
    ]
    finite = items[1][1]
    assert len(finite["399"]["beam_groups"]) == 2
    five = items[2][1]
    assert five["556"]["s0_by_axis"] == {"+X": 6.0}


def test_repeat_study_uses_five_distinct_seeds():
    seeds = MOT_3D_DECISION_REPEAT_CONFIG["repeat_seeds"]
    assert len(seeds) == 5
    assert len(set(seeds)) == 5


def test_repeat_study_can_use_selected_five_beam_summary(tmp_path):
    path = tmp_path / "summary.json"
    path.write_text(
        '{"best_five_beam": {'
        '"kind": "five_beam_gravity", "blue_s0": 1.0, '
        '"blue_detuning_gamma": -2.0, "gradient_G_cm": 1.5, '
        '"paired_green_s0": 10.0, "lower_green_s0": 1.5, '
        '"green_detuning_gamma": -20.0}}'
    )
    point = load_five_beam_point(path)
    items = representatives(
        five_beam_point=point,
        configurations=("full_donut", "five_beam_gravity"),
    )
    assert [name for name, _ in items] == ["full_donut", "five_beam_gravity"]
    five = items[1][1]
    assert five["magnetic_gradient_G_cm"] == 1.5
    assert five["556"]["s0_by_axis"] == {"+X": 1.5}


def test_repeat_submission_uses_three_full_nodes(tmp_path, monkeypatch):
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
    for seed in MOT_3D_DECISION_REPEAT_CONFIG["repeat_seeds"]:
        assert str(seed) in generated
