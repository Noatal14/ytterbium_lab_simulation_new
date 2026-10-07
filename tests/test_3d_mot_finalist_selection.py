from pathlib import Path

import pytest

from studies.select_3d_mot_finalists import select


ROOT = Path("data/optimization/mot_3d/closure_refinement_v1")


@pytest.mark.parametrize("family", ("angled_donut", "single_pass"))
def test_finalist_selection_takes_top_three_closure_lcb_candidates(family):
    payload = select(family, ROOT / family / "merged" / "refinement_summary.json")
    assert payload["candidate_count"] == 3
    assert [row["finalist_rank_from_closure"] for row in payload["candidates"]] == [1, 2, 3]


def test_selected_donut_finalists_preserve_shared_core_shell_boundary():
    payload = select("angled_donut", ROOT / "angled_donut" / "merged" / "refinement_summary.json")
    for candidate in payload["candidates"]:
        split = candidate["parameters"]["core_shell_split_radius_m"]
        profile = candidate["resolved_profile"]
        assert profile["556"]["outer_cutoff_radius_m"] == split
        assert profile["399"]["inner_cutoff_radius_m"] == split
        assert profile["399"]["outer_cutoff_radius_m"] == 0.005


def test_selected_single_pass_finalists_recompute_zeeman_detuning():
    payload = select("single_pass", ROOT / "single_pass" / "merged" / "refinement_summary.json")
    for candidate in payload["candidates"]:
        assert candidate["resolved_profile"]["399"]["detuning_gamma"] == pytest.approx(
            candidate["derived_parameters"]["blue_detuning_gamma"]
        )
