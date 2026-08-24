"""Audit the active Zeeman configuration before running particle ensembles."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy import constants as csts

from config import (
    ACTIVE_ZEEMAN_MAGNET_PROFILE,
    BLUE_SATURATION_INTENSITY_MW_CM2,
    Geometry,
    MOT_2D_MAGNET_RADIUS_M,
    ZEEMAN_BEAM_DIRECTION,
    ZEEMAN_FIELD_CONFIG,
    ZEEMAN_LASER_CONFIG,
    ZEEMAN_SIM_CONFIG,
)
from lab_setup.atom_species import create_atom
from lab_setup.mag_field_2d_mot import CustomQuadrupole
from lab_setup.mag_field_Zeeman import ZeemanSlowerField
from lab_setup.zeeman_laser_setup import setup_zeeman_laser
from utils.data_paths import ZEEMAN_VALIDATION_DIR


DEFAULT_REPORT_FILE = ZEEMAN_VALIDATION_DIR / "zeeman_validation.json"
DEFAULT_PLOT_FILE = ZEEMAN_VALIDATION_DIR / "zeeman_validation.png"


def _git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_is_dirty():
    try:
        return bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def _json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def analyze_zeeman_configuration(
    num_points=1201,
    target_entry_speed_m_s=310.0,
    target_exit_speed_m_s=50.0,
    endpoint_tolerance_m_s=20.0,
    include_2d_mot_field=True,
):
    """Sample the real field/laser implementation and return an audit summary."""
    if num_points < 3:
        raise ValueError("num_points must be at least 3.")

    radii = np.asarray(ZEEMAN_FIELD_CONFIG["radii_m"], dtype=float)
    positions = np.asarray(ZEEMAN_FIELD_CONFIG["positions_m"], dtype=float)
    tilts = np.asarray(ZEEMAN_FIELD_CONFIG["tilt_angles_deg"], dtype=float)

    laser_direction = np.asarray(ZEEMAN_BEAM_DIRECTION, dtype=float)
    atom_direction = -laser_direction
    slower_origin = laser_direction * Geometry.ZEEMAN_START_DISTANCE_M

    sample_start_m = float(positions.min() - 0.02)
    sample_end_m = float(
        Geometry.ZEEMAN_START_DISTANCE_M
        - ZEEMAN_SIM_CONFIG["cutoff_distance_m"]
    )
    axis_position_m = np.linspace(sample_start_m, sample_end_m, int(num_points))
    lab_points = slower_origin + axis_position_m[:, None] * atom_direction

    zeeman_field = ZeemanSlowerField(
        angle_deg=Geometry.ZEEMAN_ARM_ANGLE_DEG,
        start_distance=Geometry.ZEEMAN_START_DISTANCE_M,
        radii=radii,
        positions_z=positions,
        tilt_angles=tilts,
    )
    field_zeeman_T = np.asarray(zeeman_field.get_value(lab_points), dtype=float)
    field_total_T = field_zeeman_T.copy()
    if include_2d_mot_field:
        mot_field = CustomQuadrupole(radius=MOT_2D_MAGNET_RADIUS_M)
        field_total_T += np.asarray(mot_field.get_value(lab_points), dtype=float)

    field_norm_T = np.linalg.norm(field_total_T, axis=1)
    field_axial_T = field_total_T @ atom_direction
    field_transverse_T = np.linalg.norm(
        field_total_T - field_axial_T[:, None] * atom_direction,
        axis=1,
    )

    laser = setup_zeeman_laser(**ZEEMAN_LASER_CONFIG)[0]
    polarization_weights = np.asarray(
        laser.get_polarization_quant(field_total_T), dtype=float
    )

    atom = create_atom("Yb171")
    transition = atom.trans["399"]
    detuning_rad_s = ZEEMAN_LASER_CONFIG["detuning_gamma"] * transition.Gamma
    mu_rad_s_T = (
        transition.lande_factor * csts.value("Bohr magneton") / csts.hbar
    )

    # For atoms moving opposite the laser, the Doppler contribution is +kv.
    # Columns follow atomsmltr's polarization order: pi, sigma+, sigma-.
    resonant_speeds_m_s = np.column_stack(
        [
            np.full_like(field_norm_T, -detuning_rad_s / transition.k),
            (-detuning_rad_s + mu_rad_s_T * field_norm_T) / transition.k,
            (-detuning_rad_s - mu_rad_s_T * field_norm_T) / transition.k,
        ]
    )
    dominant_branch_index = np.argmax(polarization_weights, axis=1)
    dominant_resonant_speed_m_s = resonant_speeds_m_s[
        np.arange(len(axis_position_m)), dominant_branch_index
    ]

    main_start_m = 0.0
    main_end_m = float(positions.max())
    main_mask = (axis_position_m >= main_start_m) & (
        axis_position_m <= main_end_m
    )
    main_axis_m = axis_position_m[main_mask]
    ideal_fraction = (main_axis_m - main_start_m) / (main_end_m - main_start_m)
    ideal_speed_m_s = np.sqrt(
        target_entry_speed_m_s**2
        - ideal_fraction
        * (target_entry_speed_m_s**2 - target_exit_speed_m_s**2)
    )
    main_resonant_speed_m_s = dominant_resonant_speed_m_s[main_mask]

    entry_index = int(np.argmin(np.abs(axis_position_m - main_start_m)))
    exit_index = int(np.argmin(np.abs(axis_position_m - main_end_m)))
    entry_resonant_speed_m_s = float(dominant_resonant_speed_m_s[entry_index])
    exit_resonant_speed_m_s = float(dominant_resonant_speed_m_s[exit_index])

    maximum_acceleration_m_s2 = (
        csts.hbar
        * transition.k
        * transition.Gamma
        / (2.0 * atom.mass)
        * ZEEMAN_LASER_CONFIG["s0"]
        / (1.0 + ZEEMAN_LASER_CONFIG["s0"])
    )
    required_acceleration_m_s2 = (
        target_entry_speed_m_s**2 - target_exit_speed_m_s**2
    ) / (2.0 * (main_end_m - main_start_m))
    peak_intensity_W_m2 = (
        ZEEMAN_LASER_CONFIG["s0"]
        * BLUE_SATURATION_INTENSITY_MW_CM2
        * 10.0
    )
    estimated_laser_power_W = (
        peak_intensity_W_m2
        * np.pi
        * Geometry.ZEEMAN_LASER_WAIST_M**2
        / 2.0
    )

    checks = {
        "magnet_arrays_have_equal_length": len(radii) == len(positions) == len(tilts),
        "magnet_profile_has_20_rings": len(radii) == 20,
        "magnet_positions_are_strictly_increasing": bool(
            np.all(np.diff(positions) > 0.0)
        ),
        "magnet_values_are_finite": bool(
            np.all(np.isfinite(radii))
            and np.all(np.isfinite(positions))
            and np.all(np.isfinite(tilts))
        ),
        "magnet_radii_are_positive": bool(np.all(radii > 0.0)),
        "laser_is_antiparallel_to_atoms": bool(
            np.isclose(np.dot(laser_direction, atom_direction), -1.0, atol=1e-12)
        ),
        "laser_detuning_is_red": detuning_rad_s < 0.0,
        "sampled_field_is_finite": bool(np.all(np.isfinite(field_total_T))),
        "polarization_is_normalized": bool(
            np.allclose(polarization_weights.sum(axis=1), 1.0, atol=1e-10)
        ),
        "entry_resonance_matches_target": bool(
            abs(entry_resonant_speed_m_s - target_entry_speed_m_s)
            <= endpoint_tolerance_m_s
        ),
        "exit_resonance_matches_target": bool(
            abs(exit_resonant_speed_m_s - target_exit_speed_m_s)
            <= endpoint_tolerance_m_s
        ),
        "required_deceleration_is_below_maximum": bool(
            required_acceleration_m_s2 < maximum_acceleration_m_s2
        ),
    }
    target_checks = {
        "entry_resonance_matches_target",
        "exit_resonance_matches_target",
    }
    structural_checks = [key for key in checks if key not in target_checks]

    warnings = []
    if not checks["entry_resonance_matches_target"]:
        warnings.append(
            "Dominant resonant speed at the nominal slowing start differs from "
            f"the target by {entry_resonant_speed_m_s - target_entry_speed_m_s:+.2f} m/s."
        )
    if not checks["exit_resonance_matches_target"]:
        warnings.append(
            "Dominant resonant speed at the last magnet ring differs from "
            f"the target by {exit_resonant_speed_m_s - target_exit_speed_m_s:+.2f} m/s."
        )

    if not all(checks[key] for key in structural_checks):
        status = "FAIL"
    elif warnings:
        status = "REVIEW_REQUIRED"
    else:
        status = "PASS"

    summary = {
        "status": status,
        "base_git_commit": _git_commit(),
        "working_tree_was_dirty": _git_is_dirty(),
        "active_magnet_profile": ACTIVE_ZEEMAN_MAGNET_PROFILE,
        "include_2d_mot_field": include_2d_mot_field,
        "configuration": {
            "magnet_ring_count": len(radii),
            "magnet_position_min_m": float(positions.min()),
            "magnet_position_max_m": float(positions.max()),
            "laser_s0": ZEEMAN_LASER_CONFIG["s0"],
            "laser_detuning_gamma": ZEEMAN_LASER_CONFIG["detuning_gamma"],
            "laser_detuning_MHz": detuning_rad_s / (2.0 * np.pi * 1e6),
            "laser_waist_m": Geometry.ZEEMAN_LASER_WAIST_M,
            "estimated_laser_power_W": estimated_laser_power_W,
            "simulation_start_distance_m": ZEEMAN_SIM_CONFIG["start_distance_m"],
            "simulation_cutoff_distance_m": ZEEMAN_SIM_CONFIG["cutoff_distance_m"],
        },
        "directions": {
            "atom": atom_direction,
            "laser": laser_direction,
            "dot_product": float(np.dot(atom_direction, laser_direction)),
        },
        "targets": {
            "entry_speed_m_s": target_entry_speed_m_s,
            "exit_speed_m_s": target_exit_speed_m_s,
            "endpoint_tolerance_m_s": endpoint_tolerance_m_s,
        },
        "diagnostics": {
            "entry_dominant_resonant_speed_m_s": entry_resonant_speed_m_s,
            "exit_dominant_resonant_speed_m_s": exit_resonant_speed_m_s,
            "dominant_resonance_rmse_vs_ideal_m_s": float(
                np.sqrt(np.mean((main_resonant_speed_m_s - ideal_speed_m_s) ** 2))
            ),
            "dominant_resonance_nonincreasing_fraction": float(
                np.mean(np.diff(main_resonant_speed_m_s) <= 0.0)
            ),
            "field_norm_min_G": float(field_norm_T.min() * 1e4),
            "field_norm_max_G": float(field_norm_T.max() * 1e4),
            "maximum_transverse_field_G": float(field_transverse_T.max() * 1e4),
            "median_dominant_polarization_weight": float(
                np.median(np.max(polarization_weights, axis=1))
            ),
            "maximum_scattering_acceleration_m_s2": maximum_acceleration_m_s2,
            "required_constant_acceleration_m_s2": required_acceleration_m_s2,
            "required_to_max_acceleration_ratio": (
                required_acceleration_m_s2 / maximum_acceleration_m_s2
            ),
        },
        "checks": checks,
        "warnings": warnings,
    }
    summary = json.loads(json.dumps(summary, default=_json_default))
    profiles = {
        "axis_position_m": axis_position_m,
        "field_zeeman_T": field_zeeman_T,
        "field_total_T": field_total_T,
        "field_norm_T": field_norm_T,
        "field_axial_T": field_axial_T,
        "field_transverse_T": field_transverse_T,
        "polarization_weights": polarization_weights,
        "resonant_speeds_m_s": resonant_speeds_m_s,
        "dominant_branch_index": dominant_branch_index,
        "dominant_resonant_speed_m_s": dominant_resonant_speed_m_s,
        "main_axis_m": main_axis_m,
        "ideal_speed_m_s": ideal_speed_m_s,
    }
    return summary, profiles


def plot_validation(summary, profiles, output_file):
    """Write a four-panel magnetic-field and resonance diagnostic."""
    axis_mm = profiles["axis_position_m"] * 1e3
    magnet_min_mm = summary["configuration"]["magnet_position_min_m"] * 1e3
    magnet_max_mm = summary["configuration"]["magnet_position_max_m"] * 1e3

    fig, axes = plt.subplots(2, 2, figsize=(14, 10), sharex=True)
    ax_field, ax_speed, ax_pol, ax_detuning = axes.flat

    ax_field.plot(axis_mm, profiles["field_axial_T"] * 1e4, label="axial B")
    ax_field.plot(axis_mm, profiles["field_norm_T"] * 1e4, label="|B|", alpha=0.8)
    ax_field.plot(
        axis_mm,
        profiles["field_transverse_T"] * 1e4,
        label="transverse |B|",
        alpha=0.7,
    )
    ax_field.axhline(0.0, color="black", linewidth=0.8)
    ax_field.set_ylabel("magnetic field [G]")
    ax_field.set_title("Magnetic field along atomic axis")
    ax_field.legend()

    for index, (color, label) in enumerate(
        zip(
            ("0.5", "tab:red", "tab:purple"),
            ("pi resonance", "sigma+ resonance", "sigma- resonance"),
        )
    ):
        ax_speed.plot(
            axis_mm,
            profiles["resonant_speeds_m_s"][:, index],
            color=color,
            alpha=0.35,
            linewidth=1.0,
            label=label,
        )
    ax_speed.plot(
        axis_mm,
        profiles["dominant_resonant_speed_m_s"],
        color="tab:blue",
        linewidth=2.2,
        label="dominant polarization branch",
    )
    ax_speed.plot(
        profiles["main_axis_m"] * 1e3,
        profiles["ideal_speed_m_s"],
        color="black",
        linestyle="--",
        linewidth=1.5,
        label="ideal 310 -> 50 m/s guide",
    )
    ax_speed.set_ylim(bottom=-20.0)
    ax_speed.set_ylabel("resonant atomic speed [m/s]")
    ax_speed.set_title("Resonance branches for atoms moving toward the MOT")
    ax_speed.legend(fontsize=8)

    for index, label in enumerate(("pi", "sigma+", "sigma-")):
        ax_pol.plot(axis_mm, profiles["polarization_weights"][:, index], label=label)
    ax_pol.set_ylim(-0.03, 1.03)
    ax_pol.set_ylabel("polarization weight")
    ax_pol.set_xlabel("Zeeman-axis position toward MOT [mm]")
    ax_pol.set_title("Laser polarization in the local magnetic basis")
    ax_pol.legend()

    dominant = profiles["dominant_branch_index"]
    zeeman_shift_sign = np.choose(dominant, [0.0, -1.0, 1.0])
    transition = create_atom("Yb171").trans["399"]
    detuning_rad_s = ZEEMAN_LASER_CONFIG["detuning_gamma"] * transition.Gamma
    mu_rad_s_T = (
        transition.lande_factor * csts.value("Bohr magneton") / csts.hbar
    )
    ideal_speed_full = np.interp(
        profiles["axis_position_m"],
        profiles["main_axis_m"],
        profiles["ideal_speed_m_s"],
        left=profiles["ideal_speed_m_s"][0],
        right=profiles["ideal_speed_m_s"][-1],
    )
    effective_detuning_gamma = (
        detuning_rad_s
        + transition.k * ideal_speed_full
        + zeeman_shift_sign * mu_rad_s_T * profiles["field_norm_T"]
    ) / transition.Gamma
    ax_detuning.plot(axis_mm, effective_detuning_gamma, color="tab:orange")
    ax_detuning.axhline(0.0, color="black", linewidth=0.8)
    ax_detuning.set_ylabel("effective detuning [Gamma]")
    ax_detuning.set_xlabel("Zeeman-axis position toward MOT [mm]")
    ax_detuning.set_title("Ideal-guide detuning from dominant transition")

    for axis in axes.flat:
        axis.axvspan(magnet_min_mm, magnet_max_mm, color="0.8", alpha=0.18)
        axis.grid(alpha=0.22)

    fig.suptitle(
        f"Zeeman validation: {summary['active_magnet_profile']} "
        f"[{summary['status']}]",
        fontsize=15,
    )
    fig.tight_layout()
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return output_path


def write_report(summary, output_file):
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return output_path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_FILE)
    parser.add_argument("--plot", type=Path, default=DEFAULT_PLOT_FILE)
    parser.add_argument("--num-points", type=int, default=1201)
    parser.add_argument("--target-entry-speed", type=float, default=310.0)
    parser.add_argument("--target-exit-speed", type=float, default=50.0)
    parser.add_argument("--endpoint-tolerance", type=float, default=20.0)
    parser.add_argument(
        "--include-2d-mot-field",
        type=int,
        choices=[0, 1],
        default=1,
        help="Include the 2D-MOT permanent-magnet field, as production does.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    summary, profiles = analyze_zeeman_configuration(
        num_points=args.num_points,
        target_entry_speed_m_s=args.target_entry_speed,
        target_exit_speed_m_s=args.target_exit_speed,
        endpoint_tolerance_m_s=args.endpoint_tolerance,
        include_2d_mot_field=bool(args.include_2d_mot_field),
    )
    report_path = write_report(summary, args.report)
    plot_path = plot_validation(summary, profiles, args.plot)

    print(f"Zeeman validation status: {summary['status']}")
    for name, passed in summary["checks"].items():
        print(f"  {'PASS' if passed else 'REVIEW'}  {name}")
    for warning in summary["warnings"]:
        print(f"  WARNING {warning}")
    print(f"Report: {report_path}")
    print(f"Plot:   {plot_path}")


if __name__ == "__main__":
    main()
