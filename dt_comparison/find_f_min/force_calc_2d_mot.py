import numpy as np
import matplotlib.pyplot as plt
from dt_comparison.consts import F_scale
from scipy import constants as csts
from config import YB171_ISAT_MW_CM2, Geometry, BLUE_LASER_WAVELENGTH_M, BLUE_LASER_GAMMA_HZ
from lab_setup.config_builder import build_2dmot_config
from atomsmltr.simulation.simulator import RK4St

good_A = 0

def _get_force_vec(
        position: np.ndarray,
        speed: np.ndarray,
        config,
        return_list: bool = False,
    ) -> np.ndarray:

        # - get magnetic field value & norm
        B = config.getB(position)
        Bx, By, Bz = B.T
        B_norm = np.sqrt(Bx**2 + By**2 + Bz**2).T
        # - initialize force
        force = [np.zeros_like(position, dtype=float)] * 4
        # - prepare scattering list
        scattering_list = []
        # - loop over atom-light couplings
        atomlight_couples = config.get_atomlight_couples()
        i = 0
        for elements in atomlight_couples:
            transition, laser, detuning = elements
            laser_intensity = laser.get_value(position)
            polarization = laser.get_polarization_quant(B)
            # Doppler
            det_Doppler = -np.dot(speed, transition.k * laser.unit_vector)
            scattering_rate = transition.get_scattering_rate(
                laser_intensity, B_norm, polarization, detuning + det_Doppler
            )
            radiation_pressure = csts.hbar * transition.k * scattering_rate
            force[i] = radiation_pressure[..., np.newaxis] * laser.unit_vector
            i += 1

        return force

def get_force_vec(
    pos_speed_vector: np.ndarray,
    config,
    return_list: bool = False,
) -> np.ndarray:

    # TODO should we move that to the Configuration class ???
    # - get position and speed
    x, y, z, vx, vy, vz = pos_speed_vector.T
    position = np.array([x, y, z]).T
    speed = np.array([vx, vy, vz]).T
    # - get force
    res = _get_force_vec(position, speed, config, return_list)
    if return_list:
        force, scattering_list = res
        return force, scattering_list
    else:
        force = res
        return force
    
class RK4StCustom(RK4St):
    def get_force(self, u):
        force = get_force_vec(u, self.config)
        return force


def calc_f_min_2d_mot(
    s0,
    detuning_gamma,
    magnet_radius,
    velocity_range = [1, 50]
):
    atom, config = build_2dmot_config(
        s0=s0,
        detuning_gamma=detuning_gamma,
        magnet_radius=magnet_radius,
    )
    sim = RK4StCustom(config)

    results = []

    for v in range(velocity_range[0], velocity_range[1], 1):
        F_plus_vec = sim.get_force(np.array([0, Geometry.MOT_WY, 0, -v, 0, 0]))[0]
        F_plus = np.linalg.norm(F_plus_vec)

        F_minus_vec = sim.get_force(np.array([0, Geometry.MOT_WY, 0, v, 0, 0]))[0]
        F_minus = np.linalg.norm(F_minus_vec)

        A = abs(F_minus - F_plus) / (F_minus + F_plus)

        results.append({
            "v": v,
            "F_plus": F_plus,
            "F_minus": F_minus,
            "F_plus_norm": F_plus / F_scale,
            "F_minus_norm": F_minus / F_scale,
            "A": A,
        })

    for res in results:
        print(
            f"v={res['v']:2d} m/s | "
            f"A={res['A']:.3f} | "
            f"F+={res['F_plus']:.3e} N | "
            f"F-={res['F_minus']:.3e} N"
            f"F_plus_norm={res['F_plus_norm']:.3f} | "
            f"F_minus_norm={res['F_minus_norm']:.3f} | "
        )

    # Find the first velocity for which A exceeds the chosen threshold
    valid_results = [res for res in results if res["A"] > good_A]

    if not valid_results:
        raise ValueError(f"No velocity in the given range satisfies A > {good_A}")

    threshold_result = valid_results[0]

    F_min = threshold_result["F_plus"]
    F_min_norm = threshold_result["F_plus_norm"]
    

    return F_min, F_min_norm, threshold_result, results
    

if __name__ == "__main__":
    F_min, F_min_norm, threshold_result, results = calc_f_min_2d_mot(
        detuning_gamma=-1.47,
        s0=1.4,
        magnet_radius=0.055
    )

    print("F_min =", F_min)
    print("F_min / F_scale =", F_min_norm)
    print("chosen result =", threshold_result)