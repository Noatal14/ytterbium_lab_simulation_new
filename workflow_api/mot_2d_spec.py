"""Lightweight single authority for the canonical fixed-s0 2D campaign design."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

ROLE_SEEDS = {
    "discovery": list(range(3000, 3005)),
    "refinement": list(range(3005, 3010)),
    "held_out_confirmation": list(range(3010, 3015)),
    "sealed_validation": list(range(3015, 3035)),
}

RELEVANT_FILES = (
    "config.py", "simulations/mot_2d.py", "studies/mot_2d_s0_campaign.py",
    "studies/mot_2d/optimization.py", "studies/mot_2d/production.py",
    "utils/mot_2d_study.py", "utils/file_helpers.py", "utils/RK4StHybridCustom.py",
    "workflow_api/mot_2d_spec.py", "workflow_api/mot_2d_plan.py",
    "workflow_api/mot_2d_sources.py",
)

FIXED_DESIGN: dict[str, Any] = {
    "working_dt_s": 1.25e-6, "final_dt_s": 0.625e-6,
    "solver": "RK4StHybridCustom",
    "detuning_bounds_gamma": [-1.55, -0.85],
    "magnet_radius_bounds_m": [0.045, 0.051],
    "detuning_resolution_gamma": 0.01, "magnet_radius_resolution_m": 1e-5,
    "target_95_half_width_fraction": 0.0005,
    "reporting_zeeman_survivors": 10_000_000,
    "particle_counts": {"screen": 2000, "refine": 10000, "confirmation": 10000, "sensitivity": 10000, "production": "all_available"},
    "trial_budgets": {"screen_per_worker": 17, "refine_per_worker": 10},
    "control_resolution": {"status": "provisional", "detuning_gamma": 0.01, "magnet_radius_m": 1e-5},
    "stress_test_offsets": {"detuning_gamma": 0.02, "magnet_radius_m": 0.0001},
}


def build_manifest(
    *, name: str, s0_values: list[float], ensemble_directory: str,
    zeeman_profile: str, frozen_inputs: dict[str, list[dict[str, Any]]],
    git_commit: str, physical_model_sha256: str, hashed_files: list[str],
) -> dict[str, Any]:
    roles = deepcopy(ROLE_SEEDS)
    return {
        "kind": "mot_2d_s0_campaign", "name": name, "stage": "smoke",
        "s0_values": list(s0_values), "stages": {},
        "ensemble_source": {"directory": ensemble_directory, "zeeman_profile": zeeman_profile},
        "seed_roles": roles, "input_ensembles": frozen_inputs,
        "mot_seeds": {role: [40_000 + seed for seed in seeds] for role, seeds in roles.items()},
        "provenance": {
            "git_commit": git_commit, "physical_model_sha256": physical_model_sha256,
            "hashed_files": list(hashed_files),
            "capture_criterion_version": "mot_2d_extract_survivors_v1",
        },
        "fixed_design": deepcopy(FIXED_DESIGN),
    }
