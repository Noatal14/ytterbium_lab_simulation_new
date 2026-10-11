"""Central configuration for the Yb-171 cold-atom simulation.

This module exposes the simulation's resolved physical constants, atomic
properties, apparatus geometry, operating parameters, and numerical defaults.
Versioned laboratory identities are loaded from ``lab_setup/specifications``.

Conventions
-----------
- SI units are used by default.
- Non-SI units are written explicitly in variable names.
- Module-level configuration values use UPPER_SNAKE_CASE.
- Dataclass attributes and dictionary keys use snake_case.
- Transition linewidths ``gamma_rad_s`` are angular frequencies in rad/s.
- Laser detunings ``detuning_gamma`` are dimensionless and expressed in units
  of the corresponding transition linewidth Gamma.
- Lengths are in meters, times in seconds, forces in newtons, and angles in
  degrees unless the name explicitly states otherwise.
- Stage-specific names use the order ZEEMAN, MOT_2D, MOT_3D.
- Simulation code should import parameters from this module instead of
  duplicating values or introducing magic numbers elsewhere in the project.

Laboratory identities are versioned in ``lab_setup/specifications``.  Keep
their executable mirrors here synchronized with that reviewed contract.
"""

from dataclasses import dataclass

import numpy as np
from scipy import constants as csts

from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    LABORATORY_PHYSICAL_SPECIFICATION,
    ZEEMAN_MODEL_CONVENTIONS,
)
from lab_setup.numerical_policy import NUMERICAL_POLICY


# =============================================================================
# 1. Physical constants and unit conversions
# =============================================================================

MU_B_OVER_H_KHZ_PER_G = (
    csts.value("Bohr magneton") / csts.h * 1e-4 * 1e-3
)  # mu_B / h in kHz/G, approximately 1399.6

AMU_KG = csts.m_u
BOLTZMANN_CONSTANT_J_K = csts.k


# =============================================================================
# 2. Atomic species and optical transitions
# =============================================================================

@dataclass(frozen=True)
class Atom:
    """Atomic-species parameters used by the simulation."""

    name: str
    mass_kg: float
    mass_amu: float


@dataclass(frozen=True)
class Transition:
    """Optical-transition parameters used by the simulation.

    ``lande_g`` is the excited-state hyperfine factor ``g_F`` for the
    F=3/2 level.  It is not the electronic ``g_J`` factor.
    """

    wavelength_m: float
    gamma_rad_s: float
    lande_g: float


def saturation_intensity_w_m2(transition: Transition) -> float:
    """Return the saturation intensity of ``transition`` in W/m^2."""

    lifetime_s = 1.0 / transition.gamma_rad_s
    return (
        np.pi
        * csts.h
        * csts.c
        / (3.0 * transition.wavelength_m**3 * lifetime_s)
    )


# Yb-171 atomic properties owned by the versioned laboratory specification.
_LAB_SPECIES = LABORATORY_PHYSICAL_SPECIFICATION["species"]
_LAB_TRANSITIONS = LABORATORY_PHYSICAL_SPECIFICATION["transitions"]
_LAB_SOURCE = LABORATORY_PHYSICAL_SPECIFICATION["source"]
_LAB_APPARATUS = LABORATORY_PHYSICAL_SPECIFICATION["apparatus"]
_LAB_ZEEMAN_LASER = LABORATORY_PHYSICAL_SPECIFICATION["zeeman_laser_geometry"]
_NUMERICS = NUMERICAL_POLICY


def resolve_stochastic_solver(name):
    """Resolve an allowlisted stochastic solver name to its callable."""
    if name == "RK4StCustom":
        from utils.RK4StCustom import RK4StCustom
        return RK4StCustom
    if name == "RK4StHybridCustom":
        from utils.RK4StHybridCustom import RK4StHybridCustom
        return RK4StHybridCustom
    raise ValueError(f"Unsupported stochastic solver: {name}")

YB171_NAME = _LAB_SPECIES["name"]
YB171_MASS_AMU = _LAB_SPECIES["mass_amu"]
YB171_MASS_KG = YB171_MASS_AMU * AMU_KG

YB171 = Atom(
    name=YB171_NAME,
    mass_kg=YB171_MASS_KG,
    mass_amu=YB171_MASS_AMU,
)


