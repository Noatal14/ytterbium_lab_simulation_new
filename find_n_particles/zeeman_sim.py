import subprocess

from split_simulation import zeeman_simulation
from config import zeeman_configs
from pathlib import Path
from datetime import datetime
from utils.file_helpers import save_file_json

if __name__ == "__main__":
    radii, positions, tilt_angles = zeeman_configs["80_2"]

    caffeinate_process = subprocess.Popen(["caffeinate", "-i"])

    try:
        print("Running Zeeman phase simulation...")

        N_vals = [1000, 10000, 50000, 100000]

        for N in N_vals:
            print(f"Running Zeeman phase simulation for N={N}...")
            zeeman_traj, survivors, surv_idx = zeeman_simulation(
                N_particles=N,
                _2d_mot_config={ "s0": 1.4, "detuning_gamma": -1.47 },
                zeeman_config={ "s0": 3.0, "detuning_gamma": -13.75 },
                zeeman_field_config={ "radii": radii, "positions": positions, "tilt_angles": tilt_angles },
                magnet_radius=0.053,
                T_C=400.0,
                seed=N,
                stochastic=True
            )

            save_dir = "find_n_particles/zeeman_survivors"
            save_path = Path(save_dir)

            save_file_json(save_path / f"N_{N}_survivors_{datetime.utcnow().isoformat()}.json", survivors)

        print(f"Zeeman phase simulation ended")
        
    finally:
        caffeinate_process.terminate()
        print("Caffeinate stopped.")
