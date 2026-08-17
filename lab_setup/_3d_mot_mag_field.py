import numpy as np
from atomsmltr.environment.fields.magnetic import MagneticField
from config import Geometry

class Ideal3DQuadrupole(MagneticField):
    """
    A standard 3D quadrupole field centered on `origin`.

    The field is:
        B_x = +G * x
        B_y = +G * y
        B_z = -2G * z
    where x, y, z are measured relative to the field zero.
    """

    def __init__(self, origin: np.ndarray, gradient: float, tag: str = None):
        super().__init__(tag=tag)
        self.origin = np.asarray(origin, dtype=float)
        self.gradient = gradient  # Tesla / meter

    def _field_value_func(self, position):
        relative_position = position - self.origin

        B = np.zeros_like(relative_position)
        B[:, 0] = self.gradient * relative_position[:, 0]
        B[:, 1] = self.gradient * relative_position[:, 1]
        B[:, 2] = -2.0 * self.gradient * relative_position[:, 2]

        return B

    def gen_infostring_obj(self):
        return f"Ideal 3D Quadrupole Field (G={self.gradient:.2f} T/m, origin={self.origin})"


def get_builtin_3dmot_magnetic_field(gradient_G_cm=10.0, origin=Geometry.MOT_3D_CENTER):
    """
    Create an ideal 3D MOT quadrupole field centered at `origin`.
    """
    gradient_T_m = gradient_G_cm * 0.01
    return Ideal3DQuadrupole(
        origin=np.asarray(origin, dtype=float),
        gradient=gradient_T_m,
        tag=f"Ideal_3DMOT_Quadrupole_{gradient_G_cm}G/cm",
    )

if __name__ == "__main__":
    print("This module defines the Ideal3DQuadrupole class and the get_builtin_3dmot_magnetic_field function.")
