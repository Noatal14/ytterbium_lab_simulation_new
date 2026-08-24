"""Run a few deterministic on-axis trajectories through the active Zeeman slower."""

from __future__ import annotations

import argparse
import json
from functools import partial
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from config import (
    Geometry,
    MOT_2D_LASER_CONFIG,
    MOT_2D_MAGNET_RADIUS_M,
    ZEEMAN_BEAM_DIRECTION,
    ZEEMAN_FIELD_CONFIG,
    ZEEMAN_LASER_CONFIG,
    ZEEMAN_SIM_CONFIG,
)
from lab_setup.config_builder import build_base_config
from lab_setup.zones import get_zeeman_only_zone
from studies.validate_zeeman_configuration import analyze_zeeman_configuration
from utils.ScipyIVP_3DCustom import ScipyIVP_3DCustom
from utils.data_paths import ZEEMAN_TRAJECTORY_VALIDATION_DIR
from utils.simulation_helpers import generate_timepoints, run_multiple_atoms_simulation


DEFAULT_SPEEDS_M_S = (250.0, 290.0, 310.0, 330.0, 350.0)
SLOWED_EXIT_SPEED_THRESHOLD_M_S = 80.0
DEFAULT_REPORT_FILE = ZEEMAN_TRAJECTORY_VALIDATION_DIR / "trajectory_diagnostics.json"
DEFAULT_PLOT_FILE = ZEEMAN_TRAJECTORY_VALIDATION_DIR / "trajectory_diagnostics.png"


def make_on_axis_initial_states(speeds_m_s):
    """Create atoms at the configured source point, moving toward the MOT."""
    beam_direction = np.asarray(ZEEMAN_BEAM_DIRECTION, dtype=float)
    atom_direction = -beam_direction
    start_position = beam_direction * ZEEMAN_SIM_CONFIG["start_distance_m"]
    return [
        np.concatenate((start_position, atom_direction * float(speed)))
        for speed in speeds_m_s
    ]


def summarize_trajectories(results, speeds_m_s):
    """Extract compact diagnostics from solver trajectories."""
    beam_direction = np.asarray(ZEEMAN_BEAM_DIRECTION, dtype=float)
    atom_direction = -beam_direction
    cutoff = float(ZEEMAN_SIM_CONFIG["cutoff_distance_m"])
    rows = []
    for requested_speed, result in zip(speeds_m_s, results):
        positions = np.asarray(result.y[:3], dtype=float).T
        velocities = np.asarray(result.y[3:6], dtype=float).T
        distance_from_mot = positions @ beam_direction
        axial_speed = velocities @ atom_direction
        radial_position = np.linalg.norm(
            positions - distance_from_mot[:, None] * beam_direction, axis=1
        )
        closest_index = int(np.argmin(distance_from_mot))
        exit_state = None
        for event_states in getattr(result, "y_events", []) or []:
            for event_state in event_states:
                event_distance = float(event_state[:3] @ beam_direction)
                if np.isclose(event_distance, cutoff, atol=1e-6, rtol=0.0):
                    exit_state = np.asarray(event_state, dtype=float)
                    break
            if exit_state is not None:
                break
        reached_cutoff = bool(
            exit_state is not None
            or np.min(distance_from_mot) <= cutoff + 1e-6
        )
        exit_speed = (
            float(exit_state[3:] @ atom_direction)
            if exit_state is not None
            else float(axial_speed[closest_index])
        )
        rows.append(
            {
                "requested_initial_speed_m_s": float(requested_speed),
                "actual_initial_axial_speed_m_s": float(axial_speed[0]),
                "final_axial_speed_m_s": float(axial_speed[-1]),
                "minimum_axial_speed_m_s": float(np.min(axial_speed)),
                "closest_distance_from_mot_m": float(distance_from_mot[closest_index]),
                "axial_speed_at_exit_or_closest_point_m_s": exit_speed,
                "maximum_radial_displacement_mm": float(np.max(radial_position) * 1e3),
                "reached_cutoff_plane": reached_cutoff,
                "slowed_below_exit_threshold": bool(
                    reached_cutoff and exit_speed <= SLOWED_EXIT_SPEED_THRESHOLD_M_S
                ),
                "solver_success": bool(getattr(result, "success", True)),
                "solver_message": str(getattr(result, "message", "")),
            }
        )
    return rows


