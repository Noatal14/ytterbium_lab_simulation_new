import numpy as np
import matplotlib.pyplot as plt
from scipy import constants as csts
from config import BLUE_LASER_WAVELENGTH_M
from dt_comparison.consts import F_scale
from dt_comparison.find_f_min.force_calc_2d_mot import calc_f_min_2d_mot

def calc_dt(
    F_min,
    F_scale,
    wavelength=BLUE_LASER_WAVELENGTH_M,
    N_min = 15,
    safety_factor = 1.5,
):
    """
    Computes the *minimum* timestep required for the Gaussian photon-count
    (shot-noise) approximation used by the stochastic integrator to remain
    valid at the weakest non-negligible force, F_min.

    Since the expected number of scattered photons per timestep is
    Ni = F * dt / (hbar * k), requiring Ni >= N_min gives a LOWER bound:

        dt >= N_min * hbar * k / F_min = dt_gaussian_min_raw

    i.e. `calc_dt` does NOT compute "the largest numerically safe timestep",
    "optimal dt", or a "maximum timestep" -- it computes the Gaussian minimum
    timestep: the smallest dt for which the Gaussian approximation holds at
    F_min. The final production timestep must independently also satisfy the
    numerical-convergence upper bound (found separately, e.g. via a dt
    convergence scan), so in general:

        dt_gaussian_min <= dt_production <= dt_numerical_convergence_max

    `dt`/`dt_raw` are kept as the original keys for backward compatibility
    with existing callers; `dt_gaussian_min`/`dt_gaussian_min_raw` are
    provided as more accurately-named aliases and should be preferred in new
    code.

    Parameters
    ----------
    safety_factor : float, optional
        Multiplies the bare Ni=N_min timestep by this factor, by default 1.5.
        This buffers against the F_min estimate being a discrete grid scan
        (it can miss the true minimum between sample points) and against
        other numerical approximations in the integrator. Set to 1.0 to get
        the razor-edge dt where Ni is exactly N_min at F_min. NOTE: if the
        caller already divided F_min by its own separate safety margin
        (e.g. `get_optimal_dt_zeeman`'s `force_margin_factor`), using
        `safety_factor > 1` here as well *compounds* both margins
        multiplicatively (e.g. force_margin_factor=2 and safety_factor=2
        together make the effective dt margin 4x, not 2x) -- pick one place
        to apply the margin, or knowingly accept the compounding.
    """
    k = 2 * np.pi / wavelength

    dt_gaussian_min_raw = N_min * csts.hbar * k / F_min
    dt_gaussian_min = safety_factor * dt_gaussian_min_raw

    result = {
        "dt": dt_gaussian_min,
        "dt_raw": dt_gaussian_min_raw,
        "dt_gaussian_min": dt_gaussian_min,
        "dt_gaussian_min_raw": dt_gaussian_min_raw,
        "safety_factor": safety_factor,
        "F_min": F_min,
        "F_min_norm": F_min/F_scale,
        "N_min": N_min,
    }

    return result


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
    F_min, _, _, _ = calc_f_min_2d_mot(
        s0=s0,
        detuning_gamma=detuning_gamma,
        magnet_radius=magnet_radius,
        velocity_range=velocity_range,
    )

    return calc_dt(F_min=F_min, F_scale=F_scale, N_min=N_min, safety_factor=safety_factor)

def get_optimal_dt_zeeman(s0, detuning_gamma):
    return {
        "dt": 1e-5,
    }

if __name__ == "__main__":
    print('hi')


