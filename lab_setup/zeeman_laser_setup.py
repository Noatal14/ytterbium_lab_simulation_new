import numpy as np
from atomsmltr.environment.lasers.beams import LaserBeam
from atomsmltr.environment.lasers.polarization import CircularRight, CircularLeft
from config import BLUE_TRANSITION, BLUE_SATURATION_INTENSITY_MW_CM2, Geometry


ZEEMAN_LASER_WAIST_POSITION_M = (0.0, 0.0, 0.0)
ZEEMAN_LASER_DIRECTION_TYPE = "vector"
ZEEMAN_LASER_TAG = "Zeeman_Laser"


def resolved_zeeman_laser_parameters(
    s0=3.0,
    detuning_gamma=-13.75,
    polarization="CircularRight",
):
    """Return the exact JSON-native parameters used to construct the beam."""
    if polarization not in {"CircularRight", "CircularLeft"}:
        raise ValueError("Unsupported Zeeman-laser polarization.")
    wavelength_m = float(BLUE_TRANSITION.wavelength_m)
    gamma_rad_s = float(BLUE_TRANSITION.gamma_rad_s)
    saturation_intensity_W_m2 = float(BLUE_SATURATION_INTENSITY_MW_CM2 * 10.0)
    peak_intensity_W_m2 = float(s0 * saturation_intensity_W_m2)
    waist_m = float(Geometry.ZEEMAN_LASER_WAIST_M)
    angle_rad = np.radians(Geometry.ZEEMAN_ARM_ANGLE_DEG)
    direction = (0.0, -np.sin(angle_rad), -np.cos(angle_rad))
    power_W = float(peak_intensity_W_m2 * (np.pi * waist_m**2) / 2.0)
    return {
        "s0": float(s0),
        "detuning_gamma": float(detuning_gamma),
        "detuning_rad_s": float(detuning_gamma * gamma_rad_s),
        "wavelength_m": wavelength_m,
        "gamma_rad_s": gamma_rad_s,
        "saturation_intensity_W_m2": saturation_intensity_W_m2,
        "peak_intensity_W_m2": peak_intensity_W_m2,
        "power_W": power_W,
        "waist_m": waist_m,
        "waist_position_m": list(ZEEMAN_LASER_WAIST_POSITION_M),
        "direction_type": ZEEMAN_LASER_DIRECTION_TYPE,
        "direction": [float(value) for value in direction],
        "polarization": polarization,
        "tag": ZEEMAN_LASER_TAG,
    }

class CircularGaussianBeam(LaserBeam):
    """
    Custom implementation of a Circular Gaussian Laser Beam for the Zeeman Slower
    that natively integrates into the atomsmltr environment.

    The 1/e^2 beam waist is `waist`.
    """
    def __init__(
        self,
        wavelength=BLUE_TRANSITION.wavelength_m,
        waist=7e-3,
        power=1e-3,
        waist_position=None,
        direction=None,
        direction_type="vector",
        polarization=None,
        tag=None,
        **kwargs,
    ):
        self._waist = waist
        if "position" in kwargs:
            waist_position = kwargs.pop("position")
        if waist_position is None:
            waist_position = (0, 0, 0)
        if direction is None:
            direction = kwargs.pop("direction", (0, 0, 1))
        if polarization is None:
            polarization = kwargs.pop("polarization", None)
        super().__init__(
            wavelength=wavelength,
            waist=waist,
            power=power,
            waist_position=waist_position,
            direction=direction,
            direction_type=direction_type,
            polarization=polarization,
            tag=tag,
        )

    @property
    def type(self):
        return "Circular Gaussian Beam"

    @property
    def disp_type(self):
        return "Circular beam"

    @staticmethod
    def _intensity_func(self, position):
        """
        Computes the circular 3D intensity.
        `waist` is the 1/e^2 waist radius.
        """
        # Convert to local laser frame
        position_laser = self._convert_coordinates_to_laser_frame(position)
        x_laser, y_laser, z_laser = position_laser.T

        # Rayleigh length
        zR = np.pi * self._waist**2 / self.wavelength

        # Expanding waist
        wz = self._waist * np.sqrt(1 + z_laser**2 / zR**2)

        # Peak intensity computation for a standard circular beam
        # Power P = (pi / 2) * I0 * waist^2 => I0 = 2 * P / (pi * waist^2)
        I0 = 2 * self.power / (np.pi * self._waist**2)

        intensity = I0 * (self._waist / wz)**2 * np.exp(-2 * (x_laser**2 + y_laser**2) / wz**2)

        return intensity.T

    def set_power_from_peak_I(self, target_I0):
        """Sets the total power given a desired peak intensity."""
        self.power = target_I0 * (np.pi * self._waist**2) / 2.0

    # Dummy methods required by base abstract class
    def set_power_from_I(self, target_I):
        self.set_power_from_peak_I(target_I)

    def set_waist_from_I(self, target_I):
        pass


def setup_zeeman_laser(s0=3.0, detuning_gamma=-13.75, atom_species_name="Yb171", polarization="CircularRight"):
    """
    Creates the Zeeman slower laser beam.
    
    Parameters
    ----------
    s0 : float
        Saturation parameter (I_peak / I_sat).
    detuning_gamma : float
        Laser detuning in units of the transition linewidth Γ (Delta = detuning_gamma * Gamma).
    atom_species_name : str
        The atom species name to derive I_sat and Γ from.
    polarization : str
        The polarization of the beam ("CircularRight" or "CircularLeft").
        (Note: You can easily change this parameter to test different effects)

    Returns
    -------
    list of CircularGaussianBeam
    """

    resolved = resolved_zeeman_laser_parameters(
        s0=s0,
        detuning_gamma=detuning_gamma,
        polarization=polarization,
    )
    
    # Configuration for polarization
    pol_obj = CircularRight() if polarization == "CircularRight" else CircularLeft()

    # 3. Create the Beam
    beam = CircularGaussianBeam(
        wavelength=resolved["wavelength_m"],
        waist=resolved["waist_m"],
        waist_position=resolved["waist_position_m"],
        direction_type=resolved["direction_type"],
        direction=resolved["direction"],
        polarization=pol_obj,
        tag=resolved["tag"]
    )
    beam.detuning = resolved["detuning_rad_s"]
    beam.set_power_from_peak_I(resolved["peak_intensity_W_m2"])

    return [beam]

if __name__ == "__main__":
    import matplotlib.pyplot as plt
    print("Testing laser_setup.py...")
    beams = setup_zeeman_laser()
