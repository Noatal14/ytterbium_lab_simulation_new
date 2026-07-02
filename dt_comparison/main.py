import numpy as np
import matplotlib.pyplot as plt
from scipy import constants as csts
from config import BLUE_LASER_WAVELENGTH_M, BLUE_LASER_GAMMA_HZ, Geometry
from dt_comparison.find_f_min.theoretical_force_calc import calc_f_min

def calc_dt(
    laser_shape,
    laser_waist,
    detuning_gamma,
    s0,
    velocity_range=[1, 50],
    wavelength=BLUE_LASER_WAVELENGTH_M,
    gamma=BLUE_LASER_GAMMA_HZ,
    N_min=15,
):
    """
    Calculates the recommended simulation timestep based on the
    F_min criterion and the chosen N_min.
    """

    F_min, F_min_norm, threshold_result, results = calc_f_min(
        laser_shape=laser_shape,
        laser_waist=laser_waist,
        detuning_gamma=detuning_gamma,
        s0=s0,
        velocity_range=velocity_range,
        wavelength=wavelength,
        gamma=gamma,
    )

    k = 2 * np.pi / wavelength

    dt = N_min * csts.hbar * k / F_min

    return {
        "dt": dt,
        "F_min": F_min,
        "F_min_norm": F_min_norm,
        "N_min": N_min,
        "chosen_velocity": threshold_result["v"],
        "chosen_A": threshold_result["A"],
        "results": results,
    }

if __name__ == "__main__":
    result = calc_dt(
        laser_shape="elliptical",
        laser_waist=[Geometry.MOT_WX, Geometry.MOT_WY],
        detuning_gamma=-1.2 * BLUE_LASER_GAMMA_HZ,
        s0=1.5,
    )

    print(f"Recommended dt = {result['dt']:.3e} s")
    print(f"F_min/F_scale = {result['F_min_norm']:.3f}")
    print(f"Chosen velocity = {result['chosen_velocity']} m/s")
    print(f"A = {result['chosen_A']:.3f}")