"""Fail closed unless the corrected narrow-donut screen passed its gate."""

import argparse
import json
from pathlib import Path


EXPECTED_RUN_LABEL = "donut_core_shell_split_screen_v2_600"


def validate(summary_path, minimum_fraction):
    path = Path(summary_path)
    if not path.exists():
        raise FileNotFoundError(f"Corrected donut screen is missing: {path}")
    data = json.loads(path.read_text())
    if data.get("run_label") != EXPECTED_RUN_LABEL:
        raise ValueError(
            f"Expected run label {EXPECTED_RUN_LABEL!r}, "
            f"found {data.get('run_label')!r}."
        )
    if data.get("input_particle_count") != 600 or data.get("num_shards") != 3:
        raise ValueError("Corrected donut screen must contain 600 particles in 3 shards.")
    best = data.get("best")
    if not isinstance(best, dict):
        raise ValueError("Corrected donut screen has no best record.")
    fraction = float(best["usable_at_end_fraction"])
    if fraction < minimum_fraction:
        raise RuntimeError(
            f"Donut gate failed: {fraction:.6f} < {minimum_fraction:.6f}."
        )
    if best["usable_at_end_count"] != best["usable_ever_count"]:
        raise RuntimeError(
            "Donut gate failed: usable-at-end differs from usable-at-least-once."
        )
    print(
        "DISCOVERY_PREFLIGHT_OK "
        f"run_label={data['run_label']} "
        f"usable={best['usable_at_end_count']}/600 "
        f"fraction={fraction:.6f} "
        f"split_mm={1000 * best['core_shell_split_radius_m']:.3f}",
        flush=True,
    )
    return data


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--minimum-fraction", type=float, default=0.20)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    validate(args.summary, args.minimum_fraction)
