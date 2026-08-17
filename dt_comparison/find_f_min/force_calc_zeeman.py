from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.cm import ScalarMappable
from matplotlib.ticker import ScalarFormatter
from config import YB171_MASS_KG, ZEEMAN_BEAM_DIR, _2d_mot_laser_config, zeeman_laser_config, zeeman_field_config, _2d_mot_magnet_radius
from dt_comparison.consts import F_scale
from split_simulation import zeeman_simulation
from utils.file_helpers import read_data_json, save_file_json

def run_zeeman_sim_and_save_data(
        s0,
        detuning_gamma,
        N_particles=1000,
    ):
    zeeman_traj, _, surv_idx = zeeman_simulation(
        N_particles=N_particles,
        _2d_mot_config={ "s0": s0, "detuning_gamma": detuning_gamma },
        zeeman_config=zeeman_laser_config,
        zeeman_field_config=zeeman_field_config,
        magnet_radius=_2d_mot_magnet_radius,
        stochastic=False
    )

    survivors_y = [zeeman_traj[i].y for i in surv_idx]
    survivors_t = [zeeman_traj[i].t for i in surv_idx]

    save_dir = "dt_comparison/data/zeeman_sim_data"
    save_path = Path(save_dir)

    save_file_json(save_path / f"survivors_y.json", survivors_y)
    save_file_json(save_path / f"survivors_t.json", survivors_t)

def _find_cooling_window(
    axial_position,
    v_parallel,
    cooling_window_distance,
    cooling_onset_delta_v,
    cooling_end_delta_v,
    cooling_monotonic_fraction,
    cooling_end_consecutive_windows,
):
    """
    Detect the onset and end of active Zeeman-slower cooling along one
    deterministic trajectory.

    Parameters
    ----------
    axial_position : array-like
        Longitudinal position along the atomic propagation direction.
        Expected to increase as the atom propagates forward.

    v_parallel : array-like
        Velocity component along the same propagation direction.

    cooling_window_distance : float
        Physical distance over which the velocity drop is evaluated.

    cooling_onset_delta_v : float
        Minimum velocity drop over one distance window required to identify
        the beginning of cooling.

    cooling_end_delta_v : float
        Maximum velocity drop over one distance window considered effectively
        flat / no longer actively cooling.

    cooling_monotonic_fraction : float
        Required fraction of local velocity differences that must be negative
        inside an onset window.

    cooling_end_consecutive_windows : int
        Number of consecutive flat windows required to declare that cooling
        has ended.

    Returns
    -------
    onset_idx : int
        Index where active cooling begins, or -1 if no cooling window is found.

    end_idx : int
        Index where active cooling ends, or -1 if no cooling window is found.
        If cooling continues until the trajectory ends, returns the last index.
    """

    axial_position = np.asarray(axial_position)
    v_parallel = np.asarray(v_parallel)

    n = len(axial_position)

    if n < 3 or len(v_parallel) != n:
        return -1, -1

    # Distance traveled from the beginning of the trajectory.
    # For a valid forward trajectory this should be monotonically increasing.
    distance_traveled = axial_position - axial_position[0]

    # Reject trajectories that clearly move in the wrong direction.
    # Tiny numerical fluctuations are tolerated.
    scale = max(np.ptp(axial_position), 1.0)
    tol = 1e-10 * scale

    if np.any(np.diff(distance_traveled) < -tol):
        return -1, -1

    # Remove tiny floating-point non-monotonicity so searchsorted is safe.
    distance_traveled = np.maximum.accumulate(distance_traveled)

    def _window_end(i):
        target_distance = (
            distance_traveled[i] + cooling_window_distance
        )

        j = np.searchsorted(
            distance_traveled,
            target_distance,
            side="left",
        )

        return j if j < n else None

    # ---------------------------------------------------------
    # Find cooling onset
    # ---------------------------------------------------------

    onset_idx = -1

    for i in range(n):

        j = _window_end(i)

        if j is None:
            break

        window_drop = v_parallel[i] - v_parallel[j]

        if window_drop < cooling_onset_delta_v:
            continue

        local_diffs = np.diff(v_parallel[i : j + 1])

        if local_diffs.size == 0:
            continue

        monotonic_fraction = np.mean(local_diffs < 0)

        if monotonic_fraction >= cooling_monotonic_fraction:
            onset_idx = i
            break

    if onset_idx == -1:
        return -1, -1

    # ---------------------------------------------------------
    # Find cooling end
    # ---------------------------------------------------------

    end_idx = n - 1

    consecutive = 0
    run_start = None

    for i in range(onset_idx, n):

        j = _window_end(i)

        if j is None:
            break

        window_drop = v_parallel[i] - v_parallel[j]

        if window_drop < cooling_end_delta_v:

            if consecutive == 0:
                run_start = i

            consecutive += 1

            if consecutive >= cooling_end_consecutive_windows:
                end_idx = run_start
                break

        else:
            consecutive = 0
            run_start = None

    return onset_idx, end_idx

