"""Evaluate one 3D-MOT finalist on all 20 frozen selection ensembles and three seeds."""

import argparse
import json
import os
from pathlib import Path

import numpy as np

from config import MOT_3D_SIM_CONFIG
from simulations.mot_3d import mot_3d_simulation
from studies.mot_3d.analysis.retention import analyze_results
from studies.mot_3d_campaign import load_all_frozen_particles
from utils.file_helpers import save_file_json
from studies.mot_3d.integrity import (
    frozen_stage_design, sha256, validate_completed_result,
)


RECOIL_SEEDS = (43001, 43002, 43003)


def _atomic_json(path, payload):
    save_file_json(path, payload)


def run(args):
    selection = json.loads(Path(args.selection).read_text())
    if selection["family"] != args.family:
        raise ValueError("Selection family and requested family disagree.")
    candidates = selection["candidates"]
    if args.finalist_index < 0 or args.finalist_index >= len(candidates):
        raise IndexError("Finalist index is outside the selection.")
    candidate = candidates[args.finalist_index]
    if not args.input_manifest:
        raise ValueError("Canonical finalist selection requires --input-manifest.")
    states, ensemble_ids, provenance = load_all_frozen_particles(args.input_manifest)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(output_dir / "particle_selection.json", provenance)
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    # Finalist selection uses all three frozen roles, represented by a stable
    # combined role digest stored directly below.
    manifest_payload = json.loads(Path(args.input_manifest).read_text())
    combined_records = sum(
        (manifest_payload["input_roles"][role] for role in (
            "discovery", "refinement", "preliminary_check"
        )),
        [],
    )
    design = frozen_stage_design(
        args.input_manifest, args.selection, "discovery", args.dt, args.t_max,
        particle_selection=provenance,
    )
    design["input_role"] = "all_existing_selection"
    design["input_role_sha256"] = __import__("hashlib").sha256(
        json.dumps(combined_records, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    candidate_id = candidate["candidate_id"]
    for recoil_seed in RECOIL_SEEDS:
        stem = f"{candidate_id}_seed_{recoil_seed}"
        json_path = output_dir / f"{stem}.json"
        npz_path = output_dir / f"{stem}.npz"
        if validate_completed_result(
            json_path, npz_path,
            kind="mot_3d_finalist_seed_result",
            family=args.family, candidate_id=candidate_id,
            recoil_seed=recoil_seed, design=design,
        ):
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
            "outcomes_sha256": sha256(npz_path),
            "design": design,
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
    parser.add_argument("--input-manifest", required=True)
    parser.add_argument("--npools", type=int, default=200)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=0.1)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
