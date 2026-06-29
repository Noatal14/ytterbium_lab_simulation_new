def _w0(lbda: float) -> float:
    """returns the pulsation, in rad/s

    Parameters
    ----------
    lbda : float
        wavelength (m)

    Returns
    -------
    w0 : float
        pulsation (rad/s)
    """

    w0 = 2 * np.pi * csts.c / lbda
    return w0

def _Isat(lbda: float, Gamma: float) -> float:
    """Returns the saturation intensity, in W/m^2

    Parameters
    ----------
        lbda : float
            vacuum wavelength (in meters)
        Gamma : float
            natural linewidth (in rad/s)

    Returns
    -------
        Isat : float
            saturation intensity (in W/m^2)
    """
    w0 = _w0(lbda)
    Isat = csts.hbar * Gamma * w0**3 / 12 / np.pi / csts.c**2
    return Isat

def _sat_param(lbda: float, Gamma: float, I: float, detuning: float) -> float:
    """Returns the saturation parameter for a two-level system.

    Beware, detuning is 2pi * (f_laser - f_transition)

    Parameters
    ----------
        lbda : float
            vacuum wavelength (in meters)
        Gamma : float
            natural linewidth (in rad/s)
        I : float
            saturation intensity (in W/m^2)
        detuning float
            laser detuning (in rad/s)

    Returns
    -------
        s : float
            the saturation parameter
    """
    Isat = _Isat(lbda, Gamma)
    s = (I / Isat) * (Gamma**2 / 4) / (detuning**2 + Gamma**2 / 4)
    return s

def _scattering_rate(lbda: float, Gamma: float, I: float, detuning: float) -> float:
    """Returns the scattering rate for a two-level system

    Beware, detuning is 2pi * (f_laser - f_transition)

    Parameters
    ----------
        lbda : float
            vacuum wavelength (in meters)
        Gamma : float
            natural linewidth (in rad/s)
        I : float
            saturation intensity (in W/m^2)
        detuning float
            laser detuning (in rad/s)

    Returns
    -------
        gamma_scatt : float
            the scattering rate (in /s)
    """
    s = _sat_param(lbda, Gamma, I, detuning)
    gamma_scatt = 0.5 * Gamma * s / (1 + s)
    return gamma_scatt


def get_scattering_rate(
        self,
        intensity: float,  # the intensity in W/cm^2
        mag_field: float,  # the amplitude of the magnetic field
        polarization: list,  # projection (squared) of laser polarization on (pi, sigma+, sigma-)
        detuning: float,  # laser detuning (in rad/s !!!!!!)
    ):
        # -- get projections
        # TODO : checks here
        polarization = np.asanyarray(polarization)
        proj_pi, proj_sigm_plus, proj_sigm_minus = polarization.T
        proj_pi = proj_pi.T
        proj_sigm_minus = proj_sigm_minus.T
        proj_sigm_plus = proj_sigm_plus.T

        # -- Zeeman effect
        # NB : detuning is 2 * pi * (f_laser - f_atom)
        # constants
        mu_B = csts.physical_constants["Bohr magneton"][0]
        mu = self.lande_factor * mu_B / csts.hbar

        # compute detuning
        det_pi = detuning
        det_sigm_minus = detuning + mu * mag_field
        det_sigm_plus = detuning - mu * mag_field

        # -- Compute scattering rate
        # NB : we assume that the transition is not saturated and we can sum
        # all the polarization components
        scatt_pi = _scattering_rate(
            self.wavelength, self.Gamma, intensity * proj_pi, det_pi
        )
        scatt_sigm_minus = _scattering_rate(
            self.wavelength, self.Gamma, intensity * proj_sigm_minus, det_sigm_minus
        )
        scatt_sigm_plus = _scattering_rate(
            self.wavelength, self.Gamma, intensity * proj_sigm_plus, det_sigm_plus
        )

        # sum
        scatt_total = scatt_pi + scatt_sigm_minus + scatt_sigm_plus

        return scatt_total