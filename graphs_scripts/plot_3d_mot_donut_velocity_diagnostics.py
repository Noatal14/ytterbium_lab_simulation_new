"""Regenerate curated donut-ablation vz(t) figures from merged Zeus data."""

import argparse
from pathlib import Path

import numpy as np

from graphs_scripts.mot_3d_velocity_style import plot_longitudinal_velocity


LABELS = {
    "full_donut": "full donut",
    "without_positive_z_blue": "without +z blue beams",
    "without_transverse_y_blue": "without transverse y blue beams",
    "counterpropagating_pair_shell": "counterpropagating pair, full shell",
    "single_pass_counterpropagating_pair": "counterpropagating pair, single pass",
}

OUTPUT_NAMES = {
    "full_donut": "08_full_donut_longitudinal_velocity.png",
    "without_positive_z_blue": "09_without_positive_z_blue_velocity.png",
    "without_transverse_y_blue": "10_without_transverse_y_blue_velocity.png",
    "counterpropagating_pair_shell": "11_single_pair_shell_velocity.png",
    "single_pass_counterpropagating_pair": "12_single_pass_pair_velocity.png",
}


def generate_figures(input_dir, output_dir):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    generated = []
    for name, label in LABELS.items():
        path = input_dir / f"{name}.npz"
        if not path.exists():
            raise FileNotFoundError(f"Missing merged velocity data: {path}")
        with np.load(path) as data:
            time_s = np.asarray(data["time_s"], dtype=float)
            velocities = np.asarray(data["vz_m_s"], dtype=float)
            captured = np.asarray(data["capture_eligible_ever"], dtype=bool)
        generated.append(
            plot_longitudinal_velocity(
                time_s=time_s,
                velocities_m_s=velocities,
                initial_vz_m_s=velocities[:, 0],
                usable=captured,
                title=f"All incoming atoms: {label}",
                output_path=output_dir / OUTPUT_NAMES[name],
            )
        )
        print(f"Saved: {generated[-1]}")
    return generated


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(
            "data/validation/mot_3d/donut_ablation/full_600_100ms/"
            "merged/longitudinal_velocities"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("graphs/mot_3d_configuration_decision"),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    generate_figures(args.input_dir, args.output_dir)
