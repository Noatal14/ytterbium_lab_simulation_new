import numpy as np
from atomsmltr.environment.zones.generic import Zone

class FiniteCylinder(Zone):
    """
    A cylinder zone with a finite length.
    """
    def __init__(
        self,
        origin=(0, 0, 0),
        direction=(1, 0, 0),
        radius=1.0,
        length=1.0,
        target="position",
        action="ignore",
        tag=None,
        in_tag=None,
        out_tag=None,
    ):
        super().__init__(
            target=target,
            action=action,
            tag=tag,
            in_tag=in_tag,
            out_tag=out_tag,
        )
        self.origin = np.array(origin, dtype=float)
        self.direction = np.array(direction, dtype=float)
        # Normalize direction
        norm = np.linalg.norm(self.direction)
        if norm > 0:
            self.direction = self.direction / norm
        self.radius = float(radius)
        self.length = float(length)

    def _in_zone(self, position):
        """
        Evaluates whether a position is inside the finite cylinder.
        """
        pos = np.array(position)
        dr = pos - self.origin
        
        # Distance along the axis
        z_cyl = np.sum(dr * self.direction, axis=-1)
        
        # Check longitudinal bounds (assumes origin is the start of the cylinder, so z_cyl between 0 and length)
        # Wait, the prompt says for MOT chamber: "centered around Z... 20mm in -Z and 20mm in +Z". 
        # So we should define if origin is center or start. Let's make it start, and we can shift the MOT chamber origin by -20mm.
        # Actually, let's allow `origin_is_center` as a parameter, or just strictly use origin as the base, 
        # but for MOT chamber it's explicitly centered at origin.
        # Let's say z_cyl must be between 0 and length.
        in_length = (z_cyl >= 0) & (z_cyl <= self.length)

        # Distance perpendicular to the axis
        # dr_perp = dr - z_cyl * direction
        # But z_cyl could be an array. We need to do this carefully for broadcasting.
        dr_axial = z_cyl[..., np.newaxis] * self.direction
        dr_rad = dr - dr_axial
        r_cyl = np.linalg.norm(dr_rad, axis=-1)
        
        in_radius = r_cyl <= self.radius
        
        return in_length & in_radius

    @property
    def type(self):
        return "finite cylinder"

    def gen_infostring_obj(self):
        from atomsmltr.utils.infostring import InfoString
        info = InfoString("Finite Cylinder")
        info.add_property("type", self.type)
        info.add_property("tag", self.tag)
        info.add_property("target", self.target)
        info.add_property("action", self.action)
        info.add_property("origin", self.origin)
        info.add_property("direction", self.direction)
        info.add_property("radius", self.radius)
        info.add_property("length", self.length)
        return info

    def plot1D(self, *args, **kwargs):
        pass

    def plot2D(self, *args, **kwargs):
        pass

    def plot3D(self, *args, **kwargs):
        pass

class OutOfBoundsZone(Zone):
    """
    A zone that is the logical inverse of a given ZoneCollection.
    If the atom is NOT in the reference collection, it is considered inside this OutOfBoundsZone.
    Useful for stopping the simulation when atoms leave the apparatus.
    """
    def __init__(self, reference_zone, target="position", action="stop", tag="OutOfBounds"):
        super().__init__(target=target, action=action, tag=tag)
        self.reference_zone = reference_zone

    def _in_zone(self, position):
        # returns True if position is OUTSIDE the reference zone
        return ~self.reference_zone.get_value(position)

    @property
    def type(self):
        return "out of bounds inverted zone"

    def gen_infostring_obj(self):
        from atomsmltr.utils.infostring import InfoString
        info = InfoString("Out Of Bounds Zone")
        info.add_property("type", self.type)
        info.add_property("tag", self.tag)
        info.add_property("target", self.target)
        info.add_property("action", self.action)
        return info

    def plot1D(self, *args, **kwargs): pass
    def plot2D(self, *args, **kwargs): pass
    def plot3D(self, *args, **kwargs): pass



