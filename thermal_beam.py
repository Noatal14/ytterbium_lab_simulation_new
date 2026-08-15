from config import YB171_MASS_KG, Geometry, collimation_angle_deg
import numpy as np
import scipy.constants as csts
from config import seed

def _microtube_alpha(beta):
    numerator = 1 - 2 * beta**3 + (2 * beta**2 - 1) * np.sqrt(1 + beta**2)
    denominator = np.sqrt(1 + beta**2) - beta**2 * (
        np.log(np.sqrt(1 + beta**2) + 1) - np.log(beta)
    )
    return 0.5 - (1 / (3 * beta**2)) * (numerator / denominator)


def _microtube_R(q):
    q = np.clip(q, 0.0, 1.0)
    return np.arccos(q) - q * np.sqrt(1 - q**2)


def microtube_intensity_theta(theta, r_tube, L_tube):
    """
    Transparent-flow angular intensity distribution I(theta) / I(0).

    theta : angle from beam axis [rad]
    r_tube : microtube radius [m]
    L_tube : microtube length [m]
    """
    theta = np.asarray(theta)

    beta = 2 * r_tube / L_tube
    alpha = _microtube_alpha(beta)

    theta_c = np.arctan(beta)
    q = np.tan(theta) / beta

    intensity = np.zeros_like(theta, dtype=float)

    small = theta < theta_c
    large = ~small

    if np.any(small):
        q_s = q[small]
        R_s = _microtube_R(q_s)
        
        intensity[small] = np.cos(theta[small]) * (
            alpha
            + (2 / np.pi)
            * (
                (1 - alpha) * R_s
                + (2 * (1 - 2 * alpha) / (3 * q_s)) * (1 - np.sqrt((1 - q_s**2) ** 3))
            )
        )

    if np.any(large):
        q_l = q[large]
        intensity[large] = np.cos(theta[large]) * (
            alpha + 4 * (1 - 2 * alpha) / (3 * np.pi * q_l)
        )

    return np.maximum(intensity, 0.0)


def sample_microtube_angles(N, r_tube, L_tube, rng, theta_max=np.pi / 2):
    """
    Sample theta, phi from the microtube angular intensity.

    Important:
    I(theta) is intensity per solid angle, so the probability density
    for theta is proportional to I(theta) * sin(theta).

    Note:
    Truncating at `theta_max` discards whatever fraction of the true I(theta)
    lies beyond it. We report that discarded fraction via `included_fraction`
    so callers can tell how aggressive the truncation is, instead of silently
    renormalizing the sampled distribution as if nothing were cut.
    """
    theta_grid = np.linspace(1e-9, theta_max, 5000)
    weights = microtube_intensity_theta(theta_grid, r_tube, L_tube) * np.sin(theta_grid)
    truncated_mass = np.trapezoid(weights, theta_grid)

    full_grid = np.linspace(1e-9, np.pi / 2, 5000)
    full_weights = microtube_intensity_theta(full_grid, r_tube, L_tube) * np.sin(full_grid)
    full_mass = np.trapezoid(full_weights, full_grid)
    included_fraction = float(truncated_mass / full_mass)

    pdf = weights / truncated_mass
    cdf = np.cumsum(pdf)
    cdf = cdf / cdf[-1]

    u = rng.uniform(0.0, 1.0, N)
    theta = np.interp(u, cdf, theta_grid)

    phi = rng.uniform(0.0, 2 * np.pi, N)

    return theta, phi, included_fraction

