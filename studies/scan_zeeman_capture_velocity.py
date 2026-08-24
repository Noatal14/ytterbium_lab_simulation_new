"""Locate the deterministic on-axis Zeeman capture-velocity boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from config import ZEEMAN_LASER_CONFIG, ZEEMAN_SIM_CONFIG
from studies.diagnose_zeeman_trajectories import (
    SLOWED_EXIT_SPEED_THRESHOLD_M_S,
    run_diagnostics,
)
from utils.data_paths import ZEEMAN_CAPTURE_SCAN_DIR


DEFAULT_REPORT_FILE = ZEEMAN_CAPTURE_SCAN_DIR / "capture_velocity_scan.json"
DEFAULT_PLOT_FILE = ZEEMAN_CAPTURE_SCAN_DIR / "capture_velocity_scan.png"


def summarize_capture_boundary(rows):
    """Describe sampled capture intervals without assuming monotonic behavior."""
    ordered = sorted(rows, key=lambda row: row["requested_initial_speed_m_s"])
    outcomes = [bool(row["slowed_below_exit_threshold"]) for row in ordered]
    speeds = [float(row["requested_initial_speed_m_s"]) for row in ordered]
    transitions = [
        {
            "from_speed_m_s": speeds[index - 1],
            "to_speed_m_s": speeds[index],
            "from_slowed": outcomes[index - 1],
            "to_slowed": outcomes[index],
        }
        for index in range(1, len(ordered))
        if outcomes[index] != outcomes[index - 1]
    ]
    seen_unslowed = False
    monotonic_capture_loss = True
    for slowed_outcome in outcomes:
        if not slowed_outcome:
            seen_unslowed = True
        elif seen_unslowed:
            monotonic_capture_loss = False

    slowed = [row for row in ordered if row["slowed_below_exit_threshold"]]
    if not slowed:
        return {
            "capture_is_monotonic_over_sampled_speeds": True,
            "highest_slowed_initial_speed_m_s": None,
            "first_higher_unslowed_initial_speed_m_s": ordered[0][
                "requested_initial_speed_m_s"
            ] if ordered else None,
            "boundary_bracket_m_s": None,
            "outcome_transitions": transitions,
        }
    highest_slowed = max(row["requested_initial_speed_m_s"] for row in slowed)
    higher_unslowed = [
        row["requested_initial_speed_m_s"]
        for row in ordered
        if row["requested_initial_speed_m_s"] > highest_slowed
        and not row["slowed_below_exit_threshold"]
    ]
    first_unslowed = min(higher_unslowed) if higher_unslowed else None
    return {
        "capture_is_monotonic_over_sampled_speeds": monotonic_capture_loss,
        "highest_slowed_initial_speed_m_s": float(highest_slowed),
        "first_higher_unslowed_initial_speed_m_s": (
            float(first_unslowed) if first_unslowed is not None else None
        ),
        "boundary_bracket_m_s": (
            [float(highest_slowed), float(first_unslowed)]
            if first_unslowed is not None and monotonic_capture_loss
            else None
        ),
        "outcome_transitions": transitions,
    }


def plot_scan(rows, boundary, output_file):
    initial = np.array([row["requested_initial_speed_m_s"] for row in rows])
    exit_speed = np.array(
        [row["axial_speed_at_exit_or_closest_point_m_s"] for row in rows]
    )
    slowed = np.array([row["slowed_below_exit_threshold"] for row in rows])

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    ax_speed, ax_deceleration = axes
    ax_speed.plot(initial, exit_speed, color="0.65", linewidth=1.2)
    ax_speed.scatter(initial[slowed], exit_speed[slowed], color="tab:blue", label="slowed")
    ax_speed.scatter(
        initial[~slowed], exit_speed[~slowed], color="tab:red", label="not slowed"
    )
    ax_speed.axhline(
        SLOWED_EXIT_SPEED_THRESHOLD_M_S,
        color="black",
        linestyle="--",
        label=f"{SLOWED_EXIT_SPEED_THRESHOLD_M_S:.0f} m/s threshold",
    )
    ax_speed.set_xlabel("initial axial speed [m/s]")
    ax_speed.set_ylabel("speed at Zeeman exit [m/s]")
    ax_speed.set_title("Deterministic capture transition")
    ax_speed.legend()

    ax_deceleration.plot(initial, initial - exit_speed, marker="o")
    ax_deceleration.set_xlabel("initial axial speed [m/s]")
    ax_deceleration.set_ylabel("speed removed [m/s]")
    ax_deceleration.set_title("Net slowing across the Zeeman stage")

    bracket = boundary["boundary_bracket_m_s"]
    if bracket is not None:
        for axis in axes:
            axis.axvspan(bracket[0], bracket[1], color="tab:orange", alpha=0.18)
    for axis in axes:
        axis.grid(alpha=0.22)
    fig.suptitle("Zeeman on-axis capture-velocity scan", fontsize=15)
    fig.tight_layout()
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return output_path


def write_report(rows, boundary, speeds, dt, solver_settings, output_file):
    report = {
        "purpose": "deterministic on-axis capture-velocity boundary scan",
        "interpretation": (
            "This brackets the ideal on-axis mean-force capture speed. It does not "
            "replace stochastic thermal-ensemble efficiency estimates."
        ),
        "configuration": {
            "initial_speeds_m_s": [float(speed) for speed in speeds],
            "dt_s": float(dt),
            "dt_role": "saved output sampling; not the adaptive solver internal step",
            "adaptive_solver": solver_settings,
            "exit_speed_threshold_m_s": SLOWED_EXIT_SPEED_THRESHOLD_M_S,
            "laser": ZEEMAN_LASER_CONFIG,
            "t_max_s": ZEEMAN_SIM_CONFIG["t_max_s"],
        },
        "boundary": boundary,
        "trajectories": rows,
    }
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return output_path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-speed", type=float, default=310.0)
    parser.add_argument("--max-speed", type=float, default=330.0)
    parser.add_argument("--step", type=float, default=1.0)
    parser.add_argument("--dt", type=float, default=ZEEMAN_SIM_CONFIG["dt_s"])
    parser.add_argument("--solver-rtol", type=float)
    parser.add_argument("--solver-atol", type=float)
    parser.add_argument("--solver-max-step", type=float)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_FILE)
    parser.add_argument("--plot", type=Path, default=DEFAULT_PLOT_FILE)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.step <= 0.0 or args.max_speed < args.min_speed:
        raise ValueError("Require step > 0 and max-speed >= min-speed.")
    speeds = np.round(
        np.arange(
            args.min_speed,
            args.max_speed + args.step * 0.5,
            args.step,
            dtype=float,
        ),
        decimals=10,
    )
    _, rows = run_diagnostics(
        speeds,
        args.dt,
        solver_rtol=args.solver_rtol,
        solver_atol=args.solver_atol,
        solver_max_step_s=args.solver_max_step,
    )
    boundary = summarize_capture_boundary(rows)
    solver_settings = {
        "rtol": args.solver_rtol,
        "atol": args.solver_atol,
        "max_step_s": args.solver_max_step,
        "uses_scipy_defaults_when_null": True,
    }
    report_path = write_report(
        rows, boundary, speeds, args.dt, solver_settings, args.report
    )
    plot_path = plot_scan(rows, boundary, args.plot)
    print(f"Highest slowed input: {boundary['highest_slowed_initial_speed_m_s']} m/s")
    print(
        "First higher unslowed input: "
        f"{boundary['first_higher_unslowed_initial_speed_m_s']} m/s"
    )
    print(
        "Monotonic capture loss: "
        f"{boundary['capture_is_monotonic_over_sampled_speeds']}"
    )
    print(f"Report: {report_path}")
    print(f"Plot:   {plot_path}")


if __name__ == "__main__":
    main()