def run_diagnostics(
    speeds_m_s=DEFAULT_SPEEDS_M_S,
    dt=ZEEMAN_SIM_CONFIG["dt_s"],
    solver_rtol=None,
    solver_atol=None,
    solver_max_step_s=None,
):
    """Run deterministic mean-force trajectories with the production configuration."""
    speeds_m_s = tuple(float(speed) for speed in speeds_m_s)
    if not speeds_m_s or any(speed <= 0.0 for speed in speeds_m_s):
        raise ValueError("speeds_m_s must contain positive speeds.")

    _, simulation_config = build_base_config(
        atom_species="Yb171",
        gravity_enabled=True,
        include_2d_mot=True,
        include_3dmot=False,
        include_zeeman=True,
        magnet_radius=MOT_2D_MAGNET_RADIUS_M,
        zeeman_field_config=ZEEMAN_FIELD_CONFIG,
        _2d_mot_config=MOT_2D_LASER_CONFIG,
        zeeman_config=ZEEMAN_LASER_CONFIG,
        zones=get_zeeman_only_zone(ZEEMAN_SIM_CONFIG["cutoff_distance_m"]),
    )
    time_points, _ = generate_timepoints(ZEEMAN_SIM_CONFIG["t_max_s"], dt)
    solver_options = {}
    if solver_rtol is not None:
        solver_options["rtol"] = float(solver_rtol)
    if solver_atol is not None:
        solver_options["atol"] = float(solver_atol)
    if solver_max_step_s is not None:
        solver_options["max_step"] = float(solver_max_step_s)
    simulation_function = partial(ScipyIVP_3DCustom, **solver_options)
    results, _ = run_multiple_atoms_simulation(
        config=simulation_config,
        u0=make_on_axis_initial_states(speeds_m_s),
        time_points=time_points,
        sim_function=simulation_function,
        npools=0,
    )
    return results, summarize_trajectories(results, speeds_m_s)


def _trajectory_arrays(result):
    beam_direction = np.asarray(ZEEMAN_BEAM_DIRECTION, dtype=float)
    positions = np.asarray(result.y[:3], dtype=float).T
    velocities = np.asarray(result.y[3:6], dtype=float).T
    distance_from_mot = positions @ beam_direction
    axis_toward_mot = Geometry.ZEEMAN_START_DISTANCE_M - distance_from_mot
    axial_speed = velocities @ -beam_direction
    radial_mm = np.linalg.norm(
        positions - distance_from_mot[:, None] * beam_direction, axis=1
    ) * 1e3
    return axis_toward_mot, axial_speed, radial_mm


