"""Select diverse, physically useful discovery candidates for an independent check."""

import argparse
import json
from pathlib import Path

import numpy as np

from config import MOT_3D_OPTIMIZATION_CONFIG


FAMILIES = ("angled_donut", "single_pass")


def parameter_bounds(family):
    common = MOT_3D_OPTIMIZATION_CONFIG["common"]
    bounds = {
        "green_s0": common["green_s0_bounds"],
        "green_detuning_gamma": common["green_detuning_gamma_bounds"],
        "green_waist_m": common["green_waist_m_bounds"],
        "blue_s0": common["blue_s0_bounds"],
        "blue_waist_m": common["blue_waist_m_bounds"],
        "magnetic_gradient_G_cm": common["magnetic_gradient_G_cm_bounds"],
    }
    family_config = MOT_3D_OPTIMIZATION_CONFIG[family]
    if family == "angled_donut":
        bounds.update(
            blue_detuning_gamma=family_config["blue_detuning_gamma_bounds"],
            core_shell_split_radius_m=family_config[
                "core_shell_split_radius_m_bounds"
            ],
        )
    else:
        bounds.update(
            blue_detuning_anchor_gamma=family_config[
                "blue_detuning_anchor_gamma_bounds"
            ],
            blue_crossing_angle_deg=family_config[
                "blue_crossing_angle_deg_bounds"
            ],
            blue_crossing_z_offset_m=family_config[
                "blue_crossing_z_offset_m_bounds"
            ],
        )
    return bounds


def _normalized_vector(row, bounds):
    return np.asarray(
        [
            (float(row["parameters"][name]) - low) / (high - low)
            for name, (low, high) in bounds.items()
        ]
    )


def _boundary_distance(row, bounds):
    vector = _normalized_vector(row, bounds)
    return float(np.minimum(vector, 1.0 - vector).min())


def _power_proxy(row, family):
    parameters = row["parameters"]
    blue_beams = 6 if family == "angled_donut" else 2
    return float(
        6 * parameters["green_s0"] * parameters["green_waist_m"] ** 2
        + blue_beams * parameters["blue_s0"] * parameters["blue_waist_m"] ** 2
    )


def select_candidates(summary, family, count=12):
    rows = summary["ranked_trials"]
    bounds = parameter_bounds(family)
    best_fraction = float(rows[0]["usable_at_end_fraction"])
    threshold = max(
        0.55 if family == "angled_donut" else 0.10,
        best_fraction - (0.16 if family == "angled_donut" else 0.40),
    )
    pool = [row for row in rows if row["usable_at_end_fraction"] >= threshold]
    if len(pool) < count:
        pool = rows[: max(count, min(80, len(rows)))]

    selected = []
    roles = {}

    def add(row, role):
        key = (row["worker_index"], row["trial_number"])
        if key not in roles:
            selected.append(row)
            roles[key] = [role]
        elif role not in roles[key]:
            roles[key].append(role)

    add(rows[0], "global_best")
    for worker in range(3):
        worker_rows = [row for row in rows if row["worker_index"] == worker]
        add(worker_rows[0], f"worker_{worker}_best")

    interior = [row for row in pool if _boundary_distance(row, bounds) >= 0.08]
    if interior:
        add(interior[0], "best_interior")

    competitive = [
        row
        for row in pool
        if row["usable_at_end_fraction"] >= best_fraction - 0.10
    ]
    if competitive:
        add(min(competitive, key=lambda row: _power_proxy(row, family)), "lower_power")

    vectors = {
        (row["worker_index"], row["trial_number"]): _normalized_vector(row, bounds)
        for row in pool
    }
    while len(selected) < count:
        selected_vectors = [
            vectors[(row["worker_index"], row["trial_number"])]
            for row in selected
            if (row["worker_index"], row["trial_number"]) in vectors
        ]
        candidates = [
            row
            for row in pool
            if (row["worker_index"], row["trial_number"]) not in roles
        ]
        if not candidates:
            break

        def merit(row):
            vector = vectors[(row["worker_index"], row["trial_number"])]
            if selected_vectors:
                diversity = min(
                    np.linalg.norm(vector - other) / np.sqrt(len(vector))
                    for other in selected_vectors
                )
            else:
                diversity = 1.0
            quality = float(row["usable_at_end_fraction"]) / best_fraction
            interior_score = max(0.0, _boundary_distance(row, bounds))
            return 0.60 * diversity + 0.30 * quality + 0.10 * interior_score

        add(max(candidates, key=merit), "diverse_competitive_region")

    candidates = []
    for index, row in enumerate(selected[:count]):
        key = (row["worker_index"], row["trial_number"])
        candidates.append(
            {
                "candidate_id": f"{family}_{index:02d}",
                "selection_roles": roles[key],
                "discovery_rank": rows.index(row) + 1,
                "discovery_usable_at_end_fraction": row[
                    "usable_at_end_fraction"
                ],
                "discovery_usable_at_end_count": row["usable_at_end_count"],
                "worker_index": row["worker_index"],
                "trial_number": row["trial_number"],
                "normalized_boundary_distance": _boundary_distance(row, bounds),
                "power_proxy": _power_proxy(row, family),
                "parameters": row["parameters"],
                "derived_parameters": row.get("derived_parameters", {}),
                "resolved_profile": row["resolved_profile"],
            }
        )
    return {
        "kind": "mot_3d_discovery_candidate_selection",
        "family": family,
        "requested_candidate_count": count,
        "selected_candidate_count": len(candidates),
        "selection_pool_minimum_fraction": threshold,
        "parameter_bounds": bounds,
        "candidates": candidates,
    }


def main(args):
    root = Path(args.input_root)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for family in FAMILIES:
        path = root / family / "merged" / "merged_summary.json"
        summary = json.loads(path.read_text())
        selection = select_candidates(summary, family, args.count)
        destination = output / f"{family}_candidates.json"
        destination.write_text(json.dumps(selection, indent=2) + "\n")
        print(f"{family}: {selection['selected_candidate_count']} candidates")
        for row in selection["candidates"]:
            print(
                f"  {row['candidate_id']} rank={row['discovery_rank']} "
                f"capture={100 * row['discovery_usable_at_end_fraction']:.2f}% "
                f"roles={','.join(row['selection_roles'])}"
            )
        print(f"Saved: {destination}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--count", type=int, default=12)
    return parser.parse_args(argv)


if __name__ == "__main__":
    main(parse_args())