# 399 nm blue transition
BLUE_TRANSITION_WAVELENGTH_M = _LAB_TRANSITIONS["blue"]["wavelength_m"]
BLUE_TRANSITION_GAMMA_RAD_S = _LAB_TRANSITIONS["blue"]["gamma_rad_s"]
BLUE_TRANSITION_LANDE_G_J = 1.035
BLUE_TRANSITION_ZEEMAN_COEFFICIENT_KHZ_PER_G = _LAB_TRANSITIONS["blue"][
    "measured_zeeman_coefficient_khz_per_G"
]
BLUE_TRANSITION_LANDE_G_F = (
    BLUE_TRANSITION_ZEEMAN_COEFFICIENT_KHZ_PER_G
    / MU_B_OVER_H_KHZ_PER_G
)
BLUE_TRANSITION_LANDE_G = BLUE_TRANSITION_LANDE_G_F
BLUE_TRANSITION_MODEL_EFFECTIVE_LANDE_G = 1.5 * BLUE_TRANSITION_LANDE_G_F

BLUE_TRANSITION = Transition(
    wavelength_m=BLUE_TRANSITION_WAVELENGTH_M,
    gamma_rad_s=BLUE_TRANSITION_GAMMA_RAD_S,
    lande_g=BLUE_TRANSITION_LANDE_G,
)

# Reference saturation intensity used by the project.
# Keep this value explicit rather than silently replacing it with the value
# calculated from the transition parameters.
BLUE_SATURATION_INTENSITY_MW_CM2 = _LAB_TRANSITIONS["blue"][
    "reference_saturation_intensity_mw_cm2"
]

# Derived value retained as a useful consistency check.
BLUE_CALCULATED_SATURATION_INTENSITY_W_M2 = saturation_intensity_w_m2(
    BLUE_TRANSITION
)
BLUE_CALCULATED_SATURATION_INTENSITY_MW_CM2 = (
    BLUE_CALCULATED_SATURATION_INTENSITY_W_M2 / 10.0
)


# 556 nm green intercombination line: 1S0 F=1/2 -> 3P1 F=3/2
GREEN_TRANSITION_WAVELENGTH_M = _LAB_TRANSITIONS["green"]["wavelength_m"]
GREEN_TRANSITION_GAMMA_RAD_S = _LAB_TRANSITIONS["green"]["gamma_rad_s"]
GREEN_TRANSITION_LANDE_G_J = 1.492820
GREEN_TRANSITION_ZEEMAN_COEFFICIENT_KHZ_PER_G = _LAB_TRANSITIONS["green"][
    "measured_zeeman_coefficient_khz_per_G"
]
GREEN_TRANSITION_LANDE_G_F = (
    GREEN_TRANSITION_ZEEMAN_COEFFICIENT_KHZ_PER_G
    / MU_B_OVER_H_KHZ_PER_G
)
GREEN_TRANSITION_LANDE_G = GREEN_TRANSITION_LANDE_G_F
GREEN_TRANSITION_MODEL_EFFECTIVE_LANDE_G = 1.5 * GREEN_TRANSITION_LANDE_G_F

GREEN_TRANSITION = Transition(
    wavelength_m=GREEN_TRANSITION_WAVELENGTH_M,
    gamma_rad_s=GREEN_TRANSITION_GAMMA_RAD_S,
    lande_g=GREEN_TRANSITION_LANDE_G,
)

GREEN_SATURATION_INTENSITY_W_M2 = saturation_intensity_w_m2(GREEN_TRANSITION)
GREEN_SATURATION_INTENSITY_MW_CM2 = GREEN_SATURATION_INTENSITY_W_M2 / 10.0


# =============================================================================
# 3. Apparatus geometry
# =============================================================================

