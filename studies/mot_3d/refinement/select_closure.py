"""Build the final local closure designs from focused-refinement results."""

import argparse
import json
from pathlib import Path

from config import MOT_3D_OPTIMIZATION_CONFIG
from studies.mot_3d.discovery.optimize import build_profile_from_parameters
from studies.mot_3d.refinement.select import _bounds


def _candidate(family, index, role, parameters):
    profile, resolved, derived = build_profile_from_parameters(family, parameters)
    return {
        "candidate_id": f"{family}_closure_{index:02d}",
        "closure_role": role,
        "parameters": resolved,
        "derived_parameters": derived,
        "resolved_profile": profile,
    }


def _replace(parameters, **updates):
    result = dict(parameters)
    result.update(updates)
    return result


def _donut_design(ranked):
    # The focused-refinement winner is gradient_up.  The other one-at-a-time
    # results point toward the allowed blue-power/waist/detuning and split-radius
    # boundaries, so this closure explicitly tests those boundaries and their
    # combinations rather than launching another broad search.
    base = dict(ranked[0]["parameters"])
    conservative_blue = _replace(
        base,
        blue_s0=1.5,
        blue_waist_m=0.0075,
        core_shell_split_radius_m=0.0025,
    )
    full_blue = _replace(conservative_blue, blue_detuning_gamma=-0.5)
    return [
        ("focused_refinement_leader", base),
        ("gradient_5p75", _replace(base, magnetic_gradient_G_cm=5.75)),
        ("gradient_6p00", _replace(base, magnetic_gradient_G_cm=6.0)),
        ("blue_s0_boundary", _replace(base, blue_s0=1.5)),
        ("blue_waist_boundary", _replace(base, blue_waist_m=0.0075)),
        ("blue_detuning_boundary", _replace(base, blue_detuning_gamma=-0.5)),
        ("split_radius_boundary", _replace(base, core_shell_split_radius_m=0.0025)),
        (
            "green_detuning_red_with_winning_gradient",
            _replace(base, green_detuning_gamma=-20.373473780336884),
        ),
        ("conservative_blue_boundaries", conservative_blue),
        ("all_blue_boundaries", full_blue),
        (
            "conservative_blue_plus_gradient_5p75",
            _replace(conservative_blue, magnetic_gradient_G_cm=5.75),
        ),
        (
            "all_blue_plus_gradient_5p75",
            _replace(full_blue, magnetic_gradient_G_cm=5.75),
        ),
        (
            "conservative_blue_plus_gradient_6p00",
            _replace(conservative_blue, magnetic_gradient_G_cm=6.0),
        ),
        (
            "all_blue_plus_gradient_6p00",
            _replace(full_blue, magnetic_gradient_G_cm=6.0),
        ),
        (
            "red_green_conservative_blue_gradient_5p75",
            _replace(
                conservative_blue,
                green_detuning_gamma=-20.373473780336884,
                magnetic_gradient_G_cm=5.75,
            ),
        ),
        (
            "red_green_all_blue_gradient_5p75",
            _replace(
                full_blue,
                green_detuning_gamma=-20.373473780336884,
                magnetic_gradient_G_cm=5.75,
            ),
        ),
    ]


