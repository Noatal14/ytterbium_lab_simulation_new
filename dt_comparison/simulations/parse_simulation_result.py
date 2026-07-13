import numpy as np
from config import K_B, YB171_MASS_KG, F_scale, Geometry

def is_transmitted_2d_mot(final_pos, trajectory=None):
    """Determine if the final position corresponds to a transmitted atom."""
    return (final_pos[2] >= 0.0195) and (np.sqrt(final_pos[0]**2 + final_pos[1]**2) <= 0.015)


def is_transmitted_zeeman(final_pos, trajectory=None, cutoff_distance=0.100, beam_dir=None):
    """Determine whether a Zeeman trajectory reached the cutoff boundary."""
    if trajectory is None:
        return False

    if beam_dir is None:
        angle_rad = np.radians(Geometry.ZEEMAN_ARM_ANGLE_DEG)
        beam_dir = np.array([0, -np.sin(angle_rad), -np.cos(angle_rad)])

    positions = np.asarray(trajectory[:3, :]).T
    if positions.size == 0:
        return False

    proj = positions @ beam_dir
    min_proj = np.min(proj)
    return min_proj <= cutoff_distance + 0.010


def parse_stoch_results(seed_results, is_transmitted_fn=None):
    """Compute mean trajectory arrays for the transmitted stochastic runs.

    All transmitted trajectories are trimmed to the shortest transmitted length so
    the mean arrays are aligned and comparisons use a consistent size.
    """
    if is_transmitted_fn is None:
        is_transmitted_fn = is_transmitted_2d_mot

    transmitted_trajectories = []
    transmitted_Ns = []
    transmitted_forces = []
    completed_lengths = []

    for seed_idx, y, sim in seed_results:
        if y.shape[1] == 0:
            continue
        completed_lengths.append(int(y.shape[1]))
        final_pos = y[:3, -1]
        is_transmitted = bool(is_transmitted_fn(final_pos, y))
        if is_transmitted:
            transmitted_trajectories.append(y)
            if hasattr(sim, "tracked_Ni_vals") and sim.tracked_Ni_vals:
                # sim.tracked_Ni_vals is a list of per-timestep Ni arrays
                transmitted_Ns.append([np.asarray(row, dtype=float) for row in sim.tracked_Ni_vals])
            if hasattr(sim, "tracked_force_vals") and sim.tracked_force_vals:
                # sim.tracked_force_vals is a list of per-timestep force arrays
                transmitted_forces.append([np.asarray(row, dtype=float) for row in sim.tracked_force_vals])

    if not transmitted_trajectories:
        return {
            "timepoints": 0,
            "transmitted": 0,
            "mean_x_position": np.array([]),
            "mean_y_position": np.array([]),
            "mean_z_position": np.array([]),
            "mean_x_velocity": np.array([]),
            "mean_y_velocity": np.array([]),
            "mean_z_velocity": np.array([]),
            "std_x_position": np.array([]),
            "std_y_position": np.array([]),
            "std_z_position": np.array([]),
            "std_x_velocity": np.array([]),
            "std_y_velocity": np.array([]),
            "std_z_velocity": np.array([]),
            "mean_N_channels": [],
            "std_N_channels": [],
            "completed_runs": len(completed_lengths),
            "trajectory_lengths": completed_lengths,
        }

    min_steps = min(y.shape[1] for y in transmitted_trajectories)

    pos_sum = np.zeros((3, min_steps), dtype=float)
    vel_sum = np.zeros((3, min_steps), dtype=float)

    pos_sq_sum = np.zeros((3, min_steps), dtype=float)
    vel_sq_sum = np.zeros((3, min_steps), dtype=float)

    for y in transmitted_trajectories:
        pos_sum += y[:3, :min_steps]
        vel_sum += y[3:, :min_steps]
        pos_sq_sum += y[:3, :min_steps] ** 2
        vel_sq_sum += y[3:, :min_steps] ** 2

    count = len(transmitted_trajectories)

    mean_positions = pos_sum / count
    mean_velocities = vel_sum / count

    mean_pos_sq = pos_sq_sum / count
    mean_vel_sq = vel_sq_sum / count

    std_positions = np.sqrt(np.maximum(mean_pos_sq - mean_positions ** 2, 0.0))
    std_velocities = np.sqrt(np.maximum(mean_vel_sq - mean_velocities ** 2, 0.0))

    # Compute per-channel mean/std across seeds. Build an array per seed with shape (min_steps, channels)
    if transmitted_Ns:
        # Determine max channels across all seeds and timesteps
        max_channels = 0
        for seed_N in transmitted_Ns:
            for row in seed_N[:min_steps]:
                if row.size > max_channels:
                    max_channels = row.size

        # Build stack: (n_seeds, min_steps, max_channels)
        seed_stack = np.zeros((len(transmitted_Ns), min_steps, max_channels), dtype=float)
        for s_idx, seed_N in enumerate(transmitted_Ns):
            for t_idx in range(min_steps):
                if t_idx < len(seed_N):
                    row = np.asarray(seed_N[t_idx], dtype=float)
                    seed_stack[s_idx, t_idx, : row.size] = row

        mean_N_by_time_channel = np.mean(seed_stack, axis=0)  # (min_steps, max_channels)
        std_N_by_time_channel = np.std(seed_stack, axis=0, ddof=0)  # population std

        # Convert to list-of-arrays where each inner array is mean over seeds for that channel
        mean_N_channels = [mean_N_by_time_channel[:, ch] for ch in range(mean_N_by_time_channel.shape[1])]
        std_N_channels = [std_N_by_time_channel[:, ch] for ch in range(std_N_by_time_channel.shape[1])]
    else:
        mean_N_channels = []
        std_N_channels = []

    if transmitted_forces:
        max_force_channels = 0
        for seed_F in transmitted_forces:
            for row in seed_F[:min_steps]:
                if row.size > max_force_channels:
                    max_force_channels = row.size

        force_stack = np.zeros((len(transmitted_forces), min_steps, max_force_channels), dtype=float)
        for s_idx, seed_F in enumerate(transmitted_forces):
            for t_idx in range(min_steps):
                if t_idx < len(seed_F):
                    row = np.asarray(seed_F[t_idx], dtype=float)
                    force_stack[s_idx, t_idx, : row.size] = row

        mean_force_by_time_channel = np.mean(force_stack, axis=0)
        std_force_by_time_channel = np.std(force_stack, axis=0, ddof=0)

        mean_force_channels = [mean_force_by_time_channel[:, ch] for ch in range(mean_force_by_time_channel.shape[1])]
        normalized_mean_force_channels = [f/F_scale for f in mean_force_channels]
        std_force_channels = [std_force_by_time_channel[:, ch] for ch in range(std_force_by_time_channel.shape[1])]
        normalized_std_force_channels = [f/F_scale for f in std_force_channels]
    else:
        mean_force_channels = []
        normalized_mean_force_channels = []
        std_force_channels = []
        normalized_std_force_channels = []

    return {
        "timepoints": min_steps,
        "transmitted": count,
        "mean_x_position": mean_positions[0],
        "mean_y_position": mean_positions[1],
        "mean_z_position": mean_positions[2],
        "mean_x_velocity": mean_velocities[0],
        "mean_y_velocity": mean_velocities[1],
        "mean_z_velocity": mean_velocities[2],
        "std_x_position": std_positions[0],
        "std_y_position": std_positions[1],
        "std_z_position": std_positions[2],
        "std_x_velocity": std_velocities[0],
        "std_y_velocity": std_velocities[1],
        "std_z_velocity": std_velocities[2],
        "mean_N_channels": mean_N_channels,
        "std_N_channels": std_N_channels,
        "mean_force_channels": mean_force_channels,
        "std_force_channels": std_force_channels,
        "normalized_mean_force_channels": normalized_mean_force_channels,
        "normalized_std_force_channels": normalized_std_force_channels,
        "completed_runs": len(completed_lengths),
        "trajectory_lengths": completed_lengths,
    }


