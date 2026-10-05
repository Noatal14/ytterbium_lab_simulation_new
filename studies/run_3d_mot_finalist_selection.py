"""Evaluate one 3D-MOT finalist on all 15,840 existing survivors and three seeds."""

import argparse
import json
import os
from pathlib import Path

import numpy as np

from config import MOT_3D_SIM_CONFIG
from simulations.mot_3d import mot_3d_simulation
from studies.compare_3d_mot_retention import DEFAULT_INPUT, analyze_results
from utils.data_paths import load_particle_states


RECOIL_SEEDS = (43001, 43002, 43003)
EXPECTED_PARTICLE_COUNT = 15_840


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(temporary, path)


def load_all_existing_particles(input_dir):
    files = sorted(Path(input_dir).glob("*.npy"))
    if len(files) != 20:
        raise ValueError(f"Expected exactly 20 ensembles, found {len(files)}.")
    states, ensemble_ids, provenance = [], [], []
    for ensemble_id, path in enumerate(files):
        available = np.asarray(load_particle_states(path), dtype=float)
        states.append(available)
        ensemble_ids.extend([ensemble_id] * len(available))
        provenance.append(
            {
                "ensemble_id": ensemble_id,
                "file_index": ensemble_id,
                "file": str(path),
                "particle_count": len(available),
            }
        )
    combined = np.concatenate(states)
    if len(combined) != EXPECTED_PARTICLE_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_PARTICLE_COUNT:,} existing survivors, "
            f"found {len(combined):,}."
        )
    return combined, np.asarray(ensemble_ids), provenance


def run(args):
    selection = json.loads(Path(args.selection).read_text())
    if selection["family"] != args.family:
        raise ValueError("Selection family and requested family disagree.")
    candidates = selection["candidates"]
    if args.finalist_index < 0 or args.finalist_index >= len(candidates):
        raise IndexError("Finalist index is outside the selection.")
    candidate = candidates[args.finalist_index]
    states, ensemble_ids, provenance = load_all_existing_particles(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(output_dir / "particle_selection.json", provenance)
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)

    candidate_id = candidate["candidate_id"]
    for recoil_seed in RECOIL_SEEDS:
        stem = f"{candidate_id}_seed_{recoil_seed}"
        json_path = output_dir / f"{stem}.json"
        npz_path = output_dir / f"{stem}.npz"
        if json_path.exists() and npz_path.exists():
            print(f"Skipping completed {stem}", flush=True)
            continue
        print(f"FINALIST_START {stem}", flush=True)
        trajectories, _ = mot_3d_simulation(
            states,
            _3d_mot_config=candidate["resolved_profile"],
            gravity_enabled=True,
            npools=args.npools,
            dt=args.dt,
            t_max=args.t_max,
            seed=recoil_seed,
        )
        analysis = analyze_results(trajectories, time_points)
        usable_at_end = analysis["eligible_masks"][:, -1]
        usable_ever = np.any(analysis["eligible_masks"], axis=1)
        temporary_npz = output_dir / f".{stem}.{os.getpid()}.npz"
        np.savez_compressed(
            temporary_npz,
            usable_at_end=usable_at_end,
            usable_ever=usable_ever,
            ensemble_ids=ensemble_ids,
        )
        os.replace(temporary_npz, npz_path)
        diagnostics = analysis["diagnostics"]
        result = {
            "kind": "mot_3d_finalist_seed_result",
            "family": args.family,
            "candidate_id": candidate_id,
            "finalist_index": args.finalist_index,
            "recoil_seed": recoil_seed,
            "input_particle_count": len(states),
            "usable_at_end_count": int(usable_at_end.sum()),
            "usable_ever_count": int(usable_ever.sum()),
            "peak_usable_count": int(analysis["peak_count"]),
            "entered_capture_region_count": int(diagnostics["entered_capture_region_count"]),
            "slow_inside_count": int(diagnostics["slow_inside_count"]),
            "outcomes_path": str(npz_path),
        }
        _atomic_json(json_path, result)
        print(
            f"FINALIST_RESULT {stem} "
            f"usable={result['usable_at_end_count']}/{len(states)}",
            flush=True,
        )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("angled_donut", "single_pass"), required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--finalist-index", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--npools", type=int, default=200)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=0.1)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
