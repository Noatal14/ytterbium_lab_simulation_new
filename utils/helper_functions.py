import csv
import json
import numpy as np
from config import K_B, MOT_ENTRY_POSITION, MOT_ENTRY_VELOCITY
from atomsmltr.simulation.simulator import ScipyIVP_3D


def mot_entry_initial_condition():
    """
    Returns the exact physical entry state of the atom as it enters the 2D MOT
    chamber after being slowed down by the Zeeman slower in the full simulation.
    Uses centralized coordinates from config.py to avoid magic numbers.
    """
    return np.concatenate((MOT_ENTRY_POSITION, MOT_ENTRY_VELOCITY))

def run_simulation(
        seed_idx = None, 
        config = None, 
        u0 = None, 
        time_points = None, 
        sim_function = ScipyIVP_3D
    ):
    sim = sim_function(config)
    sim.rng = np.random.default_rng(seed_idx)
    sim.u0_list = [u0]

    res = sim.run(time_points, npools=0, verbose=False)[0]
    return seed_idx, res.y, sim

def generate_single_atom_state(v0=50.0, r0=0.10, angle_deg=25.0, pos_offset=(0.0, 0.0, 0.0), angle_offset=(0.0, 0.0)):
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

"""
File Save/Load functions for CSV and helper functions for data parsing.
"""

def save_file_csv(filename, data):
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)

    print(f"CSV summary saved to: {filename}")


def _json_default(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def save_file_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2, default=_json_default)

    print(f"JSON summary saved to: {filename}")


def read_data_json(filename):
    with open(filename, "r") as f:
        return json.load(f)


def _parse_csv_value(value):
    if value is None:
        return np.nan
    value = str(value).strip()
    if value == "":
        return np.nan
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def read_data_csv(filename, delimiter=","):
    """Read a CSV file and return column arrays.

    Parameters
    ----------
    filename : str
        Path to the CSV file.
    delimiter : str, optional
        Field delimiter used in the CSV file.

    Returns
    -------
    dict
        Dictionary mapping column names to NumPy arrays.
    """
    with open(filename, newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        fieldnames = reader.fieldnames or []
        columns = {name: [] for name in fieldnames}
        for row in reader:
            for name in fieldnames:
                columns[name].append(_parse_csv_value(row.get(name)))

    arrays = {}
    for name, values in columns.items():
        if all(not isinstance(v, str) for v in values):
            arrays[name] = np.asarray(values, dtype=float)
        else:
            arrays[name] = np.asarray(values, dtype=object)

    return arrays


# Backward-compatible alias
read_data = read_data_csv
