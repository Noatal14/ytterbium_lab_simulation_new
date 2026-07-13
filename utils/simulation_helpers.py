import numpy as np
from atomsmltr.simulation.simulator import ScipyIVP_3D
from config import ZEEMAN_BEAM_DIR, Geometry

def run_simulation(
        seed_idx = None, 
        config = None, 
        u0 = None, 
        time_points = None, 
        sim_function = ScipyIVP_3D,
        npools = 0
    ):
    sim = sim_function(config)
    sim.rng = np.random.default_rng(seed_idx)
    sim.u0_list = u0

    res = sim.run(time_points, npools=npools, verbose=False)[0]
    return seed_idx, res.y, sim

def run_multiple_atoms_simulation(
        seed_idx = None, 
        config = None, 
        u0 = None, 
        time_points = None, 
        sim_function = ScipyIVP_3D,
        npools = 0
    ):
    sim = sim_function(config)
    sim.rng = np.random.default_rng(seed_idx)
    sim.u0_list = u0

    res = sim.run(time_points, npools=npools, verbose=False)
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

def zeeman_extract_survivors(res_list, cutoff_distance):
    tolerance = 0.010  # 10mm tolerance
    survivor_states = []
    survivor_indices = []

    for i, res in enumerate(res_list):
        positions = res.y[:3, :].T  # (N_timesteps, 3)
        # Projection onto beam axis (larger = further from origin)
        proj = positions @ ZEEMAN_BEAM_DIR
        min_proj = np.min(proj)

        if min_proj <= cutoff_distance + tolerance:
            # This particle reached the cutoff boundary
            # Use the state at the point of minimum projection (closest to origin)
            idx_min = np.argmin(proj)
            final_state = res.y[:, idx_min]  # (6,)
            survivor_states.append(final_state)
            survivor_indices.append(i)

    if len(survivor_states) == 0:
        return np.empty((0, 6)), []

    return np.array(survivor_states), survivor_indices

def mot_extract_survivors(res_list):
    """
    Extract the states of particles successfully captured after the 2D MOT.

    A particle is considered captured if, at the first trajectory point where

        z >= Geometry.CAPTURE_DISK_Z

    its transverse distance from the z-axis satisfies

        sqrt(x**2 + y**2) <= Geometry.CAPTURE_DISK_RADIUS.

    Parameters
    ----------
    res_list : list
        List of simulation results. Each result is expected to contain
        res.y with shape (6, N_timesteps), where the state is

            [x, y, z, vx, vy, vz].

    Returns
    -------
    survivor_states : np.ndarray
        Array with shape (N_survivors, 6), containing the state of each
        captured particle at its first point inside the capture disk.

    survivor_indices : list[int]
        Indices of the captured particles in the original res_list.
    """
    survivor_states = []
    survivor_indices = []

    for i, res in enumerate(res_list):
        z_traj = res.y[2, :]

        # Find the first sampled point at or beyond the capture-disk plane.
        crossed_indices = np.where(z_traj >= Geometry.CAPTURE_DISK_Z)[0]

        if len(crossed_indices) == 0:
            continue

        idx = crossed_indices[0]

        x = res.y[0, idx]
        y = res.y[1, idx]
        rho = np.sqrt(x**2 + y**2)

        if rho <= Geometry.CAPTURE_DISK_RADIUS:
            survivor_states.append(res.y[:, idx].copy())
            survivor_indices.append(i)

    if len(survivor_states) == 0:
        return np.empty((0, 6)), []

    return np.array(survivor_states), survivor_indices

def _2d_mot_success_count(res_list):
    """
    Count the number of successful particles that reach the target region.
    A particle is considered successful if it crosses the plane z >= target_z
    and its transverse distance from the origin is less than or equal to target_radius.
    """
    success_count = 0
    for res in res_list:
        z_traj = res.y[2, :]
        crossed = np.where(z_traj >= Geometry.CAPTURE_DISK_Z)[0]
        if len(crossed) > 0:
            idx = crossed[0]
            rho = np.sqrt(res.y[0, idx]**2 + res.y[1, idx]**2)
            if rho <= Geometry.CAPTURE_DISK_RADIUS:
                success_count += 1

    return success_count