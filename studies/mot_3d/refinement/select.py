"""Build deterministic local-refinement designs from the early independent check."""

import argparse
import json
from pathlib import Path

from config import MOT_3D_OPTIMIZATION_CONFIG
from studies.mot_3d.discovery.optimize import build_profile_from_parameters


COMMON_BOUNDS = {
    "green_s0": "green_s0_bounds",
    "green_detuning_gamma": "green_detuning_gamma_bounds",
    "green_waist_m": "green_waist_m_bounds",
    "blue_s0": "blue_s0_bounds",
    "blue_waist_m": "blue_waist_m_bounds",
    "magnetic_gradient_G_cm": "magnetic_gradient_G_cm_bounds",
}
FAMILY_BOUNDS = {
    "angled_donut": {
        "blue_detuning_gamma": "blue_detuning_gamma_bounds",
        "core_shell_split_radius_m": "core_shell_split_radius_m_bounds",
    },
    "single_pass": {
        "blue_detuning_anchor_gamma": "blue_detuning_anchor_gamma_bounds",
        "blue_crossing_angle_deg": "blue_crossing_angle_deg_bounds",
        "blue_crossing_z_offset_m": "blue_crossing_z_offset_m_bounds",
    },
}


def _bounds(family):
    common = MOT_3D_OPTIMIZATION_CONFIG["common"]
    specific = MOT_3D_OPTIMIZATION_CONFIG[family]
    result = {key: common[name] for key, name in COMMON_BOUNDS.items()}
    result.update({key: specific[name] for key, name in FAMILY_BOUNDS[family].items()})
    return result


def _perturb(parameters, key, delta, bounds):
    candidate = dict(parameters)
    candidate[key] = min(max(candidate[key] + delta, bounds[key][0]), bounds[key][1])
    return candidate


def _design(family, ranked):
    leader = ranked[0]
    center = leader["parameters"]
    bounds = _bounds(family)
    rows = [("early_check_leader", center, leader)]

    if family == "angled_donut":
        moves = (
            ("green_s0_down", "green_s0", -3.0),
            ("green_s0_up", "green_s0", 3.0),
            ("green_detuning_red", "green_detuning_gamma", -2.0),
            ("green_detuning_blue", "green_detuning_gamma", 2.0),
            ("green_waist_down", "green_waist_m", -0.00035),
            ("green_waist_up", "green_waist_m", 0.00035),
            ("gradient_down", "magnetic_gradient_G_cm", -0.5),
            ("gradient_up", "magnetic_gradient_G_cm", 0.5),
            ("blue_s0_inward", "blue_s0", -0.15),
            ("blue_waist_inward", "blue_waist_m", -0.00035),
            ("blue_detuning_inward", "blue_detuning_gamma", -0.5),
            ("split_radius_inward", "core_shell_split_radius_m", 0.0004),
        )
        anchors = (ranked[1], ranked[6], ranked[3])
    else:
        moves = (
            ("green_s0_inward", "green_s0", -4.0),
            ("green_detuning_red", "green_detuning_gamma", -2.0),
            ("green_detuning_blue", "green_detuning_gamma", 2.0),
            ("green_waist_inward", "green_waist_m", -0.00035),
            ("blue_s0_down", "blue_s0", -0.04),
            ("blue_s0_up", "blue_s0", 0.04),
            ("blue_waist_inward", "blue_waist_m", -0.00035),
            ("gradient_down", "magnetic_gradient_G_cm", -0.35),
            ("gradient_up", "magnetic_gradient_G_cm", 0.35),
            ("blue_anchor_red", "blue_detuning_anchor_gamma", -0.25),
            ("blue_anchor_blue", "blue_detuning_anchor_gamma", 0.25),
            ("crossing_angle_inward", "blue_crossing_angle_deg", 2.0),
            ("crossing_z_upstream", "blue_crossing_z_offset_m", -0.0025),
            ("crossing_z_downstream", "blue_crossing_z_offset_m", 0.0025),
        )
        anchors = (ranked[1],)

    for label, key, delta in moves:
        rows.append((label, _perturb(center, key, delta, bounds), leader))
    for anchor in anchors:
        rows.append((f"anchor_{anchor['candidate_id']}", anchor["parameters"], anchor))
    if len(rows) != 16:
        raise AssertionError(f"Expected 16 refinement candidates, built {len(rows)}.")
    return rows, bounds


def select(family, early_summary):
    summary = json.loads(Path(early_summary).read_text())
    if summary["family"] != family:
        raise ValueError("Early-check summary and requested family disagree.")
    rows, bounds = _design(family, summary["ranked_candidates"])
    candidates = []
    signatures = set()
    for index, (role, parameters, source) in enumerate(rows):
        signature = tuple(sorted(parameters.items()))
        if signature in signatures:
            raise ValueError(f"Duplicate refinement point generated for {role}.")
        signatures.add(signature)
        profile, resolved, derived = build_profile_from_parameters(family, parameters)
        candidates.append(
            {
                "candidate_id": f"{family}_refine_{index:02d}",
                "refinement_role": role,
                "source_candidate_id": source["candidate_id"],
                "source_early_check_fraction": source["mean_usable_fraction"],
                "parameters": resolved,
                "derived_parameters": derived,
                "resolved_profile": profile,
            }
        )
    return {
        "kind": "mot_3d_focused_refinement_selection",
        "family": family,
        "candidate_count": len(candidates),
        "parameter_bounds": bounds,
        "design": "leader-centered one-at-a-time sensitivity plus distinct-region anchors",
        "candidates": candidates,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("angled_donut", "single_pass"), required=True)
    parser.add_argument("--early-summary", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    payload = select(args.family, args.early_summary)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Saved {len(payload['candidates'])} candidates: {destination}")


if __name__ == "__main__":
    main()
