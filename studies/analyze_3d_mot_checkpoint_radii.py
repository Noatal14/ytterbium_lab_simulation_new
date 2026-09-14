"""Re-evaluate saved final 3D-MOT states with instantaneous capture radii."""

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from config import Geometry, MOT_3D_CAPTURE_CONFIG


DEFAULT_RADII_MM = tuple(
    radius_m * 1e3 for radius_m in MOT_3D_CAPTURE_CONFIG["diagnostic_radii_m"]
)


def _checkpoint_path(report_path, report, profile):
    configured = report.get("checkpoint_dir")
    if not configured:
        raise ValueError(f"No checkpoint_dir recorded in {report_path}")
    path = Path(configured) / f"{profile}_final_states.npz"
    if path.exists():
        return path
    sibling = report_path.parent / configured / f"{profile}_final_states.npz"
    if sibling.exists():
        return sibling
    raise FileNotFoundError(
        f"Saved final states for {profile!r} were not found at {path}. "
        "Run this analysis from the repository root on the machine that ran the shards."
    )


def analyze_checkpoint_root(input_root, radii_mm=DEFAULT_RADII_MM):
    """Pool shard final states and count slow atoms inside each requested radius."""
    input_root = Path(input_root)
    report_paths = sorted(input_root.glob("shard_*/retention_summary.json"))
    if not report_paths:
        raise FileNotFoundError(f"No shard retention summaries found under {input_root}")
    reports = [json.loads(path.read_text()) for path in report_paths]
    profiles = reports[0]["profiles"]
    if any(report["profiles"] != profiles for report in reports[1:]):
        raise ValueError("Shard profile lists do not match.")

    center = np.asarray(Geometry.MOT_3D_CENTER_M, dtype=float)
    speed_limit = float(MOT_3D_CAPTURE_CONFIG["maximum_final_speed_m_s"])
    records = []
    for profile in profiles:
        states_parts = []
        available_parts = []
        final_times = []
        for report_path, report in zip(report_paths, reports):
            with np.load(_checkpoint_path(report_path, report, profile)) as checkpoint:
                states_parts.append(np.asarray(checkpoint["final_states"], dtype=float))
                available_parts.append(
                    np.asarray(checkpoint["final_state_available"], dtype=bool)
                )
                final_times.append(float(checkpoint["final_time_s"]))
        if not np.allclose(final_times, final_times[0], rtol=0.0, atol=1e-12):
            raise ValueError(f"Shard final times do not match for {profile}.")
        states = np.concatenate(states_parts, axis=0)
        available = np.concatenate(available_parts, axis=0)
        distances = np.full(len(states), np.inf)
        speeds = np.full(len(states), np.inf)
        distances[available] = np.linalg.norm(states[available, :3] - center, axis=1)
        speeds[available] = np.linalg.norm(states[available, 3:6], axis=1)
        slow = available & (speeds <= speed_limit)
        for radius_mm in radii_mm:
            inside = available & (distances <= float(radius_mm) * 1e-3)
            usable = inside & slow
            records.append(
                {
                    "profile": profile,
                    "radius_mm": float(radius_mm),
                    "input_particle_count": int(len(states)),
                    "final_time_s": final_times[0],
                    "state_available_at_end_count": int(available.sum()),
                    "inside_at_end_count": int(inside.sum()),
                    "slow_at_end_count": int(slow.sum()),
                    "usable_at_end_count": int(usable.sum()),
                    "usable_at_end_fraction": float(usable.mean()),
                    "maximum_speed_m_s": speed_limit,
                }
            )
    return records


def write_results(records, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "instantaneous_capture_by_radius.json"
    csv_path = output_dir / "instantaneous_capture_by_radius.csv"
    json_path.write_text(json.dumps({"records": records}, indent=2) + "\n")
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=records[0])
        writer.writeheader()
        writer.writerows(records)
    return json_path, csv_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--radii-mm", nargs="+", type=float, default=DEFAULT_RADII_MM)
    return parser.parse_args(argv)


if __name__ == "__main__":
    arguments = parse_args()
    rows = analyze_checkpoint_root(arguments.input_root, arguments.radii_mm)
    json_output, csv_output = write_results(rows, arguments.output_dir)
    for row in rows:
        print(
            f"{row['profile']}: radius={row['radius_mm']:g} mm, "
            f"usable={row['usable_at_end_count']}/"
            f"{row['input_particle_count']} "
            f"({100 * row['usable_at_end_fraction']:.2f}%)"
        )
    print(f"Saved: {json_output}")
    print(f"Saved: {csv_output}")
