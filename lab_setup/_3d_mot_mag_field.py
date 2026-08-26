import numpy as np
from atomsmltr.environment.fields.magnetic import MagneticField
from config import Geometry

class Ideal3DQuadrupole(MagneticField):
    """
    A standard 3D quadrupole field centered on `origin`.

    Along the selected strong axis the field gradient is -2G; along each of
    the two remaining axes it is +G. Coordinates are measured relative to the
    field zero. The default strong axis remains z for backward compatibility.
    """

    def __init__(
        self,
        origin: np.ndarray,
        gradient: float,
        strong_axis: str = "z",
        tag: str = None,
    ):
        super().__init__(tag=tag)
        self.origin = np.asarray(origin, dtype=float)
        self.gradient = gradient  # Tesla / meter
        if strong_axis not in {"x", "y", "z"}:
            raise ValueError("strong_axis must be one of 'x', 'y', or 'z'.")
        self.strong_axis = strong_axis

    def _field_value_func(self, position):
        relative_position = position - self.origin

        B = np.zeros_like(relative_position)
        B[:] = self.gradient * relative_position
        strong_axis_index = {"x": 0, "y": 1, "z": 2}[self.strong_axis]
        B[:, strong_axis_index] = (
            -2.0 * self.gradient * relative_position[:, strong_axis_index]
        )

        return B

    def gen_infostring_obj(self):
        return f"Ideal 3D Quadrupole Field (G={self.gradient:.2f} T/m, strong_axis={self.strong_axis}, origin={self.origin})"


def get_builtin_3dmot_magnetic_field(
    gradient_G_cm=10.0,
    origin=Geometry.MOT_3D_CENTER_M,
    strong_axis="z",
):
    """
    Create an ideal 3D MOT quadrupole field centered at `origin`.
    """
    gradient_T_m = gradient_G_cm * 0.01
    return Ideal3DQuadrupole(
        origin=np.asarray(origin, dtype=float),
        gradient=gradient_T_m,
        strong_axis=strong_axis,
        tag=f"Ideal_3DMOT_Quadrupole_{gradient_G_cm}G/cm",
    )

if __name__ == "__main__":
    print("This module defines the Ideal3DQuadrupole class and the get_builtin_3dmot_magnetic_field function.")
