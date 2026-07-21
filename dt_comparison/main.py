import numpy as np
import matplotlib.pyplot as plt
from scipy import constants as csts
from config import BLUE_LASER_WAVELENGTH_M, Geometry, zeeman_configs
from dt_comparison.consts import F_scale
from dt_comparison.find_f_min.force_calc_2d_mot import calc_f_min_2d_mot
from lab_setup.config_builder import build_zeeman_config
from atomsmltr.simulation.simulator.simbase import get_force_vec

def calc_dt(
    F_min,
    F_scale,
    wavelength=BLUE_LASER_WAVELENGTH_M,
    N_min = 15,
    safety_factor = 1.5,
):
    """
    Parameters
    ----------
    safety_factor : float, optional
        Multiplies the bare Ni=N_min timestep by this factor, by default 1.5.
        This buffers against the F_min estimate being a discrete grid scan
        (it can miss the true minimum between sample points) and against
        other numerical approximations in the integrator. Set to 1.0 to get
        the razor-edge dt where Ni is exactly N_min at F_min.
    """
    k = 2 * np.pi / wavelength

    dt_raw = N_min * csts.hbar * k / F_min
    dt = safety_factor * dt_raw

    return {
        "dt": dt,
        "dt_raw": dt_raw,
        "safety_factor": safety_factor,
        "F_min": F_min,
        "F_min_norm": F_min/F_scale,
        "N_min": N_min,
    }


def get_optimal_dt_2d_mot(
    s0,
    detuning_gamma,
    magnet_radius,
    velocity_range=[1, 50],
    N_min=15,
    safety_factor=1.5,
):
    """
    Computes the optimal (largest safe) simulation timestep dt for the 2D-MOT
    stochastic simulation, i.e. the largest dt such that the expected number of
    scattered photons per timestep (Ni = rate * dt) still satisfies Ni >= N_min
    whenever the scattering force is non-negligible (F >= F_min).

    F_min is found via `calc_f_min_2d_mot`'s restoring-force asymmetry
    criterion (A > 0.8, see dt_comparison/find_f_min/force_calc_2d_mot.py),
    scanned over the 2D-MOT capture-velocity range (default ~0-50 m/s).

    Note: `calc_f_min_2d_mot` opens a matplotlib plot window (`plt.show()`),
    so calling this with an interactive backend will block until it's closed.

    Parameters
    ----------
    s0 : float
        2D-MOT saturation parameter.
    detuning_gamma : float
        2D-MOT laser detuning, in units of Gamma.
    magnet_radius : float
        Radius of the 2D-MOT permanent quadrupole magnets (m).
    velocity_range : list[int, int], optional
        Velocity range (m/s) to scan for the F_min threshold, by default [1, 50].
    N_min : float, optional
        Minimum expected photon count per timestep for the Gaussian stochastic
        approximation to remain valid, by default 15.
    safety_factor : float, optional
        Extra margin applied on top of the bare Ni=N_min dt, by default 1.5.
        See `calc_dt` for details.

    Returns
    -------
    dict
        Same structure as `calc_dt`: {"dt", "dt_raw", "safety_factor", "F_min", "F_min_norm", "N_min"}.
    """
    F_min, F_min_norm, threshold_result, results = calc_f_min_2d_mot(
        s0=s0,
        detuning_gamma=detuning_gamma,
        magnet_radius=magnet_radius,
        velocity_range=velocity_range,
    )

    return calc_dt(F_min=F_min, F_scale=F_scale, N_min=N_min, safety_factor=safety_factor)