import numpy as np

def extract_cooling_trajectory_inputs(
    res_y_list,
    propagation_direction,
):
    """
    Extract axial position and longitudinal velocity for every trajectory
    returned by atomsmltr.

    Parameters
    ----------
    res_list : list
        List of atomsmltr simulation results, one result per atom.

    propagation_direction : array-like, shape (3,)
        Direction of forward atomic propagation along the Zeeman slower.

    Returns
    -------
    trajectories : list of tuples
        trajectories[i] = (axial_position, v_parallel) for atom i.
    """

    propagation_direction = np.asarray(
        propagation_direction,
        dtype=float,
    )

    propagation_direction /= np.linalg.norm(
        propagation_direction
    )

    trajectories = []

    for res_y in res_y_list:

        y = np.asarray(res_y)

        if y.ndim != 2 or y.shape[0] < 6:
            raise ValueError(
                f"Expected res.y with shape (6, N), got {y.shape}"
            )

        positions = y[:3, :].T
        velocities = y[3:6, :].T

        axial_position = positions @ propagation_direction
        v_parallel = velocities @ propagation_direction

        trajectories.append(
            (axial_position, v_parallel)
        )

    return trajectories

def get_cooling_window_forces(
    y_list,
    t_list,
    cooling_windows,
    mass=YB171_MASS_KG,
):
    """
    Compute the total force magnitude along each atom's cooling window
    using F = m * |dv/dt|.

    Parameters
    ----------
    y_list : list
        y_list[i] is the trajectory array of atom i,
        with shape (6, N_i).

    t_list : list
        t_list[i] contains the timepoints corresponding to y_list[i],
        with shape (N_i,).

    cooling_windows : list
        cooling_windows[i] = [start_idx, end_idx].
        [-1, -1] means no cooling window was detected.

    mass : float
        Atomic mass in kg.

    Returns
    -------
    force_lists : list of np.ndarray
        force_lists[i] contains |F| at every trajectory point
        inside atom i's cooling window.
    """

    if not (
        len(y_list)
        == len(t_list)
        == len(cooling_windows)
    ):
        raise ValueError(
            "y_list, t_list, and cooling_windows "
            "must have the same length."
        )

    force_lists = []

    for y, t, (start_idx, end_idx) in zip(
        y_list,
        t_list,
        cooling_windows,
    ):
        if start_idx == -1 or end_idx == -1:
            force_lists.append(np.array([]))
            continue

        y = np.asarray(y)
        t = np.asarray(t)

        velocities = y[3:6, :]  # shape (3, N)

        # dv/dt for each velocity component
        acceleration = np.gradient(
            velocities,
            t,
            axis=1,
        )

        # |a|
        acceleration_magnitude = np.linalg.norm(
            acceleration,
            axis=0,
        )

        # |F| = m|a|
        force_magnitude = mass * acceleration_magnitude

        force_lists.append(
            force_magnitude[start_idx:end_idx + 1]
        )

    return force_lists


