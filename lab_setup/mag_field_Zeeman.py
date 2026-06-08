import numpy as np
import magpylib as magpy
from scipy.spatial.transform import Rotation as R
from atomsmltr.environment.fields.magnetic import MagneticField

class ZeemanSlowerField(MagneticField):
    """
    A setup for a Zeeman slower consisting of 20 rings, 
    each with 8 permanent magnets rotated towards or away from the central axis.
    """
    def __init__(self, zeeman_axis_offset=0.0, magnet_dimensions=(0.005, 0.005, 0.005), polarization_T=-1.24, angle_deg=25.0, start_distance=0.314):
        """
        Initializes the custom magpylib Zeeman Slower field.
        
        Args:
            zeeman_axis_offset (float): An overall offset in the Z direction (default 0).
            magnet_dimensions (tuple): The xyz dimensions of each cuboid magnet in meters.
            polarization_T (float): The flux density / polarization vector magnitude in Tesla.
            angle_deg (float): The angle in degrees of the Zeeman arm w.r.t the -Z lab axis.
            start_distance (float): The distance from the lab origin to the start (Z_zeeman=0) of the Zeeman magnets.
        """
        super().__init__()
        self.zeeman_axis_offset = zeeman_axis_offset
        self.magnet_dimensions = magnet_dimensions
        self.polarization_T = polarization_T
        self.angle_deg = angle_deg
        self.start_distance = start_distance

        self.radii = [0.0175, 0.0175, 0.0175, 0.0185, 0.0175, 0.0187, 0.0181, 0.0175, 0.0175, 0.0179, 
                      0.0188, 0.0207, 0.0245, 0.0249, 0.0210, 0.0194, 0.0200, 0.0232, 0.0175, 0.0185]
        self.positions_z = [-0.0200, -0.0123, -0.0053, 0.0020, 0.0103, 0.0192, 0.0273, 0.0351, 0.0431, 
                            0.0510, 0.0592, 0.0678, 0.0784, 0.1075, 0.1193, 0.1283, 0.1370, 0.1457, 
                            0.1547, 0.1637]
        self.tilt_angles = [-70.2857, -89.9994, -90.0000, -172.7935, -138.4226, -155.4454, -171.3141, 
                            -168.2399, -167.7998, -166.2449, -161.4433, -150.2352, -145.7914, 21.2799, 
                            17.5568, 38.4814, 70.7662, 50.5701, 36.0731, 136.4575]

        self.tilt_angles = [-i for i in self.tilt_angles]

        # The polarization vector magnitude is set initially along the magnet's local Z-axis.
        pol = (0, 0, self.polarization_T)
        dim = self.magnet_dimensions

        magnets = []
        
        # We put 8 magnets per ring
        azimuthal_angles = np.linspace(0, 360, 8, endpoint=False)
        
        # Define coordinate transformation from internal to lab frame
        # Lab frame -Z axis is [0, 0, -1]. 
        # Target angle is 25 deg in the 3rd quadrant (-Y, -Z).
        # u_vec points from lab origin to the Z_zeeman=0 point.
        u_vec = np.array([0.0, -np.sin(np.radians(self.angle_deg)), -np.cos(np.radians(self.angle_deg))])
        translation = u_vec * self.start_distance
        
        # rot_env rotates the internal +Z-axis [0, 0, 1] to -u_vec [0, sin(angle), cos(angle)]
        # so that increasing Z_zeeman moves *towards* the lab origin.
        rot_env = R.from_euler('x', -self.angle_deg, degrees=True)

        for r, z_pos, tilt in zip(self.radii, self.positions_z, self.tilt_angles):
            for azi_deg in azimuthal_angles:
                azi_rad = np.radians(azi_deg)
                
                # Internal position
                pos_internal = (r * np.cos(azi_rad), r * np.sin(azi_rad), z_pos + self.zeeman_axis_offset)
                
                # Transform to lab position
                pos_lab = rot_env.apply(pos_internal) + translation
                
                # Internal orientation
                ori_internal = R.from_euler('z', azi_deg, degrees=True) * R.from_euler('y', -tilt, degrees=True)
                
                # Transform to lab orientation
                ori_lab = rot_env * ori_internal
                
                mag = magpy.magnet.Cuboid(polarization=pol, dimension=dim, position=pos_lab, orientation=ori_lab)
                magnets.append(mag)

        self.collection = magpy.Collection(magnets)

    def _field_value_func(self, position):
        return self.collection.getB(position)

    def gen_infostring_obj(self):
        return f"Zeeman Slower Magpylib Field (20 rings, 160 magnets)"

    def show_magnets(self):
        magpy.show(self.collection, style={'magnetization': {'show': True}})
