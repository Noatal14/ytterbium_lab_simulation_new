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

        N_particles = 10000

        N_vals = [60000, 70000, 80000, 90000]

        for N in N_vals:
            print(f"Running Zeeman phase simulation for N={N}...")
            zeeman_traj, survivors, surv_idx = zeeman_simulation(
                N_particles=N,
                _2d_mot_config={ "s0": 1.5, "detuning_gamma": -1.2 },
                zeeman_config={ "s0": 3.0, "detuning_gamma": -13.75 },
                zeeman_field_config={ "radii": radii, "positions": positions, "tilt_angles": tilt_angles },
                magnet_radius=0.053,
                T_C=400.0,
            )

            save_dir_1 = "find_n_particles/zeeman_phase_survivors"
            save_path_1 = Path(save_dir_1)

            save_file_json(save_path_1 / f"N_{N}_survivors_{datetime.utcnow().isoformat()}.json", survivors)

        save_dir_1 = "find_n_particles/zeeman_phase_survivors"
        save_path_1 = Path(save_dir_1)

        save_file_json(save_path_1 / f"summary_{datetime.utcnow().isoformat()}.json", survivors)

        print(f"Zeeman phase simulation ended")
        
    finally:
        caffeinate_process.terminate()
        print("Caffeinate stopped.")
