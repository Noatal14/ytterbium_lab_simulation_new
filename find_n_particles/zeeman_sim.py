import argparse
import subprocess

from split_simulation import zeeman_simulation
from config import zeeman_configs
from pathlib import Path
from datetime import datetime
from utils.file_helpers import save_file_json

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dt",
        type=float,
        required=True,
        help="Zeeman simulation timestep in seconds",
    )

    parser.add_argument(
        "--npools",
        type=int,
        default=8,
        help="Number of worker processes",
    )

    parser.add_argument(
        "--n-values",
        type=int,
        nargs="+",
        default=[1000, 10000, 50000, 100000],
        help="List of particle counts",
    )

    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    dt = args.dt
    npools = args.npools
    N_vals = args.n_values

    radii, positions, tilt_angles = zeeman_configs["80_2"]

    print(f"Running Zeeman simulations with dt={dt:.2e}")

    for N in N_vals:
        print(f"Running Zeeman phase simulation for N={N}...")
        zeeman_traj, survivors, surv_idx = zeeman_simulation(
            N_particles=N,
            _2d_mot_config={ "s0": 1.4, "detuning_gamma": -1.47 },
            zeeman_config={ "s0": 3.0, "detuning_gamma": -13.75 },
            zeeman_field_config={ "radii": radii, "positions": positions, "tilt_angles": tilt_angles },
            magnet_radius=0.053,
            T_C=400.0,
            seed=42,
            npools=npools,
            stochastic=True,
            dt=dt
        )

        save_dir = Path(f"find_n_particles/zeeman_survivors_dt_{dt:.1e}")
        save_dir.mkdir(parents=True, exist_ok=True)

        save_file_json(save_dir / f"N_{N}_survivors.json", survivors)

    print(f"Zeeman phase simulation ended")
