import numpy as np
from atomsmltr.environment.fields.magnetic import MagneticField

class Ideal2DQuadrupole(MagneticField):
    """
    A custom analytical 2D Magnetic Quadrupole strictly obeying:
        B_x = +G * (x - x_0)
        B_y = -G * (y - y_0)
        B_z =  0
    """
    def __init__(self, origin: np.ndarray, gradient: float, tag: str = None):
        super().__init__(tag=tag)
        self.origin = origin
        self.gradient = gradient # Tesla / meter

    def _field_value_func(self, position):
        # position is in the local frame (shifted by origin)
        # shape is (N, 3)
        B = np.zeros_like(position)
        B[:, 0] =  self.gradient * position[:, 0] # B_x = +G * x
        B[:, 1] = -self.gradient * position[:, 1] # B_y = -G * y
        # B[:, 2] remains 0.0
        return B
        
    def gen_infostring_obj(self):
        return f"Ideal 2D Quadrupole Field (G={self.gradient:.2f} T/m)"

def get_builtin_2dmot_magnetic_field(gradient_G_cm=50.0):
    """
    Creates an ideal 2D magnetic quadrupole field for a 2DMOT.
    
    The field is constructed such that:
        B_x = +G * x
        B_y = -G * y
        B_z =  0
    where the Z-axis is the free-flight atomic beam axis.
    
    Parameters
    ----------
    gradient_G_cm : float
        The radial magnetic field gradient in Gauss/cm.
        Typical lab values range from 10 to 60 G/cm.
        
    Returns
    -------
    Ideal2DQuadrupole
        A magnetic field object matching atomsmltr APIs.
    """
    # 1 Gauss/cm = 0.01 Tesla/m
    gradient_T_m = gradient_G_cm * 0.01
    
    ideal_2d_mot_field = Ideal2DQuadrupole(
        origin=np.array([0.0, 0.0, 0.0]),
        gradient=gradient_T_m,
        tag=f"Ideal_2DMOT_Quadrupole_{gradient_G_cm}G/cm"
    )
    
    return ideal_2d_mot_field


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
        B = np.zeros_like(position)
        B[:, 0] = self.gradient * position[:, 0]
        B[:, 1] = self.gradient * position[:, 1]
        B[:, 2] = -2.0 * self.gradient * position[:, 2]
        return B

    def gen_infostring_obj(self):
        return f"Ideal 3D Quadrupole Field (G={self.gradient:.2f} T/m, origin={self.origin})"


def get_builtin_3dmot_magnetic_field(gradient_G_cm=10.0, origin=(0.0, 0.0, 0.0)):
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
    import matplotlib.pyplot as plt
    try:
        # Test 1: Check Field Vector Math
        g_val = 50.0 # G/cm
        b_field = get_builtin_2dmot_magnetic_field(gradient_G_cm=g_val)
        print(f"✅ Generated {b_field.tag} successfully.")
        
        # Test point at x=1cm, y=1cm, z=5cm
        # We expect B_x = +50 G/cm * 1cm = 50 G = 0.005 T
        # We expect B_y = -50 G/cm * 1cm = -50 G = -0.005 T
        # We expect B_z = 0 T
        pos = np.array([[0.01, 0.01, 0.05]])
        b_vec_T = b_field.get_value(pos)[0]
        print(f"   -> Magnetic Field at (1cm, 1cm, 5cm):")
        print(f"      B_x = {b_vec_T[0]*10000:.1f} G  (Expected: +{g_val:.1f} G)")
        print(f"      B_y = {b_vec_T[1]*10000:.1f} G  (Expected: -{g_val:.1f} G)")
        print(f"      B_z = {b_vec_T[2]*10000:.1f} G  (Expected: 0.0 G)")

        # Test 2: built-in 2D Mapping Plot
        print("\n✅ Generating 2D visualization of the magnetic field...")
        fig, ax = plt.subplots(figsize=(6, 5))
        # We plot the norm (magnitude) of the field in the XY plane.
        b_field.plot2D(
            limits=(-0.02, 0.02, -0.02, 0.02),
            Npoints=(50, 50),
            plane="XY",
            cut=0.0,
            ax=ax
        )
        ax.set_title(f"Ideal 2D MOT Field Magnitude (|B|) | Gradient: {g_val} G/cm")
        
        # Optional: Add vector quiver overlay to show the quadrupole shape
        u, v = np.meshgrid(np.linspace(-0.02, 0.02, 10), np.linspace(-0.02, 0.02, 10))
        u_flat, v_flat = u.flatten(), v.flatten()
        pos_grid = np.column_stack((u_flat, v_flat, np.zeros_like(u_flat)))
        b_vecs = b_field.get_value(pos_grid)
        bx = b_vecs[:, 0].reshape((10, 10))
        by = b_vecs[:, 1].reshape((10, 10))
        ax.quiver(u, v, bx, by, color='white', alpha=0.8)

        plt.tight_layout()
        plt.savefig("builtin_magfield_test.png")
        print("✅ Saved 'builtin_magfield_test.png' to current directory.")
        
    except Exception as e:
        print(f"❌ Error occurred: {e}")
