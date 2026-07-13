import numpy as np
import matplotlib.pyplot as plt
from scipy import constants as csts
from config import BLUE_LASER_WAVELENGTH_M
from dt_comparison.consts import F_scale

def calc_dt(
    F_min,
    F_scale,
    wavelength=BLUE_LASER_WAVELENGTH_M,
    N_min = 15,
):
    k = 2 * np.pi / wavelength

    dt = N_min * csts.hbar * k / F_min

    return {
        "dt": dt,
        "F_min": F_min,
        "F_min_norm": F_min/F_scale,
        "N_min": N_min,
    }

if __name__ == "__main__":
    result = calc_dt(
        F_min=0.01*F_scale,
        N_min=15,
        F_scale=F_scale,
    )

    print(f"Recommended dt = {result['dt']:.3e} s")