import json
from pathlib import Path

import pytest

from studies.mot_3d.refinement.select import select


ROOT = Path("data/validation/mot_3d/early_independent_check_v1")


@pytest.mark.parametrize("family", ("angled_donut", "single_pass"))
def test_refinement_design_has_16_unique_in_bounds_candidates(family):
    payload = select(family, ROOT / family / "merged" / "early_check_summary.json")
    candidates = payload["candidates"]
    bounds = payload["parameter_bounds"]

    assert len(candidates) == 16
    assert len({tuple(sorted(row["parameters"].items())) for row in candidates}) == 16
    assert candidates[0]["refinement_role"] == "early_check_leader"
    for candidate in candidates:
        for key, (lower, upper) in bounds.items():
            assert lower <= candidate["parameters"][key] <= upper


def test_donut_refinement_preserves_one_shared_core_shell_boundary():
    payload = select(
        "angled_donut",
        ROOT / "angled_donut" / "merged" / "early_check_summary.json",
    )
    for candidate in payload["candidates"]:
        split = candidate["parameters"]["core_shell_split_radius_m"]
        profile = candidate["resolved_profile"]
        assert profile["556"]["outer_cutoff_radius_m"] == split
        assert profile["399"]["inner_cutoff_radius_m"] == split
        assert profile["399"]["outer_cutoff_radius_m"] == 0.005


def test_single_pass_refinement_records_zeeman_corrected_detuning():
    payload = select(
        "single_pass",
        ROOT / "single_pass" / "merged" / "early_check_summary.json",
    )
    for candidate in payload["candidates"]:
        derived = candidate["derived_parameters"]
        assert candidate["resolved_profile"]["399"]["detuning_gamma"] == pytest.approx(
            derived["blue_detuning_gamma"]
        )
