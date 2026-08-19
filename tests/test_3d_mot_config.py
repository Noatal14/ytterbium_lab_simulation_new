import copy

import numpy as np
import pytest
from atomsmltr.environment.lasers.polarization import CircularRight

from config import ACTIVE_MOT_3D_CONFIGURATION, MOT_3D_CONFIGURATIONS, BLUE_SATURATION_INTENSITY_MW_CM2
from lab_setup.config_builder import build_base_config
from lab_setup.laser_setup_3d import setup_3dmot_lasers


def _normalize(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def _axis_angle_deg(direction, z_hat=(0.0, 0.0, 1.0)):
    d = _normalize(direction)
    z = np.asarray(z_hat, dtype=float)
    return np.rad2deg(np.arccos(np.clip(abs(np.dot(d, z)), 0.0, 1.0)))


def _unique_directions(beams):
    directions = [_normalize(beam.direction) for beam in beams]
    return {tuple(np.round(d, 12)) for d in directions}


def _resolved_profile(name):
    """Return an isolated copy of a configured experimental profile."""
    return copy.deepcopy(MOT_3D_CONFIGURATIONS[name])


def test_active_3d_mot_profile_is_registered():
    assert ACTIVE_MOT_3D_CONFIGURATION in MOT_3D_CONFIGURATIONS
    profile = MOT_3D_CONFIGURATIONS[ACTIVE_MOT_3D_CONFIGURATION]
    assert "beam_layout" in profile
    assert len(MOT_3D_CONFIGURATIONS) >= 4


def test_angled_concentric_geometry_is_correct():
    profile = _resolved_profile("angled_concentric")
    assert profile["beam_layout"] == "angled_xz_y"
    theta = float(profile["xz_angle_from_z_deg"])
    beams = setup_3dmot_lasers(
        mot_3d_config=profile, center_position=(0.0, 0.0, 0.0)
    )

    unique_dirs = _unique_directions(beams)
    assert len(unique_dirs) == 6

    xz_axes = [np.asarray(d, dtype=float) for d in unique_dirs if abs(d[1]) < 1e-12]
    assert len(xz_axes) == 4
    for d in xz_axes:
        assert np.isclose(np.linalg.norm(d), 1.0)
        assert np.isclose(_axis_angle_deg(d), theta, atol=1e-8)

    y_axes = {d for d in unique_dirs if abs(d[0]) < 1e-12 and abs(d[2]) < 1e-12}
    assert y_axes == {(0.0, 1.0, 0.0), (0.0, -1.0, 0.0)}

    blue_beams = [beam for beam in beams if "3DMOT_399_" in beam.tag]
    green_beams = [beam for beam in beams if "3DMOT_556_" in beam.tag]
    assert len(blue_beams) == 6
    assert len(green_beams) == 6
    assert all(getattr(beam, "profile_kind", "gaussian") == "annular" for beam in blue_beams)
    assert all(getattr(beam, "profile_kind", "gaussian") == "gaussian" for beam in green_beams)

    beam_by_tag = {beam.tag: _normalize(beam.direction) for beam in beams}
    assert np.allclose(beam_by_tag["3DMOT_399_+XZ_1"], -beam_by_tag["3DMOT_399_-XZ_1"])
    assert np.allclose(beam_by_tag["3DMOT_399_+XZ_2"], -beam_by_tag["3DMOT_399_-XZ_2"])
    assert np.allclose(beam_by_tag["3DMOT_399_+Y"], -beam_by_tag["3DMOT_399_-Y"])


def test_angled_sequential_has_separated_blue_and_green_centers():
    beams = setup_3dmot_lasers(
        mot_3d_config=_resolved_profile("angled_sequential"),
        center_position=(0.0, 0.0, 0.0),
    )
    blue_beams = [beam for beam in beams if "3DMOT_399_" in beam.tag]
    green_beams = [beam for beam in beams if "3DMOT_556_" in beam.tag]

    assert len(blue_beams) == 6
    assert len(green_beams) == 6
    blue_center = np.asarray(blue_beams[0].waist_position, dtype=float)
    green_center = np.asarray(green_beams[0].waist_position, dtype=float)
    assert np.allclose(blue_center[:2], green_center[:2])
    assert green_center[2] > blue_center[2]
    assert np.isclose(green_center[2] - blue_center[2], 5.0e-3, atol=1e-12)


def test_five_beam_gravity_removes_upper_x_beam_only():
    profile = _resolved_profile("five_beam_gravity")
    assert profile["beam_layout"] == "orthogonal_minus_upper_x"
    beams = setup_3dmot_lasers(
        mot_3d_config=profile, center_position=(0.0, 0.0, 0.0)
    )
    directions = _unique_directions(beams)

    assert len(directions) == 5
    assert set(directions) == {
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, 0.0, -1.0),
    }
    assert (-1.0, 0.0, 0.0) not in directions

    profile["beam_components"]["+Y"]["399_enabled"] = False
    beams = setup_3dmot_lasers(
        mot_3d_config=profile, center_position=(0.0, 0.0, 0.0)
    )
    assert not any("3DMOT_399_+Y" in beam.tag for beam in beams)
    assert any("3DMOT_556_+Y" in beam.tag for beam in beams)


