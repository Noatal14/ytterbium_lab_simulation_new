import copy

import numpy as np
import pytest
from atomsmltr.environment.lasers.polarization import CircularRight
from atomsmltr.simulation.simulator.simbase import get_force_vec

from config import (
    ACTIVE_MOT_3D_CONFIGURATION,
    BLUE_SATURATION_INTENSITY_MW_CM2,
    MOT_3D_CONFIGURATIONS,
)
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


def _profile_single_wavelength_config(profile_name, wavelength_key):
    profile = _resolved_profile(profile_name)
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
    assert set(MOT_3D_CONFIGURATIONS) == {"angled_donut", "single_pass"}
    assert "orthogonal_counterpropagating" not in MOT_3D_CONFIGURATIONS


def test_3d_mot_field_accepts_single_position_and_position_batch():
    from lab_setup._3d_mot_mag_field import get_builtin_3dmot_magnetic_field

    field = get_builtin_3dmot_magnetic_field(
        gradient_G_cm=10.0,
        origin=(0.0, 0.0, 0.0),
        strong_axis="z",
    )
    position = np.array([1.0e-3, 2.0e-3, 3.0e-3])
    single = field.get_value(position)
    batch = field.get_value(position[np.newaxis, :])

    assert single.shape == (3,)
    assert batch.shape == (1, 3)
    assert np.allclose(single, batch[0])


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
    assert all(
        getattr(beam, "profile_kind", "gaussian") == "outer_clipped_gaussian"
        for beam in green_beams
    )
    assert profile["556"]["outer_cutoff_radius_m"] == pytest.approx(
        profile["399"]["inner_cutoff_radius_m"]
    )
    assert profile["magnetic_strong_axis"] == "y"
    for wavelength in ("399", "556"):
        polarizations = profile[wavelength]["polarization_by_axis"]
        assert all(
            polarizations[tag] == "right"
            for tag in ("+XZ_1", "-XZ_1", "+XZ_2", "-XZ_2")
        )
        assert polarizations["+Y"] == "left"
        assert polarizations["-Y"] == "left"

    beam_by_tag = {beam.tag: _normalize(beam.direction) for beam in beams}
    assert np.allclose(beam_by_tag["3DMOT_399_+XZ_1"], -beam_by_tag["3DMOT_399_-XZ_1"])
    assert np.allclose(beam_by_tag["3DMOT_399_+XZ_2"], -beam_by_tag["3DMOT_399_-XZ_2"])
    assert np.allclose(beam_by_tag["3DMOT_399_+Y"], -beam_by_tag["3DMOT_399_-Y"])


@pytest.mark.parametrize("axis", [0, 1, 2])
@pytest.mark.parametrize("displacement_sign", [-1.0, 1.0])
def test_angled_donut_green_force_is_restoring_on_every_axis(
    axis, displacement_sign
):
    profile, simulation_config = _profile_single_wavelength_config(
        "angled_donut", "556"
    )
    center = np.asarray(profile["center_position_m"], dtype=float)
    displacement = np.zeros(3)
    displacement[axis] = displacement_sign * 0.5e-3

    force = _force_at(simulation_config, center + displacement)

    assert force[axis] * displacement[axis] < 0.0


@pytest.mark.parametrize("axis", [0, 1, 2])
@pytest.mark.parametrize("velocity_sign", [-1.0, 1.0])
def test_angled_donut_blue_shell_force_opposes_velocity(axis, velocity_sign):
    profile, simulation_config = _profile_single_wavelength_config(
        "angled_donut", "399"
    )
    position = np.asarray(profile["center_position_m"], dtype=float)
    # This lab-frame point lies in the illuminated blue shell rather than the
    # intentionally dark 10-mm core.
    position += np.array([15.0e-3, 0.0, 0.0])
    velocity = np.zeros(3)
    velocity[axis] = velocity_sign * 10.0

    force = _force_at(simulation_config, position, velocity)

    assert force[axis] * velocity[axis] < 0.0


