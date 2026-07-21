"""
dt_2dmot_data_simulation.py

Run stochastic RK4St simulations for atoms starting at the entrance of the 2D MOT,
for several dt values, and save the data without making plots.

This is a simplified replacement for the old dt_comparison.py script:
- no Zeeman slower laser/field
- no full-apparatus zone
- no plotting
- no convergence plotting
- starts at the 2D MOT entrance with initial speed ~35 m/s
- saves raw trajectories + compact summary data
"""
import numpy as np
import subprocess
import multiprocessing as mp
from datetime import datetime
from functools import partial
from pathlib import Path
from atomsmltr.simulation.simulator import ScipyIVP_3D
from dt_comparison.RK4StCustomDt import RK4StCustomDt
from dt_comparison.simulations.parse_simulation_result import parse_results
from lab_setup.config_builder import build_2dmot_config
from utils.file_helpers import save_file_json
from utils.simulation_helpers import entry_initial_condition, run_simulation, generate_timepoints

def sim(
    dt_values=[],
    n_seeds=5000,
    t_max=3.0e-3,  # 3 ms is plenty of time for 2D MOT chamber exit
    s0=1.4,
    detuning_gamma=-1.47,
    magnet_radius=0.055,
    u0=[0, 0, 0, 0, 0, 0],
    npools=8,
    save_dir="2dmot_dt_data",
):
    """
    Run RK4St for several dt values and save the results.
    Optimized to restrict simulation to the 2D MOT chamber only.

    Saved files:
    - summary.json: full structured summary with compact result arrays and metadata
    - parameters.json: run settings used for the sweep
    - dt_<value>.npz: raw trajectory data
    """

    save_path = Path(save_dir)
    save_path.mkdir(parents=True, exist_ok=True)

    atom, config = build_2dmot_config(
        s0=s0,
        detuning_gamma=detuning_gamma,
        magnet_radius=magnet_radius,
    )

    print("--- 2D MOT dt scan (Restricted Chamber Simulation) ---")
    print(f"Initial position: {u0[:3]}")
    print(f"Initial velocity: {u0[3:]}")
    print(f"dt values: {dt_values}")
    print(f"seeds per dt: {n_seeds}")
    print(f"save dir: {save_path.resolve()}\n")

    summary_rows = []

    for dt in dt_values:
        print(f"Running dt = {dt:.2e} s")
        time_points, n_timepoints = generate_timepoints(t_max, dt)

        _, deterministic_y, det_sim = run_simulation(config=config, u0=u0, time_points=time_points, sim_function=ScipyIVP_3D)

        worker = partial(
            run_simulation,
            config=config,
            u0=[u0],
            time_points=time_points,
            sim_function=RK4StCustomDt,
        )

        if npools > 1:
            with mp.Pool(npools) as pool:
                seed_results = pool.map(worker, range(n_seeds))
        else:
            seed_results = [worker(seed_idx) for seed_idx in range(n_seeds)]

        row = parse_results(seed_results, deterministic_y, dt)
        summary_rows.append(row)
    
    run_metadata = {
        "u0": list(u0),
        "magnet_radius": magnet_radius,
        "detuning_gamma": detuning_gamma,
        "s0": s0,
        "n_seeds": n_seeds,
        "t_max": t_max,
        "dt_values": dt_values,
        "npools": npools,
        "save_dir": str(save_path),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    summary_json = {
        "run_metadata": run_metadata,
        "summary_rows": summary_rows,
    }

    save_file_json(save_path / f"summary_{datetime.utcnow().isoformat()}.json", summary_json)

    return summary_rows

if __name__ == "__main__":
    # macOS only: prevents sleep while the script is running.
    caffeinate_process = subprocess.Popen(["caffeinate", "-i"])

    real = True

    r0, v0 = entry_initial_condition(v0=35, r0=0.02)
    u0 = np.concatenate((r0, v0))
    
    params = {
        "t_max": 3.0e-3,
        "s0": 1.5,
        "detuning_gamma": -1.2,
        "magnet_radius": 0.055,
        "u0": list(u0),
        "npools": 8,
        "save_dir": "dt_comparison/data",
    }

    try:
        if (real):
            sim(
                dt_values=[9e-6, 8e-6, 7e-6, 6e-6],
                n_seeds=5000,
                **params
            )
        else:
            sim(
                dt_values=[1e-4, 9e-5],
                n_seeds=10,
                **params
            )
        
    finally:
        caffeinate_process.terminate()
        print("Caffeinate stopped.")

