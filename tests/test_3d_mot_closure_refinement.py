from pathlib import Path

import pytest

from studies.select_3d_mot_closure_candidates import select


ROOT = Path("data/optimization/mot_3d/focused_refinement_v1")


@pytest.mark.parametrize("family", ("angled_donut", "single_pass"))
def test_closure_design_has_16_unique_candidates(family):
    payload = select(family, ROOT / family / "merged" / "refinement_summary.json")
    candidates = payload["candidates"]
    assert len(candidates) == 16
    assert len({tuple(sorted(row["parameters"].items())) for row in candidates}) == 16


def test_donut_closure_preserves_shared_boundary_without_outer_blue_clip():
    payload = select("angled_donut", ROOT / "angled_donut" / "merged" / "refinement_summary.json")
    for candidate in payload["candidates"]:
        split = candidate["parameters"]["core_shell_split_radius_m"]
        profile = candidate["resolved_profile"]
        assert profile["556"]["outer_cutoff_radius_m"] == split
        assert profile["399"]["inner_cutoff_radius_m"] == split
        assert "outer_cutoff_radius_m" not in profile["399"]


def test_single_pass_closure_recomputes_zeeman_corrected_detuning():
    payload = select("single_pass", ROOT / "single_pass" / "merged" / "refinement_summary.json")
    for candidate in payload["candidates"]:
        assert candidate["resolved_profile"]["399"]["detuning_gamma"] == pytest.approx(
            candidate["derived_parameters"]["blue_detuning_gamma"]
        )
