import numpy as np
import matplotlib.pyplot as plt
HBAR = 1.054_571_817e-34  # J*s


def gaussian_beam_intensity(
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
    position_laser,
    velocity_lab,
    k_vec_lab,
    power,
    wx,
    wy,
    wavelength,
    gamma,
    delta0,
    I_sat=59.97e-3 / 1e-4,  # 59.97 mW/cm^2 -> W/m^2
):
    """
    Computes the scattering force magnitude for one laser beam.

    Parameters
    ----------
    position_laser : array-like, shape (3,)
        Atom position in the laser coordinate frame [m].
        The beam propagates along the laser-frame z axis.

    velocity_lab : array-like, shape (3,)
        Atom velocity in lab frame [m/s].

    k_vec_lab : array-like, shape (3,)
        Laser wavevector in lab frame [1/m].
        Should include direction and magnitude, |k| = 2*pi/lambda.

    power : float
        Laser power [W].

    wx, wy : float
        Beam waists in laser-frame x/y directions [m].

    wavelength : float
        Laser wavelength [m].

    gamma : float
        Natural linewidth Gamma [rad/s], if delta0 is also in rad/s.

    delta0 : float
        Laser detuning [rad/s].

    I_sat : float
        Saturation intensity [W/m^2].

    Returns
    -------
    F_mag : float
        Scattering force magnitude [N].
    """

    position_laser = np.asarray(position_laser, dtype=float)
    velocity_lab = np.asarray(velocity_lab, dtype=float)
    k_vec_lab = np.asarray(k_vec_lab, dtype=float)

    I = gaussian_beam_intensity(
        position_laser=position_laser,
        power=power,
        wx=wx,
        wy=wy,
        wavelength=wavelength,
    )

    s0 = I / I_sat

    delta = delta0 - np.dot(k_vec_lab, velocity_lab)

    gamma_p = (gamma / 2) * s0 / (1 + s0 + (2 * delta / gamma) ** 2)

    F_mag = HBAR * np.linalg.norm(k_vec_lab) * gamma_p

    return F_mag


if __name__ == "__main__":
    wavelength = 399e-9
    gamma = 2 * np.pi * 29.13e6
    k = 2 * np.pi / wavelength

    wx=19e-3
    wy=5e-3

    position_laser = np.array([0, 0.0, 0.0])  # r = 1.5 cm from beam center
    velocity_lab = np.array([-20, 0.0, 0.0])     # example velocity

    k_vec_lab = np.array([k, 0.0, 0.0])           # laser propagates in +x direction

    s0 = 1.5
    YB171_ISAT_W_CM2 = 599.7
    
    # Peak intensity based on s0 parameter
    target_peak_intensity = s0 * YB171_ISAT_W_CM2

    power = target_peak_intensity * (np.pi * wx * wy) / 2.0

    results = []

    position_laser = np.array([15e-3, 0.0, 0.0])

    for v in range(1, 50, 1):

        velocity_plus = np.array([v, 0.0, 0.0])
        velocity_minus = np.array([-v, 0.0, 0.0])

        F_plus = scattering_force_magnitude(
            position_laser=position_laser,
            velocity_lab=velocity_plus,
            k_vec_lab=k_vec_lab,
            power=power,
            wx=wx,
            wy=wy,
            wavelength=wavelength,
            gamma=gamma,
            delta0=-1.2 * gamma,
        )

        F_minus = scattering_force_magnitude(
            position_laser=position_laser,
            velocity_lab=velocity_minus,
            k_vec_lab=k_vec_lab,
            power=power,
            wx=wx,
            wy=wy,
            wavelength=wavelength,
            gamma=gamma,
            delta0=-1.2 * gamma,
        )

        A = abs(F_minus - F_plus) / (F_minus + F_plus)

        F_scale = 3.141895058426422e-20

        results.append({
            "v": v,
            "r": 15e-3,
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
    v_values = [result["v"] for result in results]
    
    plt.figure(figsize=(8, 5))
    plt.plot(v_values, A_values, marker="o", markersize=3, linewidth=1)

    plt.axhline(0.8, linestyle="--", label="A=0.8")

    plt.xlabel("v")
    plt.ylabel("A(v)")
    plt.title("Scattering Force Asymmetry vs. Transverse Velocity")
    plt.grid(True, which="both", alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()