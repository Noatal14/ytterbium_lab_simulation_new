import numpy as np
import matplotlib.pyplot as plt
from dt_comparison.consts import F_scale
from scipy import constants as csts
from config import YB171_ISAT_MW_CM2, Geometry, BLUE_LASER_WAVELENGTH_M, BLUE_LASER_GAMMA_HZ
from lab_setup.config_builder import build_2dmot_config
from atomsmltr.simulation.simulator import RK4St

def calc_f_min(
    laser_shape, # circular / elliptical
    laser_waist,
    detuning_gamma,
    s0,
    velocity_range = [1, 50],
    wavelength = BLUE_LASER_WAVELENGTH_M,
    gamma = BLUE_LASER_GAMMA_HZ,
):
    k = 2 * np.pi / wavelength
    k_vec_lab = np.array([k, 0.0, 0.0])
    target_peak_intensity = s0 * YB171_ISAT_MW_CM2 * 10
    position_laser = np.array([0.8 * laser_waist[0], 0.0, 0.0])

    results = []

    for v in range(velocity_range[0], velocity_range[1], 1):
        velocity_plus = np.array([v, 0.0, 0.0])
        velocity_minus = np.array([-v, 0.0, 0.0])

        match laser_shape:
            case "circular":
                power = target_peak_intensity * (np.pi * laser_waist[0]**2) / 2.0
            case "elliptical":
                power = target_peak_intensity * (np.pi * laser_waist[0] * laser_waist[1]) / 2.0

        F_plus = scattering_force_magnitude(
            laser_shape=laser_shape,
            detuning_gamma=detuning_gamma,
            position_laser=position_laser,
            velocity_lab=velocity_plus,
            k_vec_lab=k_vec_lab,
            power=power,
            wavelength=wavelength,
            gamma=gamma,
            waist=laser_waist
        )

        F_minus = scattering_force_magnitude(
            laser_shape=laser_shape,
            detuning_gamma=detuning_gamma,
            position_laser=position_laser,
            velocity_lab=velocity_minus,
            k_vec_lab=k_vec_lab,
            power=power,
            wavelength=wavelength,
            gamma=gamma,
            waist=laser_waist
        )

        A = abs(F_minus - F_plus) / (F_minus + F_plus)

        results.append({
            "v": v,
            "r": 15e-3,
            "F_plus": F_plus,
            "F_minus": F_minus,
            "F_plus_norm": F_plus / F_scale,
            "F_minus_norm": F_minus / F_scale,
            "A": A,
        })

    # Find the first velocity for which A exceeds the chosen threshold
    valid_results = [res for res in results if res["A"] > good_A]

    if not valid_results:
        raise ValueError(f"No velocity in the given range satisfies A > {good_A}")

    threshold_result = valid_results[0]

    F_min = threshold_result["F_plus"]
    F_min_norm = threshold_result["F_plus_norm"]

    return F_min, F_min_norm, threshold_result, results


good_A = 0.8

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

def circular_gaussian_beam_intensity(
    position_laser,
    waist,
    wavelength,
    power
):
    # Convert to local laser frame
    x_laser, y_laser, z_laser = position_laser

    # Rayleigh length
    zR = np.pi * waist**2 / wavelength

    # Expanding waist
    wz = waist * np.sqrt(1 + z_laser**2 / zR**2)

    # Peak intensity computation for a standard circular beam
    # Power P = (pi / 2) * I0 * waist^2 => I0 = 2 * P / (pi * waist^2)
    I0 = 2 * power / (np.pi * waist**2)

    I = I0 * (waist / wz)**2 * np.exp(-2 * (x_laser**2 + y_laser**2) / wz**2)
    return I

def elliptical_gaussian_beam_intensity(
    position_laser,
    power,
    wx,
    wy,
    wavelength,
):
    x, y, z = position_laser

    zRx = np.pi * wx**2 / wavelength
    zRy = np.pi * wy**2 / wavelength

    wzx = wx * np.sqrt(1 + (z / zRx)**2)
    wzy = wy * np.sqrt(1 + (z / zRy)**2)

    I0 = 2 * power / (np.pi * wx * wy)

    I = (
        I0
        * (wx / wzx)
        * (wy / wzy)
        * np.exp(-2 * (x**2 / wzx**2 + y**2 / wzy**2))
    )

    return I


