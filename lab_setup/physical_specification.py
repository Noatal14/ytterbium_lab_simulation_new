"""Strict immutable loader for versioned laboratory physical contracts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from lab_setup.strict_specification import (
    canonical_digest as _canonical_digest,
    freeze as _freeze,
    read_strict_json,
    require_exact_keys as _exact,
    require_finite_number as _num,
)

_DIR = Path(__file__).with_name("specifications")
SPECIFICATION_PATH = _DIR / "laboratory_physical_v2.json"
LEGACY_SPECIFICATION_PATH = _DIR / "laboratory_physical_v1.json"
MODEL_CONVENTIONS_PATH = _DIR / "zeeman_model_conventions_v1.json"
MAX_SPECIFICATION_BYTES = 128 * 1024
PINNED_LEGACY_SPEC_VERSION = "laboratory-physical-v1"
PINNED_LEGACY_SPEC_SHA256 = (
    "8a5fb876dce0825c7cc9154d1a0f0fb4ba01fe9d179e052e747a201246dcd0ab"
)


def _posint(v, label):
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise ValueError(f"Invalid {label}.")


def _vector(v, n, label, positive=False):
    if not isinstance(v, list) or len(v) != n:
        raise ValueError(f"Invalid {label}.")
    for x in v:
        _num(x, label, lo=0 if positive else None)


def _profile(v):
    _exact(
        v,
        {
            "name",
            "ring_count",
            "canonical_json_sha256",
            "radii_m",
            "positions_m",
            "tilt_angles_deg",
        },
        "canonical Zeeman profile",
    )
    _posint(v["ring_count"], "Zeeman ring count")
    if v["name"] != "corrected_projectant_19ring_20261005" or v["ring_count"] != 19:
        raise ValueError("Unexpected canonical Zeeman profile identity.")
    rows = [v[k] for k in ("radii_m", "positions_m", "tilt_angles_deg")]
    if any(not isinstance(r, list) or len(r) != 19 for r in rows):
        raise ValueError("Canonical Zeeman profile must contain 19 complete rings.")
    for x in rows[0]:
        _num(x, "Zeeman radius", lo=0)
    for x in rows[1]:
        _num(x, "Zeeman position")
    for x in rows[2]:
        _num(x, "Zeeman tilt", lo=0, hi=360, closed=True)
    if any(x >= 360 for x in rows[2]) or any(
        a >= b for a, b in zip(rows[1], rows[1][1:])
    ):
        raise ValueError("Invalid canonical Zeeman geometry.")
    if _canonical_digest(rows) != v["canonical_json_sha256"]:
        raise ValueError("Canonical Zeeman profile checksum mismatch.")


def _history(v, v2):
    keys = {
        "removed_profile_names",
        "active_20ring_ring_count",
        "active_20ring_canonical_json_sha256",
    }
    if v2:
        keys.add("readable_laboratory_spec_versions")
    _exact(v, keys, "historical compatibility registry")
    _posint(v["active_20ring_ring_count"], "historical ring count")
    if v["removed_profile_names"] != ["active"] or v["active_20ring_ring_count"] != 20:
        raise ValueError("Invalid historical Zeeman registry.")
    h = v["active_20ring_canonical_json_sha256"]
    if (
        not isinstance(h, str)
        or len(h) != 64
        or any(c not in "0123456789abcdef" for c in h)
    ):
        raise ValueError("Invalid historical Zeeman checksum.")
    if v2 and v["readable_laboratory_spec_versions"] != ["laboratory-physical-v1"]:
        raise ValueError("Invalid readable version registry.")


def _common(v, v2):
    _exact(v["species"], {"name", "mass_amu"}, "species")
    if v["species"]["name"] != "Yb171":
        raise ValueError("Unexpected atomic species.")
    _num(v["species"]["mass_amu"], "mass", lo=0)
    _exact(v["transitions"], {"blue", "green"}, "transitions")
    ck = (
        "measured_zeeman_coefficient_khz_per_G"
        if v2
        else "zeeman_coefficient_khz_per_G"
    )
    for color in ("blue", "green"):
        keys = {"wavelength_m", "gamma_rad_s", ck} | (
            {"reference_saturation_intensity_mw_cm2"} if color == "blue" else set()
        )
        _exact(v["transitions"][color], keys, color)
        for k in ("wavelength_m", "gamma_rad_s", ck):
            _num(v["transitions"][color][k], k, lo=0)
    _num(
        v["transitions"]["blue"]["reference_saturation_intensity_mw_cm2"], "Isat", lo=0
    )
    if (
        v["transitions"]["blue"]["wavelength_m"]
        >= v["transitions"]["green"]["wavelength_m"]
    ):
        raise ValueError("Invalid wavelength order.")
    s = v["source"]
    _exact(
        s,
        {
            "oven_temperature_C",
            "collimation_angle_deg",
            "microtube_radius_m",
            "microtube_length_m",
            "microtube_count",
            "yb171_natural_abundance",
        },
        "source",
    )
    _num(s["oven_temperature_C"], "temperature", lo=-273.15)
    _num(s["collimation_angle_deg"], "collimation", lo=0, hi=90)
    _num(s["microtube_radius_m"], "radius", lo=0)
    _num(s["microtube_length_m"], "length", lo=0)
    _posint(s["microtube_count"], "count")
    _num(s["yb171_natural_abundance"], "abundance", lo=0, hi=1)
    if s["microtube_length_m"] <= s["microtube_radius_m"]:
        raise ValueError("Invalid microtube geometry.")
    _profile(v["canonical_zeeman_profile"])
    if not v2:
        _history(v["historical_read_compatibility"], False)


def _validate_v1(v):
    _exact(
        v,
        {
            "spec_version",
            "species",
            "transitions",
            "source",
            "apparatus",
            "canonical_zeeman_profile",
            "historical_read_compatibility",
        },
        "v1 specification",
    )
    if v["spec_version"] != "laboratory-physical-v1":
        raise ValueError("Invalid v1 version.")
    _common(v, False)
    a = v["apparatus"]
    _exact(
        a,
        {
            "mot_2d_chamber_length_m",
            "mot_2d_chamber_radius_m",
            "science_region_center_z_m",
            "zeeman_arm_angle_deg",
            "zeeman_start_distance_m",
        },
        "apparatus",
    )
    for k, x in a.items():
        _num(x, k, lo=0, hi=90 if k.endswith("angle_deg") else None)
    if a["science_region_center_z_m"] <= a["zeeman_start_distance_m"]:
        raise ValueError("Invalid v1 apparatus geometry ordering.")
    return v


def _validate(v):
    _exact(
        v,
        {
            "spec_version",
            "species",
            "transitions",
            "source",
            "apparatus",
            "canonical_zeeman_profile",
            "zeeman_field_hardware",
            "zeeman_laser_geometry",
        },
        "v2 specification",
    )
    if v["spec_version"] != "laboratory-physical-v2":
        raise ValueError("Invalid v2 version.")
    _common(v, True)
    a = v["apparatus"]
    keys = {
        "mot_2d_chamber_length_m",
        "mot_2d_chamber_radius_m",
        "science_region_center_z_m",
        "zeeman_arm_angle_deg",
        "zeeman_start_distance_m",
        "zeeman_arm_1_length_m",
        "zeeman_arm_1_radius_m",
        "zeeman_arm_1_short_length_m",
        "zeeman_arm_1_extended_length_m",
        "zeeman_arm_2_length_m",
        "zeeman_arm_2_radius_m",
        "zeeman_arm_3_length_m",
        "zeeman_arm_3_radius_m",
        "science_arm_1_length_m",
        "science_arm_1_radius_m",
        "science_arm_total_length_m",
        "dps_length_m",
        "dps_radius_m",
        "science_arm_3_radius_m",
    }
    _exact(a, keys, "apparatus")
    for k, x in a.items():
        _num(x, k, lo=0, hi=90 if k.endswith("angle_deg") else None)
    if (
        a["science_region_center_z_m"] <= a["zeeman_start_distance_m"]
        or a["science_arm_total_length_m"]
        <= a["science_arm_1_length_m"] + a["dps_length_m"]
    ):
        raise ValueError("Invalid apparatus geometry ordering.")
    f = v["zeeman_field_hardware"]
    _exact(
        f,
        {
            "axis_offset_m",
            "magnet_dimensions_m",
            "magnet_polarization_T",
            "magnets_per_ring",
        },
        "field construction",
    )
    _num(f["axis_offset_m"], "axis offset")
    _vector(f["magnet_dimensions_m"], 3, "dimensions", True)
    _num(f["magnet_polarization_T"], "polarization")
    _posint(f["magnets_per_ring"], "magnets")
    if f != {
        "axis_offset_m": 0.0,
        "magnet_dimensions_m": [0.005, 0.005, 0.005],
        "magnet_polarization_T": -1.24,
        "magnets_per_ring": 8,
    }:
        raise ValueError("Invalid field construction.")
    l = v["zeeman_laser_geometry"]
    _exact(l, {"waist_m", "waist_position_m"}, "laser geometry")
    _num(l["waist_m"], "waist", lo=0)
    _vector(l["waist_position_m"], 3, "waist position")
    if l != {"waist_m": 0.007, "waist_position_m": [0.0, 0.0, 0.0]}:
        raise ValueError("Invalid Zeeman laser hardware geometry.")
    return v


def _validate_model_conventions(value):
    expected = {
        "spec_version": "zeeman-model-conventions-v1",
        "lab_z_axis": [0.0, 0.0, 1.0],
        "zeeman_internal_axis": "+z",
        "zeeman_lab_axis_direction": "toward_lab_origin_in_negative_y_negative_z_arm",
        "zeeman_tilt_input_sign": -1,
        "azimuth_start_deg": 0.0,
        "azimuth_stop_deg": 360.0,
        "azimuth_endpoint_included": False,
        "laser_direction_type": "vector",
        "laser_tag": "Zeeman_Laser",
    }
    _exact(value, expected, "Zeeman model conventions")
    _vector(value["lab_z_axis"], 3, "lab z axis")
    if (
        value != expected
        or type(value["zeeman_tilt_input_sign"]) is not int
        or type(value["azimuth_endpoint_included"]) is not bool
    ):
        raise ValueError("Unexpected Zeeman model conventions.")
    return value


def _read_path(path, validator):
    return read_strict_json(
        path,
        validator,
        max_bytes=MAX_SPECIFICATION_BYTES,
        error_message="The bundled laboratory physical specification is invalid.",
    )


def _read_validated():
    return _read_path(SPECIFICATION_PATH, _validate)


def _load_validated_bundle(reader=_read_validated):
    v = reader()
    return _freeze(v), _canonical_digest(v)


def _load_legacy_bundle(path=LEGACY_SPECIFICATION_PATH):
    """Load only the one historically published v1 bundle identity."""
    value = _read_path(path, _validate_v1)
    digest = _canonical_digest(value)
    if (
        value["spec_version"] != PINNED_LEGACY_SPEC_VERSION
        or digest != PINNED_LEGACY_SPEC_SHA256
    ):
        raise RuntimeError("The bundled legacy laboratory identity is not recognized.")
    return value, digest


LABORATORY_PHYSICAL_SPECIFICATION, LABORATORY_SPEC_SHA256 = _load_validated_bundle()
_legacy, LEGACY_LABORATORY_SPEC_SHA256 = _load_legacy_bundle()
_model_conventions = _read_path(MODEL_CONVENTIONS_PATH, _validate_model_conventions)
LEGACY_LABORATORY_PHYSICAL_SPECIFICATION = _freeze(_legacy)
LEGACY_LABORATORY_SPEC_VERSION = _legacy["spec_version"]
ZEEMAN_MODEL_CONVENTIONS = _freeze(_model_conventions)
ZEEMAN_MODEL_CONVENTIONS_SHA256 = _canonical_digest(_model_conventions)
LABORATORY_SPEC_VERSION = LABORATORY_PHYSICAL_SPECIFICATION["spec_version"]
CANONICAL_ZEEMAN_PROFILE_NAME = LABORATORY_PHYSICAL_SPECIFICATION[
    "canonical_zeeman_profile"
]["name"]
CANONICAL_ZEEMAN_PROFILE_SHA256 = LABORATORY_PHYSICAL_SPECIFICATION[
    "canonical_zeeman_profile"
]["canonical_json_sha256"]


@lru_cache(maxsize=1)
def load_laboratory_physical_specification():
    return LABORATORY_PHYSICAL_SPECIFICATION


def validate_laboratory_provenance_identity(
    version, specification_sha256, profile_sha256, *, allow_legacy=False
):
    """Return the exact known identity without upgrading or relabeling it."""
    identity = (version, specification_sha256, profile_sha256)
    current = (
        LABORATORY_SPEC_VERSION,
        LABORATORY_SPEC_SHA256,
        CANONICAL_ZEEMAN_PROFILE_SHA256,
    )
    legacy = (
        LEGACY_LABORATORY_SPEC_VERSION,
        LEGACY_LABORATORY_SPEC_SHA256,
        CANONICAL_ZEEMAN_PROFILE_SHA256,
    )
    if identity == current or (allow_legacy and identity == legacy):
        return {
            "laboratory_spec_version": version,
            "laboratory_spec_sha256": specification_sha256,
            "zeeman_profile_sha256": profile_sha256,
            "legacy_attested_profile": identity == legacy,
        }
    raise ValueError("Laboratory provenance identity is incomplete or mismatched.")


def attest_canonical_zeeman_metadata(metadata, *, allow_legacy=False):
    """Validate embedded canonical arrays and their exact versioned identity."""
    if not isinstance(metadata, dict):
        raise ValueError("Invalid Zeeman metadata.")
    p = metadata.get("parameters")
    field = p.get("zeeman_field_config") if isinstance(p, dict) else None
    if (
        not isinstance(p, dict)
        or p.get("resolved_zeeman_magnet_profile") != CANONICAL_ZEEMAN_PROFILE_NAME
        or not isinstance(field, dict)
        or set(field) != {"radii_m", "positions_m", "tilt_angles_deg"}
    ):
        raise ValueError("Zeeman metadata lacks canonical identity.")
    rows = [field[k] for k in ("radii_m", "positions_m", "tilt_angles_deg")]
    if (
        any(not isinstance(r, list) or len(r) != 19 for r in rows)
        or _canonical_digest(rows) != CANONICAL_ZEEMAN_PROFILE_SHA256
    ):
        raise ValueError("Zeeman arrays do not match the canonical profile.")
    version = metadata.get("laboratory_spec_version")
    digest = metadata.get("laboratory_spec_sha256")
    profile_digest = metadata.get("zeeman_profile_sha256")
    common = {"zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256}
    provenance_present = any(value is not None for value in (version, digest, profile_digest))
    if provenance_present and profile_digest != CANONICAL_ZEEMAN_PROFILE_SHA256:
        raise ValueError("Zeeman profile provenance is incomplete or mismatched.")
    if provenance_present:
        return validate_laboratory_provenance_identity(
            version, digest, profile_digest, allow_legacy=allow_legacy
        )
    if not allow_legacy:
        raise ValueError("Zeeman laboratory provenance is missing.")
    return {
        **common,
        "legacy_attested_profile": True,
        "original_laboratory_spec_version": None,
        "original_laboratory_spec_sha256": None,
    }