class Geometry:
    """Fixed geometric parameters of the experimental apparatus."""

    Z_AXIS = tuple(ZEEMAN_MODEL_CONVENTIONS["lab_z_axis"])

    # 2D-MOT chamber and beams
    MOT_2D_CHAMBER_LENGTH_M = _LAB_APPARATUS["mot_2d_chamber_length_m"]
    MOT_2D_CHAMBER_RADIUS_M = _LAB_APPARATUS["mot_2d_chamber_radius_m"]
    MOT_2D_CHAMBER_ORIGIN_M = (
        0.0,
        0.0,
        -MOT_2D_CHAMBER_LENGTH_M / 2,
    )

    MOT_2D_BEAM_WAIST_X_M = 19e-3
    MOT_2D_BEAM_WAIST_Y_M = 5e-3

    # Zeeman-slower arm
    ZEEMAN_ARM_ANGLE_DEG = _LAB_APPARATUS["zeeman_arm_angle_deg"]
    ZEEMAN_ARM_ANGLE_RAD = np.radians(ZEEMAN_ARM_ANGLE_DEG)

    ZEEMAN_ARM_1_LENGTH_M = _LAB_APPARATUS["zeeman_arm_1_length_m"]
    ZEEMAN_ARM_1_RADIUS_M = _LAB_APPARATUS["zeeman_arm_1_radius_m"]
    ZEEMAN_ARM_1_SHORT_LENGTH_M = _LAB_APPARATUS["zeeman_arm_1_short_length_m"]
    ZEEMAN_ARM_1_EXTENDED_LENGTH_M = _LAB_APPARATUS["zeeman_arm_1_extended_length_m"]

    ZEEMAN_ARM_2_LENGTH_M = _LAB_APPARATUS["zeeman_arm_2_length_m"]
    ZEEMAN_ARM_2_RADIUS_M = _LAB_APPARATUS["zeeman_arm_2_radius_m"]

    ZEEMAN_ARM_3_LENGTH_M = _LAB_APPARATUS["zeeman_arm_3_length_m"]
    ZEEMAN_ARM_3_RADIUS_M = _LAB_APPARATUS["zeeman_arm_3_radius_m"]

    ZEEMAN_LASER_WAIST_M = _LAB_ZEEMAN_LASER["waist_m"]
    ZEEMAN_START_DISTANCE_M = _LAB_APPARATUS["zeeman_start_distance_m"]

    # Science arm and differential-pumping stage
    SCIENCE_ARM_1_LENGTH_M = _LAB_APPARATUS["science_arm_1_length_m"]
    SCIENCE_ARM_1_RADIUS_M = _LAB_APPARATUS["science_arm_1_radius_m"]
    SCIENCE_ARM_TOTAL_LENGTH_M = _LAB_APPARATUS["science_arm_total_length_m"]

    DPS_LENGTH_M = _LAB_APPARATUS["dps_length_m"]
    DPS_RADIUS_M = _LAB_APPARATUS["dps_radius_m"]
    DPS_START_Z_M = SCIENCE_ARM_1_LENGTH_M

    CAPTURE_MIN_Z_M = DPS_START_Z_M + DPS_LENGTH_M

    SCIENCE_REGION_CENTER_Z_M = _LAB_APPARATUS["science_region_center_z_m"]
    MOT_3D_CENTER_M = (0.0, 0.0, SCIENCE_REGION_CENTER_Z_M)

    SCIENCE_ARM_3_LENGTH_M = (
        SCIENCE_ARM_TOTAL_LENGTH_M
        - DPS_LENGTH_M
        - SCIENCE_ARM_1_LENGTH_M
    )
    SCIENCE_ARM_3_RADIUS_M = _LAB_APPARATUS["science_arm_3_radius_m"]

    # Oven microtubes
    OVEN_MICROTUBE_RADIUS_M = _LAB_SOURCE["microtube_radius_m"]
    OVEN_MICROTUBE_LENGTH_M = _LAB_SOURCE["microtube_length_m"]


ZEEMAN_BEAM_DIRECTION = np.array(
    [
        0.0,
        -np.sin(Geometry.ZEEMAN_ARM_ANGLE_RAD),
        -np.cos(Geometry.ZEEMAN_ARM_ANGLE_RAD),
    ]
)


# =============================================================================
# 4. Oven and atomic-beam source
# =============================================================================

OVEN_TEMPERATURE_C = _LAB_SOURCE["oven_temperature_C"]
COLLIMATION_ANGLE_DEG = _LAB_SOURCE["collimation_angle_deg"]
OVEN_MICROTUBE_COUNT = _LAB_SOURCE["microtube_count"]
YB171_NATURAL_ABUNDANCE = _LAB_SOURCE["yb171_natural_abundance"]


# =============================================================================
# 5. Zeeman slower
# =============================================================================

