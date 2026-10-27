import json
from pathlib import Path
from types import MappingProxyType

import pytest

from studies.mot_3d.discovery.optimize import build_profile_from_parameters
from lab_setup.numerical_policy import NUMERICAL_POLICY_SHA256, NUMERICAL_POLICY_VERSION
from lab_setup.physical_specification import LABORATORY_SPEC_SHA256, LABORATORY_SPEC_VERSION
from workflow_api.mot_3d_run_specification import (
    MOT_3D_RUN_SPECIFICATION,
    MOT_3D_RUN_SPEC_SHA256,
    MOT_3D_RUN_SPEC_VERSION,
)
import workflow_api.mot_3d_run_specification as specification


def test_individual_3d_spec_is_versioned_immutable_and_policy_bound():
    spec = MOT_3D_RUN_SPECIFICATION
    assert MOT_3D_RUN_SPEC_VERSION == "mot-3d-individual-v1"
    assert len(MOT_3D_RUN_SPEC_SHA256) == 64
    assert isinstance(spec, MappingProxyType)
    assert spec["particle_count"]["maximum_by_execution_mode"] == {
        "local": 1000,
        "zeus": 50000,
    }
    assert spec["authority_references"] == {
        "laboratory_specification": {
            "version": LABORATORY_SPEC_VERSION,
            "sha256": LABORATORY_SPEC_SHA256,
        },
        "numerical_policy": {
            "version": NUMERICAL_POLICY_VERSION,
            "sha256": NUMERICAL_POLICY_SHA256,
        },
    }
    assert spec["fixed_classification"] == {
        "suitability": "individual_only",
        "solver": "RK4StHybridCustom",
        "timestep_s": 10e-6,
        "t_max_s": 0.1,
        "convergence_claim": "not_established",
        "gravity_enabled": True,
        "capture": {
            "capture_radius_m": 0.005,
            "minimum_residence_time_s": 0.005,
            "maximum_final_speed_m_s": 1.0,
        },
        "green_full_angle_deg": 62.0,
        "donut_shared_aperture_radius_m": 0.005,
        "single_pass_green_aperture_radius_m": 0.005,
        "single_pass_blue_aperture_radius_m": 0.0075,
    }
    with pytest.raises(TypeError):
        spec["particle_count"]["default"] = 1


@pytest.mark.parametrize("family", ["angled_donut", "single_pass"])
def test_defaults_round_trip_to_locked_winning_family_profile(family):
    defaults = dict(MOT_3D_RUN_SPECIFICATION["defaults"][family])
    profile, parameters, _derived = build_profile_from_parameters(family, defaults)
    locked = json.loads(specification.WINNING_PRESETS_PATH.read_text())["families"][family]
    current = locked["resolved_profile"]
    assert defaults == locked["parameters"]

    assert parameters == defaults
    assert profile["556"]["s0"] == current["556"]["s0"]
    assert profile["556"]["detuning_gamma"] == current["556"]["detuning_gamma"]
    assert profile["556"]["waist_m"] == current["556"]["waist_m"]
    assert profile["399"]["s0"] == current["399"]["s0"]
    assert profile["399"]["detuning_gamma"] == pytest.approx(
        current["399"]["detuning_gamma"]
    )
    assert profile["399"]["waist_m"] == current["399"]["waist_m"]
    assert profile["magnetic_gradient_G_cm"] == current["magnetic_gradient_G_cm"]
    if family == "angled_donut":
        assert profile["399"]["inner_cutoff_radius_m"] == current["399"][
            "inner_cutoff_radius_m"
        ]
    else:
        assert profile["blue_crossing_angle_deg"] == current[
            "blue_crossing_angle_deg"
        ]
        assert profile["blue_crossing_z_offset_m"] == current[
            "blue_crossing_z_offset_m"
        ]


def test_loader_rejects_drifted_bundled_spec():
    source = Path("workflow_api/specifications/mot_3d_individual_v1.json")
    payload = json.loads(source.read_text())
    payload["particle_count"]["maximum_by_execution_mode"]["local"] = 1001
    with pytest.raises(ValueError, match="particle policy"):
        specification._validate(payload)

    payload = json.loads(source.read_text())
    payload["authority_references"]["numerical_policy"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="authority references"):
        specification._validate(payload)


def test_checked_in_typescript_contract_matches_authority_exactly():
    generated = Path("ui/src/generated/mot3dIndividualSpec.v1.ts")
    assert generated.read_text() == specification.render_typescript_specification()


def test_individual_horizon_is_explicit_and_not_bound_to_generic_default(monkeypatch):
    payload = json.loads(
        Path("workflow_api/specifications/mot_3d_individual_v1.json").read_text()
    )
    monkeypatch.setitem(specification.MOT_3D_SIM_CONFIG, "t_max_s", 0.777)
    assert specification._validate(payload)["fixed_classification"]["t_max_s"] == 0.1

    payload["fixed_classification"]["t_max_s"] = 0.025
    with pytest.raises(ValueError, match="fixed classification"):
        specification._validate(payload)


def test_defaults_reject_changes_to_locked_winner_evidence(tmp_path, monkeypatch):
    value = json.loads(specification.WINNING_PRESETS_PATH.read_text())
    value["families"]["single_pass"]["parameters"]["green_s0"] += 1
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(value))
    monkeypatch.setattr(specification, "WINNING_PRESETS_PATH", changed)
    with pytest.raises(RuntimeError, match="locked winning"):
        specification._expected_defaults()
