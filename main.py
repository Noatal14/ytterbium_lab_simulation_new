import numpy as np
import matplotlib.pyplot as plt

from lab_setup.config_builder import build_base_config
from atomsmltr.simulation.simulator import ScipyIVP_3D

if __name__ == "__main__":
    print("Initializing Default Configuration...")
    atom, config = build_base_config()

