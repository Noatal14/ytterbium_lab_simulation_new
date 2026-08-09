import subprocess

from split_simulation import mot_simulation
from config import zeeman_configs
from pathlib import Path
from datetime import datetime
from utils.file_helpers import read_data_json, read_data_json, save_file_json

if __name__ == "__main__":
    radii, positions, tilt_angles = zeeman_configs["80_2"]

    caffeinate_process = subprocess.Popen(["caffeinate", "-i"])

    try:
        N_results = [
            1000,
            10000,
            50000,
            100000,
        ]

        for N in N_results:
            path = (
                "find_n_particles/"
                "zeeman_survivors/"
                f"N_{N}.json"
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
                seed=N,
                stochastic=True
            )

            print(f"N={N}, Success count: {success_count}")

            save_dir = "find_n_particles/mot_survivors"
            save_path = Path(save_dir)

            save_file_json(save_path / f"N_{N}_survivors_{datetime.utcnow().isoformat()}.json", mot_survivor_states)

        
    finally:
        caffeinate_process.terminate()
        print("Caffeinate stopped.")
