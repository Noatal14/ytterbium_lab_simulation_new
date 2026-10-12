import json
from pathlib import Path

from studies.mot_3d_campaign import prepare_refinement, render_refinement_transition


SUMMARY_ROOT = Path("data/validation/mot_3d/early_independent_check_v1")
FAMILIES = ("angled_donut", "single_pass")


def test_pure_refinement_transition_matches_canonical_cli_bytes(tmp_path):
    logical = Path("data/optimization/mot_3d/campaign")
    root = tmp_path / logical
    root.mkdir(parents=True)
    manifest = {
        "name": "campaign",
        "stage": "preliminary_check",
        "provenance": {"git_commit": "a" * 40},
        "design": {"screening_dt_s": 1e-5},
        "stages": {},
    }
    summaries = {
        family: json.loads(
            (SUMMARY_ROOT / family / "merged" / "early_check_summary.json").read_text()
        )
        for family in FAMILIES
    }
    rendered, updated = render_refinement_transition(logical, manifest, summaries)
    assert set(rendered) == {
        "campaign.json",
        "selection/refinement/angled_donut.json",
        "selection/refinement/single_pass.json",
        "jobs/refinement/angled_donut_array.pbs",
        "jobs/refinement/angled_donut_merge.pbs",
        "jobs/refinement/single_pass_array.pbs",
        "jobs/refinement/single_pass_merge.pbs",
    }
    assert updated["stage"] == "refinement"
    assert manifest["stage"] == "preliminary_check"
    joined = b"\n".join(rendered.values())
    assert b"/home/" not in joined
    assert str(tmp_path).encode() not in joined
    assert b".." not in joined
    assert render_refinement_transition(root, manifest, summaries) == (rendered, updated)

    for family, summary in summaries.items():
        destination = root / "preliminary_check" / family / "merged"
        destination.mkdir(parents=True)
        (destination / "early_check_summary.json").write_text(json.dumps(summary))
    mutable = json.loads(json.dumps(manifest))
    prepare_refinement(root, mutable)
    assert {
        relative: (root / relative).read_bytes() for relative in rendered
    } == rendered
    assert mutable == updated
