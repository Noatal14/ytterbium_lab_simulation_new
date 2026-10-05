"""Merge full-existing-data finalist outcomes using a crossed paired bootstrap."""

import argparse
import json
from pathlib import Path

import numpy as np


RECOIL_SEEDS = (43001, 43002, 43003)


def merge(args):
    selection = json.loads(Path(args.selection).read_text())
    candidates = selection["candidates"]
    input_root = Path(args.input_root)
    outcome_rows = []
    ensemble_ids = None
    for candidate in candidates:
        arrays = []
        for seed in RECOIL_SEEDS:
            matches = list(
                input_root.glob(f"finalist_*/{candidate['candidate_id']}_seed_{seed}.npz")
            )
            if len(matches) != 1:
                raise ValueError(
                    f"Expected one outcome for {candidate['candidate_id']} seed {seed}; "
                    f"found {len(matches)}."
                )
            with np.load(matches[0]) as data:
                arrays.append(np.asarray(data["usable_at_end"], dtype=bool))
                current_ids = np.asarray(data["ensemble_ids"], dtype=int)
                if ensemble_ids is None:
                    ensemble_ids = current_ids
                elif not np.array_equal(ensemble_ids, current_ids):
                    raise ValueError("Particle grouping differs between finalists.")
        outcome_rows.append(np.stack(arrays))
    outcomes = np.stack(outcome_rows)

    groups = [np.flatnonzero(ensemble_ids == group) for group in range(20)]
    if any(len(group) == 0 for group in groups):
        raise ValueError("At least one expected ensemble is empty.")
    rng = np.random.default_rng(args.bootstrap_seed)
    bootstrap = np.empty((args.bootstrap_replicates, len(candidates)))
    for replicate in range(args.bootstrap_replicates):
        sampled_seeds = rng.integers(0, 3, size=3)
        sampled_groups = rng.integers(0, 20, size=20)
        particle_indices = np.concatenate([groups[group] for group in sampled_groups])
        bootstrap[replicate] = outcomes[:, sampled_seeds][:, :, particle_indices].mean(
            axis=(1, 2)
        )

    means = outcomes.mean(axis=(1, 2))
    lower = np.quantile(bootstrap, 0.025, axis=0)
    upper = np.quantile(bootstrap, 0.975, axis=0)
    leader_index = int(np.argmax(lower))
    records = []
    for index, candidate in enumerate(candidates):
        difference = bootstrap[:, index] - bootstrap[:, leader_index]
        diff_ci = [
            float(np.quantile(difference, 0.025)),
            float(np.quantile(difference, 0.975)),
        ]
        records.append(
            {
                **{key: value for key, value in candidate.items() if key != "resolved_profile"},
                "mean_usable_fraction": float(means[index]),
                "mean_usable_count_per_15840": float(15_840 * means[index]),
                "bootstrap_95_ci": [float(lower[index]), float(upper[index])],
                "paired_difference_from_lcb_leader_95_ci": diff_ci,
                "paired_difference_half_width": float((diff_ci[1] - diff_ci[0]) / 2),
                "seed_counts": [int(value) for value in outcomes[index].sum(axis=1)],
            }
        )
    records.sort(key=lambda row: (-row["bootstrap_95_ci"][0], -row["mean_usable_fraction"]))
    summary = {
        "kind": "merged_mot_3d_finalist_selection",
        "family": selection["family"],
        "candidate_count": len(candidates),
        "particle_count": 15_840,
        "ensemble_file_indices": list(range(20)),
        "recoil_seed_count": 3,
        "bootstrap_method": "crossed resampling of 20 ensemble clusters and recoil seeds",
        "bootstrap_replicates": args.bootstrap_replicates,
        "paired_difference_target_half_width": 0.004,
        "lcb_leader_candidate_id": candidates[leader_index]["candidate_id"],
        "ranked_candidates": records,
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "finalist_summary.json"
    destination.write_text(json.dumps(summary, indent=2) + "\n")
    for rank, row in enumerate(records, 1):
        lo, hi = row["bootstrap_95_ci"]
        print(
            f"{rank}. {row['candidate_id']}: mean={100 * row['mean_usable_fraction']:.3f}% "
            f"CI=[{100 * lo:.3f}, {100 * hi:.3f}]% "
            f"paired_half_width={100 * row['paired_difference_half_width']:.3f}pp "
            f"seeds={row['seed_counts']}"
        )
    print(f"Saved: {destination}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=82001)
    return parser.parse_args(argv)


if __name__ == "__main__":
    merge(parse_args())
