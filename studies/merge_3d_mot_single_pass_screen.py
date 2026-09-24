"""Merge the three 600-atom single-pass screen shards into a compact report."""

import argparse
import json
import math
import shutil
from pathlib import Path

from config import MOT_3D_CONFIGURATIONS
from studies.merge_3d_mot_retention_shards import run_merge


PROFILE = "single_pass"


def merge_screen(input_root, output_dir, graph_dir=None):
    output_dir = Path(output_dir)
    analyses, plot_path, merged_summary_path = run_merge(input_root, output_dir)
    analysis = analyses[PROFILE]
    diagnostics = analysis["diagnostics"]
    total = int(diagnostics["particle_count"])
    usable_at_end = int(analysis["capture_eligible_counts"][-1])
    usable_ever = int(diagnostics["capture_eligible_ever_count"])
    peak_usable = int(analysis["peak_count"])
    profile = MOT_3D_CONFIGURATIONS[PROFILE]
    angle_rad = math.radians(profile["blue_crossing_angle_deg"])
    center_axis_distance_m = abs(profile["blue_crossing_z_offset_m"]) * math.sin(
        0.5 * angle_rad
    )
    estimated_center_fraction = math.exp(
        -2.0 * (center_axis_distance_m / profile["399"]["waist_m"]) ** 2
    )

    summary = {
        "status": "new yz single-pass 600-atom geometry screen",
        "profile": PROFILE,
        "input_particle_count": total,
        "num_shards": 3,
        "final_time_s": 0.1,
        "usable_at_end_count": usable_at_end,
        "usable_at_end_fraction": usable_at_end / total if total else 0.0,
        "usable_ever_count": usable_ever,
        "usable_ever_fraction": usable_ever / total if total else 0.0,
        "peak_usable_count": peak_usable,
        "entered_capture_region_count": int(
            diagnostics["entered_capture_region_count"]
        ),
        "slow_inside_count": int(diagnostics["slow_inside_count"]),
        "minimum_residence_met_count": int(
            diagnostics["minimum_residence_met_count"]
        ),
        "geometry": {
            "blue_plane": "yz",
            "blue_crossing_angle_deg": profile["blue_crossing_angle_deg"],
            "blue_crossing_z_offset_m": profile["blue_crossing_z_offset_m"],
            "blue_propagation_z_component": "negative for both beams",
            "blue_axis_distance_from_mot_center_m": center_axis_distance_m,
            "estimated_blue_center_to_peak_intensity_ratio_per_beam": (
                estimated_center_fraction
            ),
            "maximum_allowed_blue_center_to_peak_intensity_ratio": profile[
                "maximum_blue_center_relative_intensity"
            ],
        },
        "operating_point": {
            "green_s0": profile["556"]["s0"],
            "green_detuning_gamma": profile["556"]["detuning_gamma"],
            "green_waist_m": profile["556"]["waist_m"],
            "blue_s0": profile["399"]["s0"],
            "blue_detuning_gamma": profile["399"]["detuning_gamma"],
            "blue_waist_m": profile["399"]["waist_m"],
            "magnetic_gradient_G_cm": profile["magnetic_gradient_G_cm"],
        },
        "capture_definition": (
            "at 100 ms: distance from MOT center <= 5 mm and total speed <= 1 m/s"
        ),
        "merged_retention_summary": str(merged_summary_path),
    }
    summary_path = output_dir / "single_pass_screen_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    final_plot = plot_path
    if graph_dir is not None:
        graph_dir = Path(graph_dir)
        graph_dir.mkdir(parents=True, exist_ok=True)
        final_plot = graph_dir / "single_pass_yz_screen.png"
        shutil.copy2(plot_path, final_plot)
    print("=" * 72)
    print("NEW YZ SINGLE-PASS SCREEN")
    print(f"usable at 100 ms: {usable_at_end}/{total} ({100 * usable_at_end / total:.1f}%)")
    print(f"usable at least once: {usable_ever}/{total} ({100 * usable_ever / total:.1f}%)")
    print(f"peak usable: {peak_usable}")
    print(f"entered 5-mm region: {diagnostics['entered_capture_region_count']}")
    print(f"slow inside: {diagnostics['slow_inside_count']}")
    print(f"Saved summary: {summary_path}")
    print(f"Saved graph: {final_plot}")
    return summary_path, final_plot


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--graph-dir", default="graphs/mot_3d_configuration_decision"
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    merge_screen(args.input_root, args.output_dir, args.graph_dir)
