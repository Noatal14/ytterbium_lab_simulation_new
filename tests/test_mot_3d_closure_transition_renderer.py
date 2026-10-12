import json
from pathlib import Path

from studies.mot_3d_campaign import prepare_closure, render_closure_transition


SUMMARY_ROOT = Path("data/validation/mot_3d/early_independent_check_v1")
FAMILIES = ("angled_donut", "single_pass")


def _refinement_summaries():
    summaries = {}
    for family in FAMILIES:
        source = json.loads(
            (SUMMARY_ROOT / family / "merged" / "early_check_summary.json").read_text()
        )
        rows = []
        for index, row in enumerate(source["ranked_candidates"]):
            rows.append(
                {
                    "candidate_id": f"{family}_refine_{index:02d}",
                    "refinement_role": (
                        "early_check_leader" if index == 0 else f"anchor_{index}"
                    ),
                    "parameters": row["parameters"],
                    "mean_usable_fraction": row["mean_usable_fraction"],
                    "simultaneous_95_ci": row["bootstrap_95_ci"],
                }
            )
        summaries[family] = {"family": family, "ranked_candidates": rows}
    return summaries


def test_pure_closure_transition_matches_canonical_cli_bytes(tmp_path):
    logical = Path("data/optimization/mot_3d/campaign")
    root = tmp_path / logical
    root.mkdir(parents=True)
    manifest = {
        "name": "campaign",
        "stage": "refinement",
        "provenance": {"git_commit": "a" * 40},
        "design": {"screening_dt_s": 1e-5},
        "stages": {},
    }
    summaries = _refinement_summaries()
    rendered, updated = render_closure_transition(logical, manifest, summaries)
    assert set(rendered) == {
        "campaign.json",
        "selection/closure/angled_donut.json",
        "selection/closure/single_pass.json",
        "jobs/closure/angled_donut_array.pbs",
        "jobs/closure/angled_donut_merge.pbs",
        "jobs/closure/single_pass_array.pbs",
        "jobs/closure/single_pass_merge.pbs",
    }
    assert updated["stage"] == "closure"
    assert manifest["stage"] == "refinement"
    joined = b"\n".join(rendered.values())
    assert b"/home/" not in joined
    assert str(tmp_path).encode() not in joined
    assert b".." not in joined
    assert render_closure_transition(root, manifest, summaries) == (rendered, updated)

    for family, summary in summaries.items():
        destination = root / "refinement" / family / "merged"
        destination.mkdir(parents=True)
        (destination / "refinement_summary.json").write_text(json.dumps(summary))
    mutable = json.loads(json.dumps(manifest))
    prepare_closure(root, mutable)
    assert {
        relative: (root / relative).read_bytes() for relative in rendered
    } == rendered
    assert mutable == updated
