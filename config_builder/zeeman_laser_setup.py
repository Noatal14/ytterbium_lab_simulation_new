import numpy as np
from atomsmltr.environment.lasers.beams import LaserBeam
from atomsmltr.environment.lasers.polarization import CircularRight, CircularLeft
from .atom_species import create_atom, YB171_ISAT_MW_CM2

class CircularGaussianBeam(LaserBeam):
    """
    Custom implementation of a Circular Gaussian Laser Beam for the Zeeman Slower
    that natively integrates into the atomsmltr environment.
    
    The 1/e^2 beam waist is `waist`.
    """
    def __init__(self, wavelength=399e-9, waist=7e-3, power=1e-3, **kwargs):
        self._waist = waist
        super().__init__(wavelength=wavelength, waist=waist, power=power, **kwargs)

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
    # 1. Fetch atomic properties
    atom = create_atom(atom_species_name)
    main_trans = list(atom.trans.keys())[0] if atom.trans else None
    if not main_trans:
        raise ValueError(f"Atom '{atom_species_name}' has no defined transition.")
    
    trans = atom.trans[main_trans]
    wavelength = trans.wavelength
    
    # Calculate I_sat in pure SI units (W/m^2)
    isat_W_m2 = YB171_ISAT_MW_CM2 * 10.0 
    
    # Peak intensity based on s0 parameter
    target_peak_intensity = s0 * isat_W_m2
    
    # 2. Geometry
    # 1/e^2 waist is 7mm based on the provided diameter of 14mm
    waist = 7e-3  
    
    # Direction: Angle of 25 degrees with the positive Z axis, in the ZY plane
    # Coming from (+Z, +Y) and pointing towards (-Z, -Y).
    angle_deg = 25.0
    angle_rad = np.radians(angle_deg)
    
    # The direction vector is normalized.
    # It points entirely in the YZ plane to (-Z, -Y) coordinates.
    direction_vec = (0.0, -np.sin(angle_rad), -np.cos(angle_rad))
    
    # Configuration for polarization
    pol_obj = CircularRight() if polarization == "CircularRight" else CircularLeft()

    # 3. Create the Beam
    beam = CircularGaussianBeam(
        wavelength=wavelength,
        waist=waist,
        waist_position=(0, 0, 0),
        direction_type="vector",
        direction=direction_vec,
        polarization=pol_obj,
        tag="Zeeman_Laser"
    )
    beam.detuning = detuning_gamma * trans.Gamma  # Setting detuning directly as an attribute
    beam.set_power_from_peak_I(target_peak_intensity)

    return [beam]