# The single runnable Zeeman-magnet profile.
# It contains:
#   [magnet radii (m), longitudinal positions (m), tilt angles (deg)]
#
# Retired arrays are deliberately absent; historical identity recognition is
# implemented separately and cannot feed a simulation.
ZEEMAN_MAGNET_PROFILES = {}

_CANONICAL_ZEEMAN_PROFILE = LABORATORY_PHYSICAL_SPECIFICATION[
    "canonical_zeeman_profile"
]
ZEEMAN_MAGNET_PROFILES[CANONICAL_ZEEMAN_PROFILE_NAME] = [
    list(_CANONICAL_ZEEMAN_PROFILE["radii_m"]),
    list(_CANONICAL_ZEEMAN_PROFILE["positions_m"]),
    list(_CANONICAL_ZEEMAN_PROFILE["tilt_angles_deg"]),
]

ACTIVE_ZEEMAN_MAGNET_PROFILE = CANONICAL_ZEEMAN_PROFILE_NAME

(
    ZEEMAN_MAGNET_RADII_M,
    ZEEMAN_MAGNET_POSITIONS_M,
    ZEEMAN_MAGNET_TILT_ANGLES_DEG,
) = ZEEMAN_MAGNET_PROFILES[ACTIVE_ZEEMAN_MAGNET_PROFILE]

ZEEMAN_FIELD_CONFIG = {
    "radii_m": ZEEMAN_MAGNET_RADII_M,
    "positions_m": ZEEMAN_MAGNET_POSITIONS_M,
    "tilt_angles_deg": ZEEMAN_MAGNET_TILT_ANGLES_DEG,
}

ZEEMAN_LASER_CONFIG = {
    "s0": 3.0,
    "detuning_gamma": -13.75,
}

ZEEMAN_SIM_CONFIG = {
    "t_max_s": _NUMERICS["zeeman"]["t_max_s"],
    "dt_s": _NUMERICS["zeeman"]["dt_s"],
    "start_distance_m": 0.450,
    "cutoff_distance_m": 0.100,
}


# =============================================================================
# 6. 2D MOT
# =============================================================================

MOT_2D_MAGNET_RADIUS_M = 0.0517

MOT_2D_LASER_CONFIG = {
    "s0": 1.4,
    "detuning_gamma": -1.161,
    "swap_polarization": False,
}

MOT_2D_SIM_CONFIG = {
    "t_max_s": _NUMERICS["mot_2d"]["t_max_s"],
    # Accepted hybrid-solver production timestep after convergence validation.
    # All 2D-MOT entry points must read this value rather than duplicate it.
    "dt_s": _NUMERICS["mot_2d"]["dt_s"],
    "start_distance_m": 0.100,
}
MOT_2D_STOCHASTIC_SOLVER_NAME = _NUMERICS["mot_2d"]["solver"]
MOT_2D_STOCHASTIC_SOLVER = resolve_stochastic_solver(
    MOT_2D_STOCHASTIC_SOLVER_NAME
)

# Global force scale used across the simulation pipeline.
# This is the authoritative normalization constant and is not limited to the
# 2D-MOT stage.
FORCE_SCALE_N = 3.141895058426422e-20


# =============================================================================
# 7. 3D MOT
# =============================================================================

MOT_3D_MAGNETIC_FIELD_GRADIENT_G_CM = 10.0

