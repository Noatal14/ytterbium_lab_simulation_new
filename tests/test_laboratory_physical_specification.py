"""Integrity tests for the versioned laboratory physical contract."""

from __future__ import annotations

from copy import deepcopy
import json
from types import MappingProxyType

import pytest

import config
from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_PHYSICAL_SPECIFICATION,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
    SPECIFICATION_PATH,
    _canonical_digest,
    _load_validated_bundle,
    attest_canonical_zeeman_metadata,
    _validate,
)


def _mutable_specification():
    return json.loads(SPECIFICATION_PATH.read_text(encoding="utf-8"))


def test_versioned_contract_is_immutable_and_drives_the_active_profile():
    assert isinstance(LABORATORY_PHYSICAL_SPECIFICATION, MappingProxyType)
    profile = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]
    assert CANONICAL_ZEEMAN_PROFILE_NAME == "corrected_projectant_19ring_20261005"
    assert config.ACTIVE_ZEEMAN_MAGNET_PROFILE == CANONICAL_ZEEMAN_PROFILE_NAME
    assert "active" not in config.ZEEMAN_MAGNET_PROFILES
    assert set(config.ZEEMAN_MAGNET_PROFILES) == {CANONICAL_ZEEMAN_PROFILE_NAME}
    assert config.ZEEMAN_MAGNET_PROFILES[CANONICAL_ZEEMAN_PROFILE_NAME] == [
        list(profile["radii_m"]),
        list(profile["positions_m"]),
        list(profile["tilt_angles_deg"]),
    ]
    assert LABORATORY_SPEC_VERSION == "laboratory-physical-v1"
    assert len(LABORATORY_SPEC_SHA256) == 64
    assert CANONICAL_ZEEMAN_PROFILE_SHA256 == profile["canonical_json_sha256"]


def test_contract_and_digest_are_derived_from_one_read():
    value = _mutable_specification()
    calls = []

    def reader():
        calls.append(True)
        return value

    frozen, digest = _load_validated_bundle(reader)
    assert len(calls) == 1
    assert isinstance(frozen, MappingProxyType)
    assert digest == _canonical_digest(value)


def test_pre_c2_corrected_metadata_is_attested_without_mutation():
    profile = _mutable_specification()["canonical_zeeman_profile"]
    metadata = {"parameters": {
        "resolved_zeeman_magnet_profile": CANONICAL_ZEEMAN_PROFILE_NAME,
        "zeeman_field_config": {
            key: profile[key]
            for key in ("radii_m", "positions_m", "tilt_angles_deg")
        },
    }}
    before = deepcopy(metadata)
    result = attest_canonical_zeeman_metadata(metadata, allow_legacy=True)
    assert result["legacy_attested_profile"] is True
    assert result["zeeman_profile_sha256"] == CANONICAL_ZEEMAN_PROFILE_SHA256
    assert metadata == before


@pytest.mark.parametrize("change", ["missing", "tampered"])
def test_modern_metadata_requires_exact_embedded_profile(change):
    profile = _mutable_specification()["canonical_zeeman_profile"]
    field = {key: list(profile[key]) for key in ("radii_m", "positions_m", "tilt_angles_deg")}
    metadata = {
        "laboratory_spec_version": LABORATORY_SPEC_VERSION,
        "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
        "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
        "parameters": {
            "resolved_zeeman_magnet_profile": CANONICAL_ZEEMAN_PROFILE_NAME,
            "zeeman_field_config": field,
        },
    }
    if change == "missing":
        metadata["parameters"].pop("zeeman_field_config")
    else:
        metadata["parameters"]["zeeman_field_config"]["radii_m"][0] += 1e-6
    with pytest.raises(ValueError):
        attest_canonical_zeeman_metadata(metadata, allow_legacy=True)


@pytest.mark.parametrize("profile_name,include_arrays", [("active", True), (CANONICAL_ZEEMAN_PROFILE_NAME, False)])
def test_legacy_attestation_rejects_retired_or_evidence_free_metadata(profile_name, include_arrays):
    profile = _mutable_specification()["canonical_zeeman_profile"]
    parameters = {"resolved_zeeman_magnet_profile": profile_name}
    if include_arrays:
        parameters["zeeman_field_config"] = {
            key: profile[key] for key in ("radii_m", "positions_m", "tilt_angles_deg")
        }
    with pytest.raises(ValueError):
        attest_canonical_zeeman_metadata({"parameters": parameters}, allow_legacy=True)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["canonical_zeeman_profile"].update(name="active"),
        lambda value: value["canonical_zeeman_profile"].update(ring_count=20),
        lambda value: value["canonical_zeeman_profile"]["positions_m"].__setitem__(1, -1.0),
        lambda value: value["canonical_zeeman_profile"].update(canonical_json_sha256="0" * 64),
        lambda value: value["historical_read_compatibility"].update(removed_profile_names=[]),
        lambda value: value["species"].update(mass_amu=True),
        lambda value: value["species"].update(extra=1),
        lambda value: value["transitions"]["blue"].update(wavelength_m=float("nan")),
        lambda value: value["transitions"]["green"].update(gamma_rad_s=-1),
        lambda value: value["source"].update(microtube_count=True),
        lambda value: value["source"].update(yb171_natural_abundance=1.0),
        lambda value: value["source"].update(microtube_length_m=1e-6),
        lambda value: value["apparatus"].update(zeeman_arm_angle_deg=90),
        lambda value: value["apparatus"].update(science_region_center_z_m=0.1),
        lambda value: value["canonical_zeeman_profile"]["tilt_angles_deg"].__setitem__(0, 360),
    ],
)
def test_invalid_or_drifted_physical_contract_is_rejected(mutation):
    value = deepcopy(_mutable_specification())
    mutation(value)
    with pytest.raises(ValueError):
        _validate(value)
