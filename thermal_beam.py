from config import YB171_MASS_KG, Geometry
import numpy as np
import scipy.constants as csts
from atomsmltr.atoms import Ytterbium

def _microtube_alpha(beta):
    numerator = 1 - 2 * beta**3 + (2 * beta**2 - 1) * np.sqrt(1 + beta**2)
    denominator = np.sqrt(1 + beta**2) - beta**2 * (
        np.log(np.sqrt(1 + beta**2) + 1) - np.log(beta)
    )
    return 0.5 - (1 / (3 * beta**2)) * (numerator / denominator)


def _microtube_R(q):
    q = np.clip(q, 0.0, 1.0)
    return np.arccos(q) - q * np.sqrt(1 - q**2)


def geometric_acceptance_angle_deg(r0):
    """
    Computes the tightest (most restrictive) half-angle, in degrees, that still
    geometrically clears every downstream vacuum-tube aperture (Zeeman_Arm_1/2/3,
    see lab_setup/zones.py) along a straight-line path from a source at axial
    distance `r0` (along the beam axis, matching the `distance_m` convention used
    throughout this module) down to the origin (2D-MOT chamber center).

    This replaces an arbitrary hardcoded collimation-angle cutoff with a value
    directly tied to the actual apparatus geometry in `config.Geometry`, so the
    emission-angle sampling cutoff no longer needs to be guessed.

    Parameters
    ----------
    r0 : float
        distance from the origin to the atom source, along the beam axis [m]

    Returns
    -------
    float
        the tightest acceptance half-angle, in degrees (capped at 90 deg if no
        segment is actually a constraint, e.g. for sources very close to origin)
    """
    # (z_start, radius) for each tube segment, ordered from the 2D-MOT/origin
    # side (z=0) outward towards the oven -- matches lab_setup/zones.py
    # get_apparatus_internal_volume() ordering.
    segments = [
        (0.0, Geometry.ZEEMAN_ARM_1_RADIUS),
        (Geometry.ZEEMAN_ARM_1_LENGTH, Geometry.ZEEMAN_ARM_2_RADIUS),
        (Geometry.ZEEMAN_ARM_1_LENGTH + Geometry.ZEEMAN_ARM_2_LENGTH, Geometry.ZEEMAN_ARM_3_RADIUS),
    ]

    theta_max_deg = 90.0
    for z_start, radius in segments:
        # worst-case transverse deviation for this segment occurs at its
        # farthest point from the source, i.e. at z_start (distance = r0 - z_start)
        distance_from_source = r0 - z_start
        if distance_from_source <= 0:
            continue  # source is before (or inside) this segment; not yet a constraint
        theta_max_deg = min(theta_max_deg, np.degrees(np.arctan(radius / distance_from_source)))

    return theta_max_deg


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
    config_name="thermal beam",
    N=1000,
    T_C=400.0,
    v_target=50.0,
    v_spread=5.0,
    collimation_angle_deg=None,
    m=None,
    distance_m=None,
    seed=42
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
    config_name : str
        Configuration type. Must be one of:
        - "thermal beam": 10cm away, thermal beam pointing to origin.
        - "Atomic Zeeman beam": 10cm away, Gaussian velocity peaked at v_target pointing to origin.
        - "GAS at oven": 431.7mm away, isotropic 3D gas.
        - "beam from oven": 431.7mm away, thermal beam pointing to origin.
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
    if distance_m is not None:
        r0 = distance_m
    else:
        if config_name in ["thermal beam", "Atomic Zeeman beam"]:
            r0 = 0.10  # 10 cm
        elif config_name in ["GAS at oven", "beam from oven"]:
            r0 = 0.4317  # 431.7 mm
        else:
            raise ValueError(f"Unknown config_name: '{config_name}'")

    # If not explicitly overridden, derive the collimation half-angle from the
    # actual apparatus geometry instead of using an arbitrary fixed cutoff.
    if collimation_angle_deg is None:
        collimation_angle_deg = geometric_acceptance_angle_deg(r0)

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
        "config_name": config_name,
        "temperature_C": T_C,
        "temperature_K": T_K,
        "distance_m": r0,
        "mass_kg": m
    }

    if config_name == "GAS at oven":
        # Isotropic 3D Maxwell-Boltzmann Gas
        vx = rng.normal(0, sigma, N)
        vy = rng.normal(0, sigma, N)
        vz = rng.normal(0, sigma, N)
        v_vecs = np.vstack((vx, vy, vz)).T
        
        info["description"] = "Isotropic 3D Maxwell-Boltzmann Gas"
        info["v_rms"] = np.sqrt(3) * sigma
        info["v_mean_magnitude"] = np.sqrt(8 * csts.k * T_K / (np.pi * m))

    elif config_name in ["thermal beam", "beam from oven"]:
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
        
        info["description"] = f"Collimated Thermal Beam (Gaussian I(theta), sigma={collimation_angle_deg} deg)"
        info["collimation_angle_deg"] = collimation_angle_deg
        info["emission_included_flux_fraction"] = included_fraction
        info["mean_axial_velocity"] = float(np.mean(v_L_arr))
        info["std_axial_velocity"] = float(np.std(v_L_arr))
        info["most_probable_velocity_theory"] = np.sqrt(3 * csts.k * T_K / m)

    elif config_name == "Atomic Zeeman beam":
        # Narrow Gaussian velocity profile around a target velocity, with small transverse spread
        v_L_arr = rng.normal(v_target, v_spread, N)
        
        # Keep transverse spread characteristic of a collimated beam at that velocity
        target_transverse_spread = v_target * np.tan(np.radians(collimation_angle_deg))
        # ensure spread is not 0
        target_transverse_spread = max(target_transverse_spread, 1.0)
        
        v_T1_arr = rng.normal(0, target_transverse_spread, N)
        v_T2_arr = rng.normal(0, target_transverse_spread, N)
        
        # Ensure moving forward
        mask = v_L_arr > 0
        v_L_arr = np.where(mask, v_L_arr, -v_L_arr) # flip any negative tail just in case
        
        v_vecs = (v_T1_arr[:, None] * u_T1 + 
                  v_T2_arr[:, None] * u_T2 + 
                  v_L_arr[:, None] * u_L)
                  
        info["description"] = "Zeeman Slowed Beam (Gaussian Longitudinal Peak)"
        info["target_velocity"] = v_target
        info["velocity_spread"] = v_spread
        info["mean_axial_velocity"] = float(np.mean(v_L_arr))
        info["std_axial_velocity"] = float(np.std(v_L_arr))

    return r_vecs, v_vecs, info
