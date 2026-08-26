import copy

import numpy as np
import pytest
from atomsmltr.environment.lasers.polarization import CircularRight
from atomsmltr.simulation.simulator.simbase import get_force_vec

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


def _single_wavelength_config(wavelength_key):
    profile = _resolved_profile("angled_sequential")
    other_key = "556" if wavelength_key == "399" else "399"
    profile[other_key]["enabled"] = False
    _, simulation_config = build_base_config(
        include_2d_mot=False,
        include_zeeman=False,
        include_3dmot=True,
        _3d_mot_config=profile,
        zones=[],
    )
    return profile, simulation_config


def _force_at(simulation_config, position, velocity=(0.0, 0.0, 0.0)):
    state = np.array([[*position, *velocity]], dtype=float)
    return np.asarray(get_force_vec(state, simulation_config)[0], dtype=float)


def test_active_3d_mot_profile_is_registered():
    assert ACTIVE_MOT_3D_CONFIGURATION in MOT_3D_CONFIGURATIONS
    profile = MOT_3D_CONFIGURATIONS[ACTIVE_MOT_3D_CONFIGURATION]
    assert "beam_layout" in profile
    assert len(MOT_3D_CONFIGURATIONS) == 3
    assert "orthogonal_counterpropagating" not in MOT_3D_CONFIGURATIONS


def test_angled_donut_geometry_is_correct():
    profile = _resolved_profile("angled_donut")
    assert profile["399"]["inner_cutoff_radius_m"] == pytest.approx(0.01)
    assert "ring_radius_m" not in profile["399"]
    assert "ring_width_m" not in profile["399"]
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
    assert all(getattr(beam, "profile_kind", "gaussian") == "donut" for beam in blue_beams)
    assert all(getattr(beam, "profile_kind", "gaussian") == "gaussian" for beam in green_beams)

    beam_by_tag = {beam.tag: _normalize(beam.direction) for beam in beams}
    assert np.allclose(beam_by_tag["3DMOT_399_+XZ_1"], -beam_by_tag["3DMOT_399_-XZ_1"])
    assert np.allclose(beam_by_tag["3DMOT_399_+XZ_2"], -beam_by_tag["3DMOT_399_-XZ_2"])
    assert np.allclose(beam_by_tag["3DMOT_399_+Y"], -beam_by_tag["3DMOT_399_-Y"])


def test_angled_sequential_matches_plotkin_swing_crossed_beam_geometry():
    beams = setup_3dmot_lasers(
        mot_3d_config=_resolved_profile("angled_sequential"),
        center_position=(0.0, 0.0, 0.0),
    )
    blue_beams = [beam for beam in beams if "3DMOT_399_" in beam.tag]
    green_beams = [beam for beam in beams if "3DMOT_556_" in beam.tag]

    assert len(blue_beams) == 2
    assert len(green_beams) == 6
    blue_center = np.asarray(blue_beams[0].waist_position, dtype=float)
    green_center = np.asarray(green_beams[0].waist_position, dtype=float)
    assert np.allclose(blue_center, (0.0, 0.0, -10.0e-3))
    assert np.allclose(green_center, (0.0, 0.0, 0.0))

    blue_directions = [_normalize(beam.direction) for beam in blue_beams]
    assert all(
        np.isclose(direction[2], -1.0 / np.sqrt(2.0))
        for direction in blue_directions
    )
    assert np.isclose(blue_directions[0][0], -blue_directions[1][0])
    assert all(beam.profile_kind == "elliptical" for beam in blue_beams)
    assert all(beam.wx == pytest.approx(1.5e-3) for beam in blue_beams)
    assert all(beam.wy == pytest.approx(10.0e-3) for beam in blue_beams)

    profile = MOT_3D_CONFIGURATIONS["angled_sequential"]
    assert profile["399"]["s0"] == pytest.approx(0.3)
    assert profile["399"]["detuning_gamma"] == pytest.approx(-1.45)
    assert "detuning_hz" not in profile["399"]


def test_crossed_blue_beams_slow_positive_z_atoms():
    profile, simulation_config = _single_wavelength_config("399")
    crossing = np.asarray(profile["center_position_m"], dtype=float)
    crossing += np.asarray(profile["399"]["center_offset_m"], dtype=float)

    force = _force_at(simulation_config, crossing, velocity=(0.0, 0.0, 10.0))

    assert force[2] < 0.0


@pytest.mark.parametrize("z_offset_m", [-0.5e-3, 0.0, 0.5e-3])
def test_crossed_blue_beam_transverse_forces_cancel_on_atomic_axis(z_offset_m):
    profile, simulation_config = _single_wavelength_config("399")
    position = np.asarray(profile["center_position_m"], dtype=float)
    position += np.asarray(profile["399"]["center_offset_m"], dtype=float)
    position[2] += z_offset_m

    force = _force_at(simulation_config, position, velocity=(0.0, 0.0, 10.0))

    transverse = np.linalg.norm(force[:2])
    assert force[2] < 0.0
    assert transverse <= 1e-6 * abs(force[2]) + 1e-30


@pytest.mark.parametrize("axis", [0, 1, 2])
@pytest.mark.parametrize("displacement_sign", [-1.0, 1.0])
def test_green_mot_force_is_restoring_on_every_axis(axis, displacement_sign):
    profile, simulation_config = _single_wavelength_config("556")
    center = np.asarray(profile["center_position_m"], dtype=float)
    displacement = np.zeros(3)
    displacement[axis] = displacement_sign * 0.5e-3

    force = _force_at(simulation_config, center + displacement)

    assert force[axis] * displacement[axis] < 0.0


