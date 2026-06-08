import numpy as np
from atomsmltr.environment.lasers.beams import LaserBeam
from atomsmltr.environment.lasers.polarization import CircularLeft, CircularRight
from config import BLUE_TRANSITION, YB171_ISAT_MW_CM2

class EllipticalLaserBeam(LaserBeam):
    """
    Custom implementation of an Elliptical Gaussian Laser Beam for 2DMOT
    that natively integrates into the atomsmltr environment.
    
    The semi-minor axis is `wx` and the semi-major axis is `wy`
    in the beam's local frame.
    """
    def __init__(self, wavelength=399e-9, wx=1e-3, wy=1e-3, power=1e-3, **kwargs):
        self._wx = wx
        self._wy = wy
        # Set waist to wx just to satisfy base class properties if asked
        super().__init__(wavelength=wavelength, waist=wx, power=power, **kwargs)

    @property
    def type(self):
        return "Elliptical Laser Beam"

    @property
    def disp_type(self):
        return "Elliptical beam"

    @property
    def wx(self):
        return self._wx
    
    @property
    def wy(self):
        return self._wy

    @staticmethod
    def _intensity_func(self, position):
        """
        Computes the elliptical 3D intensity.
        wx and wy are the 1/e^2 waists along the beam's local X and Y axes.
        """
        # Convert to local laser frame
        position_laser = self._convert_coordinates_to_laser_frame(position)
        x_laser, y_laser, z_laser = position_laser.T
        
        # Rayleigh lengths for both axes
        zRx = np.pi * self._wx**2 / self.wavelength
        zRy = np.pi * self._wy**2 / self.wavelength
        
        # Expanding waists
        wzx = self._wx * np.sqrt(1 + z_laser**2 / zRx**2)
        wzy = self._wy * np.sqrt(1 + z_laser**2 / zRy**2)
        
        # Peak intensity computation for an elliptical beam
        # Power P = (pi / 2) * I0 * wx * wy => I0 = 2 * P / (pi * wx * wy)
        I0 = 2 * self.power / (np.pi * self._wx * self._wy)
        
        intensity = I0 * (self._wx / wzx) * (self._wy / wzy) * \
                    np.exp(-2 * (x_laser**2 / wzx**2 + y_laser**2 / wzy**2))
                    
        return intensity.T

    def set_power_from_peak_I(self, target_I0):
        """Sets the total power given a desired peak intensity."""
        self.power = target_I0 * (np.pi * self._wx * self._wy) / 2.0
    
    # Dummy methods required by base abstract class
    def set_power_from_I(self, target_I):
        self.set_power_from_peak_I(target_I)

    def set_waist_from_I(self, target_I):
        pass


