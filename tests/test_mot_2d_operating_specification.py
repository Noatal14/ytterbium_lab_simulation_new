"""Integrity and authority tests for generic 2D-MOT operating defaults."""

from copy import deepcopy
import inspect
import json
from types import MappingProxyType

import pytest

import config
from lab_setup.mot_2d_operating_specification import (
    MOT_2D_OPERATING_SPECIFICATION,
    MOT_2D_OPERATING_SPEC_SHA256,
    MOT_2D_OPERATING_SPEC_VERSION,
    SPECIFICATION_PATH,
    _load_validated_bundle,
    _validate,
)
from lab_setup.strict_specification import read_strict_json
from simulations.mot_2d import mot_simulation
from workflow_api.mot_2d_run_specification import MOT_2D_RUN_SPECIFICATION


def _mutable():
    return json.loads(SPECIFICATION_PATH.read_text(encoding="utf-8"))


def test_contract_identity_immutability_and_exact_facade_parity():
    assert MOT_2D_OPERATING_SPEC_VERSION == "mot-2d-operating-v1"
    assert MOT_2D_OPERATING_SPEC_SHA256 == (
        "5a1dceda5c0cfe18625bc341556b19e499eb4237e652078c43e979901a524900"
    )
    assert isinstance(MOT_2D_OPERATING_SPECIFICATION, MappingProxyType)
    assert isinstance(MOT_2D_OPERATING_SPECIFICATION["laser"], MappingProxyType)
    with pytest.raises(TypeError):
        MOT_2D_OPERATING_SPECIFICATION["laser"]["s0"] = 2.0
    assert config.MOT_2D_LASER_CONFIG == {
        "s0": 1.4,
        "detuning_gamma": -1.161,
        "swap_polarization": False,
    }
    assert type(config.MOT_2D_LASER_CONFIG["swap_polarization"]) is bool
    assert config.MOT_2D_MAGNET_RADIUS_M == 0.0517
    assert config.MOT_2D_SIM_CONFIG == {
        "t_max_s": 0.025,
        "dt_s": 0.625e-6,
        "start_distance_m": 0.1,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra=True),
        lambda value: value["laser"].pop("s0"),
        lambda value: value["laser"].update(s0=True),
        lambda value: value["laser"].update(s0=0.0),
        lambda value: value["laser"].update(s0=float("nan")),
        lambda value: value["laser"].update(detuning_gamma="-1.161"),
        lambda value: value["laser"].update(detuning_gamma=0.0),
        lambda value: value["laser"].update(detuning_gamma=float("inf")),
        lambda value: value["laser"].update(swap_polarization=0),
        lambda value: value["magnetic_field"].update(magnet_radius_m=False),
        lambda value: value["magnetic_field"].update(magnet_radius_m=-0.1),
        lambda value: value["propagation_boundary"].update(
            start_distance_m=float("-inf")
        ),
    ],
)
def test_invalid_operating_contract_is_rejected(mutation):
    value = deepcopy(_mutable())
    mutation(value)
    with pytest.raises(ValueError):
        _validate(value)


def test_bundle_is_derived_from_one_exact_read():
    value = _mutable()
    calls = []

    def reader():
        calls.append(True)
        return value

    frozen, digest = _load_validated_bundle(reader)
    assert len(calls) == 1
    assert isinstance(frozen, MappingProxyType)
    assert digest == MOT_2D_OPERATING_SPEC_SHA256


def test_duplicate_keys_fail_before_operating_schema_validation(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"spec_version":"mot-2d-operating-v1","spec_version":"other"}',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError):
        read_strict_json(
            path,
            _validate,
            max_bytes=16 * 1024,
            error_message="invalid",
        )


def test_generic_runtime_defaults_are_the_facade_values():
    defaults = {
        name: parameter.default
        for name, parameter in inspect.signature(mot_simulation).parameters.items()
    }
    assert defaults["_2d_mot_config"] is config.MOT_2D_LASER_CONFIG
    assert defaults["magnet_radius"] == config.MOT_2D_MAGNET_RADIUS_M
    assert defaults["dt"] == config.MOT_2D_SIM_CONFIG["dt_s"]
    assert defaults["t_max_s"] == config.MOT_2D_SIM_CONFIG["t_max_s"]


def test_generic_defaults_are_not_individual_ui_control_defaults():
    """These are deliberately separate authorities, not drifting mirrors."""
    controls = MOT_2D_RUN_SPECIFICATION["controls"]
    assert config.MOT_2D_LASER_CONFIG["s0"] != controls["s0"]["default"]
    assert (
        config.MOT_2D_LASER_CONFIG["detuning_gamma"]
        != controls["detuning_gamma"]["default"]
    )
    assert (
        config.MOT_2D_MAGNET_RADIUS_M
        != controls["magnet_radius_m"]["default"]
    )
    assert (
        config.MOT_2D_SIM_CONFIG["start_distance_m"]
        == MOT_2D_RUN_SPECIFICATION["fixed_classification"]["start_distance_m"]
    )


def test_operating_authority_is_inside_every_relevant_provenance_closure():
    from studies.mot_3d_campaign import CAMPAIGN_FILES
    from workflow_api.mot_2d_spec import RELEVANT_FILES
    from workflow_api.repository_snapshot import (
        MOT_2D_INDIVIDUAL_RELEVANT_FILES,
        ZEEMAN_RELEVANT_FILES,
    )

    required = {
        "lab_setup/mot_2d_operating_specification.py",
        "lab_setup/specifications/mot_2d_operating_v1.json",
        "lab_setup/strict_specification.py",
    }
    for closure in (
        ZEEMAN_RELEVANT_FILES,
        MOT_2D_INDIVIDUAL_RELEVANT_FILES,
        RELEVANT_FILES,
        CAMPAIGN_FILES,
    ):
        assert required.issubset(closure)
