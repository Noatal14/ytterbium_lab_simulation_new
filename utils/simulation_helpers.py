import numpy as np
from utils.ScipyIVP_3DCustom import ScipyIVP_3DCustom
from config import ZEEMAN_BEAM_DIRECTION, Geometry, DEFAULT_RANDOM_SEED

def run_simulation(
        seed_idx = DEFAULT_RANDOM_SEED, 
        config = None, 
        u0 = None, 
        time_points = None, 
        sim_function = ScipyIVP_3DCustom,
        npools = 0
    ):
    sim = sim_function(config)
    sim.rng = np.random.default_rng(seed_idx)
    sim.u0_list = u0

    res = sim.run(time_points, npools=npools, verbose=True)[0]
    return seed_idx, res.y, sim

def run_multiple_atoms_simulation(
        seed_idx = DEFAULT_RANDOM_SEED, 
        config = None, 
        u0 = None, 
        time_points = None, 
        sim_function = ScipyIVP_3DCustom,
        npools = 0,
        trajectory_seed_sequences = None,
    ):
    sim = sim_function(config)
    sim.seed_idx = seed_idx
    sim.trajectory_seed_sequences = trajectory_seed_sequences

    sim.rng = np.random.default_rng(seed_idx)
    sim.u0_list = u0

    res = sim.run(time_points, npools=npools, verbose=True)
    return res, sim

def entry_initial_condition(v0=50.0, r0=0.10, angle_deg=25.0, pos_offset=(0.0, 0.0, 0.0), angle_offset=(0.0, 0.0)):
    """
    Generate the position and velocity vector for a single atom source,
    following the standard conventions for the 2DMOT simulator.

    The convention:
    - ZY plane is parallel to the ground.
    - X axis is normal to the ground.
    - Atom starts in the 3rd quadrant of the ZY plane (Z < 0, Y < 0).
    - Base angle (`angle_deg`) is relative to the -Z axis, pointing into -Y.
    - Velocity base direction is perfectly towards the origin.

    Parameters
    ----------
    v0 : float
        Initial velocity magnitude in m/s (default: 50.0).
    r0 : float
        Initial distance from the origin in meters (default: 0.10 m = 10 cm).
    angle_deg : float
        Angle from the -Z axis in degrees (default: 25.0).
    pos_offset : tuple of floats
        Local offsets (dx, dy_trans, dz_long) in meters relative to the beam direction.
        - dx: vertical offset (along X).
        - dy_trans: horizontal side-offset (perpendicular to beam in ZY plane).
        - dz_long: longitudinal offset (along the beam path).
    angle_offset : tuple of floats
        Angular divergence (d_theta_in, d_theta_out) in degrees to apply to the velocity direction.
        - d_theta_in: angle offset in the ZY plane.
        - d_theta_out: angle offset towards the X axis (out of plane).

    Returns
    -------
    tuple of (numpy.ndarray, numpy.ndarray)
        (r_vec, v_vec) where each is a 1D numpy array of shape (3,) representing (X, Y, Z).
    """
    
    # Convert angles to radians
    alpha = np.radians(angle_deg)
    d_theta_in = np.radians(angle_offset[0])
    d_theta_out = np.radians(angle_offset[1])
    
    # 1. Base position at distance r0 in 3rd quadrant
    # Path direction unit vector (from origin to source): 
    # u_long = (0, -sin(alpha), -cos(alpha))
    u_long = np.array([0, -np.sin(alpha), -np.cos(alpha)])
    
    # 2. Side-offset unit vector in ZY plane (perpendicular to u_long)
    # We want u_trans such that it's in ZY and dot(u_trans, u_long) = 0
    # u_trans = (0, cos(alpha), -sin(alpha))
    u_trans = np.array([0, np.cos(alpha), -np.sin(alpha)])
    
    # 3. Handle offsets
    dx, dy_trans, dz_long = pos_offset
    
    # Start with base position (r0 along u_long)
    # Then add longitudinal shift (dz_long), side shift (dy_trans), and vertical shift (dx)
    # r_base = (r0 + dz_long) * u_long
    # r_offset = dy_trans * u_trans + dx * [1, 0, 0]
    
    r_vec = (r0 + dz_long) * u_long + dy_trans * u_trans + np.array([dx, 0, 0])
    
    # 4. Velocity Calculation
    # Note: Velocity vector is "pointed back" towards the origin, so it is in the -u_long direction primarily.
    # Out-of-plane angle creates X velocity.
    v_x = v0 * np.sin(d_theta_out)
    
    # Current plan projection in ZY
    v_plane_mag = v0 * np.cos(d_theta_out)
    
    # In the ZY plane, base velocity -u_long has components: (sin(alpha), cos(alpha)) for (y, z)
    # Applying d_theta_in adds to alpha
    v_y = v_plane_mag * np.sin(alpha + d_theta_in)
    v_z = v_plane_mag * np.cos(alpha + d_theta_in)
    
    v_vec = np.array([v_x, v_y, v_z])
    
    return r_vec, v_vec