# Full-search domains. Length bounds are 1/e^2 Gaussian waist radii. Chamber
# holes are represented separately as hard transverse apertures, so a waist is
# not interpreted as a physical beam diameter.
MOT_3D_OPTIMIZATION_CONFIG = {
    "common": {
        "green_s0_bounds": (0.5, 150.0),
        "green_detuning_gamma_bounds": (-35.0, -5.0),
        "green_waist_m_bounds": (0.002, 0.020),
        "blue_s0_bounds": (0.05, 1.5),
        "blue_waist_m_bounds": (0.002, 0.020),
        "magnetic_gradient_G_cm_bounds": (0.5, 100.0),
        "particles_per_trial": 600,
        "t_max_s": 0.1,
    },
    "angled_donut": {
        "blue_detuning_gamma_bounds": (-6.0, -0.5),
        # Shared hard boundary between the green core and blue shell.
        "core_shell_split_radius_m_bounds": (0.0005, 0.0049),
        "shared_aperture_radius_m": 0.005,
        "total_discovery_trials": 350,
    },
    "single_pass": {
        "blue_detuning_anchor_gamma_bounds": (-3.75, -1.75),
        "blue_crossing_angle_deg_bounds": (45.0, 70.0),
        "blue_crossing_z_offset_m_bounds": (-0.050, -0.040),
        "maximum_blue_center_relative_intensity": 1e-3,
        "green_full_angle_deg": 62.0,
        "green_aperture_radius_m": 0.005,
        "blue_aperture_radius_m": 0.0075,
        "slowing_position_waist_factor": 1.1,
        "blue_zeeman_gamma_per_G": 0.04969,
        "reference_gradient_G_cm": 2.5,
        "reference_crossing_z_offset_m": -0.050,
        "reference_blue_waist_m": 0.0075,
        "total_discovery_trials": 600,
    },
}

# Some 3D-MOT geometry parameters are provisional because the final
# experimental configuration is still under investigation. They are kept
# as numeric defaults so each profile remains directly runnable and easy
# to modify or optimize.
MOT_3D_CONFIGURATIONS = {
    "angled_donut": {
        "description": "Two xz axes with a 62-degree full included angle plus a y axis. A shared optimized radius splits each coaxial beam into a green core and blue shell, and the common chamber hole clips both colors at 5 mm radius.",
        "beam_layout": "angled_xz_y",
        "xz_angle_from_z_deg": 31.0,
        # The y beam is the third MOT axis, so y is the quadrupole strong axis
        # for the configured 2:1 gradient convention.
        "magnetic_strong_axis": "y",
        # Lower scan boundary selected after correcting the force signs;
        # provisional until the expanded optimization is performed.
        "magnetic_gradient_G_cm": 2.5,
        "center_position_m": Geometry.MOT_3D_CENTER_M,
        "blue_green_center_separation_m": 0.0,
        "399": {
            "enabled": True,
            # Selected by the polarization-corrected 900-particle staged scan.
            # This provisional point lies on the scanned intensity boundary.
            "s0": 1.5,
            "detuning_gamma": -3.0,
            "waist_m": 0.0075,
            "profile": "donut",
            "polarization_by_axis": {
                "+XZ_1": "right",
                "-XZ_1": "right",
                "+XZ_2": "right",
                "-XZ_2": "right",
                "+Y": "left",
                "-Y": "left",
            },
            # The experimental mirrors remove the center of an otherwise
            # ordinary Gaussian beam; the intensity jumps from exactly zero to
            # the unmodified Gaussian tail at this radius.
            "inner_cutoff_radius_m": 0.0025,
            "outer_cutoff_radius_m": 0.005,
        },
        "556": {
            "enabled": True,
            # Both values lie on boundaries of the current scan and are used
            # only as a provisional retention-study operating point.
            "s0": 30.0,
            "detuning_gamma": -25.0,
            "waist_m": 0.0075,
            "profile": "outer_clipped_gaussian",
            # Required by the quadrupole sign convention for restoring force
            # along all three lab axes.
            "polarization_by_axis": {
                "+XZ_1": "right",
                "-XZ_1": "right",
                "+XZ_2": "right",
                "-XZ_2": "right",
                "+Y": "left",
                "-Y": "left",
            },
            # The optimized profile replaces this provisional shared split.
            "outer_cutoff_radius_m": 0.0025,
        },
    },
    "single_pass": {
        "description": "Six-beam angled green MOT with one localized pair of 399-nm entrance-slowing beams in the yz plane. The blue beams cross upstream of the MOT center and both propagate with a -z component.",
        "beam_layout": "angled_green_yz_single_pass",
        "gravity_axis": "x",
        "transport_axis": "z",
        "magnetic_strong_axis": "y",
        "magnetic_gradient_G_cm": 2.5,
        # Full angle between the two blue propagation vectors. This is an
        # optimization variable with the approved range 45--70 degrees.
        "blue_crossing_angle_deg": 45.0,
        # The blue X-shaped crossing is upstream along the atomic +z path.
        # At -50 mm with a 10-mm waist and 45-degree included angle, each
        # physical Gaussian beam contributes <0.1% of its peak intensity at
        # the MOT center; no artificial longitudinal clipping is assumed.
        "blue_crossing_z_offset_m": -50e-3,
        "maximum_blue_center_relative_intensity": 1e-3,
        "xz_angle_from_z_deg": 31.0,
        "center_position_m": Geometry.MOT_3D_CENTER_M,
        "beam_components": {
            "+XZ_1": {"399_enabled": False, "556_enabled": True},
            "-XZ_1": {"399_enabled": False, "556_enabled": True},
            "+XZ_2": {"399_enabled": False, "556_enabled": True},
            "-XZ_2": {"399_enabled": False, "556_enabled": True},
            "+Y": {"399_enabled": False, "556_enabled": True},
            "-Y": {"399_enabled": False, "556_enabled": True},
            "SP_FROM_NEG_Y": {"399_enabled": True, "556_enabled": False},
            "SP_FROM_POS_Y": {"399_enabled": True, "556_enabled": False},
        },
        "399": {
            "enabled": True,
            "s0": 0.75,
            "detuning_gamma": -2.0,
            "waist_m": 0.010,
            "profile": "outer_clipped_gaussian",
            "outer_cutoff_radius_m": 0.0075,
            "polarization_by_axis": {
                "SP_FROM_NEG_Y": "right",
                "SP_FROM_POS_Y": "right",
            },
        },
        "556": {
            "enabled": True,
            "s0": 30.0,
            "detuning_gamma": -25.0,
            "waist_m": 0.01,
            "profile": "outer_clipped_gaussian",
            "outer_cutoff_radius_m": 0.005,
            "polarization_by_axis": {
                "+XZ_1": "right",
                "-XZ_1": "right",
                "+XZ_2": "right",
                "-XZ_2": "right",
                "+Y": "left",
                "-Y": "left",
            },
        },
    },
}

