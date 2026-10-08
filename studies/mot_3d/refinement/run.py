"""Evaluate 3D-MOT refinement candidates on 3,000 particles and three seeds."""

import argparse
import json
import os
from pathlib import Path

import numpy as np

from config import DEFAULT_RANDOM_SEED, MOT_3D_SIM_CONFIG
from simulations.mot_3d import mot_3d_simulation
from studies.mot_3d.analysis.retention import analyze_results
from studies.mot_3d_campaign import load_role_particles
from utils.file_helpers import save_file_json
from studies.mot_3d.integrity import (
    frozen_stage_design, sha256, validate_completed_result,
)


RECOIL_SEEDS = (42001, 42002, 42003)


def _atomic_json(path, payload):
    save_file_json(path, payload)


def run(args):
    selection = json.loads(Path(args.selection).read_text())
    if selection["family"] != args.family:
        raise ValueError("Selection family and requested family disagree.")
    if not args.input_manifest:
        raise ValueError("Canonical refinement requires --input-manifest.")
    states, ensemble_ids, provenance = load_role_particles(
        args.input_manifest,
        "refinement",
        args.particles_per_ensemble,
        args.selection_seed,
    )
    if len(states) != 3000:
        raise AssertionError("Refinement design must contain exactly 3,000 particles.")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(output_dir / "particle_selection.json", provenance)
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    design = frozen_stage_design(
        args.input_manifest, args.selection, "refinement", args.dt, args.t_max,
        particle_selection=provenance,
        particles_per_ensemble=args.particles_per_ensemble,
        selection_seed=args.selection_seed,
    )

    for candidate in selection["candidates"][args.worker_index :: args.num_workers]:
        candidate_id = candidate["candidate_id"]
        for recoil_seed in RECOIL_SEEDS:
            stem = f"{candidate_id}_seed_{recoil_seed}"
            json_path = output_dir / f"{stem}.json"
            npz_path = output_dir / f"{stem}.npz"
            if validate_completed_result(
                json_path, npz_path,
                kind="mot_3d_focused_refinement_seed_result",
                family=args.family, candidate_id=candidate_id,
                recoil_seed=recoil_seed, design=design,
            ):
                print(f"Skipping completed {stem}", flush=True)
                continue
            print(f"REFINEMENT_START {stem}", flush=True)
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
                "kind": "mot_3d_focused_refinement_seed_result",
                "family": args.family,
                "candidate_id": candidate_id,
                "worker_index": args.worker_index,
                "recoil_seed": recoil_seed,
                "input_particle_count": len(states),
                "usable_at_end_count": int(usable_at_end.sum()),
                "usable_ever_count": int(usable_ever.sum()),
                "peak_usable_count": int(analysis["peak_count"]),
                "entered_capture_region_count": int(diagnostics["entered_capture_region_count"]),
                "slow_inside_count": int(diagnostics["slow_inside_count"]),
                "outcomes_path": str(npz_path),
                "outcomes_sha256": sha256(npz_path),
                "design": design,
            }
            _atomic_json(json_path, result)
            print(f"REFINEMENT_RESULT {stem} usable={result['usable_at_end_count']}/3000", flush=True)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("angled_donut", "single_pass"), required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--input-manifest", required=True)
    parser.add_argument("--worker-index", type=int, required=True)
    parser.add_argument("--num-workers", type=int, default=3)
    parser.add_argument("--particles-per-ensemble", type=int, default=750)
    parser.add_argument("--selection-seed", type=int, default=DEFAULT_RANDOM_SEED + 6000)
    parser.add_argument("--npools", type=int, default=200)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=0.1)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