def test_crossed_blue_elliptical_intensity_in_lab_coordinates():
    profile = _resolved_profile("angled_sequential")
    beams = setup_3dmot_lasers(mot_3d_config=profile)
    blue_beams = [beam for beam in beams if "3DMOT_399_" in beam.tag]
    expected_ratio = np.exp(-2.0)

    for beam in blue_beams:
        center = np.asarray(beam.waist_position, dtype=float)
        direction = _normalize(beam.direction)
        short_axis_lab = _normalize(np.cross((0.0, 1.0, 0.0), direction))
        long_axis_lab = np.array([0.0, 1.0, 0.0])

        peak = float(beam.get_value(np.array([center]))[0])
        short_value = float(
            beam.get_value(np.array([center + beam.wx * short_axis_lab]))[0]
        )
        long_value = float(
            beam.get_value(np.array([center + beam.wy * long_axis_lab]))[0]
        )

        assert short_value / peak == pytest.approx(expected_ratio, rel=1e-10)
        assert long_value / peak == pytest.approx(expected_ratio, rel=1e-10)


def test_five_beam_gravity_removes_upper_x_beam_only():
    profile = _resolved_profile("five_beam_gravity")
    assert profile["399"]["inner_cutoff_radius_m"] == pytest.approx(0.01)
    assert profile["beam_layout"] == "rotated_yz_minus_upper_x"
    beams = setup_3dmot_lasers(
        mot_3d_config=profile, center_position=(0.0, 0.0, 0.0)
    )
    directions = _unique_directions(beams)

    assert len(directions) == 5
    diagonal = np.round(np.sqrt(0.5), 12)
    assert set(directions) == {
        (1.0, 0.0, 0.0),
        (0.0, diagonal, diagonal),
        (0.0, -diagonal, -diagonal),
        (0.0, -diagonal, diagonal),
        (0.0, diagonal, -diagonal),
    }
    assert (-1.0, 0.0, 0.0) not in directions

    positive_z_axes = [
        np.asarray(direction)
        for direction in directions
        if np.isclose(direction[2], diagonal)
    ]
    assert len(positive_z_axes) == 2
    assert all(
        np.isclose(_axis_angle_deg(direction), 45.0)
        for direction in positive_z_axes
    )
    assert np.isclose(np.dot(positive_z_axes[0], positive_z_axes[1]), 0.0)

    blue_beams = [beam for beam in beams if "3DMOT_399_" in beam.tag]
    green_beams = [beam for beam in beams if "3DMOT_556_" in beam.tag]
    assert len(blue_beams) == 5
    assert len(green_beams) == 5
    assert all(beam.profile_kind == "donut" for beam in blue_beams)
    assert all(beam.profile_kind == "gaussian" for beam in green_beams)
    assert all(
        np.allclose(blue.waist_position, green.waist_position)
        for blue, green in zip(blue_beams, green_beams)
    )

    profile["beam_components"]["+YZ_1"]["399_enabled"] = False
    beams = setup_3dmot_lasers(
        mot_3d_config=profile, center_position=(0.0, 0.0, 0.0)
    )
    assert not any("3DMOT_399_+YZ_1" in beam.tag for beam in beams)
    assert any("3DMOT_556_+YZ_1" in beam.tag for beam in beams)


def test_active_angled_profile_emits_expected_vectors():
    beams = setup_3dmot_lasers(
        mot_3d_config=_resolved_profile("angled_donut"),
        center_position=(0.0, 0.0, 0.0),
    )
    directions = {tuple(np.round(_normalize(beam.direction), 8)) for beam in beams}
    assert (0.5, 0.0, 0.8660254) in directions
    assert (-0.5, 0.0, 0.8660254) in directions
    assert (-0.5, 0.0, -0.8660254) in directions
    assert (0.5, 0.0, -0.8660254) in directions
    assert (0.0, 1.0, 0.0) in directions
    assert (0.0, -1.0, 0.0) in directions


def test_donut_is_an_unmodified_gaussian_with_a_hard_central_cutoff():
    from lab_setup.laser_setup_3d import DonutGaussianBeam

    beam = DonutGaussianBeam(
        wavelength=399e-9,
        waist=1e-3,
        power=1e-3,
        polarization=CircularRight(),
        inner_cutoff_radius=1.0e-3,
    )
    target_I0 = 7.5e5
    beam.set_power_from_peak_I(target_I0)
    rho = np.linspace(0.0, 5e-3, 1001)
    intensity = np.array([beam._intensity_func(beam, np.array([[x, 0.0, 0.0]])).item() for x in rho])
    assert np.all(intensity[rho < beam.inner_cutoff_radius] == 0.0)
    outside = rho >= beam.inner_cutoff_radius
    expected = target_I0 * np.exp(-2.0 * rho[outside] ** 2 / beam.waist**2)
    assert np.allclose(intensity[outside], expected)
    assert intensity[np.flatnonzero(outside)[0]] > intensity[np.flatnonzero(outside)[-1]]

    invalid = DonutGaussianBeam
    try:
        invalid(inner_cutoff_radius=0.0, polarization=CircularRight())
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for non-positive cutoff radius")


def test_3d_mot_builder_uses_profile_values_not_detuning_arguments():
    mot_cfg = _resolved_profile("angled_donut")
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
        "beam_layout": "angled_xz_y",
        "xz_angle_from_z_deg": 30.0,
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