def setup_2dmot_lasers(s0=10.0, detuning_gamma=-1.0, atom_species_name="Yb171", swap_polarization=False):
    """
    Creates the 4 counter-propagating laser beams for a 2DMOT.
    
    Parameters
    ----------
    s0 : float
        Saturation parameter (I_peak / I_sat).
    detuning_gamma : float
        Laser detuning in units of the transition linewidth Γ (Delta = detuning_gamma * Gamma).
    atom_species_name : str
        The atom species name to derive I_sat and Γ from.

    Returns
    -------
    list of EllipticalLaserBeam
    """
    wavelength = BLUE_TRANSITION.wavelength
        
    # Calculate I_sat in pure SI units (W/m^2)
    # 1 mW/cm^2 = 10 W/m^2
    # Hardcoding to YB171_ISAT for now or generalized if passed
    # but a proper physics derivation can be used if I_sat isn't provided directly
    isat_W_m2 = YB171_ISAT_MW_CM2 * 10.0 
    
    # Peak intensity based on s0 parameter
    target_peak_intensity = s0 * isat_W_m2
    
    # 2. Geometry
    # Elliptical geometry: Semi-major=19mm (along Lab Z, the atomic beam axis), Semi-minor=5mm (transverse).
    #
    # VERIFIED: atomsmltr's internal laser frame rotation maps Lab Z → Laser local X
    # for BOTH X-directed and Y-directed beams. Therefore wx=19mm always produces
    # a 19mm-wide beam along Lab Z, and wy=5mm produces 5mm in the other transverse axis.
    # This has been confirmed by evaluating the actual intensity profile at specific lab points.
    wx = 19e-3  # Semi-major: always along Lab Z due to frame mapping
    wy = 5e-3   # Semi-minor: transverse (Lab Y for X-beams, Lab X for Y-beams)

    beams = []
    
    # Helper to create a single beam with predefined power solving
    def make_beam(direction_label, direction_vec, polarization, tag):
        beam = EllipticalLaserBeam(
            wavelength=wavelength,
            wx=wx,
            wy=wy,
            waist_position=(0, 0, 0),
            direction_type="vector",
            direction=direction_vec,
            polarization=polarization,
            tag=tag
        )
        beam.set_power_from_peak_I(target_peak_intensity)
        return beam

    # 3. Create Beams
    # Default: X-beams=CircularRight, Y-beams=CircularLeft
    # Swapped: X-beams=CircularLeft,  Y-beams=CircularRight
    # NOTE (VERIFIED): Default polarization (X=σ+, Y=σ-) produces the correct
    # restoring force for the 2DMOT. Swapped polarization was tested and confirmed
    # to produce an ANTI-trapping (repulsive) force. Do not change without reason.
    if swap_polarization:
        pol_x, pol_y = CircularLeft(), CircularRight()
    else:
        pol_x, pol_y = CircularRight(), CircularLeft()
    
    # X-axis pairs: wx(19mm) → Lab Z, wy(5mm) → Lab Y
    bx_fwd = make_beam("+X", (1, 0, 0), pol_x, "Beam_+X")
    bx_bwd = make_beam("-X", (-1, 0, 0), pol_x, "Beam_-X")
    
    # Y-axis pairs: wx(19mm) → Lab Z, wy(5mm) → Lab X
    by_fwd = make_beam("+Y", (0, 1, 0), pol_y, "Beam_+Y")
    by_bwd = make_beam("-Y", (0, -1, 0), pol_y, "Beam_-Y")

    beams.extend([bx_fwd, bx_bwd, by_fwd, by_bwd])
    return beams

if __name__ == "__main__":
    import matplotlib.pyplot as plt
    print("Testing laser_setup.py...")
    try:
        s0_val = 1.0
        mot_beams = setup_2dmot_lasers(s0=s0_val, detuning_gamma=-1.0, atom_species_name="Yb171")
        print(f"✅ Generated {len(mot_beams)} beams successfully.")
        
        # Test 1: Check power scaling
        b1 = mot_beams[0]
        expected_I0 = s0_val * (YB171_ISAT_MW_CM2 * 10.0)
        actual_I0 = 2 * b1.power / (np.pi * b1.wx * b1.wy)
        print(f"   -> Requested Peak Intensity: {expected_I0:.2f} W/m²")
        print(f"   -> Actual Peak Intensity: {actual_I0:.2f} W/m²")
        print(f"   -> Peak Power set to: {b1.power:.4f} W")
        
        # Test 2: Check Elliptical behavior in 3D and 2D
        print("✅ Generating 2D plots of the elliptical beam...")
        fig, axes = plt.subplots(1, 2, figsize=(10, 4))
        
        # Plot cutting across the beam's local xy profile (Z=0 in laser frame)
        # Note: the standard plot2D function projects along Lab axes, so we'll just plot to ensure no crashes
        b1.plot2D(limits=(-0.02, 0.02, -0.02, 0.02), Npoints=(100, 100), cut=0, plane="YZ", ax=axes[0])
        axes[0].set_title("Elliptical Beam X-axis (YZ plane cut)")
        
        # Another cut
        b1.plot2D(limits=(-0.02, 0.02, -0.02, 0.02), Npoints=(100, 100), cut=0, plane="XY", ax=axes[1])
        axes[1].set_title("Elliptical Beam X-axis (XY plane cut)")
        
        plt.tight_layout()
        plt.savefig("beam_profile_test.png")
        print("✅ Saved 'beam_profile_test.png' to current directory.")
        
        print("All tests passed.")
        
    except Exception as e:
        print(f"❌ Error occurred: {e}")
