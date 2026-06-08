import numpy as np
import magpylib as magpy
from scipy.spatial.transform import Rotation as R
from atomsmltr.environment.fields.magnetic import MagneticField

class CustomQuadrupole(MagneticField):
    """
    A setup for a 2DMOT quadrupole field composed of four permanent magnets, 
    implemented using magpylib and integrated as an atomsmltr MagneticField.

    The length is aligned with the Z-axis (atomic beam free-flight axis).
    The magnets are placed at a specified radius from the origin in the X-Y plane at 45, 135, 225, and 315 degree positions.
    """
    def __init__(self, radius=0.06, magnet_dimensions=(0.01, 0.01, 0.08), polarization_T=1.17):
        """
        Initializes the custom magpylib quadrupole.
        
        Args:
            radius (float): Distance from the Z-axis origin to the center of each magnet in meters. Default 6cm.
            magnet_dimensions (tuple): The (width, height, length) in meters. The default pole points along width (X axis).
            polarization_T (float): The flux density / polarization vector magnitude in Tesla.
        """
        super().__init__()
        self.radius = radius
        self.magnet_dimensions = magnet_dimensions
        self.polarization_T = polarization_T

        # Define 4 magnets using magpylib.
        # Polarization by default points along the +X axis (local width). 
        # They will be rotated and positioned.
        
        pol = (self.polarization_T, 0, 0)
        dim = self.magnet_dimensions

        # Magnet 1: Positioned at 45 degrees, oriented at 135 degrees.
        pos_angle_1 = np.radians(45)
        pos_1 = (self.radius * np.cos(pos_angle_1), self.radius * np.sin(pos_angle_1), 0)
        ori_1 = R.from_euler('z', 135, degrees=True)
        self.mag1 = magpy.magnet.Cuboid(polarization=pol, dimension=dim, position=pos_1, orientation=ori_1)

        # Magnet 2: Positioned at 135 degrees, oriented at 45 degrees.
        pos_angle_2 = np.radians(135)
        pos_2 = (self.radius * np.cos(pos_angle_2), self.radius * np.sin(pos_angle_2), 0)
        ori_2 = R.from_euler('z', 45, degrees=True)
        self.mag2 = magpy.magnet.Cuboid(polarization=pol, dimension=dim, position=pos_2, orientation=ori_2)

        # Magnet 3: Positioned at 225 degrees, oriented at 315 degrees.
        pos_angle_3 = np.radians(225)
        pos_3 = (self.radius * np.cos(pos_angle_3), self.radius * np.sin(pos_angle_3), 0)
        ori_3 = R.from_euler('z', 315, degrees=True)
        self.mag3 = magpy.magnet.Cuboid(polarization=pol, dimension=dim, position=pos_3, orientation=ori_3)

        # Magnet 4: Positioned at 315 degrees, oriented at 225 degrees.
        pos_angle_4 = np.radians(315)
        pos_4 = (self.radius * np.cos(pos_angle_4), self.radius * np.sin(pos_angle_4), 0)
        ori_4 = R.from_euler('z', 225, degrees=True)
        self.mag4 = magpy.magnet.Cuboid(polarization=pol, dimension=dim, position=pos_4, orientation=ori_4)

        # Group them into a collection
        self.collection = magpy.Collection(self.mag1, self.mag2, self.mag3, self.mag4)

    def _field_value_func(self, position):
        """
        Overrides the atomsmltr MagneticField evaluation function.
        Calculates the B-field from the magpylib collection.
        
        Args:
            position (np.ndarray): Shape (3,) or (N, 3) coordinate array in meters.
        Returns:
            np.ndarray: Evaluated B-field vector in Tesla.
        """
        # magpy.getB expects a single array or list of observers, returning the same shape array.
        B = self.collection.getB(position)
        return B

    def gen_infostring_obj(self):
        return f"Custom Magpylib Quadrupole (Radius={self.radius}m, B_r={self.polarization_T}T)"

    def show_magnets(self):
        """
        Displays the physical arrangement and orientations using magpylib's 3D viewer.
        """
        # Show configuration centered at origin 
        magpy.show(self.collection, style={'magnetization': {'show': True}})
