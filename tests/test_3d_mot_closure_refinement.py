import json

import pytest

from studies.mot_3d.refinement.select_closure import select


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
def refinement_summary(tmp_path):
    def write(family):
        path = tmp_path / f"{family}_refinement_summary.json"
        path.write_text(
            json.dumps(
                {
                    "family": family,
                    "ranked_candidates": [
                        {
                            "candidate_id": f"{family}_leader",
                            "parameters": BASE_PARAMETERS[family],
                        }
                    ],
                }
            )
        )
        return path

    return write


@pytest.mark.parametrize("family", ("angled_donut", "single_pass"))
def test_closure_design_has_16_unique_candidates(family, refinement_summary):
    payload = select(family, refinement_summary(family))
    candidates = payload["candidates"]
    assert len(candidates) == 16
    assert len({tuple(sorted(row["parameters"].items())) for row in candidates}) == 16


def test_donut_closure_preserves_shared_boundary_and_shared_hole(refinement_summary):
    payload = select("angled_donut", refinement_summary("angled_donut"))
    for candidate in payload["candidates"]:
        split = candidate["parameters"]["core_shell_split_radius_m"]
        profile = candidate["resolved_profile"]
        assert profile["556"]["outer_cutoff_radius_m"] == split
        assert profile["399"]["inner_cutoff_radius_m"] == split
        assert profile["399"]["outer_cutoff_radius_m"] == 0.005


def test_single_pass_closure_recomputes_zeeman_corrected_detuning(refinement_summary):
    payload = select("single_pass", refinement_summary("single_pass"))
    for candidate in payload["candidates"]:
        assert candidate["resolved_profile"]["399"]["detuning_gamma"] == pytest.approx(
            candidate["derived_parameters"]["blue_detuning_gamma"]
        )
