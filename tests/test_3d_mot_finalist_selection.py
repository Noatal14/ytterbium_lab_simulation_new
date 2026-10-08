import json

import pytest

from studies.mot_3d.finalists.select import select

BASE_PARAMETERS = {
    "angled_donut": {
        "green_s0": 18.0,
        "green_detuning_gamma": -18.0,
        "green_waist_m": 0.0065,
        "blue_s0": 1.4,
        "blue_waist_m": 0.0074,
        "magnetic_gradient_G_cm": 5.5,
        "blue_detuning_gamma": -0.8,
        "core_shell_split_radius_m": 0.0026,
    },
    "single_pass": {
        "green_s0": 38.0,
        "green_detuning_gamma": -25.0,
        "green_waist_m": 0.0074,
        "blue_s0": 0.2,
        "blue_waist_m": 0.0073,
        "magnetic_gradient_G_cm": 2.3,
        "blue_detuning_anchor_gamma": -2.5,
        "blue_crossing_angle_deg": 46.0,
        "blue_crossing_z_offset_m": -0.046,
    },
}


@pytest.fixture
def closure_summary(tmp_path):
    def write(family):
        rows = []
        for index in range(3):
            parameters = dict(BASE_PARAMETERS[family])
            parameters["green_s0"] += index
            rows.append(
                {
                    "candidate_id": f"{family}_closure_{index:02d}",
                    "closure_role": f"synthetic_rank_{index + 1}",
                    "mean_usable_fraction": 0.7 - 0.01 * index,
                    "bootstrap_95_ci": [0.68 - 0.01 * index, 0.72 - 0.01 * index],
                    "parameters": parameters,
                }
            )
        path = tmp_path / f"{family}_closure_summary.json"
        path.write_text(json.dumps({"family": family, "ranked_candidates": rows}))
        return path

    return write


@pytest.mark.parametrize("family", ("angled_donut", "single_pass"))
def test_finalist_selection_takes_top_three_closure_lcb_candidates(family, closure_summary):
    payload = select(family, closure_summary(family))
    assert payload["candidate_count"] == 3
    assert [row["finalist_rank_from_closure"] for row in payload["candidates"]] == [1, 2, 3]


def test_selected_donut_finalists_preserve_shared_core_shell_boundary(closure_summary):
    payload = select("angled_donut", closure_summary("angled_donut"))
    for candidate in payload["candidates"]:
        split = candidate["parameters"]["core_shell_split_radius_m"]
        profile = candidate["resolved_profile"]
        assert profile["556"]["outer_cutoff_radius_m"] == split
        assert profile["399"]["inner_cutoff_radius_m"] == split
        assert profile["399"]["outer_cutoff_radius_m"] == 0.005


def test_selected_single_pass_finalists_recompute_zeeman_detuning(closure_summary):
    payload = select("single_pass", closure_summary("single_pass"))
    for candidate in payload["candidates"]:
        assert candidate["resolved_profile"]["399"]["detuning_gamma"] == pytest.approx(
            candidate["derived_parameters"]["blue_detuning_gamma"]
        )
