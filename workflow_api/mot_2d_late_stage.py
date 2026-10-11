"""Pure scientific derivations for the late fixed-s0 2D-MOT stages."""

from __future__ import annotations

import math
from typing import Any

from utils.mot_2d_study import student_mean_interval


def paired_comparison(
    candidate: dict[str, Any],
    reference: dict[str, Any],
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Compare exactly aligned replicate evidence with a paired interval."""
    candidate_replicates = candidate["evaluation"]["replicates"]
    reference_replicates = reference["evaluation"]["replicates"]
    if not candidate_replicates or len(candidate_replicates) != len(reference_replicates):
        raise ValueError("Replicates are not paired")
    differences = []
    for left, right in zip(candidate_replicates, reference_replicates):
        if any(
            left[key] != right[key]
            for key in ("zeeman_seed", "mot_seed", "n_input", "subset_seed")
        ):
            raise ValueError("Replicates are not paired")
        left_efficiency = float(left["conditional_efficiency"])
        right_efficiency = float(right["conditional_efficiency"])
        if not math.isfinite(left_efficiency) or not math.isfinite(right_efficiency):
            raise ValueError("Replicates are not paired")
        differences.append(left_efficiency - right_efficiency)
    mean, low, high, half = student_mean_interval(
        differences, confidence=confidence
    )
    return {
        "mean_difference_fraction": mean,
        "95_ci_fraction": [low, high],
        "95_ci_half_width_fraction": half,
        "differences_fraction": differences,
    }


def select_production_point(
    rows: list[dict[str, Any]],
    reference: dict[str, Any],
    *,
    target_loss_fraction: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Choose a clearly superior tested neighbor, otherwise the center."""
    if not math.isfinite(target_loss_fraction) or target_loss_fraction < 0.0:
        raise ValueError("target_loss_fraction must be finite and non-negative")
    point_summaries = []
    clearly_better = []
    familywise_confidence = 1.0 - 0.05 / max(1, len(rows) - 1)
    for row in rows:
        comparison = paired_comparison(
            row, reference, confidence=familywise_confidence
        )
        summary = {
            "parameters": row["parameters"],
            "offsets": row["offsets"],
            "mean_efficiency": row["evaluation"]["statistics"][
                "mean_conditional_efficiency"
            ],
            "comparison_to_reference": comparison,
            "within_loss_margin_at_95_percent": bool(
                comparison["95_ci_fraction"][0] >= -target_loss_fraction
            ),
        }
        point_summaries.append(summary)
        if comparison["95_ci_fraction"][0] > 0.0:
            clearly_better.append(summary)

    if clearly_better:
        selected = max(
            clearly_better,
            key=lambda item: (
                item["comparison_to_reference"]["95_ci_fraction"][0],
                item["mean_efficiency"],
            ),
        )
        reason = "sensitivity_neighbor_clearly_better_at_95_percent"
    else:
        selected = next(
            item for item in point_summaries
            if item["offsets"]
            == {"detuning_gamma": 0.0, "magnet_radius_m": 0.0}
        )
        reason = "no_sensitivity_neighbor_clearly_better_at_95_percent"

    return point_summaries, {
        "parameters": selected["parameters"],
        "offsets_from_confirmed_winner": selected["offsets"],
        "mean_efficiency": selected["mean_efficiency"],
        "comparison_to_confirmed_winner": selected["comparison_to_reference"],
        "selection_reason": reason,
        "familywise_method": "Bonferroni simultaneous paired intervals",
        "familywise_confidence_per_comparison": familywise_confidence,
    }


def derive_production_transition(
    manifest: dict[str, Any],
    confirmation_rows: list[dict[str, Any]],
    sensitivity_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Derive the exact sensitivity summary and sealed production registry."""
    target_loss_fraction = float(
        manifest["fixed_design"]["target_95_half_width_fraction"]
    )
    if not math.isfinite(target_loss_fraction) or target_loss_fraction < 0.0:
        raise ValueError("Invalid frozen target_95_half_width_fraction.")
    sensitivity: dict[str, Any] = {}
    for value in manifest["s0_values"]:
        confirmed = [row for row in confirmation_rows if row["s0"] == value]
        confirmed.sort(key=lambda row: (
            -row["evaluation"]["statistics"]["conditional_95_ci"][0],
            -row["evaluation"]["statistics"]["mean_conditional_efficiency"],
            row["candidate_index"],
        ))
        if len(confirmed) != 5:
            raise ValueError(f"Invalid confirmation candidate count for s0={value}.")
        rows = [row for row in sensitivity_rows if row["s0"] == value]
        if not rows:
            raise ValueError(f"Sensitivity results are missing for s0={value}.")
        reference = next(
            row for row in rows
            if row["offsets"]
            == {"detuning_gamma": 0.0, "magnet_radius_m": 0.0}
        )
        points, selection = select_production_point(
            rows,
            reference,
            target_loss_fraction=target_loss_fraction,
        )
        key = f"s0_{float(value):.6f}".replace(".", "p")
        sensitivity[key] = {
            "reference": confirmed[0]["parameters"],
            "points": points,
            "production_selection": selection,
            "robustness_status": (
                "not_established_pending_adaptive_challenger_validation"
            ),
            "near_optimality_status": (
                "not_established_pending_domain_challenger_elimination"
            ),
        }

    sealed = manifest["seed_roles"]["sealed_validation"]
    mot_seeds = manifest["mot_seeds"]["sealed_validation"]
    tasks = [
        {
            "s0": value,
            "zeeman_seed": seed,
            "mot_seed": mot_seeds[sealed.index(seed)],
            "parameters": sensitivity[
                f"s0_{float(value):.6f}".replace(".", "p")
            ]["production_selection"]["parameters"],
        }
        for value in manifest["s0_values"]
        for seed in sealed
    ]
    return sensitivity, tasks