def test_single_pass_geometry_has_six_green_and_two_upstream_blue_beams():
    profile = _resolved_profile("single_pass")
    assert profile["beam_layout"] == "angled_green_yz_single_pass"
    assert profile["blue_crossing_angle_deg"] == pytest.approx(45.0)
    assert profile["blue_crossing_z_offset_m"] == pytest.approx(-10e-3)
    beams = setup_3dmot_lasers(
        mot_3d_config=profile, center_position=(0.0, 0.0, 0.0)
    )
    blue_beams = [beam for beam in beams if "3DMOT_399_" in beam.tag]
    green_beams = [beam for beam in beams if "3DMOT_556_" in beam.tag]
    assert len(blue_beams) == 2
    assert len(green_beams) == 6
    assert all(beam.profile_kind == "gaussian" for beam in blue_beams)
    assert all(beam.profile_kind == "gaussian" for beam in green_beams)

    blue_directions = [_normalize(beam.direction) for beam in blue_beams]
    assert all(np.isclose(direction[0], 0.0) for direction in blue_directions)
    assert all(direction[2] < 0.0 for direction in blue_directions)
    assert blue_directions[0][1] * blue_directions[1][1] < 0.0
    included_angle = np.rad2deg(
        np.arccos(np.clip(np.dot(*blue_directions), -1.0, 1.0))
    )
    assert included_angle == pytest.approx(45.0)
    assert all(beam.waist_position[2] == pytest.approx(-10e-3) for beam in blue_beams)

    green_directions = _unique_directions(green_beams)
    assert len(green_directions) == 6
    assert profile["magnetic_strong_axis"] == "y"


def test_single_pass_angle_and_crossing_offset_are_config_driven():
    profile = _resolved_profile("single_pass")
    profile["blue_crossing_angle_deg"] = 70.0
    profile["blue_crossing_z_offset_m"] = -25e-3
    beams = setup_3dmot_lasers(
        mot_3d_config=profile, center_position=(0.0, 0.0, 0.0)
    )
    blue_beams = [beam for beam in beams if "3DMOT_399_" in beam.tag]
    directions = [_normalize(beam.direction) for beam in blue_beams]
    included_angle = np.rad2deg(
        np.arccos(np.clip(np.dot(*directions), -1.0, 1.0))
    )
    assert included_angle == pytest.approx(70.0)
    assert all(beam.waist_position[2] == pytest.approx(-25e-3) for beam in blue_beams)


def test_angled_donut_uses_selected_provisional_operating_point():
    profile = _resolved_profile("angled_donut")

    assert profile["magnetic_gradient_G_cm"] == pytest.approx(2.5)
    assert profile["399"]["s0"] == pytest.approx(1.5)
    assert profile["399"]["detuning_gamma"] == pytest.approx(-3.0)
    assert profile["556"]["s0"] == pytest.approx(30.0)
    assert profile["556"]["detuning_gamma"] == pytest.approx(-25.0)

def test_single_pass_blue_pair_slows_incoming_atoms_without_net_y_kick():
    profile, simulation_config = _profile_single_wavelength_config(
        "single_pass", "399"
    )
    center = np.asarray(profile["center_position_m"], dtype=float)
    position = center + np.array([0.0, 0.0, -10.0e-3])

    force = _force_at(simulation_config, position, velocity=(0.0, 0.0, 12.0))

    assert force[2] < 0.0
    assert abs(force[0]) <= 1e-12 * abs(force[2]) + 1e-30
    assert abs(force[1]) <= 1e-12 * abs(force[2]) + 1e-30


@pytest.mark.parametrize("axis", [0, 1, 2])
@pytest.mark.parametrize("displacement_sign", [-1.0, 1.0])
def test_single_pass_green_mot_is_restoring(axis, displacement_sign):
    profile, simulation_config = _profile_single_wavelength_config(
        "single_pass", "556"
    )
    center = np.asarray(profile["center_position_m"], dtype=float)
    displacement = np.zeros(3)
    displacement[axis] = displacement_sign * 0.5e-3
    force = _force_at(simulation_config, center + displacement)
    assert force[axis] * displacement[axis] < 0.0


def test_global_wavelength_switch_disables_explicit_axis_components():
    profile = _resolved_profile("single_pass")
    profile["399"]["enabled"] = False

    beams = setup_3dmot_lasers(profile)

    assert not any("3DMOT_399_" in beam.tag for beam in beams)


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


def test_angled_donut_green_and_blue_profiles_are_complementary():
    profile = _resolved_profile("angled_donut")
    beams = setup_3dmot_lasers(
        mot_3d_config=profile,
        center_position=(0.0, 0.0, 0.0),
    )
    blue = next(beam for beam in beams if beam.tag == "3DMOT_399_+Y")
    green = next(beam for beam in beams if beam.tag == "3DMOT_556_+Y")
    cutoff = profile["399"]["inner_cutoff_radius_m"]
    assert green.outer_cutoff_radius == pytest.approx(cutoff)

    inside = np.array([[0.5 * cutoff, 0.0, 0.0]])
    boundary = np.array([[cutoff, 0.0, 0.0]])
    outside = np.array([[1.5 * cutoff, 0.0, 0.0]])

    assert blue.get_value(inside)[0] == 0.0
    assert green.get_value(inside)[0] > 0.0
    assert blue.get_value(boundary)[0] > 0.0
    assert green.get_value(boundary)[0] == 0.0
    assert blue.get_value(outside)[0] > 0.0
    assert green.get_value(outside)[0] == 0.0


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
