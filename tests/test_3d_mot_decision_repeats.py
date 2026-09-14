from config import MOT_3D_DECISION_REPEAT_CONFIG
from studies import submit_3d_mot_decision_repeats as submitter
from studies.run_3d_mot_decision_repeats import representatives


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
