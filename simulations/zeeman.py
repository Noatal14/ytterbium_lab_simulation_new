"""Run the Zeeman-slower stage from a generated thermal beam."""

import argparse
import hashlib
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import atomsmltr

from config import (
    ACTIVE_ZEEMAN_MAGNET_PROFILE,
    COLLIMATION_ANGLE_DEG,
    DEFAULT_NUM_PARTICLES,
    DEFAULT_NUM_POOLS,
    DEFAULT_RANDOM_SEED,
    MOT_2D_LASER_CONFIG,
    MOT_2D_MAGNET_RADIUS_M,
    ZEEMAN_FIELD_CONFIG,
    ZEEMAN_LASER_CONFIG,
    ZEEMAN_SIM_CONFIG,
)
from lab_setup.config_builder import build_base_config
from lab_setup.zones import get_zeeman_only_zone
from simulations.thermal_beam import generate_thermal_beam_state
from utils.RK4StCustom import RK4StCustom
from utils.ScipyIVP_3DCustom import ScipyIVP_3DCustom
from utils.data_paths import DEFAULT_ZEEMAN_STATES_FILE, save_particle_states
from utils.file_helpers import save_file_json
from utils.simulation_helpers import (
    generate_timepoints,
    run_multiple_atoms_simulation,
    zeeman_extract_survivors,
)


def zeeman_simulation(
    N_particles=DEFAULT_NUM_PARTICLES,
    _2d_mot_config=MOT_2D_LASER_CONFIG,
    zeeman_config=ZEEMAN_LASER_CONFIG,
    zeeman_field_config=ZEEMAN_FIELD_CONFIG,
    magnet_radius=MOT_2D_MAGNET_RADIUS_M,
    gravity_enabled=True,
    npools=DEFAULT_NUM_POOLS,
    stochastic=True,
    dt=ZEEMAN_SIM_CONFIG["dt_s"],
    collimation_angle_deg=COLLIMATION_ANGLE_DEG,
    angular_broadening_factor=1.0,
    seed=DEFAULT_RANDOM_SEED,
):
    """Generate a thermal beam and return the states that survive Zeeman."""
    atom, simulation_config = build_base_config(
        atom_species="Yb171",
        gravity_enabled=gravity_enabled,
        include_2d_mot=True,
        include_3dmot=False,
        include_zeeman=True,
        magnet_radius=magnet_radius,
        zeeman_field_config=zeeman_field_config,
        _2d_mot_config=_2d_mot_config,
        zeeman_config=zeeman_config,
        zones=get_zeeman_only_zone(
            cutoff_distance=ZEEMAN_SIM_CONFIG["cutoff_distance_m"]
        ),
    )
    r0_arr, v0_arr, _ = generate_thermal_beam_state(
        N=N_particles,
        collimation_angle_deg=collimation_angle_deg,
        angular_broadening_factor=angular_broadening_factor,
        m=atom.mass,
        distance_m=ZEEMAN_SIM_CONFIG["start_distance_m"],
        seed=seed,
    )
    time_points, _ = generate_timepoints(ZEEMAN_SIM_CONFIG["t_max_s"], dt)
    initial_states = [
        np.concatenate((position, velocity))
        for position, velocity in zip(r0_arr, v0_arr)
    ]
    simulation_function = RK4StCustom if stochastic else ScipyIVP_3DCustom
    results, _ = run_multiple_atoms_simulation(
        config=simulation_config,
        u0=initial_states,
        time_points=time_points,
        sim_function=simulation_function,
        npools=npools,
        seed_idx=seed,
    )
    survivor_states, survivor_indices = zeeman_extract_survivors(
        results, ZEEMAN_SIM_CONFIG["cutoff_distance_m"]
    )
    return results, survivor_states, survivor_indices