def get_apparatus_internal_volume():
    """
    Creates the 'apparatus internal volume' zone collection consisting of 5 finite cylinders.
    """
    # 1. MOT_Chamber: Centered at origin along Z axis. Length 40mm, Radius 15mm.
    # To center it at origin of Z, we start it at Z = -20mm (-0.02m)
    mot_chamber = FiniteCylinder(
        origin=(0, 0, -0.02),
        direction=(0, 0, 1),
        radius=0.015,
        length=0.04,
        tag="MOT_chamber"
    )

    # 2. Zeeman_Arm_1: Starts from origin, in ZY plane, 25 degree angle with -Z axis.
    # Length 378mm, Radius 8mm.
    # Convention: Atom beam enters from the 3rd quadrant (-Y, -Z) of the ZY plane.
    # Direction points FROM origin TOWARD the atom source (into -Y, -Z).
    angle_rad = np.radians(25)
    dir_z1 = np.array([0, -np.sin(angle_rad), -np.cos(angle_rad)])
    L1 = 0.378
    z1 = FiniteCylinder(
        origin=(0, 0, 0),
        direction=dir_z1,
        radius=0.008,
        length=L1,
        tag="Zeeman_Arm_1"
    )

    # 3. Zeeman_Arm_2: Collinear with last one, starts at the end of Arm 1. Length 23.7mm, radius 3.5mm
    end_z1 = dir_z1 * L1
    L2 = 0.0237
    z2 = FiniteCylinder(
        origin=end_z1,
        direction=dir_z1,
        radius=0.0035,
        length=L2,
        tag="Zeeman_Arm_2"
    )

    # 4. Zeeman_Arm_3: Collinear with last one, starts at the end of Arm 2. Length 60mm, radius 17.4mm.
    end_z2 = end_z1 + dir_z1 * L2
    z3 = FiniteCylinder(
        origin=end_z2,
        direction=dir_z1,
        radius=0.0174,
        length=0.060,
        tag="Zeeman_Arm_3"
    )

    # 5. Science_Arm_Part1: Length 144.5mm, radius 8mm.
    len_part1 = 0.1445
    science_arm_part1 = FiniteCylinder(
        origin=(0, 0, 0),
        direction=(0, 0, 1),
        radius=0.008,
        length=len_part1,
        tag="Science_Arm_Part1"
    )

    # 6. Science_Arm_DPS: Cylinder radius 1.5mm, length 7cm.
    len_dps = 0.070
    science_arm_dps = FiniteCylinder(
        origin=(0, 0, len_part1),
        direction=(0, 0, 1),
        radius=0.0015,
        length=len_dps,
        tag="Science_Arm_DPS"
    )
    
    # 7. Science_Arm_Part3: Original radius 8mm, reaching to 510mm from origin.
    len_part3 = 0.510 - (len_part1 + len_dps)
    science_arm_part3 = FiniteCylinder(
        origin=(0, 0, len_part1 + len_dps),
        direction=(0, 0, 1),
        radius=0.008,
        length=len_part3,
        tag="Science_Arm_Part3"
    )

    # Combine them using the OR logic (|)
    # The atom is in the 'apparatus internal volume' if it is in *any* of these cylinders.
    apparatus_internal_volume = mot_chamber | z1 | z2 | z3 | science_arm_part1 | science_arm_dps | science_arm_part3
    apparatus_internal_volume.tag = "apparatus_internal_volume"
    
    return apparatus_internal_volume


def get_2dmot_testing_zone():
    """
    Creates the '2D MOT testing zone' configuration.
    This includes the MOT chamber, Zeeman Arm 1 (shortened to 10cm), and the Science Arm.
    """
    # 1. MOT_Chamber: Centered at origin along Z axis. Length 40mm, Radius 15mm.
    mot_chamber = FiniteCylinder(
        origin=(0, 0, -0.02),
        direction=(0, 0, 1),
        radius=0.015,
        length=0.04,
        tag="MOT_chamber"
    )

    # 2. Zeeman_Arm_1 (shortened): Starts from origin, in ZY plane, 25 degree angle with -Z axis.
    # Convention: 3rd quadrant (-Y, -Z).
    # Length 100mm (10cm), Radius 8mm.
    angle_rad = np.radians(25)
    dir_z1 = np.array([0, -np.sin(angle_rad), -np.cos(angle_rad)])
    z1_short = FiniteCylinder(
        origin=(0, 0, 0),
        direction=dir_z1,
        radius=0.008,
        length=0.10,  # 10 cm
        tag="Zeeman_Arm_1_short"
    )

    # 5. Science_Arm: Collinear with Positive Z axis, starts at origin, length 510mm, radius 8mm.
    science_arm = FiniteCylinder(
        origin=(0, 0, 0),
        direction=(0, 0, 1),
        radius=0.008,
        length=0.510,
        tag="Science_Arm"
    )

    # Combine them using the OR logic (|)
    testing_zone = mot_chamber | z1_short | science_arm
    testing_zone.tag = "2dmot_testing_zone"
    
    return testing_zone

