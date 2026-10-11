"""Integrity and parity tests for the Zeeman operating-point contract."""

from copy import deepcopy
import json
from types import MappingProxyType

import pytest

import config
from lab_setup.zeeman_operating_specification import (
    SPECIFICATION_PATH,
    ZEEMAN_OPERATING_SPECIFICATION,
    ZEEMAN_OPERATING_SPEC_SHA256,
    ZEEMAN_OPERATING_SPEC_VERSION,
    _load_validated_bundle,
    _validate,
)
from lab_setup.physical_specification import _read_path


def _mutable():
    return json.loads(SPECIFICATION_PATH.read_text(encoding="utf-8"))


def test_contract_identity_immutability_and_exact_facade_parity():
    assert ZEEMAN_OPERATING_SPEC_VERSION == "zeeman-operating-v1"
    assert ZEEMAN_OPERATING_SPEC_SHA256 == "2f993c79fd4f4a7522e77b896e67e54288f8e9777d57be89016760edd8de6266"
    assert isinstance(ZEEMAN_OPERATING_SPECIFICATION, MappingProxyType)
    assert config.ZEEMAN_LASER_CONFIG == {"s0": 3.0, "detuning_gamma": -13.75}
    assert config.ZEEMAN_SIM_CONFIG == {
        "t_max_s": 0.02,
        "dt_s": 4e-5,
        "start_distance_m": 0.45,
        "cutoff_distance_m": 0.1,
    }


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(extra=True),
    lambda value: value["laser"].pop("s0"),
    lambda value: value["laser"].update(s0=True),
    lambda value: value["laser"].update(s0=float("nan")),
    lambda value: value["laser"].update(detuning_gamma="-13.75"),
    lambda value: value["laser"].update(detuning_gamma=0.0),
    lambda value: value["laser"].update(detuning_gamma=1.0),
    lambda value: value["laser"].update(detuning_gamma=True),
    lambda value: value["laser"].update(detuning_gamma=float("nan")),
    lambda value: value["laser"].update(detuning_gamma=float("inf")),
    lambda value: value["laser"].update(detuning_gamma=float("-inf")),
    lambda value: value["propagation_boundary"].update(start_distance_m=0.1),
    lambda value: value["propagation_boundary"].update(cutoff_distance_m=False),
])
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
    assert digest == ZEEMAN_OPERATING_SPEC_SHA256


def test_duplicate_keys_fail_before_operating_schema_validation(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"spec_version":"zeeman-operating-v1","spec_version":"other"}', encoding="utf-8")
    with pytest.raises(RuntimeError):
        _read_path(path, _validate)


def test_operating_authority_is_inside_every_relevant_provenance_closure():
    from studies.mot_3d_campaign import CAMPAIGN_FILES
    from workflow_api.mot_2d_spec import RELEVANT_FILES
    from workflow_api.repository_snapshot import (
        MOT_2D_INDIVIDUAL_RELEVANT_FILES,
        ZEEMAN_RELEVANT_FILES,
    )
    required = {
        "lab_setup/zeeman_operating_specification.py",
        "lab_setup/specifications/zeeman_operating_v1.json",
    }
    for closure in (
        ZEEMAN_RELEVANT_FILES,
        MOT_2D_INDIVIDUAL_RELEVANT_FILES,
        RELEVANT_FILES,
        CAMPAIGN_FILES,
    ):
        assert required.issubset(closure)
