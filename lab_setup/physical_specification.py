"""Strict immutable loader for the versioned laboratory physical contract."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

SPECIFICATION_PATH = Path(__file__).with_name("specifications") / "laboratory_physical_v1.json"
MAX_SPECIFICATION_BYTES = 128 * 1024


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _canonical_digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _exact_mapping(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"Invalid {label} schema.")


def _number(value, label, *, lower=None, upper=None):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or (lower is not None and value <= lower)
            or (upper is not None and value >= upper)):
        raise ValueError(f"Invalid {label}.")


def _positive_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"Invalid {label}.")


def _validate(value):
    _exact_mapping(value, {
        "spec_version", "species", "transitions", "source", "apparatus",
        "canonical_zeeman_profile", "historical_read_compatibility",
    }, "laboratory physical specification")
    if value["spec_version"] != "laboratory-physical-v1":
        raise ValueError("Invalid laboratory physical specification version.")

    species = value["species"]
    _exact_mapping(species, {"name", "mass_amu"}, "species")
    if species["name"] != "Yb171":
        raise ValueError("Unexpected atomic species.")
    _number(species["mass_amu"], "species mass", lower=0)

    transitions = value["transitions"]
    _exact_mapping(transitions, {"blue", "green"}, "transitions")
    _exact_mapping(transitions["blue"], {
        "wavelength_m", "gamma_rad_s", "zeeman_coefficient_khz_per_G",
        "reference_saturation_intensity_mw_cm2",
    }, "blue transition")
    _exact_mapping(transitions["green"], {
        "wavelength_m", "gamma_rad_s", "zeeman_coefficient_khz_per_G",
    }, "green transition")
    for color, transition in transitions.items():
        for key in ("wavelength_m", "gamma_rad_s", "zeeman_coefficient_khz_per_G"):
            _number(transition[key], f"{color} {key}", lower=0)
    _number(transitions["blue"]["reference_saturation_intensity_mw_cm2"],
            "blue reference saturation intensity", lower=0)
    if transitions["blue"]["wavelength_m"] >= transitions["green"]["wavelength_m"]:
        raise ValueError("Transition wavelength ordering is invalid.")

    source = value["source"]
    _exact_mapping(source, {
        "oven_temperature_C", "collimation_angle_deg", "microtube_radius_m",
        "microtube_length_m", "microtube_count", "yb171_natural_abundance",
    }, "source")
    _number(source["oven_temperature_C"], "oven temperature", lower=-273.15)
    _number(source["collimation_angle_deg"], "collimation angle", lower=0, upper=90)
    _number(source["microtube_radius_m"], "microtube radius", lower=0)
    _number(source["microtube_length_m"], "microtube length", lower=0)
    _positive_integer(source["microtube_count"], "microtube count")
    _number(source["yb171_natural_abundance"], "natural abundance", lower=0, upper=1)
    if source["microtube_length_m"] <= source["microtube_radius_m"]:
        raise ValueError("Microtube length must exceed its radius.")

    apparatus = value["apparatus"]
    _exact_mapping(apparatus, {
        "mot_2d_chamber_length_m", "mot_2d_chamber_radius_m",
        "science_region_center_z_m", "zeeman_arm_angle_deg",
        "zeeman_start_distance_m",
    }, "apparatus")
    for key in ("mot_2d_chamber_length_m", "mot_2d_chamber_radius_m",
                "science_region_center_z_m", "zeeman_start_distance_m"):
        _number(apparatus[key], key, lower=0)
    _number(apparatus["zeeman_arm_angle_deg"], "Zeeman arm angle", lower=0, upper=90)
    if apparatus["science_region_center_z_m"] <= apparatus["zeeman_start_distance_m"]:
        raise ValueError("Science-region center must follow the Zeeman start distance.")

    profile = value["canonical_zeeman_profile"]
    _exact_mapping(profile, {
        "name", "ring_count", "canonical_json_sha256", "radii_m",
        "positions_m", "tilt_angles_deg",
    }, "canonical Zeeman profile")
    if profile["name"] != "corrected_projectant_19ring_20261005":
        raise ValueError("Unexpected canonical Zeeman profile identity.")
    _positive_integer(profile["ring_count"], "Zeeman ring count")
    arrays = [profile[key] for key in ("radii_m", "positions_m", "tilt_angles_deg")]
    if (profile["ring_count"] != 19 or any(not isinstance(row, list) for row in arrays)
            or [len(row) for row in arrays] != [19, 19, 19]):
        raise ValueError("Canonical Zeeman profile must contain 19 complete rings.")
    for radius in profile["radii_m"]:
        _number(radius, "Zeeman radius", lower=0)
    for position in profile["positions_m"]:
        _number(position, "Zeeman position")
    for angle in profile["tilt_angles_deg"]:
        if (isinstance(angle, bool) or not isinstance(angle, (int, float))
                or not math.isfinite(angle) or not 0 <= angle < 360):
            raise ValueError("Invalid Zeeman tilt.")
    if any(left >= right for left, right in zip(profile["positions_m"], profile["positions_m"][1:])):
        raise ValueError("Canonical Zeeman positions must be strictly increasing.")
    profile_arrays = [profile[key] for key in ("radii_m", "positions_m", "tilt_angles_deg")]
    if _canonical_digest(profile_arrays) != profile["canonical_json_sha256"]:
        raise ValueError("Canonical Zeeman profile checksum mismatch.")

    history = value["historical_read_compatibility"]
    _exact_mapping(history, {
        "removed_profile_names", "active_20ring_ring_count",
        "active_20ring_canonical_json_sha256",
    }, "historical compatibility registry")
    if history["removed_profile_names"] != ["active"]:
        raise ValueError("Invalid retired Zeeman profile registry.")
    if history["active_20ring_ring_count"] != 20:
        raise ValueError("Invalid historical Zeeman ring count.")
    checksum = history["active_20ring_canonical_json_sha256"]
    if (not isinstance(checksum, str) or len(checksum) != 64
            or any(character not in "0123456789abcdef" for character in checksum)):
        raise ValueError("Invalid historical Zeeman checksum.")
    return value


def _read_validated():
    try:
        before = SPECIFICATION_PATH.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SPECIFICATION_BYTES:
            raise ValueError
        descriptor = os.open(SPECIFICATION_PATH, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_SPECIFICATION_BYTES
                    or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                    != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)):
                raise ValueError
            chunks, remaining = [], MAX_SPECIFICATION_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
            if (len(raw) > MAX_SPECIFICATION_BYTES
                    or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                    != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)):
                raise ValueError
        finally:
            os.close(descriptor)
        return _validate(json.loads(raw.decode("utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError("The bundled laboratory physical specification is invalid.") from error


def _load_validated_bundle(reader=_read_validated):
    """Return an immutable contract and digest derived from one exact read."""
    value = reader()
    return _freeze(value), _canonical_digest(value)


LABORATORY_PHYSICAL_SPECIFICATION, LABORATORY_SPEC_SHA256 = (
    _load_validated_bundle()
)


@lru_cache(maxsize=1)
def load_laboratory_physical_specification():
    return LABORATORY_PHYSICAL_SPECIFICATION


CANONICAL_ZEEMAN_PROFILE_NAME = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]["name"]
CANONICAL_ZEEMAN_PROFILE_SHA256 = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]["canonical_json_sha256"]
LABORATORY_SPEC_VERSION = LABORATORY_PHYSICAL_SPECIFICATION["spec_version"]


def attest_canonical_zeeman_metadata(metadata, *, allow_legacy=False):
    """Return canonical provenance, deriving it only for attested old metadata.

    Pre-C2 metadata is accepted only when it names the corrected profile and
    embeds the exact canonical 19-ring arrays.  The returned provenance exists
    in memory only; callers must not rewrite the historical JSON.
    """
    if not isinstance(metadata, dict):
        raise ValueError("Invalid Zeeman metadata.")
    parameters = metadata.get("parameters")
    if not isinstance(parameters, dict) or parameters.get(
        "resolved_zeeman_magnet_profile"
    ) != CANONICAL_ZEEMAN_PROFILE_NAME:
        raise ValueError("Zeeman metadata does not name the canonical profile.")
    field = parameters.get("zeeman_field_config")
    if not isinstance(field, dict) or set(field) != {
        "radii_m", "positions_m", "tilt_angles_deg",
    }:
        raise ValueError("Zeeman metadata lacks embedded canonical arrays.")
    arrays = [field[key] for key in ("radii_m", "positions_m", "tilt_angles_deg")]
    if any(not isinstance(row, list) or len(row) != 19 for row in arrays):
        raise ValueError("Zeeman metadata has invalid ring arrays.")
    if _canonical_digest(arrays) != CANONICAL_ZEEMAN_PROFILE_SHA256:
        raise ValueError("Zeeman arrays do not match the canonical profile.")
    expected = {
        "laboratory_spec_version": LABORATORY_SPEC_VERSION,
        "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
        "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
    }
    present = {key for key in expected if key in metadata}
    if present:
        if present != set(expected) or any(metadata[key] != value for key, value in expected.items()):
            raise ValueError("Zeeman laboratory provenance is incomplete or mismatched.")
        return {**expected, "legacy_attested_profile": False}
    if not allow_legacy:
        raise ValueError("Zeeman laboratory provenance is missing.")
    return {
        "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
        "legacy_attested_profile": True,
        "original_laboratory_spec_version": metadata.get("laboratory_spec_version"),
        "original_laboratory_spec_sha256": metadata.get("laboratory_spec_sha256"),
    }
