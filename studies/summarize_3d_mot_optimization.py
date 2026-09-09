"""Combine selected scan points into one provisional operating-point report."""

import argparse
import json
from pathlib import Path


def run_summary(selections, output_path):
    configurations = {}
    for profile, selection_path in selections:
        selection = json.loads(Path(selection_path).read_text())
        point = selection["best_point"]
        configurations[profile] = {
            "blue_s0": point["s0"],
            "blue_detuning_gamma": point["detuning_gamma"],
            "gradient_G_cm": point["gradient_G_cm"],
            "green_s0": point["green_s0"],
            "green_detuning_gamma": point["green_detuning_gamma"],
            "capture_eligible_ever_count": point["capture_eligible_ever_count"],
            "peak_capture_eligible_count": point["peak_capture_eligible_count"],
            "source_selection": str(selection_path),
        }
        for field in (
            "blue_waist_mm",
            "green_exclusion_radius_mm",
            "crossing_distance_mm",
        ):
            if field in point:
                configurations[profile][field] = point[field]
    report = {
        "status": "provisional optimization results; not laboratory-set values",
        "configurations": configurations,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"Saved optimization summary: {output_path}")
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--selection", nargs=2, action="append", metavar=("PROFILE", "JSON"), required=True
    )
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    run_summary(args.selection, args.output)