def plot_cooling_forces_vs_time(
    force_lists,
    t_list,
    cooling_windows,
    F_scale,
    initial_velocities,
    alpha=1.0,
):
    fig, ax = plt.subplots(figsize=(8, 5))

    initial_velocities = np.asarray(initial_velocities)

    norm = mcolors.Normalize(
        vmin=100,
        vmax=330,
    )

    cmap = plt.colormaps["coolwarm"]

    for i, (forces, t, (start_idx, end_idx)) in enumerate(
        zip(force_lists, t_list, cooling_windows)
    ):
        if start_idx == -1 or end_idx == -1 or len(forces) == 0:
            continue

        t = np.asarray(t)
        timepoints = t[start_idx:end_idx + 1]

        if len(timepoints) != len(forces):
            raise ValueError(
                f"Time/force length mismatch: "
                f"{len(timepoints)} timepoints vs "
                f"{len(forces)} forces."
            )

        normalized_forces = np.asarray(forces) / F_scale

        color = cmap(norm(initial_velocities[i]))

        ax.plot(
            timepoints,
            normalized_forces,
            color=color,
            alpha=alpha,
        )

    ax.set_xlabel("Time [s]")
    ax.set_ylabel(r"$|F| / F_{\mathrm{scale}}$")

    formatter = ScalarFormatter(useMathText=True)
    formatter.set_scientific(True)
    formatter.set_powerlimits((0, 0))
    ax.xaxis.set_major_formatter(formatter)

    ax.grid(alpha=0.3)

    # Colorbar showing the initial velocity
    sm = ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])

    cbar = fig.colorbar(sm, ax=ax)
    cbar.set_label(
        r"Initial longitudinal velocity $v_0$ [m/s]"
    )

    ax.axhline(
        y=0.1,
        color="gray",
        linestyle="--",
        linewidth=1.5,
        alpha=0.8,
    )
        
    plt.tight_layout()
    plt.show()

def select_representative_atoms_by_velocity(
    y_list,
    propagation_direction,
    bin_width=5.0,
):
    propagation_direction = np.asarray(
        propagation_direction,
        dtype=float,
    )
    propagation_direction /= np.linalg.norm(propagation_direction)

    initial_v_parallel = []

    for y in y_list:
        y = np.asarray(y)

        v0 = y[3:6, 0]
        v_parallel_0 = np.dot(v0, propagation_direction)

        initial_v_parallel.append(v_parallel_0)

    initial_v_parallel = np.asarray(initial_v_parallel)

    v_min = np.floor(initial_v_parallel.min() / bin_width) * bin_width
    v_max = np.ceil(initial_v_parallel.max() / bin_width) * bin_width

    bin_edges = np.arange(
        v_min,
        v_max + bin_width,
        bin_width,
    )

    selected_indices = []

    for left, right in zip(bin_edges[:-1], bin_edges[1:]):

        in_bin = np.where(
            (initial_v_parallel >= left)
            & (initial_v_parallel < right)
        )[0]

        if len(in_bin) == 0:
            continue

        bin_center = 0.5 * (left + right)

        representative = in_bin[
            np.argmin(
                np.abs(
                    initial_v_parallel[in_bin] - bin_center
                )
            )
        ]

        selected_indices.append(representative)

    selected_velocities = initial_v_parallel[selected_indices]

    return selected_indices, selected_velocities


def get_optimal_dt_zeeman(
    cooling_window_distance=0.01,
    cooling_onset_delta_v=4.0,
    cooling_end_delta_v=2.0,
    cooling_monotonic_fraction=0.9,
    cooling_end_consecutive_windows=3,
):
    y_path = (
        "dt_comparison/"
        "data/"
        "zeeman_sim_data/"
        f"survivors_y.json"
    )

    t_path = (
        "dt_comparison/"
        "data/"
        "zeeman_sim_data/"
        f"survivors_t.json"
    )

    y_list = read_data_json(y_path)
    t_list = read_data_json(t_path)

    selected_indices, selected_velocities = select_representative_atoms_by_velocity(
        y_list,
        -ZEEMAN_BEAM_DIR,
        bin_width=5.0,
    )

    y_list = [y_list[i] for i in selected_indices]
    t_list = [t_list[i] for i in selected_indices]

    trajectories = extract_cooling_trajectory_inputs(y_list, -ZEEMAN_BEAM_DIR)

    cooling_windows = []

    for axial_position, v_parallel in trajectories:
        onset_idx, end_idx = _find_cooling_window(
            axial_position=axial_position,
            v_parallel=v_parallel,
            cooling_window_distance=cooling_window_distance,
            cooling_onset_delta_v=cooling_onset_delta_v,
            cooling_end_delta_v=cooling_end_delta_v,
            cooling_monotonic_fraction=cooling_monotonic_fraction,
            cooling_end_consecutive_windows=cooling_end_consecutive_windows,
        )

        cooling_windows.append((onset_idx, end_idx))

    force_lists = get_cooling_window_forces(
        y_list,
        t_list,
        cooling_windows,
        YB171_MASS_KG
    )

    plot_cooling_forces_vs_time(
        force_lists,
        t_list,
        cooling_windows,
        F_scale,
        initial_velocities=selected_velocities,
        alpha=1,
    )

    

if __name__ == "__main__":
    get_optimal_dt_zeeman()