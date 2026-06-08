import numpy as np
from lab_setup.zeeman_laser_setup import CircularGaussianBeam
from atomsmltr.environment.lasers.polarization import CircularRight, CircularLeft
from config import YB171_ISAT_MW_CM2

def setup_3dmot_lasers(
    s0_399=0.5,
    detuning_gamma_399=-1.0,
    waist_399=0.01,
    s0_556=5.0,
    detuning_gamma_556=-10.0,
    waist_556=0.015,
    atom_species_name="Yb171"
):
    """
    Sets up the 6 3D MOT beams. Each "beam" actually consists of two overlapping 
    lasers (one 399nm, one 556nm) propagating in the exact same direction.

    Geometry:
    - 2 beams along the Z axis (+Z and -Z)
    - 4 transverse beams. You mentioned they are at a 60 degree angle from Z.
      To ensure the forces balance out, we assume 2 are at 60 degrees from +Z, 
      and 2 are at 60 degrees from -Z (120 degrees), spaced azimuthally.
      You can freely adjust the `theta` and `phi` arrays below.
    """
    
    # Calculate physical intensities in W/m^2
    isat_W_m2_399 = YB171_ISAT_MW_CM2 * 10.0 
    peak_intensity_399 = s0_399 * isat_W_m2_399

    isat_W_m2_556 = YB171_ISAT_MW_CM2 * 10.0 
    peak_intensity_556 = s0_556 * isat_W_m2_556

    beams = []
    
    # 1. Define the direction vectors for the 6 beam axes
    # Format: (theta_deg, phi_deg, polarization, name_suffix)
    # Theta is polar angle from +Z. Phi is azimuthal angle in X-Y plane.
    
    beam_configs = [
        # Z-axis beams (Theta = 0 and 180)
        (180.0,   0.0, CircularRight(), "Z_Plus"),  # Propagating towards -Z (from +Z)
        (  0.0,   0.0, CircularRight(), "Z_Minus"), # Propagating towards +Z (from -Z)
        
        # Transverse beams (Tilted 60 degrees from Z)
        # Assuming they are arranged symmetrically to balance the forces
        ( 60.0,   0.0, CircularRight(), "Trans_1"),
        ( 60.0, 180.0, CircularRight(), "Trans_2"),
        (120.0,  90.0, CircularRight(), "Trans_3"),
        (120.0, 270.0, CircularRight(), "Trans_4"),
    ]

    # Note on Polarization:
    # Standard MOT uses opposite circular polarizations for counter-propagating beams 
    # depending on the magnetic field gradient direction. 
    # Because atomsmltr's `CircularGaussianBeam` defines polarization relative to its 
    # direction of propagation, two counter-propagating beams that both have `CircularRight()`
    # actually have opposite helicity in the lab frame.
    
    for theta_deg, phi_deg, pol, name in beam_configs:
        
        # Convert spherical to Cartesian direction vector
        theta = np.radians(theta_deg)
        phi = np.radians(phi_deg)
        
        dir_x = np.sin(theta) * np.cos(phi)
        dir_y = np.sin(theta) * np.sin(phi)
        dir_z = np.cos(theta)
        direction = np.array([dir_x, dir_y, dir_z])
        
        # Normalize just in case
        direction = direction / np.linalg.norm(direction)
        
        # For a standard MOT, we assume beams are aligned and cross at the origin
        position = np.array([0.0, 0.0, 0.0])

        # --- Create the 399nm shell ---
        beam_399 = CircularGaussianBeam(
            power=peak_intensity_399 * (np.pi * waist_399**2 / 2), # Convert peak I to total Power
            waist=waist_399,
            position=position,
            direction=direction,
            polarization=pol,
            tag=f"3DMOT_399_{name}"
        )
        beams.append(beam_399)

        # --- Create the 556nm shell ---
        beam_556 = CircularGaussianBeam(
            power=peak_intensity_556 * (np.pi * waist_556**2 / 2), 
            waist=waist_556,
            position=position,
            direction=direction,
            polarization=pol,
            tag=f"3DMOT_556_{name}"
        )
        beams.append(beam_556)
        
    return beams
