"""Merge independent 3D-MOT Optuna worker outputs into one ranked table."""

import argparse
import csv
import json
from pathlib import Path


def merge(
    input_root, output_dir, expected_trial_count=None, expected_worker_count=None,
    campaign_manifest_sha256=None,
):
    input_root = Path(input_root)
    paths = sorted(input_root.glob("worker_*/trials/trial_[0-9][0-9][0-9][0-9].json"))
    rows = [json.loads(path.read_text()) for path in paths]
    if not rows:
        raise FileNotFoundError(f"No completed trial JSON files found below {input_root}.")
    if expected_trial_count is not None and len(rows) != expected_trial_count:
        raise RuntimeError(
            f"Discovery is incomplete: found {len(rows)} completed trials below "
            f"{input_root}, expected exactly {expected_trial_count}. Resume the "
            "workers before merging."
        )
    families = {row["family"] for row in rows}
    if len(families) != 1:
        raise ValueError(f"Mixed optimization families: {sorted(families)}")
    design_ids = {row.get("design_id") for row in rows}
    designs = [row.get("scientific_design") for row in rows]
    worker_indices = sorted({row["worker_index"] for row in rows})
    required_workers = expected_worker_count or len(worker_indices)
    if None in design_ids or len(design_ids) != required_workers:
        # Each worker has its own immutable identity, hence exactly three IDs.
        raise ValueError("Discovery results have missing or unexpected worker designs.")
    if expected_worker_count is not None and worker_indices != list(range(expected_worker_count)):
        raise ValueError(
            f"Expected worker indices {list(range(expected_worker_count))}, "
            f"found {worker_indices}."
        )
    for worker in worker_indices:
        worker_designs = [
            row.get("scientific_design") for row in rows if row["worker_index"] == worker
        ]
        if not worker_designs or any(value != worker_designs[0] for value in worker_designs[1:]):
            raise ValueError(f"Discovery worker {worker} contains mixed designs.")
    for path, row in zip(paths, rows):
        row["source_path"] = str(path)
    rows.sort(
        key=lambda row: (
            -row["usable_at_end_fraction"],
            row["runtime_seconds"],
            row["worker_index"],
            row["trial_number"],
        )
    )
    summary = {
        "kind": "merged_mot_3d_full_optuna_discovery",
        "family": rows[0]["family"],
        "completed_trial_count": len(rows),
        "software_revisions": sorted({row["software_revision"] for row in rows}),
        "worker_design_ids": sorted(design_ids),
        "campaign_manifest_sha256": campaign_manifest_sha256,
        "best": rows[0],
        "ranked_trials": rows,
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "merged_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    csv_path = output_dir / "ranked_trials.csv"
    parameter_names = sorted(
        {name for row in rows for name in row["parameters"]}
    )
    derived_names = sorted(
        {name for row in rows for name in row.get("derived_parameters", {})}
    )
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "rank",
                "worker_index",
                "trial_number",
                "usable_at_end_count",
                "usable_at_end_fraction",
                "usable_ever_count",
                "entered_capture_region_count",
                "runtime_seconds",
                *parameter_names,
                *derived_names,
            ),
        )
        writer.writeheader()
        for rank, row in enumerate(rows, start=1):
            writer.writerow(
                {
                    "rank": rank,
                    "worker_index": row["worker_index"],
                    "trial_number": row["trial_number"],
                    "usable_at_end_count": row["usable_at_end_count"],
                    "usable_at_end_fraction": row["usable_at_end_fraction"],
                    "usable_ever_count": row["usable_ever_count"],
                    "entered_capture_region_count": row[
                        "entered_capture_region_count"
                    ],
                    "runtime_seconds": row["runtime_seconds"],
                    **row["parameters"],
                    **row.get("derived_parameters", {}),
                }
            )
    print(f"Merged {len(rows)} completed {rows[0]['family']} trials.")
    print(
        f"Best: {rows[0]['usable_at_end_count']}/{rows[0]['input_particle_count']} "
        f"({100 * rows[0]['usable_at_end_fraction']:.2f}%)"
    )
    print(f"Saved: {summary_path}")
    print(f"Saved: {csv_path}")
    return summary_path, csv_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-trial-count", type=int)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    merge(args.input_root, args.output_dir, args.expected_trial_count)