def generate_timepoints(t_final, dt):
    """
    Generate simulation timepoints from 0 to t_final.
    """
    n_steps = int(np.ceil(t_final / dt))
    time_points = np.linspace(0, t_final, n_steps + 1)
    
    return time_points, len(time_points)

def zeeman_extract_survivors(
    res_list,
    cutoff_distance,
    radial_tolerance=1e-9,
    event_tolerance=1e-6,
):
    survivor_states = []
    survivor_indices = []

    for i, res in enumerate(res_list):

        # =====================================================
        # Deterministic: ScipyIVP_3D
        # =====================================================
        if getattr(res, "y_events", None) is not None:

            survivor_found = False

            for event_states in res.y_events:
                for state_event in event_states:

                    r_event = state_event[:3]
                    proj_event = r_event @ ZEEMAN_BEAM_DIRECTION

                    if np.isclose(
                        proj_event,
                        cutoff_distance,
                        atol=event_tolerance,
                        rtol=0.0,
                    ):
                        survivor_states.append(state_event.copy())
                        survivor_indices.append(i)
                        survivor_found = True
                        break

                if survivor_found:
                    break

        # =====================================================
        # Stochastic: RK4StCustom / SimRes
        # =====================================================
        else:
            if res.y.shape[1] < 2:
                continue

            state_before = res.y[:, -2]
            state_after = res.y[:, -1]

            r_before = state_before[:3]
            r_after = state_after[:3]

            p_before = r_before @ ZEEMAN_BEAM_DIRECTION
            p_after = r_after @ ZEEMAN_BEAM_DIRECTION

            # Did this RK4 step cross the inner cutoff plane?
            if not (
                p_before > cutoff_distance
                and p_after <= cutoff_distance
            ):
                continue

            # Interpolate to the exact cutoff crossing.
            alpha = (
                (p_before - cutoff_distance)
                / (p_before - p_after)
            )

            state_cutoff = (
                state_before
                + alpha * (state_after - state_before)
            )

            r_cutoff = state_cutoff[:3]

            # Distance from the Zeeman beam axis.
            axial_point = (
                (r_cutoff @ ZEEMAN_BEAM_DIRECTION)
                * ZEEMAN_BEAM_DIRECTION
            )

            rho = np.linalg.norm(r_cutoff - axial_point)

            # Must cross through the physical opening of Arm 1.
            if rho <= Geometry.ZEEMAN_ARM_1_RADIUS_M + radial_tolerance:
                survivor_states.append(state_cutoff)
                survivor_indices.append(i)

    if len(survivor_states) == 0:
        return np.empty((0, 6)), []

    return np.array(survivor_states), survivor_indices

def mot_extract_survivors(res_list):
    """
    Extract the states of particles successfully captured after the 2D MOT.

    Per the proposal (Sec. 2.1.3), capture is defined qualitatively as an atom
    being "deflected toward the downstream 3D-MOT capture region" after passing
    through the 2D-MOT. We operationalize this as: the particle survives past
    the differential-pumping stage (DPS) bore --

        z >= Geometry.CAPTURE_MIN_Z  (= DPS_START_Z + DPS_LENGTH)

    while still moving toward the science chamber (vz > 0).

    Parameters
    ----------
    res_list : list
        List of simulation results.

    Returns
    -------
    survivor_states : np.ndarray
        Array with shape (N_survivors, 6).

    survivor_indices : list[int]
        Indices of the captured particles in the original res_list.
    """
    survivor_states = []
    survivor_indices = []

    for i, res in enumerate(res_list):
        z_traj = res.y[2, :]
        vz_traj = res.y[5, :]

        crossed_indices = np.where(
            (z_traj >= Geometry.CAPTURE_MIN_Z_M) &
            (vz_traj > 0)
        )[0]

        if len(crossed_indices) == 0:
            continue

        idx = crossed_indices[0]
        survivor_states.append(res.y[:, idx].copy())
        survivor_indices.append(i)


    if len(survivor_states) == 0:
        return np.empty((0, 6)), 0, []

    count = len(survivor_states)

    return np.array(survivor_states), count, survivor_indices

def extract_trajectory_data(results):
    """
    Convert a list of scipy OdeResult objects into a JSON-serializable format.

    Parameters
    ----------
    results : list[OdeResult]

    Returns
    -------
    list[dict]
        Each element contains only the time vector and state matrix.
    """
    return [
        {
            "t": res.t.tolist(),
            "y": res.y.tolist(),
        }
        for res in results
    ]