def get_dps_testing_zone():
    """
    Creates the '2D MOT testing zone with DPS' configuration.
    """
    # 1. MOT_Chamber: Centered at origin along Z axis. Length 40mm, Radius 15mm.
    mot_chamber = FiniteCylinder(
        origin=(0, 0, -0.02),
        direction=(0, 0, 1),
        radius=0.015,
        length=0.04,
        tag="MOT_chamber"
    )

    # 2. Zeeman_Arm_1 (extended to encompass source): 
    # Starts from origin, in ZY plane, 25 degree angle with -Z axis.
    # Source generates atoms at dist=10cm. We make it 12cm long so they start inside.
    angle_rad = np.radians(25)
    dir_z1 = np.array([0, -np.sin(angle_rad), -np.cos(angle_rad)])
    z1_short = FiniteCylinder(
        origin=(0, 0, 0),
        direction=dir_z1,
        radius=0.008,
        length=0.12,  # 12 cm to comfortably contain distance=10cm atoms
        tag="Zeeman_Arm_1_short"
    )

    # 3. Science_Arm_Part1: Length 144.5mm, radius 8mm.
    len_part1 = 0.1445
    science_arm_part1 = FiniteCylinder(
        origin=(0, 0, 0),
        direction=(0, 0, 1),
        radius=0.008,
        length=len_part1,
        tag="Science_Arm_Part1"
    )
    
    # 4. Science_Arm_DPS: Cylinder radius 1.5mm, length 7cm.
    len_dps = 0.070
    science_arm_dps = FiniteCylinder(
        origin=(0, 0, len_part1),
        direction=(0, 0, 1),
        radius=0.0015,
        length=len_dps,
        tag="Science_Arm_DPS"
    )
    
    # 5. Science_Arm_Part3: Original radius 8mm, reaching to 510mm from origin.
    len_part3 = 0.510 - (len_part1 + len_dps)
    science_arm_part3 = FiniteCylinder(
        origin=(0, 0, len_part1 + len_dps),
        direction=(0, 0, 1),
        radius=0.008,
        length=len_part3,
        tag="Science_Arm_Part3"
    )

    # Combine them using the OR logic (|)
    dps_testing_zone = mot_chamber | z1_short | science_arm_part1 | science_arm_dps | science_arm_part3
    dps_testing_zone.tag = "2dmot_testing_zone_dps"
    
    return dps_testing_zone

def get_bounded_dps_testing_zone():
    """
    Returns a LIST containing the 2D MOT testing zone with DPS,
    PLUS an 'OutOfBoundsZone' that stops the simulation if the atom leaves the chamber.
    Returning a list ensures the config registers both objects independently.
    """
    dps_testing_zone = get_dps_testing_zone()
    dps_testing_zone.action = "ignore"  # Ensure it is not considered a stop zone itself
    out_of_bounds = OutOfBoundsZone(dps_testing_zone, action="stop", tag="Chamber_Boundary")
    return [dps_testing_zone, out_of_bounds]

def get_entire_apparatus_zone():
    """
    Returns a LIST containing the full 2D MOT apparatus internal volume,
    PLUS an 'OutOfBoundsZone' that stops the simulation if the atom leaves the chamber.
    """
    apparatus = get_apparatus_internal_volume()
    apparatus.action = "ignore"
    out_of_bounds = OutOfBoundsZone(apparatus, action="stop", tag="Entire_Chamber_Boundary")
    return [apparatus, out_of_bounds]
