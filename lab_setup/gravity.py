import numpy as np
from scipy.constants import g
from atomsmltr.environment import ConstantForce

def get_gravity_force(atom_mass, enabled=True):
    """
    Creates a constant force environment object representing gravity.
    For this 2DMOT setup, the YZ plane is parallel to the ground,
    so gravity acts along the -X axis.

    Parameters:
    -----------
    atom_mass : float
        The mass of the atom in kg.
    enabled : bool
        If True, returns the actual gravitational force object.
        If False, returns a zero-force object (useful for toggling without breaking config).

    Returns:
    --------
    atomsmltr.environment.ConstantForce
        The gravity force object to be added to the simulation environment.
    """
    if enabled:
        # F = m * g; downward is -X axis
        f_vec = np.array([-atom_mass * g, 0.0, 0.0])
        tag = "Gravity"
    else:
        # Zero force if gravity is disabled
        f_vec = np.array([0.0, 0.0, 0.0])
        tag = "Gravity (Disabled)"
        
    return ConstantForce(field_value=f_vec, tag=tag)
