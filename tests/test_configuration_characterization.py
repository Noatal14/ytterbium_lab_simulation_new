"""Characterize every active configuration authority without changing it."""

from __future__ import annotations

import ast
from dataclasses import asdict, is_dataclass
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType

import numpy as np

import config
from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    LABORATORY_PHYSICAL_SPECIFICATION,
)
from lab_setup.numerical_policy import NUMERICAL_POLICY
from simulations.zeeman import _resolved_run_parameters
from studies import mot_2d_s0_campaign, mot_3d_campaign
from studies.mot_2d.optimization import BOUNDS_DETUNING, BOUNDS_MAGNET_RADIUS_M
from studies.zeeman import generate_ensembles
from workflow_api import mot_2d_spec
from workflow_api.mot_2d_specification import MOT_2D_SPECIFICATION


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_CONFIG_CONSUMERS = {
    "graphs_scripts/mot_3d_velocity_style.py", "graphs_scripts/plot_3d_mot_configurations.py",
    "lab_setup/_3d_mot_mag_field.py", "lab_setup/atom_species.py", "lab_setup/config_builder.py",
    "lab_setup/laser_setup_2d_mot.py", "lab_setup/laser_setup_3d.py",
    "lab_setup/zeeman_laser_setup.py", "lab_setup/zones.py",
    "simulations/mot_2d.py", "simulations/mot_3d.py", "simulations/pipeline.py",
    "simulations/thermal_beam.py", "simulations/zeeman.py",
    "studies/beam_source/estimate_oven_flux.py", "studies/beam_source/full_thermal_flux.py",
    "studies/mot_2d/optimization.py", "studies/mot_2d/production.py",
    "studies/mot_2d/validation/photon_counts.py", "studies/mot_2d_s0_campaign.py",
    "studies/mot_3d/analysis/retention.py", "studies/mot_3d/discovery/optimize.py",
    "studies/mot_3d/discovery/select.py", "studies/mot_3d/finalists/run.py",
    "studies/mot_3d/preliminary/run.py", "studies/mot_3d/refinement/run.py",
    "studies/mot_3d/refinement/select.py", "studies/mot_3d/refinement/select_closure.py",
    "studies/mot_3d/timestep_validation.py",
    "studies/mot_3d/validation/single_pass_stability.py", "studies/mot_3d_campaign.py",
    "studies/zeeman/capture_velocity.py", "studies/zeeman/generate_ensembles.py",
    "studies/zeeman/stochastic_convergence.py", "studies/zeeman/trajectories.py",
    "studies/zeeman/validate_configuration.py", "utils/simulation_helpers.py",
    "workflow_api/zeeman_local_execution.py", "workflow_api/zeeman_run_plan.py",
    "workflow_api/zeeman_run_specification.py",
}
EXPECTED_EXECUTABLE_SPEC_CONSUMERS = {
    "studies/mot_2d_s0_campaign.py", "workflow_api/mot_2d_plan.py",
    "workflow_api/repository_snapshot.py",
}
EXPECTED_VERSIONED_SPEC_CONSUMERS = {
    "tools/verify_mot_2d_specification.py", "workflow_api/mutation.py",
    "workflow_api/zeus_transfer.py",
}
EXPECTED_NUMERICAL_POLICY_CONSUMERS = {"config.py", "workflow_api/zeeman_run_plan.py"}


