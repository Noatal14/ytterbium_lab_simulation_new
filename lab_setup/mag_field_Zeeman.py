import numpy as np
import magpylib as magpy
from scipy.spatial.transform import Rotation as R
from atomsmltr.environment.fields.magnetic import MagneticField
from lab_setup.physical_specification import (
    LABORATORY_PHYSICAL_SPECIFICATION, ZEEMAN_MODEL_CONVENTIONS,
)

_CONSTRUCTION = LABORATORY_PHYSICAL_SPECIFICATION["zeeman_field_hardware"]
_CANONICAL_PROFILE = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]
ZEEMAN_AXIS_OFFSET_M = _CONSTRUCTION["axis_offset_m"]
ZEEMAN_MAGNET_DIMENSIONS_M = tuple(_CONSTRUCTION["magnet_dimensions_m"])
ZEEMAN_MAGNET_POLARIZATION_T = _CONSTRUCTION["magnet_polarization_T"]
ZEEMAN_MAGNETS_PER_RING = _CONSTRUCTION["magnets_per_ring"]
ZEEMAN_TILT_INPUT_SIGN = ZEEMAN_MODEL_CONVENTIONS["zeeman_tilt_input_sign"]
ZEEMAN_INTERNAL_AXIS = ZEEMAN_MODEL_CONVENTIONS["zeeman_internal_axis"]
ZEEMAN_LAB_AXIS_DIRECTION = ZEEMAN_MODEL_CONVENTIONS["zeeman_lab_axis_direction"]


def resolved_zeeman_field_construction(
    *, radii_m, positions_m, tilt_angles_deg, angle_deg, start_distance_m
):
    """Return exact JSON-native construction semantics for the slower field."""
    return {
        "radii_m": [float(value) for value in radii_m],
        "positions_m": [float(value) for value in positions_m],
        "tilt_angles_deg": [float(value) for value in tilt_angles_deg],
        "zeeman_axis_offset_m": ZEEMAN_AXIS_OFFSET_M,
        "magnet_dimensions_m": list(ZEEMAN_MAGNET_DIMENSIONS_M),
        "magnet_polarization_T": ZEEMAN_MAGNET_POLARIZATION_T,
        "arm_angle_deg": float(angle_deg),
        "start_distance_m": float(start_distance_m),
        "magnets_per_ring": ZEEMAN_MAGNETS_PER_RING,
        "azimuthal_angles_deg": [
            float(value)
            for value in np.linspace(ZEEMAN_MODEL_CONVENTIONS["azimuth_start_deg"], ZEEMAN_MODEL_CONVENTIONS["azimuth_stop_deg"], ZEEMAN_MAGNETS_PER_RING, endpoint=ZEEMAN_MODEL_CONVENTIONS["azimuth_endpoint_included"])
        ],
        "tilt_input_sign": ZEEMAN_TILT_INPUT_SIGN,
        "internal_axis": ZEEMAN_INTERNAL_AXIS,
        "lab_axis_direction": ZEEMAN_LAB_AXIS_DIRECTION,
    }

class ZeemanSlowerField(MagneticField):
    """
    A setup for the canonical 19-ring Zeeman slower,
    each with 8 permanent magnets rotated towards or away from the central axis.
    """
    def __init__(
        self,
        zeeman_axis_offset=ZEEMAN_AXIS_OFFSET_M,
        magnet_dimensions=ZEEMAN_MAGNET_DIMENSIONS_M,
        polarization_T=ZEEMAN_MAGNET_POLARIZATION_T,
        angle_deg=25.0,
        start_distance=0.314,
        radii=None,
        positions_z=None,
        tilt_angles=None,
    ):
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

        default_radii = _CANONICAL_PROFILE["radii_m"]
        default_positions_z = _CANONICAL_PROFILE["positions_m"]
        default_tilt_angles = _CANONICAL_PROFILE["tilt_angles_deg"]

        self.radii = list(radii) if radii is not None else list(default_radii)
        self.positions_z = list(positions_z) if positions_z is not None else list(default_positions_z)
        self.tilt_angles = list(tilt_angles) if tilt_angles is not None else list(default_tilt_angles)
        self.tilt_angles = [-angle for angle in self.tilt_angles]

        # The polarization vector magnitude is set initially along the magnet's local Z-axis.
        pol = (0, 0, self.polarization_T)
        dim = self.magnet_dimensions

        magnets = []
        
        # We put 8 magnets per ring
        azimuthal_angles = np.linspace(ZEEMAN_MODEL_CONVENTIONS["azimuth_start_deg"], ZEEMAN_MODEL_CONVENTIONS["azimuth_stop_deg"], ZEEMAN_MAGNETS_PER_RING, endpoint=ZEEMAN_MODEL_CONVENTIONS["azimuth_endpoint_included"])
        
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
        return f"Zeeman Slower Magpylib Field ({len(self.radii)} rings, {len(self.radii) * ZEEMAN_MAGNETS_PER_RING} magnets)"

    def show_magnets(self):
        magpy.show(self.collection, style={'magnetization': {'show': True}})