def parse_det_results(y, is_transmitted_fn=None):
    """Analyze a deterministic trajectory `y` and return the same row format as stochastic analysis."""
    timepoints = y.shape[1]

    position_x = np.full(timepoints, np.nan)
    position_y = np.full(timepoints, np.nan)
    position_z = np.full(timepoints, np.nan)

    velocity_x = np.full(timepoints, np.nan)
    velocity_y = np.full(timepoints, np.nan)
    velocity_z = np.full(timepoints, np.nan)

    if is_transmitted_fn is None:
        is_transmitted_fn = is_transmitted_2d_mot

    if timepoints > 0:
        final_pos = y[:3, -1]
        final_vel = y[3:, -1]

        position_x[:] = y[0, :]
        position_y[:] = y[1, :]
        position_z[:] = y[2, :]
        velocity_x[:] = y[3, :]
        velocity_y[:] = y[4, :]
        velocity_z[:] = y[5, :]

        is_transmitted = bool(is_transmitted_fn(final_pos, y))

    return {
        "transmitted": is_transmitted,
        "timepoints": timepoints,
        "position_x": position_x,
        "position_y": position_y,
        "position_z": position_z,
        "velocity_x": velocity_x,
        "velocity_y": velocity_y,
        "velocity_z": velocity_z,
    }


def parse_results(seed_results, det_y, dt, is_transmitted_fn=None):
    """Compare stochastic seed results to one deterministic trajectory.

    Returns a compact row with raw stochastic mean/std arrays and deterministic arrays.
    """
    det_row = parse_det_results(det_y, is_transmitted_fn=is_transmitted_fn)
    stoch_row = parse_stoch_results(seed_results, is_transmitted_fn=is_transmitted_fn)

    return {
        "dt": dt,
        "stochastic_results": stoch_row,
        "deterministic_results": det_row,
    }