def get_optimal_dt_zeeman(
    s0,
    detuning_gamma,
    velocity_range=(35, 350),
    n_velocity_points=26,
    position_range=(0.05, 0.5),
    n_position_points=80,
    N_min=15,
    safety_factor=1.5,
):
    """
    Computes the optimal (largest safe) simulation timestep dt for the Zeeman-
    slower stochastic simulation.

    Unlike the 2D-MOT (which has a symmetric restoring force and a natural
    A > 0.8 asymmetry threshold), the Zeeman slower is a one-directional
    deceleration process, so there is no equivalent restoring-force asymmetry
    to exploit. Instead, F_min is defined as the weakest point of the
    *on-resonance* deceleration force: for each velocity in `velocity_range`,
    we scan atom positions along the whole slower (`position_range`, distance
    from the origin along the beam axis) and take the *maximum* force reached
    -- i.e. the force the atom would feel right where it crosses resonance,
    wherever that happens to be along the slower for that velocity. F_min is
    then the minimum of that on-resonance force over the whole velocity range,
    i.e. the weakest point of the intended deceleration profile.

    Uses the standard "80_2" permanent-magnet configuration (see
    config.zeeman_configs), matching the production Zeeman slower field.

    Parameters
    ----------
    s0 : float
        Zeeman-slower saturation parameter.
    detuning_gamma : float
        Zeeman-slower laser detuning, in units of Gamma.
    velocity_range : tuple[float, float], optional
        Velocity range (m/s) to scan, by default (50, 300).
    n_velocity_points : int, optional
        Number of velocity samples in `velocity_range`, by default 26.
    position_range : tuple[float, float], optional
        Distance-from-origin range (m) to scan along the beam axis, by
        default (0.05, 0.5), covering the full extent of the slower.
    n_position_points : int, optional
        Number of position samples in `position_range`, by default 80.
    N_min : float, optional
        Minimum expected photon count per timestep for the Gaussian stochastic
        approximation to remain valid, by default 15.
    safety_factor : float, optional
        Extra margin applied on top of the bare Ni=N_min dt, by default 1.5.
        See `calc_dt` for details.

    Returns
    -------
    dict
        Same structure as `calc_dt`: {"dt", "dt_raw", "safety_factor", "F_min", "F_min_norm", "N_min"}.
    """
    radii, positions, tilt_angles = zeeman_configs["80_2"]

    _, config = build_zeeman_config(
        s0_zeeman=s0,
        detuning_gamma_zeeman=detuning_gamma,
        gravity_enabled=False,
        include_mot_lasers=False,
        include_zeeman_field=True,
        include_zeeman_laser=True,
        radii=radii,
        positions=positions,
        tilt_angles=tilt_angles,
    )

    angle_rad = np.radians(Geometry.ZEEMAN_ARM_ANGLE_DEG)
    beam_dir = np.array([0, -np.sin(angle_rad), -np.cos(angle_rad)])

    v_grid = np.linspace(velocity_range[0], velocity_range[1], n_velocity_points)
    r0_grid = np.linspace(position_range[0], position_range[1], n_position_points)
    r_vecs = r0_grid[:, None] * beam_dir[None, :]

    F_min = np.inf
    for v in v_grid:
        v_vecs = np.tile(-v * beam_dir, (n_position_points, 1))
        u_batch = np.concatenate([r_vecs, v_vecs], axis=1)
        forces = get_force_vec(u_batch, config)
        F_best_at_v = np.linalg.norm(forces, axis=-1).max()
        F_min = min(F_min, F_best_at_v)

    return calc_dt(F_min=F_min, F_scale=F_scale, N_min=N_min, safety_factor=safety_factor)


if __name__ == "__main__":
    dt_2d_mot = get_optimal_dt_2d_mot(
        s0=1.4,
        detuning_gamma=-1.47,
        magnet_radius=0.053,
    )
    print(f"2D-MOT: F_min={dt_2d_mot['F_min']:.3e} N ({dt_2d_mot['F_min_norm']:.4f} F_scale), "
          f"dt_raw={dt_2d_mot['dt_raw']:.3e} s, optimal dt (x{dt_2d_mot['safety_factor']})={dt_2d_mot['dt']:.3e} s")

    dt_zeeman = get_optimal_dt_zeeman(
        s0=3.0,
        detuning_gamma=-13.75,
    )
    print(f"Zeeman: F_min={dt_zeeman['F_min']:.3e} N ({dt_zeeman['F_min_norm']:.4f} F_scale), "
          f"dt_raw={dt_zeeman['dt_raw']:.3e} s, optimal dt (x{dt_zeeman['safety_factor']})={dt_zeeman['dt']:.3e} s")