def scattering_force_magnitude(
    laser_shape,
    detuning_gamma,
    position_laser,
    velocity_lab,
    k_vec_lab,
    power,
    wavelength,
    gamma,
    waist
):
    position_laser = np.asarray(position_laser, dtype=float)
    velocity_lab = np.asarray(velocity_lab, dtype=float)
    k_vec_lab = np.asarray(k_vec_lab, dtype=float)

    match laser_shape:
        case "circular":
            I = circular_gaussian_beam_intensity(
                position_laser=position_laser,
                power=power,
                waist=waist[0],
                wavelength=wavelength,
            )  
        case "elliptical":
            I = elliptical_gaussian_beam_intensity(
                position_laser=position_laser,
                power=power,
                wx=waist[0],
                wy=waist[1],
                wavelength=wavelength,
            )

    I_sat=YB171_ISAT_MW_CM2 * 10

    s0 = I / I_sat

    delta = detuning_gamma - np.dot(k_vec_lab, velocity_lab)

    gamma_p = (gamma / 2) * s0 / (1 + s0 + (2 * delta / gamma) ** 2)

    F_mag = csts.hbar * np.linalg.norm(k_vec_lab) * gamma_p

    return F_mag


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

    
    A_values = [result["A"] for result in results]
    F_plus_norm_values = [result["F_plus_norm"] for result in results]

    plt.figure(figsize=(8, 5))

    plt.plot(
        A_values,
        F_plus_norm_values,
        marker="o",
        markersize=3,
        linewidth=1,
    )

    plt.axvline(
        0.8,
        linestyle="--",
        label="A=0.8",
    )

    plt.xlabel("A")
    plt.ylabel(r"$F_+/F_{\mathrm{scale}}$")
    plt.title(r"Weak-beam force vs. force asymmetry")
    plt.grid(True, which="both", alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()

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
        detuning_gamma=-1.2,
        s0=1.5,
        magnet_radius=0.055
    )

    # F_min, F_min_norm, threshold_result, results = calc_f_min(
    #     laser_shape="elliptical",
    #     laser_waist=[Geometry.MOT_WX, Geometry.MOT_WY],
    #     detuning_gamma=-1.2 * BLUE_LASER_GAMMA_HZ,
    #     s0=1.5,
    # )

    print("F_min =", F_min)
    print("F_min / F_scale =", F_min_norm)
    print("chosen result =", threshold_result)

    # wavelength = 399e-9
    # gamma = 2 * np.pi * 29.13e6
    # k = 2 * np.pi / wavelength

    # wx=Geometry.MOT_WX
    # wy=Geometry.MOT_WY

    # k_vec_lab = np.array([k, 0.0, 0.0])           # laser propagates in +x direction

    # s0 = 1.5
    # # Peak intensity based on s0 parameter
    # target_peak_intensity = s0 * YB171_ISAT_MW_CM2 * 10

    # power = target_peak_intensity * (np.pi * wx * wy) / 2.0

    # results = []

    # position_laser = np.array([15e-3, 0.0, 0.0])

    # for v in range(1, 50, 1):
    #     velocity_plus = np.array([v, 0.0, 0.0])
    #     velocity_minus = np.array([-v, 0.0, 0.0])

    #     F_plus = scattering_force_magnitude(
    #         laser_shape='elliptical',
    #         detuning_gamma=-1.2 * gamma,
    #         position_laser=position_laser,
    #         velocity_lab=velocity_plus,
    #         k_vec_lab=k_vec_lab,
    #         power=power,
    #         wavelength=wavelength,
    #         gamma=gamma,
    #         waist=[wx, wy]
    #     )

    #     F_minus = scattering_force_magnitude(
    #         laser_shape='elliptical',
    #         detuning_gamma=-1.2 * gamma,
    #         position_laser=position_laser,
    #         velocity_lab=velocity_minus,
    #         k_vec_lab=k_vec_lab,
    #         power=power,
    #         wavelength=wavelength,
    #         gamma=gamma,
    #         waist=[wx, wy]
    #     )

    #     A = abs(F_minus - F_plus) / (F_minus + F_plus)

    #     results.append({
    #         "v": v,
    #         "r": 15e-3,
    #         "F_plus": F_plus,
    #         "F_minus": F_minus,
    #         "F_plus_norm": F_plus / F_scale,
    #         "F_minus_norm": F_minus / F_scale,
    #         "A": A,
    #     })

    # for res in results:
    #     print(
    #         f"v={res['v']:2d} m/s | "
    #         f"A={res['A']:.3f} | "
    #         f"F+={res['F_plus']:.3e} N | "
    #         f"F-={res['F_minus']:.3e} N"
    #         f"F_plus_norm={res['F_plus_norm']:.3f} | "
    #         f"F_minus_norm={res['F_minus_norm']:.3f} | "
    #     )