def generate_thermal_beam_state(
    N=1000,
    T_C=400.0,
    collimation_angle_deg=collimation_angle_deg,
    m=None,
    distance_m=None,
    seed=seed
):
    """
    Generate the position and velocity arrays for a collection of atoms (thermal source),
    following the standard conventions for the 2DMOT simulator.

    The convention:
    - ZY plane is parallel to the ground.
    - X axis is normal to the ground.
    - Base angle is 25 degrees relative to the -Z axis, pointing into -Y (3rd quadrant).
    
    Parameters
    ----------
    N : int
        Number of atoms to generate.
    T_C : float
        Temperature of the source in Celsius (default: 400.0 C).
    v_target : float
        Target final velocity for the 'Atomic Zeeman beam' in m/s (default: 50.0).
    v_spread : float
        Velocity spread for the 'Atomic Zeeman beam' in m/s (default: 5.0).
    collimation_angle_deg : float, optional
        Angular divergence constraint for collimated beams in degrees. If None
        (default), it is derived from `Geometry` as the tightest half-angle that
        geometrically clears every downstream vacuum-tube aperture between the
        source and the origin (see `geometric_acceptance_angle_deg`), rather than
        an arbitrary fixed cutoff.
    m : float, optional
        Mass of the atom in kg. Defaults to Ytterbium mass.

    Returns
    -------
    tuple of (numpy.ndarray, numpy.ndarray, dict)
        (r_vecs, v_vecs, info_dict)
        where r_vecs and v_vecs are arrays of shape (N, 3), representing (X, Y, Z).
        info_dict contains metadata and statistics about the generated distribution.
    """
    
    if m is None:
        m = YB171_MASS_KG

    angle_deg = Geometry.ZEEMAN_ARM_ANGLE_DEG
    alpha = np.radians(angle_deg)
    
    # Determine distance based on configuration
    r0 = distance_m

    # Base position in 3rd quadrant of ZY plane
    x_pos = 0.0
    y_pos = -r0 * np.sin(alpha)
    z_pos = -r0 * np.cos(alpha)
    
    r_vecs = np.zeros((N, 3))
    r_vecs[:, 0] = x_pos
    r_vecs[:, 1] = y_pos
    r_vecs[:, 2] = z_pos

    # Calculate local basis vectors
    # u_L points from source perfectly towards the origin
    u_L = np.array([-x_pos, -y_pos, -z_pos]) / r0
    
    # Construct transverse orthogonal unit vectors
    # Since u_L is in the ZY plane (x=0), u_T1 can be the X axis
    u_T1 = np.array([1.0, 0.0, 0.0])
    u_T2 = np.cross(u_L, u_T1)  # Orthogonal to both, in ZY plane
    rng = np.random.default_rng(seed) #if seed is None will be random, otherwise will be fixed
    T_K = T_C + 273.15
    sigma = np.sqrt(csts.k * T_K / m)
    
    info = {
        "temperature_C": T_C,
        "temperature_K": T_K,
        "distance_m": r0,
        "mass_kg": m
    }

    # Thermal beam pointing to origin
    # The axial velocity v_L for an effusive beam flux follows a v^3 exp(-v^2 / (2*sigma^2)) distribution.
    # This is mathematically equivalent to a scaled Chi distribution with 4 degrees of freedom.
    x1 = rng.normal(0, sigma, N)
    x2 = rng.normal(0, sigma, N)
    x3 = rng.normal(0, sigma, N)
    x4 = rng.normal(0, sigma, N)
    v_L_arr = np.sqrt(x1**2 + x2**2 + x3**2 + x4**2)
    
    # Transparent-flow microtube angular intensity distribution
    # We cap theta at the collimation angle to simulate the physical acceptance
    # of the downstream apertures (see geometric_acceptance_angle_deg).
    theta, phi, included_fraction = sample_microtube_angles(
        N=N,
        r_tube=Geometry.R_TUBE,
        L_tube=Geometry.L_TUBE,
        rng=rng,
        theta_max=np.radians(collimation_angle_deg)
    )
    v_T1_arr = v_L_arr * np.tan(theta) * np.cos(phi)
    v_T2_arr = v_L_arr * np.tan(theta) * np.sin(phi)
    
    # Transform from local beam frame (u_T1, u_T2, u_L) to lab frame (X, Y, Z)
    v_vecs = (v_T1_arr[:, None] * u_T1 + 
                v_T2_arr[:, None] * u_T2 + 
                v_L_arr[:, None] * u_L)
    
    info["description"] = f"Microcapillary thermal beam (transparent-flow angular distribution), sigma={collimation_angle_deg} deg)"
    info["collimation_angle_deg"] = collimation_angle_deg
    info["emission_included_flux_fraction"] = included_fraction
    info["mean_axial_velocity"] = float(np.mean(v_L_arr))
    info["std_axial_velocity"] = float(np.std(v_L_arr))
    info["most_probable_velocity_theory"] = np.sqrt(3 * csts.k * T_K / m)

    return r_vecs, v_vecs, info
