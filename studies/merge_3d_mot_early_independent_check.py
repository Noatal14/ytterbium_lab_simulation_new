"""Merge early-check outcomes using a crossed ensemble/recoil bootstrap."""

import argparse
import json
from pathlib import Path

import numpy as np


def merge(args):
    selection = json.loads(Path(args.selection).read_text())
    candidates = selection["candidates"]
    root = Path(args.input_root)
    seed_records = [json.loads(path.read_text()) for path in sorted(root.glob("worker_*/*.json")) if "particle_selection" not in path.name]
    expected = len(candidates) * 3
    if len(seed_records) != expected:
        raise RuntimeError(f"Early check incomplete: found {len(seed_records)}/{expected} seed results.")

    outcome_rows = []
    ensemble_ids = None
    for candidate in candidates:
        records = sorted(
            [row for row in seed_records if row["candidate_id"] == candidate["candidate_id"]],
            key=lambda row: row["recoil_seed"],
        )
        if len(records) != 3:
            raise RuntimeError(f"{candidate['candidate_id']} has {len(records)}/3 seeds.")
        arrays = []
        for record in records:
            with np.load(record["outcomes_path"]) as data:
                arrays.append(np.asarray(data["usable_at_end"], dtype=float))
                current_ids = np.asarray(data["ensemble_ids"], dtype=int)
                if ensemble_ids is None:
                    ensemble_ids = current_ids
                elif not np.array_equal(ensemble_ids, current_ids):
                    raise ValueError("Particle grouping differs between candidates.")
        outcome_rows.append(np.stack(arrays))
    outcomes = np.stack(outcome_rows)  # candidate, recoil seed, particle

    rng = np.random.default_rng(args.bootstrap_seed)
    bootstrap = np.empty((args.bootstrap_replicates, len(candidates)))
    groups = [np.flatnonzero(ensemble_ids == group) for group in range(4)]
    for replicate in range(args.bootstrap_replicates):
        sampled_seeds = rng.integers(0, 3, size=3)
        sampled_groups = rng.integers(0, 4, size=4)
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
        records.append(
            {
                **{key: value for key, value in candidate.items() if key != "resolved_profile"},
                "mean_usable_fraction": float(means[index]),
                "mean_usable_count_per_600": float(600 * means[index]),
                "bootstrap_95_ci": [float(lower[index]), float(upper[index])],
                "paired_difference_from_lcb_leader_95_ci": [
                    float(np.quantile(difference, 0.025)),
                    float(np.quantile(difference, 0.975)),
                ],
                "seed_counts": [int(value) for value in outcomes[index].sum(axis=1)],
            }
        )
    records.sort(key=lambda row: (-row["bootstrap_95_ci"][0], -row["mean_usable_fraction"]))
    summary = {
        "kind": "merged_mot_3d_early_independent_check",
        "family": selection["family"],
        "candidate_count": len(candidates),
        "particle_count": 600,
        "ensemble_file_indices": [16, 17, 18, 19],
        "recoil_seed_count": 3,
        "bootstrap_method": "crossed resampling of ensemble clusters and recoil seeds",
        "bootstrap_replicates": args.bootstrap_replicates,
        "lcb_leader_candidate_id": candidates[leader_index]["candidate_id"],
        "ranked_candidates": records,
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "early_check_summary.json"
    destination.write_text(json.dumps(summary, indent=2) + "\n")
    for rank, row in enumerate(records, 1):
        lo, hi = row["bootstrap_95_ci"]
        print(
            f"{rank:2d}. {row['candidate_id']}: "
            f"mean={100 * row['mean_usable_fraction']:.2f}% "
            f"CI=[{100 * lo:.2f}, {100 * hi:.2f}]% "
            f"seeds={row['seed_counts']}"
        )
    print(f"Saved: {destination}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=5000)
    parser.add_argument("--bootstrap-seed", type=int, default=52001)
    return parser.parse_args(argv)


if __name__ == "__main__":
    merge(parse_args())
