"""Lightweight single authority for the canonical fixed-s0 2D campaign design."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
)

ROLE_SEEDS = {
    "discovery": list(range(3000, 3005)),
    "refinement": list(range(3005, 3010)),
    "held_out_confirmation": list(range(3010, 3015)),
    "sealed_validation": list(range(3015, 3035)),
}

RELEVANT_FILES = (
    "workflow_api/acceptance_inputs.py",
    "config.py", "simulations/mot_2d.py", "studies/mot_2d_s0_campaign.py",
    "studies/mot_2d/optimization.py", "studies/mot_2d/production.py",
    "utils/optuna_replay.py",
    "utils/mot_2d_study.py", "utils/file_helpers.py", "utils/RK4StHybridCustom.py",
    "workflow_api/mot_2d_spec.py", "workflow_api/mot_2d_plan.py",
    "workflow_api/acceptance_profile.py",
    "workflow_api/specifications/ui_acceptance_v1.json",
    "workflow_api/platform_io.py",
    "workflow_api/mot_2d_sources.py",
    "workflow_api/smoke_receipt.py",
    "workflow_api/mot_2d_late_stage.py",
    "workflow_api/mot_2d_prediction.py",
    "workflow_api/mot_2d_validation.py",
    "workflow_api/mot_2d_statistical_verification.py",
    "workflow_api/repository_paths.py",
    "lab_setup/physical_specification.py",
    "lab_setup/historical_zeeman_source.py",
    "lab_setup/specifications/laboratory_physical_v1.json",
    "lab_setup/specifications/laboratory_physical_v2.json",
    "lab_setup/specifications/zeeman_model_conventions_v1.json",
    "lab_setup/zeeman_operating_specification.py",
    "lab_setup/specifications/zeeman_operating_v1.json",
    "lab_setup/mot_2d_operating_specification.py",
    "lab_setup/specifications/mot_2d_operating_v1.json",
    "lab_setup/strict_specification.py",
    "lab_setup/numerical_policy.py",
    "lab_setup/specifications/numerical_policy_v2.json",
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
    acceptance_profile_id: str | None = None,
) -> dict[str, Any]:
    frozen_inputs = deepcopy(frozen_inputs)
    records = [row for rows in frozen_inputs.values() for row in rows]
    historical_evidence = None
    if any(row.get("legacy_attested_profile") for row in records):
        from lab_setup.historical_zeeman_source import historical_source_evidence
        if acceptance_profile_id is not None:
            raise ValueError("Historical scientific inputs cannot be used as TEST ONLY inputs.")
        historical_evidence = historical_source_evidence(records)
        # A profile hash alone is not an original laboratory provenance trio.
        # Preserve legacy identity; do not label these inputs as current-spec.
        for row in records:
            row.pop("zeeman_profile_sha256", None)
    roles = deepcopy(ROLE_SEEDS)
    manifest = {
        "kind": "mot_2d_s0_campaign", "name": name, "stage": "smoke",
        "s0_values": list(s0_values), "stages": {},
        "ensemble_source": {
            "directory": ensemble_directory,
            "zeeman_profile": zeeman_profile,
            "laboratory_spec_version": LABORATORY_SPEC_VERSION,
            "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
            "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
        },
        "seed_roles": roles, "input_ensembles": frozen_inputs,
        "mot_seeds": {role: [40_000 + seed for seed in seeds] for role, seeds in roles.items()},
        "provenance": {
            "git_commit": git_commit, "physical_model_sha256": physical_model_sha256,
            "hashed_files": list(hashed_files),
            "capture_criterion_version": "mot_2d_extract_survivors_v1",
            "path_contract": "repository-relative-v1",
        },
        "fixed_design": deepcopy(FIXED_DESIGN),
    }
    if historical_evidence is not None:
        source = manifest["ensemble_source"]
        for key in ("laboratory_spec_version", "laboratory_spec_sha256", "zeeman_profile_sha256"):
            source.pop(key)
        source["historical_evidence"] = historical_evidence
    if acceptance_profile_id is not None:
        from workflow_api.acceptance_profile import load_acceptance_profile
        profile = load_acceptance_profile(acceptance_profile_id)
        manifest['kind'] = 'mot_2d_ui_acceptance_v1'
        manifest['acceptance'] = profile.provenance()
        manifest['fixed_design'] = acceptance_fixed_design()
        validate_campaign_policy(manifest)
    return manifest


def acceptance_fixed_design() -> dict[str, Any]:
    """Frozen physical design with only reviewed miniature workloads changed."""
    from workflow_api.acceptance_profile import load_acceptance_profile
    profile = load_acceptance_profile().family('mot_2d')
    design = deepcopy(FIXED_DESIGN)
    design['particle_counts'] = {
        stage: profile['stages'][stage]['particles_per_ensemble']
        for stage in FIXED_DESIGN['particle_counts']
    }
    design['trial_budgets'] = {
        f'{stage}_per_worker': profile['stages'][stage]['trials_per_worker']
        for stage in ('screen', 'refine')
    }
    return design


def validate_campaign_policy(manifest: dict[str, Any]):
    """Authenticate acceptance workloads; retain canonical historical behavior."""
    from workflow_api.acceptance_profile import policy_for_manifest
    if "kind" not in manifest and "acceptance" not in manifest:
        return None  # Internal historical projections can omit the kind.
    profile = policy_for_manifest(manifest)
    if profile is not None:
        if manifest['kind'] != 'mot_2d_ui_acceptance_v1':
            raise ValueError('Expected a 2D acceptance campaign.')
        if manifest.get('fixed_design') != acceptance_fixed_design():
            raise ValueError('Acceptance frozen design differs from its reviewed policy.')
        if manifest.get('seed_roles') != ROLE_SEEDS:
            raise ValueError('Acceptance seed roles differ from the reviewed registry.')
        if manifest.get('s0_values') != list(profile.family('mot_2d')['s0_values']):
            raise ValueError('Acceptance s0 differs from its reviewed policy.')
    return profile


def campaign_kind_matches(manifest: dict[str, Any]) -> bool:
    if manifest.get('kind') == 'mot_2d_s0_campaign':
        from workflow_api.acceptance_profile import policy_for_manifest
        policy_for_manifest(manifest)
        return True
    if manifest.get('kind') == 'mot_2d_ui_acceptance_v1':
        validate_campaign_policy(manifest)
        return True
    return False


def stage_npools(manifest: dict[str, Any], stage: str, canonical: int) -> int:
    profile = validate_campaign_policy(manifest)
    return profile.stage('mot_2d', stage)['npools'] if profile else canonical


def refinement_targets(manifest: dict[str, Any]) -> tuple[int, ...]:
    profile = validate_campaign_policy(manifest)
    return tuple(profile.family('mot_2d')['refinement_cumulative_targets']) if profile else (3, 6, 9, 10)


def survivor_states_directory(manifest: dict[str, Any], campaign_root, value: float):
    from pathlib import Path
    profile = validate_campaign_policy(manifest)
    label = f'{float(value):.6f}'.rstrip('0').rstrip('.')
    if profile:
        return Path(campaign_root) / 'survivor_states' / f's0_{label}'
    return Path('data/particle_states/after_2d_mot') / f'final_ensemble_s0_{label}'


def reviewed_job_resources(manifest: dict[str, Any], stage: str, canonical: dict[str, Any]) -> dict[str, Any]:
    """One explicit hook for review DTOs and remote submission validators."""
    profile = validate_campaign_policy(manifest)
    result = dict(canonical)
    if profile:
        policy = profile.stage('mot_2d', stage)
        result.update(cores_per_task=policy['ncpus'], memory_per_task_bytes=policy['memory_gb'] * 1024**3,
                      walltime_seconds=policy['walltime_seconds'])
        vnode = profile.policy.get('scheduler', {}).get('vnode')
        if vnode is not None:
            result['vnode'] = vnode
    return result


def trial_budget(manifest: dict[str, Any], stage: str) -> int:
    profile = validate_campaign_policy(manifest)
    return profile.stage('mot_2d', stage)['trials_per_worker'] if profile else {'screen': 17, 'refine': 10}[stage]


def authorize_review_target(manifest, profile, campaign, repository_root, error_type):
    """Match the frozen workload to its remote checkout before any stage review."""
    from workflow_api.acceptance_remote import assert_campaign_target
    try:
        # Internal reviewed projections historically omit the discriminator.
        # Public registry reads authenticate it before producing these projections.
        if "kind" not in manifest:
            from workflow_api.acceptance_profile import assert_scientific_source
            assert_scientific_source(manifest)
            manifest = {"kind": "mot_2d_s0_campaign", **manifest}
        assert_campaign_target(manifest, profile.username, profile.project_directory,
                               campaign.relative_to(repository_root).as_posix())
    except ValueError as error:
        raise error_type('profile_invalid') from error


def project_historical_manifest(current: dict[str, Any], stage: str, expected_sha256: str) -> dict[str, Any]:
    """Prove one bounded historical manifest for read-only receipt inspection.

    Callers must never use this projection to authorize a submission or publish
    a transition. The current manifest is never changed, unknown fields remain,
    and the exact independently frozen predecessor hash is mandatory.
    """
    import hashlib
    import json
    import re

    order = ('smoke', 'screen', 'refine', 'confirmation', 'sensitivity', 'production', 'complete')
    if (not isinstance(current, dict) or not campaign_kind_matches(current)
            or stage not in order or current.get('stage') not in order
            or order.index(current['stage']) < order.index(stage)
            or not isinstance(expected_sha256, str)
            or re.fullmatch(r'[0-9a-f]{64}', expected_sha256) is None):
        raise ValueError('Invalid historical campaign projection.')
    validate_campaign_policy(current)
    projected = deepcopy(current)
    projected['stage'] = stage
    stages = projected.get('stages')
    if stages is not None:
        if not isinstance(stages, dict):
            raise ValueError('Invalid historical campaign stage registry.')
        for later in order[order.index(stage) + 1:]:
            stages.pop(later, None)
        if stage != 'complete':
            stages.pop('final_report', None)
    candidates = [projected]
    if stages == {}:
        without_empty_registry = deepcopy(projected)
        without_empty_registry.pop('stages')
        candidates.append(without_empty_registry)
    for candidate in candidates:
        raw = (json.dumps(candidate, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
        if hashlib.sha256(raw).hexdigest() == expected_sha256:
            return candidate
    raise ValueError('Historical campaign differs from its exact frozen hash.')


def sensitivity_task_count(manifest: dict[str, Any]) -> int:
    """Read the frozen, canonically derived clamped/deduplicated point count."""
    validate_campaign_policy(manifest)
    count = manifest.get('stages', {}).get('sensitivity', {}).get('tasks')
    values = manifest.get('s0_values')
    if (type(count) is not int or not isinstance(values, list) or not values
            or not 1 <= count <= 17 * len(values)):
        raise ValueError('Invalid frozen sensitivity task count.')
    return count
