"""Integrity tests for the versioned laboratory physical contract."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from types import MappingProxyType

import pytest

import config
from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_PHYSICAL_SPECIFICATION,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
    LEGACY_LABORATORY_SPEC_SHA256, LEGACY_LABORATORY_SPEC_VERSION,
    LEGACY_SPECIFICATION_PATH, _read_path,
    MODEL_CONVENTIONS_PATH, _validate_model_conventions,
    _load_legacy_bundle,
    validate_laboratory_provenance_identity,
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
    assert LABORATORY_SPEC_VERSION == "laboratory-physical-v2"
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
        lambda value: value["zeeman_field_hardware"].update(magnets_per_ring=True),
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


def test_version_identities_and_duplicate_key_rejection(tmp_path):
    legacy = json.loads(LEGACY_SPECIFICATION_PATH.read_text(encoding="utf-8"))
    assert LEGACY_LABORATORY_SPEC_VERSION == "laboratory-physical-v1"
    assert LEGACY_LABORATORY_SPEC_SHA256 == _canonical_digest(legacy)
    assert LEGACY_LABORATORY_SPEC_SHA256 == "8a5fb876dce0825c7cc9154d1a0f0fb4ba01fe9d179e052e747a201246dcd0ab"
    assert LABORATORY_SPEC_SHA256 == "1ef77eecdd306d2d92c08fde9897f283de57e741e9f1a45a6bc6c0063779eac3"
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"spec_version":"laboratory-physical-v2","spec_version":"other"}', encoding="utf-8")
    with pytest.raises(RuntimeError):
        _read_path(duplicate, _validate)


def test_exact_v1_provenance_remains_attestable_without_relabeling():
    profile = _mutable_specification()["canonical_zeeman_profile"]
    metadata = {"laboratory_spec_version": LEGACY_LABORATORY_SPEC_VERSION,
                "laboratory_spec_sha256": LEGACY_LABORATORY_SPEC_SHA256,
                "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
                "parameters": {"resolved_zeeman_magnet_profile": CANONICAL_ZEEMAN_PROFILE_NAME,
                               "zeeman_field_config": {key: list(profile[key]) for key in ("radii_m", "positions_m", "tilt_angles_deg")}}}
    with pytest.raises(ValueError):
        attest_canonical_zeeman_metadata(metadata)
    result = attest_canonical_zeeman_metadata(metadata, allow_legacy=True)
    assert result["laboratory_spec_version"] == "laboratory-physical-v1"
    assert result["laboratory_spec_sha256"] == LEGACY_LABORATORY_SPEC_SHA256
    assert result["legacy_attested_profile"] is True


@pytest.mark.parametrize("key,bad", [
    ("zeeman_tilt_input_sign", True),
    ("azimuth_endpoint_included", 0),
    ("laser_direction_type", "axis"),
    ("laser_tag", ""),
    ("lab_z_axis", [False, 0.0, 1.0]),
])
def test_model_conventions_are_exact_and_type_strict(key, bad):
    value = json.loads(MODEL_CONVENTIONS_PATH.read_text(encoding="utf-8"))
    value[key] = bad
    with pytest.raises(ValueError):
        _validate_model_conventions(value)


def test_partial_or_tampered_provenance_trio_is_rejected():
    with pytest.raises(ValueError):
        validate_laboratory_provenance_identity(
            LABORATORY_SPEC_VERSION, LABORATORY_SPEC_SHA256, None
        )
    with pytest.raises(ValueError):
        validate_laboratory_provenance_identity(
            LABORATORY_SPEC_VERSION, LABORATORY_SPEC_SHA256, "0" * 64
        )


def test_v2_migration_preserves_the_complete_pre_v2_physics_projection():
    legacy = json.loads(LEGACY_SPECIFICATION_PATH.read_text(encoding="utf-8"))
    current = _mutable_specification()
    assert current["species"] == legacy["species"]
    assert current["source"] == legacy["source"]
    assert current["canonical_zeeman_profile"] == legacy["canonical_zeeman_profile"]
    for key, value in legacy["apparatus"].items():
        assert current["apparatus"][key] == value
    for color in ("blue", "green"):
        before = dict(legacy["transitions"][color])
        coefficient = before.pop("zeeman_coefficient_khz_per_G")
        after = dict(current["transitions"][color])
        assert after.pop("measured_zeeman_coefficient_khz_per_G") == coefficient
        assert after == before


def test_descriptor_short_read_fails_closed(monkeypatch):
    real_read = os.read
    calls = 0
    def short_read(descriptor, size):
        nonlocal calls
        calls += 1
        return real_read(descriptor, max(1, size // 2)) if calls == 1 else b""
    monkeypatch.setattr(os, "read", short_read)
    with pytest.raises(RuntimeError):
        _read_path(SPECIFICATION_PATH, _validate)


def test_schema_valid_but_unpublished_v1_bundle_identity_is_rejected(tmp_path):
    legacy = json.loads(LEGACY_SPECIFICATION_PATH.read_text(encoding="utf-8"))
    legacy["species"]["mass_amu"] += 1e-9
    path = tmp_path / "laboratory_physical_v1.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    with pytest.raises(RuntimeError, match="legacy laboratory identity"):
        _load_legacy_bundle(path)
