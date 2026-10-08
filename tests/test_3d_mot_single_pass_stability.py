import json

import numpy as np
import pytest

from config import MOT_3D_CONFIGURATIONS
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from studies.mot_3d.validation.single_pass_stability import (
    BLUE_APERTURE_RADIUS_M,
    GREEN_APERTURE_RADIUS_M,
    REFERENCE_S0,
    stability_profile,
    study_points,
)
from studies.mot_3d.validation.submit_single_pass_stability import (
    _array_body,
    _validate_inputs,
)


@pytest.fixture
def single_pass_selection(tmp_path):
    path = tmp_path / "single_pass_finalists.json"
    path.write_text(
        json.dumps(
            {
                "family": "single_pass",
                "candidates": [
                    {"resolved_profile": MOT_3D_CONFIGURATIONS["single_pass"]}
                ],
            }
        )
    )
    return path


def test_factorial_and_dense_scan_are_paired_without_duplicate_reference():
    points = study_points()
    factorial = [point for point in points if point["role"] == "factorial"]
    dense = [point for point in points if point["variant"] == "angle62_clipped"]
    assert len(factorial) == 4
    assert len(points) == 17
    assert sum(np.isclose(point["blue_s0"], REFERENCE_S0) for point in dense) == 1
    assert min(point["blue_s0"] for point in dense) == pytest.approx(0.16)
    assert max(point["blue_s0"] for point in dense) == pytest.approx(0.28)


def test_62_degree_clipped_profile_has_approved_hard_apertures(single_pass_selection):
    profile = stability_profile("angle62_clipped", REFERENCE_S0, single_pass_selection)
    assert profile["xz_angle_from_z_deg"] == pytest.approx(31.0)
    assert profile["399"]["profile"] == "outer_clipped_gaussian"
    assert profile["399"]["outer_cutoff_radius_m"] == pytest.approx(7.5e-3)
    assert profile["556"]["profile"] == "outer_clipped_gaussian"
    assert profile["556"]["outer_cutoff_radius_m"] == pytest.approx(5e-3)

    beams = setup_3dmot_lasers(profile)
    blue = next(beam for beam in beams if beam.tag == "3DMOT_399_SP_FROM_NEG_Y")
    green = next(beam for beam in beams if beam.tag == "3DMOT_556_+Y")
    assert blue.outer_cutoff_radius == pytest.approx(BLUE_APERTURE_RADIUS_M)
    assert green.outer_cutoff_radius == pytest.approx(GREEN_APERTURE_RADIUS_M)

    # Probe in each beam's own transverse plane, at its waist position.
    blue_center = np.asarray(blue.waist_position)
    green_center = np.asarray(green.waist_position)
    assert blue.get_value((blue_center + np.array([7.4e-3, 0.0, 0.0]))[None, :])[0] > 0
    assert blue.get_value((blue_center + np.array([7.6e-3, 0.0, 0.0]))[None, :])[0] == 0
    assert (
        green.get_value((green_center + np.array([4.9e-3, 0.0, 0.0]))[None, :])[0] > 0
    )
    assert (
        green.get_value((green_center + np.array([5.1e-3, 0.0, 0.0]))[None, :])[0] == 0
    )


def test_factorial_changes_only_angle_and_aperture_flags(single_pass_selection):
    baseline = stability_profile("angle60_unclipped", REFERENCE_S0, single_pass_selection)
    angle = stability_profile("angle62_unclipped", REFERENCE_S0, single_pass_selection)
    clipped = stability_profile("angle60_clipped", REFERENCE_S0, single_pass_selection)
    both = stability_profile("angle62_clipped", REFERENCE_S0, single_pass_selection)

    assert baseline["xz_angle_from_z_deg"] == pytest.approx(30.0)
    assert angle["xz_angle_from_z_deg"] == pytest.approx(31.0)
    assert clipped["xz_angle_from_z_deg"] == pytest.approx(30.0)
    assert both["xz_angle_from_z_deg"] == pytest.approx(31.0)
    assert baseline["399"]["profile"] == angle["399"]["profile"] == "gaussian"
    assert clipped["399"]["profile"] == both["399"]["profile"]
    assert baseline["399"]["s0"] == angle["399"]["s0"] == REFERENCE_S0


def test_submission_array_propagates_explicit_quoted_inputs():
    body = _array_body("states with spaces", "selection;literal.json")
    assert "--input 'states with spaces'" in body
    assert "--selection 'selection;literal.json'" in body
    assert '--shard-index "$PBS_ARRAY_INDEX"' in body


def test_submission_rejects_wrong_family_selection(tmp_path):
    states = tmp_path / "states.npy"
    states.touch()
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"family": "angled_donut", "candidates": [{}]}))
    with pytest.raises(ValueError, match="single-pass"):
        _validate_inputs(states, selection)