ACTIVE_MOT_3D_CONFIGURATION = "angled_donut"
MOT_3D_LASER_CONFIG = MOT_3D_CONFIGURATIONS[ACTIVE_MOT_3D_CONFIGURATION]

MOT_3D_SIM_CONFIG = {
    "t_max_s": _NUMERICS["mot_3d"]["t_max_s"],
    # Provisional values only.  The 0.625-us production value is supported by
    # the 2D-MOT convergence study, not yet by a 3D-MOT convergence study.
    # A new campaign must pass its paired dt-validation gate before discovery.
    "dt_s": _NUMERICS["mot_3d"]["dt_s"],
    "screening_dt_s": _NUMERICS["mot_3d"]["screening_dt_s"],
    "production_dt_s": _NUMERICS["mot_3d"]["production_dt_s"],
    # Include deliberately aggressive values so the validation can establish
    # whether a cheaper timestep is defensible instead of only checking the
    # provisional choices selected before canonical 2D survivors existed.
    "dt_validation_candidates_s": tuple(_NUMERICS["mot_3d"]["dt_validation_candidates_s"]),
    "dt_validation_reference_s": _NUMERICS["mot_3d"]["dt_validation_reference_s"],
    "solver": _NUMERICS["mot_3d"]["solver"],
}
MOT_3D_STOCHASTIC_SOLVER_NAME = MOT_3D_SIM_CONFIG["solver"]
MOT_3D_STOCHASTIC_SOLVER = resolve_stochastic_solver(
    MOT_3D_STOCHASTIC_SOLVER_NAME
)

# Provisional operational definition of 3D-MOT capture. These values are
# intentionally centralized here so they can be tuned against simulation and
# experiment without changing the stage implementation.
MOT_3D_CAPTURE_CONFIG = {
    "capture_radius_m": 5e-3,
    "diagnostic_radii_m": (5e-3, 7.5e-3, 10e-3),
    "minimum_residence_time_s": 5e-3,
    "maximum_final_speed_m_s": 1.0,
}


# =============================================================================
# 8. Full-pipeline simulation
# =============================================================================

FULL_SIM_CONFIG = {
    "dt_s": 1e-5,
    "t_max_s": 25e-3,
    "start_distance_m": 0.450,
}


# =============================================================================
# 9. Runtime defaults
# =============================================================================

DEFAULT_NUM_PARTICLES = 50_000
DEFAULT_RANDOM_SEED = 42
DEFAULT_NUM_POOLS = 8