def test_active_angled_profile_emits_expected_vectors():
    beams = setup_3dmot_lasers(
        mot_3d_config=_resolved_profile("angled_concentric"),
        center_position=(0.0, 0.0, 0.0),
    )
    directions = {tuple(np.round(_normalize(beam.direction), 8)) for beam in beams}
    assert (0.5, 0.0, 0.8660254) in directions
    assert (-0.5, 0.0, 0.8660254) in directions
    assert (-0.5, 0.0, -0.8660254) in directions
    assert (0.5, 0.0, -0.8660254) in directions
    assert (0.0, 1.0, 0.0) in directions
    assert (0.0, -1.0, 0.0) in directions


def test_annular_beam_peak_intensity_matches_target():
    from lab_setup.laser_setup_3d import AnnularGaussianBeam

    beam = AnnularGaussianBeam(
        wavelength=399e-9,
        waist=1e-3,
        power=1e-3,
        polarization=CircularRight(),
        ring_radius=2.5e-3,
        ring_width=1.0e-3,
    )
    target_I0 = 7.5e5
    beam.set_power_from_peak_I(target_I0)
    rho = np.linspace(0.0, 5e-3, 1001)
    intensity = np.array([beam._intensity_func(beam, np.array([[x, 0.0, 0.0]])).item() for x in rho])
    assert intensity[np.argmin(np.abs(rho - beam.ring_radius))] == pytest.approx(target_I0, rel=1e-8)
    assert intensity[0] < intensity[np.argmin(np.abs(rho - beam.ring_radius))]

    invalid = AnnularGaussianBeam
    try:
        invalid(ring_radius=0.0, ring_width=1e-3, polarization=CircularRight())
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for non-positive ring_radius")

    try:
        invalid(ring_radius=1e-3, ring_width=0.0, polarization=CircularRight())
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for non-positive ring_width")


def test_3d_mot_builder_uses_profile_values_not_detuning_arguments():
    mot_cfg = _resolved_profile("angled_concentric")
    mot_cfg["399"]["s0"] = 1.25
    mot_cfg["399"]["waist_m"] = 0.02
    mot_cfg["556"]["s0"] = 7.0

    beams = setup_3dmot_lasers(mot_3d_config=mot_cfg)
    blue = [beam for beam in beams if "3DMOT_399_" in beam.tag][0]
    green = [beam for beam in beams if "3DMOT_556_" in beam.tag][0]

    assert blue.waist == pytest.approx(0.02)
    assert blue.power > 0.0
    assert green.power > 0.0
    assert not hasattr(blue, "detuning")


def test_config_builder_applies_detuning_in_atom_light_coupling():
    test_cfg = {
        "beam_layout": "orthogonal_counterpropagating",
        "center_position_m": (0.0, 0.0, 0.413),
        "399": {"enabled": True, "s0": 0.5, "detuning_gamma": -2.0, "waist_m": 0.01, "profile": "gaussian"},
        "556": {"enabled": True, "s0": 5.0, "detuning_gamma": -2.0, "waist_m": 0.015, "profile": "gaussian"},
    }
    atom, config = build_base_config(
        include_2d_mot=False,
        include_zeeman=False,
        include_3dmot=True,
        _3d_mot_config=test_cfg,
        zones=[],
    )
    couplings = config._Configuration__atomlight
    assert couplings is not None

    for transition_tag, detuning in [
        ("399", -2.0 * atom.trans["399"].Gamma),
        ("556", -2.0 * atom.trans["556"].Gamma),
    ]:
        laser_tag = next(k for k in couplings[transition_tag].keys())
        coupling = couplings[transition_tag][laser_tag]
        assert coupling["detuning"] == pytest.approx(detuning)
