"""Run the 3D-MOT stage and evaluate a configurable capture criterion."""

import argparse

import numpy as np

from config import (
    DEFAULT_NUM_POOLS,
    DEFAULT_RANDOM_SEED,
    Geometry,
    MOT_2D_LASER_CONFIG,
    MOT_2D_MAGNET_RADIUS_M,
    MOT_3D_CAPTURE_CONFIG,
    MOT_3D_LASER_CONFIG,
    MOT_3D_SIM_CONFIG,
    ZEEMAN_LASER_CONFIG,
)
from lab_setup.config_builder import build_base_config
from lab_setup.zones import get_entire_apparatus_zone
from utils.ScipyIVP_3DCustom import ScipyIVP_3DCustom
from utils.data_paths import (
    DEFAULT_2D_MOT_STATES_FILE,
    DEFAULT_3D_MOT_STATES_FILE,
    DEFAULT_3D_MOT_SUMMARY_FILE,
    load_particle_states,
    save_particle_states,
)
from utils.file_helpers import save_file_json
from utils.simulation_helpers import generate_timepoints, run_multiple_atoms_simulation


def _continuous_final_residence_time(time_points, inside_capture_region):
    """Return time spent continuously inside the region at trajectory end."""
    if len(time_points) == 0 or not inside_capture_region[-1]:
        return 0.0
    outside_indices = np.flatnonzero(~inside_capture_region)
    start_index = outside_indices[-1] + 1 if len(outside_indices) else 0
    return float(time_points[-1] - time_points[start_index])


def extract_3d_mot_captured(
    results,
    center_m=Geometry.MOT_3D_CENTER_M,
    capture_radius_m=MOT_3D_CAPTURE_CONFIG["capture_radius_m"],
    minimum_residence_time_s=MOT_3D_CAPTURE_CONFIG[
        "minimum_residence_time_s"
    ],
    maximum_final_speed_m_s=MOT_3D_CAPTURE_CONFIG[
        "maximum_final_speed_m_s"
    ],
):
    """Select atoms that finish slow and remain near the 3D-MOT center.

    An atom is captured when its final continuous stay inside the spherical
    capture region lasts at least ``minimum_residence_time_s`` and its final
    speed does not exceed ``maximum_final_speed_m_s``.
    """
    center = np.asarray(center_m, dtype=float)
    captured_states = []
    captured_indices = []

    for index, trajectory in enumerate(results):
        time_points = np.asarray(trajectory.t, dtype=float)
        states = np.asarray(trajectory.y, dtype=float)
        if time_points.size == 0 or states.ndim != 2 or states.shape[0] < 6:
            continue
        distances = np.linalg.norm(states[:3].T - center, axis=1)
        residence_time = _continuous_final_residence_time(
            time_points, distances <= capture_radius_m
        )
        final_speed = float(np.linalg.norm(states[3:6, -1]))
        if (
            residence_time + np.finfo(float).eps >= minimum_residence_time_s
            and final_speed <= maximum_final_speed_m_s
        ):
            captured_indices.append(index)
            captured_states.append(states[:6, -1].copy())

    states_array = (
        np.asarray(captured_states, dtype=float)
        if captured_states
        else np.empty((0, 6))
    )
    return states_array, captured_indices


def mot_3d_simulation(
    survivor_states,
    _3d_mot_config=MOT_3D_LASER_CONFIG,
    gravity_enabled=True,
    npools=DEFAULT_NUM_POOLS,
    dt=MOT_3D_SIM_CONFIG["dt_s"],
    seed=DEFAULT_RANDOM_SEED,
):
    """Propagate saved 2D-MOT states through the 3D-MOT stage."""
    if len(survivor_states) == 0:
        return [], np.empty((0, 6))
    _, simulation_config = build_base_config(
        atom_species="Yb171",
        include_zeeman=True,
        include_2d_mot=True,
        include_3dmot=True,
        gravity_enabled=gravity_enabled,
        magnet_radius=MOT_2D_MAGNET_RADIUS_M,
        _2d_mot_config=MOT_2D_LASER_CONFIG,
        zeeman_config=ZEEMAN_LASER_CONFIG,
        zones=get_entire_apparatus_zone(),
        _3d_mot_config=_3d_mot_config,
    )
    time_points, _ = generate_timepoints(MOT_3D_SIM_CONFIG["t_max_s"], dt)
    results, _ = run_multiple_atoms_simulation(
        config=simulation_config,
        u0=[np.asarray(state).copy() for state in survivor_states],
        time_points=time_points,
        sim_function=ScipyIVP_3DCustom,
        npools=npools,
        seed_idx=seed,
    )
    captured_states, _ = extract_3d_mot_captured(results)
    return results, captured_states


def run_3d_mot_from_file(input_file, output_file, summary_file, **kwargs):
    input_states = load_particle_states(input_file)
    results, captured_states = mot_3d_simulation(input_states, **kwargs)
    output_path = save_particle_states(output_file, captured_states)
    captured_count = len(captured_states)
    capture_percentage = (
        100.0 * captured_count / len(input_states) if len(input_states) else 0.0
    )
    summary = {
        "input_particle_count": len(input_states),
        "captured_particle_count": captured_count,
        "capture_percentage": capture_percentage,
        "criterion": dict(MOT_3D_CAPTURE_CONFIG),
        "capture_center_m": list(Geometry.MOT_3D_CENTER_M),
        "captured_states_file": str(output_path),
    }
    save_file_json(summary_file, summary)
    print(
        f"3D-MOT captured: {captured_count}/{len(input_states)} "
        f"({capture_percentage:.4f}%)"
    )
    return results, captured_states, summary


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_2D_MOT_STATES_FILE))
    parser.add_argument("--output", default=str(DEFAULT_3D_MOT_STATES_FILE))
    parser.add_argument("--summary", default=str(DEFAULT_3D_MOT_SUMMARY_FILE))
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_3d_mot_from_file(
        args.input,
        args.output,
        args.summary,
        npools=args.npools,
        dt=args.dt,
        seed=args.seed,
    )
