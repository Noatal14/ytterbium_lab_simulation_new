"""Estimate the Yb-171 oven flux used to scale full-angle simulations.

The calculation follows the project's microcapillary source model. It reports
the total transmitted flux, before downstream geometric acceptance; that is
the correct denominator for a Zeeman simulation sampled over the complete
forward angular distribution.
"""

import argparse
import json

import numpy as np
from scipy import constants as csts

from config import (
    Geometry,
    OVEN_MICROTUBE_COUNT,
    OVEN_TEMPERATURE_C,
    YB171_MASS_KG,
    YB171_NATURAL_ABUNDANCE,
)
from simulations.thermal_beam import microtube_intensity_theta


def ytterbium_vapor_pressure_pa(temperature_k):
    """Return Yb vapor pressure in Pa for the source-model correlation."""
    log10_pressure = (
        5.006
        + 9.111
        - 8111.0 / temperature_k
        - 1.0849 * np.log10(temperature_k)
    )
    return float(10.0**log10_pressure)


def estimate_oven_flux(temperature_c=OVEN_TEMPERATURE_C):
    temperature_k = temperature_c + 273.15
    pressure_pa = ytterbium_vapor_pressure_pa(temperature_k)
    number_density_m3 = pressure_pa / (csts.k * temperature_k)
    mean_thermal_speed_m_s = np.sqrt(
        8.0 * csts.k * temperature_k / (np.pi * YB171_MASS_KG)
    )
    incident_flux_density_m2_s = (
        number_density_m3 * mean_thermal_speed_m_s / 4.0
    )
    tube_area_m2 = np.pi * Geometry.OVEN_MICROTUBE_RADIUS_M**2

    theta = np.linspace(1e-9, np.pi / 2 - 1e-9, 200_000)
    angular_transmission = float(
        2.0
        * np.trapezoid(
            microtube_intensity_theta(
                theta,
                Geometry.OVEN_MICROTUBE_RADIUS_M,
                Geometry.OVEN_MICROTUBE_LENGTH_M,
            )
            * np.sin(theta),
            theta,
        )
    )
    all_yb_per_tube_s = (
        incident_flux_density_m2_s * tube_area_m2 * angular_transmission
    )
    all_yb_total_s = all_yb_per_tube_s * OVEN_MICROTUBE_COUNT
    yb171_total_s = all_yb_total_s * YB171_NATURAL_ABUNDANCE

    return {
        "temperature_c": float(temperature_c),
        "temperature_k": float(temperature_k),
        "vapor_pressure_pa": pressure_pa,
        "number_density_m3": float(number_density_m3),
        "mean_thermal_speed_m_s": float(mean_thermal_speed_m_s),
        "microtube_count": OVEN_MICROTUBE_COUNT,
        "microtube_radius_m": Geometry.OVEN_MICROTUBE_RADIUS_M,
        "microtube_length_m": Geometry.OVEN_MICROTUBE_LENGTH_M,
        "angular_transmission_fraction": angular_transmission,
        "all_yb_flux_per_tube_s": float(all_yb_per_tube_s),
        "all_yb_total_flux_s": float(all_yb_total_s),
        "yb171_natural_abundance": YB171_NATURAL_ABUNDANCE,
        "yb171_total_flux_s": float(yb171_total_s),
        "denominator_note": (
            "Total transmitted Yb-171 flux before downstream geometric "
            "acceptance; pair with a full-angular-distribution simulation."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temperature-c", type=float, default=OVEN_TEMPERATURE_C)
    args = parser.parse_args()
    print(json.dumps(estimate_oven_flux(args.temperature_c), indent=2))


if __name__ == "__main__":
    main()