def plot_diagnostics(results, rows, output_file):
    """Plot speed, resonance tracking, transverse displacement, and time traces."""
    _, profiles = analyze_zeeman_configuration()
    resonance_axis = profiles["axis_position_m"]
    resonance_speed = profiles["dominant_resonant_speed_m_s"]
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    ax_speed, ax_mismatch, ax_radial, ax_time = axes.flat
    ax_speed.plot(
        resonance_axis * 1e3,
        resonance_speed,
        "k--",
        linewidth=2,
        label="dominant local resonance",
    )

    for result, row in zip(results, rows):
        axis, speed, radial_mm = _trajectory_arrays(result)
        local_resonance = np.interp(axis, resonance_axis, resonance_speed)
        label = f"{row['requested_initial_speed_m_s']:.0f} m/s"
        line = ax_speed.plot(axis * 1e3, speed, label=label)[0]
        color = line.get_color()
        ax_mismatch.plot(axis * 1e3, speed - local_resonance, color=color)
        ax_radial.plot(axis * 1e3, radial_mm, color=color)
        ax_time.plot(np.asarray(result.t) * 1e3, speed, color=color)

    cutoff_axis_mm = (
        Geometry.ZEEMAN_START_DISTANCE_M - ZEEMAN_SIM_CONFIG["cutoff_distance_m"]
    ) * 1e3
    ax_speed.axvline(cutoff_axis_mm, color="0.4", linestyle=":", label="cutoff")
    ax_speed.set_ylabel("axial speed [m/s]")
    ax_speed.set_title("Particle speed and local Zeeman resonance")
    ax_speed.legend(fontsize=8)
    ax_mismatch.axhline(0.0, color="black", linewidth=0.8)
    ax_mismatch.set_ylabel("particle speed - resonance [m/s]")
    ax_mismatch.set_title("Resonance tracking (near zero means following)")
    ax_radial.axhline(
        Geometry.ZEEMAN_ARM_1_RADIUS_M * 1e3,
        color="black",
        linestyle="--",
        label="arm-1 radius",
    )
    ax_radial.set_ylabel("distance from axis [mm]")
    ax_radial.set_title("Transverse motion")
    ax_time.set_ylabel("axial speed [m/s]")
    ax_time.set_xlabel("time [ms]")
    ax_time.set_title("Speed versus time")
    for axis in (ax_speed, ax_mismatch, ax_radial):
        axis.set_xlabel("distance traveled toward MOT [mm]")
    for axis in axes.flat:
        axis.grid(alpha=0.22)
    fig.suptitle("Deterministic Zeeman trajectory diagnostics", fontsize=15)
    fig.tight_layout()
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return output_path


def write_report(rows, speeds_m_s, dt, output_file):
    report = {
        "purpose": "small deterministic on-axis Zeeman trajectory diagnostic",
        "interpretation": (
            "These mean-force trajectories are a physics diagnostic, not a statistical "
            "capture-efficiency estimate. Production runs remain stochastic and multi-seed."
        ),
        "configuration": {
            "initial_speeds_m_s": [float(speed) for speed in speeds_m_s],
            "dt_s": float(dt),
            "t_max_s": ZEEMAN_SIM_CONFIG["t_max_s"],
            "start_distance_m": ZEEMAN_SIM_CONFIG["start_distance_m"],
            "cutoff_distance_m": ZEEMAN_SIM_CONFIG["cutoff_distance_m"],
            "slowed_exit_speed_threshold_m_s": SLOWED_EXIT_SPEED_THRESHOLD_M_S,
            "laser": ZEEMAN_LASER_CONFIG,
        },
        "trajectories": rows,
    }
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return output_path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speeds", type=float, nargs="+", default=DEFAULT_SPEEDS_M_S)
    parser.add_argument("--dt", type=float, default=ZEEMAN_SIM_CONFIG["dt_s"])
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_FILE)
    parser.add_argument("--plot", type=Path, default=DEFAULT_PLOT_FILE)
    return parser.parse_args()


def main():
    args = parse_args()
    results, rows = run_diagnostics(args.speeds, args.dt)
    report_path = write_report(rows, args.speeds, args.dt, args.report)
    plot_path = plot_diagnostics(results, rows, args.plot)
    for row in rows:
        print(
            f"{row['requested_initial_speed_m_s']:6.1f} -> "
            f"{row['axial_speed_at_exit_or_closest_point_m_s']:7.2f} m/s; "
            f"cutoff={'yes' if row['reached_cutoff_plane'] else 'no'}; "
            f"slowed={'yes' if row['slowed_below_exit_threshold'] else 'no'}; "
            f"closest={row['closest_distance_from_mot_m'] * 1e3:.2f} mm"
        )
    print(f"Report: {report_path}")
    print(f"Plot:   {plot_path}")


if __name__ == "__main__":
    main()
