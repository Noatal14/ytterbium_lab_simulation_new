import argparse
import subprocess

from split_simulation import mot_simulation
from config import zeeman_configs
from pathlib import Path
from datetime import datetime
from utils.file_helpers import read_data_json, read_data_json, save_file_json

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

    for N in N_vals:
        path = (
            "find_n_particles/"
            f"zeeman_survivors_dt_{dt:.1e}/"
            f"N_{N}_survivors.json"
        )

        survivors = read_data_json(path)

        print(
            f"Loaded {len(survivors)} survivors "
            f"from simulation with N={N}"
        )

        print(f"Running MOT phase simulation for N={N}...")

        _, success_count, mot_survivor_states = mot_simulation(
            survivor_states=survivors,
            _2d_mot_config={ "s0": 1.4, "detuning_gamma": -1.47 },
            magnet_radius=0.053,
            seed=42,
            npools=npools,
            stochastic=True,
            dt=dt
        )

        print(f"N={N}, Success count: {success_count}")

        save_dir = "find_n_particles/mot_survivors"
        save_path = Path(save_dir)

        save_file_json(save_path / f"N_{N}_survivors_{datetime.utcnow().isoformat()}.json", mot_survivor_states)
