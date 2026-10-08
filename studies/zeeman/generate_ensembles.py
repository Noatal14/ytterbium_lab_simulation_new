"""Generate canonical production ensembles with the corrected 19-ring slower."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from config import ZEEMAN_MAGNET_PROFILES
from simulations.zeeman import run_and_save_zeeman


PROFILE_NAME = "corrected_projectant_19ring_20261005"
OUTPUT_DIR = Path("data/particle_states/after_zeeman") / PROFILE_NAME
N_INITIAL = 50_000


def corrected_field():
    radii, positions, tilts = ZEEMAN_MAGNET_PROFILES[PROFILE_NAME]
    arrays = [np.asarray(values, dtype=float) for values in (radii, positions, tilts)]
    if [len(values) for values in arrays] != [19, 19, 19]:
        raise ValueError("Corrected Zeeman profile must contain 19 complete rings.")
    if not all(np.all(np.isfinite(values)) for values in arrays):
        raise ValueError("Corrected Zeeman profile contains non-finite values.")
    if np.any(np.diff(arrays[1]) <= 0.0):
        raise ValueError("Corrected Zeeman positions must be strictly increasing.")
    return {"radii_m": radii, "positions_m": positions, "tilt_angles_deg": tilts}


def output_path(seed, output_dir=OUTPUT_DIR):
    return Path(output_dir) / f"production_zeeman_n50000_dt40us_seed{seed}.npy"


def run(seed, npools=200, output_dir=OUTPUT_DIR):
    path = output_path(seed, output_dir)
    metadata = path.with_suffix(".json")
    if path.exists() and metadata.exists():
        print(f"Skipping complete corrected Zeeman ensemble seed {seed}: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    run_and_save_zeeman(
        path,
        N_particles=N_INITIAL,
        seed=seed,
        dt=4e-5,
        npools=npools,
        stochastic=True,
        collimation_angle_deg=1.5,
        zeeman_field_config=corrected_field(),
    )
    return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--npools", type=int, default=200)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    run(args.seed, args.npools, args.output_dir)