def _normalize(value):
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, (dict, MappingProxyType)):
        return {str(key): _normalize(child) for key, child in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_normalize(child) for child in value]
    if isinstance(value, np.ndarray):
        return _normalize(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _resolved_baseline_payload():
    versioned_spec = json.loads(
        (ROOT / "workflow_api/specifications/mot_2d_v1.json").read_text(encoding="utf-8")
    )
    geometry = {
        name: getattr(config.Geometry, name)
        for name in sorted(vars(config.Geometry)) if name.isupper()
    }
    return _normalize({
        "physical": {
            "MU_B_OVER_H_KHZ_PER_G": config.MU_B_OVER_H_KHZ_PER_G,
            "AMU_KG": config.AMU_KG, "BOLTZMANN_CONSTANT_J_K": config.BOLTZMANN_CONSTANT_J_K,
            "YB171": config.YB171, "BLUE_TRANSITION": config.BLUE_TRANSITION,
            "GREEN_TRANSITION": config.GREEN_TRANSITION,
            "BLUE_TRANSITION_LANDE_G_J": config.BLUE_TRANSITION_LANDE_G_J,
            "GREEN_TRANSITION_LANDE_G_J": config.GREEN_TRANSITION_LANDE_G_J,
            "BLUE_TRANSITION_ZEEMAN_COEFFICIENT_KHZ_PER_G": config.BLUE_TRANSITION_ZEEMAN_COEFFICIENT_KHZ_PER_G,
            "GREEN_TRANSITION_ZEEMAN_COEFFICIENT_KHZ_PER_G": config.GREEN_TRANSITION_ZEEMAN_COEFFICIENT_KHZ_PER_G,
            "BLUE_SATURATION_INTENSITY_MW_CM2": config.BLUE_SATURATION_INTENSITY_MW_CM2,
            "BLUE_CALCULATED_SATURATION_INTENSITY_W_M2": config.BLUE_CALCULATED_SATURATION_INTENSITY_W_M2,
            "BLUE_CALCULATED_SATURATION_INTENSITY_MW_CM2": config.BLUE_CALCULATED_SATURATION_INTENSITY_MW_CM2,
            "GREEN_SATURATION_INTENSITY_W_M2": config.GREEN_SATURATION_INTENSITY_W_M2,
            "GREEN_SATURATION_INTENSITY_MW_CM2": config.GREEN_SATURATION_INTENSITY_MW_CM2,
        },
        "versioned_laboratory_physical_contract": LABORATORY_PHYSICAL_SPECIFICATION,
        "versioned_numerical_policy": NUMERICAL_POLICY,
        "geometry": geometry,
        "beam_source": {
            "ZEEMAN_BEAM_DIRECTION": config.ZEEMAN_BEAM_DIRECTION,
            "OVEN_TEMPERATURE_C": config.OVEN_TEMPERATURE_C,
            "COLLIMATION_ANGLE_DEG": config.COLLIMATION_ANGLE_DEG,
            "OVEN_MICROTUBE_COUNT": config.OVEN_MICROTUBE_COUNT,
            "YB171_NATURAL_ABUNDANCE": config.YB171_NATURAL_ABUNDANCE,
        },
        "zeeman": {
            "profiles": config.ZEEMAN_MAGNET_PROFILES,
            "active_profile": config.ACTIVE_ZEEMAN_MAGNET_PROFILE,
            "field": config.ZEEMAN_FIELD_CONFIG, "laser": config.ZEEMAN_LASER_CONFIG,
            "simulation": config.ZEEMAN_SIM_CONFIG,
        },
        "mot_2d": {
            "magnet_radius_m": config.MOT_2D_MAGNET_RADIUS_M,
            "laser": config.MOT_2D_LASER_CONFIG, "simulation": config.MOT_2D_SIM_CONFIG,
            "force_scale_n": config.FORCE_SCALE_N,
        },
        "mot_3d": {
            "default_gradient_G_cm": config.MOT_3D_MAGNETIC_FIELD_GRADIENT_G_CM,
            "optimization": config.MOT_3D_OPTIMIZATION_CONFIG,
            "configurations": config.MOT_3D_CONFIGURATIONS,
            "active_configuration": config.ACTIVE_MOT_3D_CONFIGURATION,
            "active_laser": config.MOT_3D_LASER_CONFIG,
            "simulation": config.MOT_3D_SIM_CONFIG, "capture": config.MOT_3D_CAPTURE_CONFIG,
        },
        "full_simulation": config.FULL_SIM_CONFIG,
        "runtime": {"default_num_particles": config.DEFAULT_NUM_PARTICLES,
                    "default_random_seed": config.DEFAULT_RANDOM_SEED,
                    "default_num_pools": config.DEFAULT_NUM_POOLS},
        "mot_2d_executable_campaign": {
            "role_seeds": mot_2d_spec.ROLE_SEEDS, "relevant_files": mot_2d_spec.RELEVANT_FILES,
            "fixed_design": mot_2d_spec.FIXED_DESIGN,
            "stage_role": mot_2d_s0_campaign.STAGE_ROLE,
            "refinement_cumulative_targets": mot_2d_s0_campaign.REFINEMENT_CUMULATIVE_TARGETS,
            "screen_walltime": mot_2d_s0_campaign.SCREEN_WALLTIME,
            "refinement_round_walltime": mot_2d_s0_campaign.REFINEMENT_ROUND_WALLTIME,
            "confirmation_candidates": mot_2d_s0_campaign.CONFIRMATION_CANDIDATES,
            "capture_criterion_version": mot_2d_s0_campaign.CAPTURE_CRITERION_VERSION,
            "default_profile": mot_2d_s0_campaign.DEFAULT_PROFILE,
        },
        "mot_2d_versioned_ui_job_contract": versioned_spec,
        "mot_3d_campaign": {
            "families": mot_3d_campaign.FAMILIES, "expected_seeds": mot_3d_campaign.EXPECTED_SEEDS,
            "role_seeds": mot_3d_campaign.ROLE_SEEDS, "sampler_seeds": mot_3d_campaign.SAMPLER_SEEDS,
            "discovery_rounds": mot_3d_campaign.DISCOVERY_ROUNDS,
            "final_validation_zeeman_seeds": mot_3d_campaign.FINAL_VALIDATION_ZEEMAN_SEEDS,
            "final_validation_mot_seeds": mot_3d_campaign.FINAL_VALIDATION_MOT_SEEDS,
        },
    })


def _canonical_sha256(value):
    encoded = json.dumps(_normalize(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _direct_imports(module_name):
    consumers, imported_names = set(), {}
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(("tests/", "atomsmltr/tests/")):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names, found = set(), False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == module_name:
                found = True
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import) and any(alias.name == module_name for alias in node.names):
                found = True
        if found:
            consumers.add(relative)
            imported_names[relative] = names
    return consumers, imported_names


def _walk_numbers(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_numbers(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_numbers(child)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield value


def test_complete_normalized_resolved_baseline_has_golden_hash():
    payload = _resolved_baseline_payload()
    assert all(math.isfinite(value) for value in _walk_numbers(payload))
    assert _canonical_sha256(payload) == (
        "de6e5625555b6f021dd76193ecf7adba1d3fe53ff7b4ea830400067f5cc2bd9a"
    )


def test_atomic_geometry_beam_and_source_cross_field_invariants():
    physical = LABORATORY_PHYSICAL_SPECIFICATION
    assert physical["species"]["name"] == config.YB171_NAME
    assert physical["species"]["mass_amu"] == config.YB171_MASS_AMU
    assert physical["transitions"]["blue"]["wavelength_m"] == config.BLUE_TRANSITION_WAVELENGTH_M
    assert physical["transitions"]["blue"]["gamma_rad_s"] == config.BLUE_TRANSITION_GAMMA_RAD_S
    assert physical["transitions"]["green"]["wavelength_m"] == config.GREEN_TRANSITION_WAVELENGTH_M
    assert physical["transitions"]["green"]["gamma_rad_s"] == config.GREEN_TRANSITION_GAMMA_RAD_S
    assert physical["source"]["oven_temperature_C"] == config.OVEN_TEMPERATURE_C
    assert physical["source"]["collimation_angle_deg"] == config.COLLIMATION_ANGLE_DEG
    assert physical["apparatus"]["science_region_center_z_m"] == config.Geometry.SCIENCE_REGION_CENTER_Z_M
    assert tuple(config.Atom.__dataclass_fields__) == ("name", "mass_kg", "mass_amu")
    assert tuple(config.Transition.__dataclass_fields__) == (
        "wavelength_m", "gamma_rad_s", "lande_g"
    )
    for name in (name for name in vars(config.Geometry) if name.isupper()):
        assert name == "Z_AXIS" or name.endswith(("_M", "_DEG", "_RAD"))
    assert config.YB171.mass_kg > 0
    assert config.YB171.mass_amu == config.YB171_MASS_AMU
    assert config.BLUE_TRANSITION.wavelength_m == config.BLUE_TRANSITION_WAVELENGTH_M
    assert config.GREEN_TRANSITION.gamma_rad_s == config.GREEN_TRANSITION_GAMMA_RAD_S
    assert config.BLUE_TRANSITION.gamma_rad_s > config.GREEN_TRANSITION.gamma_rad_s > 0
    assert config.BLUE_SATURATION_INTENSITY_MW_CM2 > 0
    assert config.GREEN_SATURATION_INTENSITY_W_M2 > 0
    assert np.isclose(np.linalg.norm(config.ZEEMAN_BEAM_DIRECTION), 1.0)
    assert config.Geometry.OVEN_MICROTUBE_LENGTH_M > config.Geometry.OVEN_MICROTUBE_RADIUS_M > 0
    assert config.Geometry.MOT_2D_CHAMBER_RADIUS_M > 0
    assert config.Geometry.SCIENCE_REGION_CENTER_Z_M == config.Geometry.MOT_3D_CENTER_M[2]
    assert 0 < config.YB171_NATURAL_ABUNDANCE < 1
    assert config.OVEN_MICROTUBE_COUNT > 0


def test_numerical_policy_facade_equivalence_and_separate_campaign_authority():
    assert config.ZEEMAN_SIM_CONFIG["dt_s"] == NUMERICAL_POLICY["zeeman"]["dt_s"]
    assert config.ZEEMAN_SIM_CONFIG["t_max_s"] == NUMERICAL_POLICY["zeeman"]["t_max_s"]
    assert config.MOT_2D_SIM_CONFIG["dt_s"] == NUMERICAL_POLICY["mot_2d"]["dt_s"]
    assert config.MOT_2D_SIM_CONFIG["t_max_s"] == NUMERICAL_POLICY["mot_2d"]["t_max_s"]
    assert config.MOT_3D_SIM_CONFIG == {
        key: (tuple(value) if key == "dt_validation_candidates_s" else value)
        for key, value in NUMERICAL_POLICY["mot_3d"].items()
    }
    assert mot_2d_spec.FIXED_DESIGN["working_dt_s"] == 1.25e-6
    assert mot_2d_spec.FIXED_DESIGN["final_dt_s"] == 0.625e-6
    assert "trial_budgets" not in NUMERICAL_POLICY["mot_2d"]
    assert "particle_counts" not in NUMERICAL_POLICY["mot_2d"]


def test_numerical_policy_direct_consumer_ledger_is_complete():
    consumers, _ = _direct_imports("lab_setup.numerical_policy")
    assert consumers == EXPECTED_NUMERICAL_POLICY_CONSUMERS


def test_zeeman_profiles_and_corrected_generator_metadata_binding():
    for radii_m, positions_m, tilts_deg in config.ZEEMAN_MAGNET_PROFILES.values():
        assert len(radii_m) == len(positions_m) == len(tilts_deg)
        assert all(radius > 0 and math.isfinite(radius) for radius in radii_m)
        assert all(math.isfinite(value) for value in (*positions_m, *tilts_deg))
        assert all(left < right for left, right in zip(positions_m, positions_m[1:]))
    active = config.ZEEMAN_MAGNET_PROFILES[config.ACTIVE_ZEEMAN_MAGNET_PROFILE]
    corrected = config.ZEEMAN_MAGNET_PROFILES[generate_ensembles.PROFILE_NAME]
    assert "active" not in config.ZEEMAN_MAGNET_PROFILES
    assert config.ACTIVE_ZEEMAN_MAGNET_PROFILE == CANONICAL_ZEEMAN_PROFILE_NAME
    assert active is corrected
    assert generate_ensembles.PROFILE_NAME == "corrected_projectant_19ring_20261005"
    assert generate_ensembles.OUTPUT_DIR.name == generate_ensembles.PROFILE_NAME
    assert generate_ensembles.N_INITIAL == config.DEFAULT_NUM_PARTICLES
    assert tuple(map(len, corrected)) == (19, 19, 19)
    assert _canonical_sha256(corrected) == "7159e48b25124c3083b0dfa004f07bfdad8ad1aa6ae840a7bae1db970ab7d534"
    assert generate_ensembles.corrected_field() == {
        "radii_m": corrected[0], "positions_m": corrected[1], "tilt_angles_deg": corrected[2]
    }
    resolved = _resolved_run_parameters({"zeeman_field_config": generate_ensembles.corrected_field()})
    assert resolved["resolved_zeeman_magnet_profile"] == generate_ensembles.PROFILE_NAME
    assert resolved["active_zeeman_magnet_profile"] == generate_ensembles.PROFILE_NAME
    assert resolved["dt_s"] == config.ZEEMAN_SIM_CONFIG["dt_s"]
    assert resolved["collimation_angle_deg"] == config.COLLIMATION_ANGLE_DEG


def test_red_detunings_positive_intensities_bounds_and_time_coherence():
    assert config.MOT_3D_LASER_CONFIG is config.MOT_3D_CONFIGURATIONS[
        config.ACTIVE_MOT_3D_CONFIGURATION
    ]
    assert set(config.ZEEMAN_FIELD_CONFIG) == {
        "radii_m", "positions_m", "tilt_angles_deg"
    }
    assert set(config.ZEEMAN_SIM_CONFIG) == {
        "t_max_s", "dt_s", "start_distance_m", "cutoff_distance_m"
    }
    assert set(config.MOT_2D_SIM_CONFIG) == {"t_max_s", "dt_s", "start_distance_m"}
    assert set(config.FULL_SIM_CONFIG) == {"dt_s", "t_max_s", "start_distance_m"}
    assert config.ZEEMAN_LASER_CONFIG["detuning_gamma"] < 0
    assert config.MOT_2D_LASER_CONFIG["detuning_gamma"] < 0
    assert config.ZEEMAN_LASER_CONFIG["s0"] > 0
    assert config.MOT_2D_LASER_CONFIG["s0"] > 0
    for family in config.MOT_3D_CONFIGURATIONS.values():
        for color in ("399", "556"):
            assert family[color]["s0"] > 0
            assert family[color]["detuning_gamma"] < 0
            assert family[color]["waist_m"] > 0
    for stage in (config.ZEEMAN_SIM_CONFIG, config.MOT_2D_SIM_CONFIG, config.MOT_3D_SIM_CONFIG, config.FULL_SIM_CONFIG):
        assert stage["dt_s"] > 0
        assert stage["t_max_s"] > stage["dt_s"]
    assert config.ZEEMAN_SIM_CONFIG["start_distance_m"] > config.ZEEMAN_SIM_CONFIG["cutoff_distance_m"] > 0
    assert config.FULL_SIM_CONFIG["start_distance_m"] == config.ZEEMAN_SIM_CONFIG["start_distance_m"]
    assert config.MOT_3D_SIM_CONFIG["dt_validation_reference_s"] < min(config.MOT_3D_SIM_CONFIG["dt_validation_candidates_s"])
    assert all(left > right for left, right in zip(config.MOT_3D_SIM_CONFIG["dt_validation_candidates_s"], config.MOT_3D_SIM_CONFIG["dt_validation_candidates_s"][1:]))

    def assert_bounds(node):
        for key, value in node.items():
            if isinstance(value, dict):
                assert_bounds(value)
            elif key.endswith("_bounds"):
                assert len(value) == 2 and value[0] < value[1]
                if "detuning" in key:
                    assert value[1] < 0
                if any(token in key for token in ("s0", "waist", "radius", "gradient")):
                    assert value[0] > 0
    assert_bounds(config.MOT_3D_OPTIMIZATION_CONFIG)


def test_three_2d_authorities_are_exactly_coherent_where_they_overlap():
    display, fixed = _normalize(MOT_2D_SPECIFICATION), mot_2d_spec.FIXED_DESIGN
    assert mot_2d_s0_campaign.SEED_ROLES is mot_2d_spec.ROLE_SEEDS
    assert mot_2d_s0_campaign.RELEVANT_CODE_FILES == list(mot_2d_spec.RELEVANT_FILES)
    assert config.MOT_2D_SIM_CONFIG["dt_s"] == mot_2d_s0_campaign.FINAL_DT_S == fixed["final_dt_s"] == display["design"]["final_dt_s"]
    assert mot_2d_s0_campaign.WORKING_DT_S == fixed["working_dt_s"] == display["design"]["working_dt_s"]
    assert fixed["solver"] == display["design"]["solver"] == "RK4StHybridCustom"
    assert mot_2d_s0_campaign.SCREEN_TRIALS == fixed["trial_budgets"]["screen_per_worker"] == display["design"]["screen_trials_per_worker"]
    assert mot_2d_s0_campaign.REFINE_TRIALS == fixed["trial_budgets"]["refine_per_worker"] == display["design"]["refine_trials_per_worker"]
    assert mot_2d_s0_campaign.CONFIRMATION_CANDIDATES == display["design"]["confirmation_candidates_per_s0"]
    assert list(BOUNDS_DETUNING) == fixed["detuning_bounds_gamma"]
    assert list(BOUNDS_MAGNET_RADIUS_M) == fixed["magnet_radius_bounds_m"]
    assert mot_2d_s0_campaign.REFINEMENT_CUMULATIVE_TARGETS == tuple(display["stages"]["refine"]["cumulative_trial_targets"])
    assert display["stages"]["screen"]["walltime_seconds"] == 24 * 60 * 60
    assert display["stages"]["refine"]["walltime_seconds"] == 20 * 60 * 60


def test_ast_discovered_configuration_consumer_ledgers_are_complete():
    consumers, imported = _direct_imports("config")
    assert consumers == EXPECTED_CONFIG_CONSUMERS
    for path, names in imported.items():
        missing = sorted(name for name in names if name != "*" and not hasattr(config, name))
        assert not missing, f"{path} imports missing config symbols: {missing}"
    consumers, imported = _direct_imports("workflow_api.mot_2d_spec")
    assert consumers == EXPECTED_EXECUTABLE_SPEC_CONSUMERS
    for path, names in imported.items():
        missing = sorted(name for name in names if name != "*" and not hasattr(mot_2d_spec, name))
        assert not missing, f"{path} imports missing executable spec symbols: {missing}"
    consumers, _ = _direct_imports("workflow_api.mot_2d_specification")
    assert consumers == EXPECTED_VERSIONED_SPEC_CONSUMERS
