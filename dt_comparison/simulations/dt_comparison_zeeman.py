"""Run a Zeeman-only dt convergence scan analogous to the 2D MOT dt script."""

import multiprocessing as mp
import subprocess
from datetime import datetime
from functools import partial
from pathlib import Path
import numpy as np
from atomsmltr.simulation.simulator import ScipyIVP_3D
from config import Geometry, zeeman_sim_config, zeeman_configs
from dt_comparison.RK4StCustomDt import RK4StCustomDt
from dt_comparison.simulations.parse_simulation_result import parse_results, is_transmitted_zeeman
from lab_setup.config_builder import build_zeeman_config
from utils.file_helpers import save_file_json
from utils.simulation_helpers import generate_timepoints, entry_initial_condition, run_simulation


def build_zeeman_initial_condition(v0=250.0, r0=zeeman_sim_config["start_distance"], angle_deg=Geometry.ZEEMAN_ARM_ANGLE_DEG, pos_offset=(0.0, 0.0, 0.0)):
    """Build an initial condition aligned with the Zeeman-arm geometry."""
    r_vec, v_vec = entry_initial_condition(v0=v0, r0=r0, angle_deg=angle_deg, pos_offset=pos_offset)
    return np.concatenate((r_vec, v_vec)).astype(float)


def sim(
    dt_values=(1e-4, 5e-5, 2e-5, 1e-5, 5e-6),
    n_seeds=5000,
    t_max=2.0e-2,
    s0_zeeman=3.0,
    detuning_gamma_zeeman=-13.75,
    npools=8,
    save_dir="dt_comparison/data",
    cutoff_distance=0.100,
    pos_offs=0,
    _v0=250,
):
    """Run a Zeeman-only dt scan and save deterministic/stochastic summary data."""
    u0 = build_zeeman_initial_condition(
        v0=_v0, 
        r0=zeeman_sim_config["start_distance"], 
        angle_deg=Geometry.ZEEMAN_ARM_ANGLE_DEG,
        pos_offset=(pos_offs, 0.0, 0.0)
    )

    save_path = Path(save_dir)
    save_path.mkdir(parents=True, exist_ok=True)

    radii, positions, tilt_angles = zeeman_configs["80_2"]

    _, config = build_zeeman_config(
        s0_zeeman=s0_zeeman,
        detuning_gamma_zeeman=detuning_gamma_zeeman,
        gravity_enabled=False,
        radii=radii,
        positions=positions,
        tilt_angles=tilt_angles,
    )

    print("--- Zeeman dt scan (Zeeman-only simulation) ---")
    print(f"Initial position: {u0[:3]}")
    print(f"Initial velocity: {u0[3:]}")
    print(f"dt values: {dt_values}")
    print(f"seeds per dt: {n_seeds}")
    print(f"save dir: {save_path.resolve()}\n")

    summary_rows = []

    for dt in dt_values:
        print(f"Running dt = {dt:.2e} s")
        time_points, _ = generate_timepoints(t_max, dt)

        _, deterministic_y, _ = run_simulation(
            config=config,
            u0=[u0],
            time_points=time_points,
            sim_function=ScipyIVP_3D,
        )

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

        row = parse_results(
            seed_results,
            deterministic_y,
            dt,
            is_transmitted_fn=lambda final_pos, trajectory: is_transmitted_zeeman(
                final_pos,
                trajectory=trajectory,
                cutoff_distance=cutoff_distance,
            ),
        )
        summary_rows.append(row)

    run_metadata = {
        "u0": list(u0),
        "s0_zeeman": s0_zeeman,
        "detuning_gamma_zeeman": detuning_gamma_zeeman,
        "n_seeds": n_seeds,
        "t_max": t_max,
        "dt_values": list(dt_values),
        "npools": npools,
        "cutoff_distance": cutoff_distance,
        "save_dir": str(save_path),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    summary_payload = {"run_metadata": run_metadata, "summary_rows": summary_rows}
    save_file_json(save_path / f"summary_{datetime.utcnow().isoformat()}.json", summary_payload)
    return summary_rows


if __name__ == "__main__":
    caffeinate_process = subprocess.Popen(["caffeinate", "-i"])
    try:
        sim(
            dt_values=[9e-5, 8e-5, 7e-5, 6e-5, 4e-5, 3e-5, 9e-6, 8e-6],
            n_seeds=5000,
            npools=8,
            save_dir="dt_comparison/data",
            pos_offs=0,
            _v0=250,
        )
    finally:
        caffeinate_process.terminate()
        print("Caffeinate stopped.")
