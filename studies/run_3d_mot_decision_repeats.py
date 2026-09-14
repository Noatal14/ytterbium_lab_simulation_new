"""Repeat current 3D-MOT family representatives across stochastic seeds."""

import argparse
import json
from pathlib import Path

import numpy as np

from config import (
    DEFAULT_RANDOM_SEED,
    MOT_3D_DECISION_REPEAT_CONFIG as STUDY_CONFIG,
    MOT_3D_SIM_CONFIG,
)
from simulations.mot_3d import mot_3d_simulation
from studies.analyze_3d_mot_donut_ablation import DEFAULT_INPUT
from studies.compare_3d_mot_retention import (
    analyze_results,
    load_shared_ensemble,
    select_particle_shard,
)
from studies.scan_3d_mot_five_beam_decision import profile_for_point as five_profile
from studies.scan_3d_mot_single_pass_gate_followup import profile_for_point as gate_profile


def representatives(settings=None):
    settings = settings or STUDY_CONFIG
    return (
        ("full_donut", gate_profile({"kind": "full_donut"})),
        (
            "finite_four_blue",
            gate_profile(
                {
                    "kind": "entrance_plus_backstop",
                    "backstop_crossing_offset_m": settings[
                        "finite_gate_backstop_crossing_offset_m"
                    ],
                    "backstop_s0": settings["finite_gate_backstop_s0"],
                }
            ),
        ),
        (
            "five_beam_gravity",
            five_profile(
                {
                    "kind": "five_beam_gravity",
                    "blue_s0": 1.0,
                    "blue_detuning_gamma": -2.0,
                    "gradient_G_cm": 2.5,
                    "paired_green_s0": 10.0,
                    "lower_green_s0": settings["five_beam_lower_green_s0"],
                    "green_detuning_gamma": -20.0,
                }
            ),
        ),
    )


def run_repeats(args):
    selected, input_files = load_shared_ensemble(
        args.input, args.max_atoms, args.selection_seed
    )
    states, global_indices = select_particle_shard(
        selected, args.num_shards, args.shard_index
    )
    if not len(states):
        raise ValueError("The selected shard contains no atoms.")
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    configurations = representatives()
    records = []
    total = len(configurations) * len(args.repeat_seeds)
    point_index = 0
    for seed in args.repeat_seeds:
        shard_seed = int(
            np.random.SeedSequence([seed, args.shard_index]).generate_state(1)[0]
        )
        for name, profile in configurations:
            point_index += 1
            print(
                f"Starting repeat {point_index}/{total}: {name}, seed={seed}",
                flush=True,
            )
            trajectories, _ = mot_3d_simulation(
                states,
                _3d_mot_config=profile,
                gravity_enabled=True,
                npools=args.npools,
                dt=args.dt,
                t_max=args.t_max,
                seed=shard_seed,
                magnetic_gradient_G_cm=profile["magnetic_gradient_G_cm"],
            )
            analysis = analyze_results(trajectories, time_points)
            usable_ever = np.any(analysis["eligible_masks"], axis=1)
            usable_at_end = analysis["eligible_masks"][:, -1]
            np.savez_compressed(
                output_dir / f"seed_{seed}_{name}_outcomes.npz",
                global_particle_indices=global_indices,
                usable_ever=usable_ever,
                usable_at_end=usable_at_end,
            )
            records.append(
                {
                    "configuration": name,
                    "repeat_seed": int(seed),
                    "input_particle_count": len(states),
                    "usable_ever_count": int(usable_ever.sum()),
                    "usable_at_end_count": int(usable_at_end.sum()),
                    "peak_usable_count": int(analysis["peak_count"]),
                }
            )
            print(
                f"Completed {name}, seed={seed}: at end="
                f"{usable_at_end.sum()}/{len(states)}",
                flush=True,
            )
    report = {
        "status": "stochastic-repeat comparison of provisional representatives",
        "purpose": "measure seed-to-seed uncertainty with a paired ensemble",
        "input_files": [str(path) for path in input_files],
        "selected_particle_count_before_sharding": len(selected),
        "input_particle_count": len(states),
        "num_shards": args.num_shards,
        "shard_index": args.shard_index,
        "selection_seed": args.selection_seed,
        "repeat_seeds": list(args.repeat_seeds),
        "dt_s": args.dt,
        "t_max_s": args.t_max,
        "records": records,
    }
    (output_dir / "decision_repeats.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-atoms", type=int, default=STUDY_CONFIG["max_atoms"])
    parser.add_argument("--num-shards", type=int, default=STUDY_CONFIG["num_shards"])
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--npools", type=int, default=STUDY_CONFIG["pbs_ncpus_per_shard"])
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=STUDY_CONFIG["t_max_s"])
    parser.add_argument("--selection-seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument(
        "--repeat-seeds", nargs="+", type=int, default=list(STUDY_CONFIG["repeat_seeds"])
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_repeats(parse_args())
