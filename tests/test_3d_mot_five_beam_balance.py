import numpy as np
import pytest

from config import MOT_3D_FIVE_BEAM_BALANCE_SCREEN_CONFIG
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from studies import submit_3d_mot_five_beam_balance as submitter
from studies.scan_3d_mot_five_beam_balance import (
    equilibrium_displacement_m,
    profile_with_lower_green_s0,
)


def _green_peak_intensity_by_tag(profile):
    return {
        beam.tag.removeprefix("3DMOT_556_"): beam.get_value(
            np.asarray(profile["center_position_m"])[None, :]
        )[0]
        for beam in setup_3dmot_lasers(profile)
        if "3DMOT_556_" in beam.tag
    }


def test_only_lower_green_beam_gets_intensity_override():
    profile = profile_with_lower_green_s0(6.55)
    intensities = _green_peak_intensity_by_tag(profile)

    assert intensities["+X"] / intensities["+YZ_1"] == pytest.approx(0.655)
    assert intensities["+YZ_1"] == pytest.approx(intensities["-YZ_1"])
    assert intensities["+YZ_2"] == pytest.approx(intensities["-YZ_2"])


def test_balance_candidate_moves_equilibrium_close_to_field_zero():
    baseline = equilibrium_displacement_m(profile_with_lower_green_s0(10.0))
    balanced = equilibrium_displacement_m(profile_with_lower_green_s0(6.55))

    assert baseline == pytest.approx(0.82325e-3, abs=1e-7)
    assert abs(balanced) < 0.05e-3


def test_balance_submission_uses_three_full_nodes(tmp_path, monkeypatch):
    submitted = []

    def fake_submit(path, dependency=None):
        submitted.append((path, dependency))
        return f"job{len(submitted)}"

    monkeypatch.setattr(submitter, "_submit", fake_submit)
    assert submitter.submit(tmp_path) == "job2"
    assert submitted[1][1] == "job1"
    generated = submitted[0][0].read_text()
    assert "#PBS -l select=1:ncpus=200:mem=64gb" in generated
    assert "--max-atoms 600" in generated
    assert "--num-shards 3" in generated
    assert "--npools 200" in generated


def test_balance_grid_contains_analytic_point_and_current_baseline():
    assert MOT_3D_FIVE_BEAM_BALANCE_SCREEN_CONFIG["lower_green_s0_values"] == (
        5.0,
        6.0,
        6.55,
        7.0,
        8.0,
        10.0,
    )