def _git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _tracked_worktree_is_dirty():
    try:
        return subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode != 0
    except OSError:
        return None


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved_run_parameters(simulation_kwargs):
    collimation_angle_deg = simulation_kwargs.get(
        "collimation_angle_deg", COLLIMATION_ANGLE_DEG
    )
    return {
        "n_initial_atoms": int(
            simulation_kwargs.get("N_particles", DEFAULT_NUM_PARTICLES)
        ),
        "seed": int(simulation_kwargs.get("seed", DEFAULT_RANDOM_SEED)),
        "dt_s": float(simulation_kwargs.get("dt", ZEEMAN_SIM_CONFIG["dt_s"])),
        "npools": int(simulation_kwargs.get("npools", DEFAULT_NUM_POOLS)),
        "stochastic": bool(simulation_kwargs.get("stochastic", True)),
        "gravity_enabled": bool(simulation_kwargs.get("gravity_enabled", True)),
        "collimation_angle_deg": (
            None
            if collimation_angle_deg is None
            else float(collimation_angle_deg)
        ),
        "full_angular_distribution": collimation_angle_deg is None,
        "angular_broadening_factor": float(
            simulation_kwargs.get("angular_broadening_factor", 1.0)
        ),
        "magnet_radius_m": float(
            simulation_kwargs.get("magnet_radius", MOT_2D_MAGNET_RADIUS_M)
        ),
        "zeeman_laser_config": simulation_kwargs.get(
            "zeeman_config", ZEEMAN_LASER_CONFIG
        ),
        "zeeman_field_config": simulation_kwargs.get(
            "zeeman_field_config", ZEEMAN_FIELD_CONFIG
        ),
        "mot_2d_laser_config": simulation_kwargs.get(
            "_2d_mot_config", MOT_2D_LASER_CONFIG
        ),
        "zeeman_sim_config": ZEEMAN_SIM_CONFIG,
        "active_zeeman_magnet_profile": ACTIVE_ZEEMAN_MAGNET_PROFILE,
    }


def write_zeeman_metadata(output_path, survivors, simulation_kwargs, elapsed_seconds):
    """Write provenance metadata adjacent to a reusable survivor ensemble."""
    output_path = Path(output_path)
    parameters = _resolved_run_parameters(simulation_kwargs)
    n_initial = parameters["n_initial_atoms"]
    metadata = {
        "kind": "zeeman_survivor_ensemble",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "output_file": output_path.name,
        "output_sha256": _sha256(output_path),
        "state_layout": ["x_m", "y_m", "z_m", "vx_m_s", "vy_m_s", "vz_m_s"],
        "shape": list(np.asarray(survivors).shape),
        "dtype": str(np.asarray(survivors).dtype),
        "n_survivors": int(len(survivors)),
        "survival_fraction": float(len(survivors) / n_initial),
        "elapsed_seconds": float(elapsed_seconds),
        "parameters": parameters,
        "software": {
            "git_commit": _git_commit(),
            "tracked_worktree_was_dirty": _tracked_worktree_is_dirty(),
            "python_version": platform.python_version(),
            "atomsmltr_version": getattr(atomsmltr, "__version__", None),
            "numpy_version": np.__version__,
            "host": platform.node(),
        },
    }
    metadata_path = output_path.with_suffix(".json")
    save_file_json(metadata_path, metadata)
    return metadata_path


def run_and_save_zeeman(output_file, **simulation_kwargs):
    """Run Zeeman and save reusable survivors with adjacent provenance metadata."""
    started = time.time()
    _, survivors, _ = zeeman_simulation(**simulation_kwargs)
    output_path = save_particle_states(output_file, survivors)
    elapsed_seconds = time.time() - started
    metadata_path = write_zeeman_metadata(
        output_path, survivors, simulation_kwargs, elapsed_seconds
    )
    print(f"Zeeman survivors: {len(survivors)}")
    print(f"Saved states to: {output_path}")
    print(f"Saved metadata to: {metadata_path}")
    return np.asarray(survivors)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n_atoms", type=int, default=DEFAULT_NUM_PARTICLES)
    parser.add_argument("--output", default=str(DEFAULT_ZEEMAN_STATES_FILE))
    parser.add_argument("--cutoff_angle_deg", type=float, default=COLLIMATION_ANGLE_DEG)
    parser.add_argument(
        "--full-angular-distribution",
        action="store_true",
        help=(
            "Sample the complete forward microtube distribution and let the "
            "apparatus geometry determine acceptance. Overrides --cutoff_angle_deg."
        ),
    )
    parser.add_argument("--angular-broadening-factor", type=float, default=1.0)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--stochastic", type=int, choices=[0, 1], default=1)
    parser.add_argument("--dt", type=float, default=ZEEMAN_SIM_CONFIG["dt_s"])
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_and_save_zeeman(
        args.output,
        N_particles=args.n_atoms,
        collimation_angle_deg=(
            None if args.full_angular_distribution else args.cutoff_angle_deg
        ),
        angular_broadening_factor=args.angular_broadening_factor,
        npools=args.npools,
        stochastic=bool(args.stochastic),
        dt=args.dt,
        seed=args.seed,
    )