def _single_pass_design(ranked):
    leader = dict(ranked[0]["parameters"])
    original = next(
        dict(row["parameters"])
        for row in ranked
        if row["refinement_role"] == "early_check_leader"
    )
    upstream_z = original["blue_crossing_z_offset_m"] - 0.0025
    middle_z = original["blue_crossing_z_offset_m"] - 0.00125
    return [
        ("focused_refinement_leader", leader),
        ("early_check_leader_control", original),
        ("red_green_plus_upstream_z", _replace(leader, blue_crossing_z_offset_m=upstream_z)),
        ("red_green_plus_middle_z", _replace(leader, blue_crossing_z_offset_m=middle_z)),
        ("blue_s0_minus_0p01", _replace(leader, blue_s0=leader["blue_s0"] - 0.01)),
        ("blue_s0_plus_0p01", _replace(leader, blue_s0=leader["blue_s0"] + 0.01)),
        (
            "blue_anchor_minus_0p05",
            _replace(leader, blue_detuning_anchor_gamma=leader["blue_detuning_anchor_gamma"] - 0.05),
        ),
        (
            "blue_anchor_plus_0p05",
            _replace(leader, blue_detuning_anchor_gamma=leader["blue_detuning_anchor_gamma"] + 0.05),
        ),
        ("angle_45", _replace(leader, blue_crossing_angle_deg=45.0)),
        ("angle_45p5", _replace(leader, blue_crossing_angle_deg=45.5)),
        ("green_s0_40", _replace(leader, green_s0=40.0)),
        ("green_waist_7p5mm", _replace(leader, green_waist_m=0.0075)),
        ("blue_waist_7p5mm", _replace(leader, blue_waist_m=0.0075)),
        (
            "hardware_waists_and_green_s0",
            _replace(leader, green_s0=40.0, green_waist_m=0.0075, blue_waist_m=0.0075),
        ),
        (
            "angle_45p5_middle_z",
            _replace(leader, blue_crossing_angle_deg=45.5, blue_crossing_z_offset_m=middle_z),
        ),
        (
            "hardware_waists_angle_45p5_middle_z",
            _replace(
                leader,
                green_s0=40.0,
                green_waist_m=0.0075,
                blue_waist_m=0.0075,
                blue_crossing_angle_deg=45.5,
                blue_crossing_z_offset_m=middle_z,
            ),
        ),
    ]


def _current_local_design(family, ranked, count=16):
    """Build a bounds-aware local closure without historical magic values."""
    leader = dict(ranked[0]["parameters"])
    bounds = _bounds(family)
    rows = [("focused_refinement_leader", leader)]
    signatures = {tuple(sorted(leader.items()))}
    for key in bounds:
        low, high = bounds[key]
        delta = 0.05 * (high - low)
        for direction, sign in (("down", -1.0), ("up", 1.0)):
            candidate = dict(leader)
            candidate[key] = min(max(candidate[key] + sign * delta, low), high)
            signature = tuple(sorted(candidate.items()))
            if signature == tuple(sorted(leader.items())) or signature in signatures:
                # At a boundary, use an inward step rather than duplicate center.
                candidate[key] = min(max(candidate[key] - 2 * sign * delta, low), high)
                signature = tuple(sorted(candidate.items()))
            if signature not in signatures:
                signatures.add(signature)
                rows.append((f"{key}_{direction}", candidate))
            if len(rows) == count:
                return rows
    for source in ranked[1:]:
        candidate = dict(source["parameters"])
        signature = tuple(sorted(candidate.items()))
        if signature not in signatures:
            signatures.add(signature)
            rows.append((f"refinement_anchor_{source['candidate_id']}", candidate))
        if len(rows) == count:
            return rows
    raise RuntimeError(f"Could only construct {len(rows)}/{count} unique closure points.")


def select(family, refinement_summary):
    summary = json.loads(Path(refinement_summary).read_text())
    if summary["family"] != family:
        raise ValueError("Refinement summary and requested family disagree.")
    rows = _current_local_design(family, summary["ranked_candidates"])
    if len(rows) != 16:
        raise AssertionError(f"Expected 16 closure candidates, built {len(rows)}.")
    candidates = [_candidate(family, index, role, params) for index, (role, params) in enumerate(rows)]
    signatures = {tuple(sorted(row["parameters"].items())) for row in candidates}
    if len(signatures) != len(candidates):
        raise ValueError("Closure design contains duplicate parameter points.")
    return {
        "kind": "mot_3d_local_closure_selection",
        "family": family,
        "candidate_count": len(candidates),
        "design": "bounds-aware local one-at-a-time closure around the refinement leader",
        "candidates": candidates,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("angled_donut", "single_pass"), required=True)
    parser.add_argument("--refinement-summary", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    payload = select(args.family, args.refinement_summary)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Saved {len(payload['candidates'])} candidates: {destination}")


if __name__ == "__main__":
    main()
