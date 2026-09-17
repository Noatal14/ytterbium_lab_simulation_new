"""Merge donut velocity-only shards and regenerate curated figures 08--12."""

import argparse
from pathlib import Path

import numpy as np

from graphs_scripts.plot_3d_mot_donut_velocity_diagnostics import generate_figures
from studies.analyze_3d_mot_donut_velocity import VARIANT_ORDER


def merge(input_root, output_dir, graph_dir):
    input_root = Path(input_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports = sorted(input_root.glob("shard_*/donut_velocity_shard.json"))
    if len(reports) != 3:
        raise ValueError(f"Expected three donut velocity shards, found {len(reports)}.")
    for name in VARIANT_ORDER:
        parts = [
            np.load(path.parent / f"{name}_longitudinal_velocities.npz")
            for path in reports
        ]
        time_s = np.asarray(parts[0]["time_s"])
        if any(not np.array_equal(time_s, part["time_s"]) for part in parts[1:]):
            raise ValueError(f"Time grids differ for {name}.")
        indices = np.concatenate([part["global_particle_indices"] for part in parts])
        order = np.argsort(indices)
        np.savez_compressed(
            output_dir / f"{name}.npz",
            time_s=time_s,
            vz_m_s=np.concatenate([part["vz_m_s"] for part in parts])[order],
            capture_eligible_ever=np.concatenate(
                [part["capture_eligible_ever"] for part in parts]
            )[order],
            global_particle_indices=indices[order],
        )
    generate_figures(output_dir, graph_dir)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--graph-dir", default="graphs/mot_3d_configuration_decision")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    merge(args.input_root, args.output_dir, args.graph_dir)
