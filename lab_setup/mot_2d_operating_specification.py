"""Strict immutable loader for the generic 2D-MOT operating defaults."""

from __future__ import annotations

from pathlib import Path

from lab_setup.strict_specification import (
    canonical_digest,
    freeze,
    read_strict_json,
    require_exact_keys,
    require_finite_number,
)


SPECIFICATION_PATH = (
    Path(__file__).with_name("specifications") / "mot_2d_operating_v1.json"
)
MAX_SPECIFICATION_BYTES = 16 * 1024


def _validate(value):
    require_exact_keys(
        value,
        {"spec_version", "laser", "magnetic_field", "propagation_boundary"},
        "2D-MOT operating specification",
    )
    if value["spec_version"] != "mot-2d-operating-v1":
        raise ValueError("Invalid 2D-MOT operating specification version.")

    laser = value["laser"]
    require_exact_keys(
        laser,
        {"s0", "detuning_gamma", "swap_polarization"},
        "2D-MOT laser operating defaults",
    )
    require_finite_number(laser["s0"], "2D-MOT laser s0", lo=0)
    require_finite_number(
        laser["detuning_gamma"], "2D-MOT laser detuning", hi=0
    )
    if type(laser["swap_polarization"]) is not bool:
        raise ValueError("Invalid 2D-MOT polarization-swap default.")

    magnetic_field = value["magnetic_field"]
    require_exact_keys(
        magnetic_field, {"magnet_radius_m"}, "2D-MOT magnetic-field defaults"
    )
    require_finite_number(
        magnetic_field["magnet_radius_m"], "2D-MOT magnet radius", lo=0
    )

    boundary = value["propagation_boundary"]
    require_exact_keys(
        boundary, {"start_distance_m"}, "2D-MOT propagation boundary"
    )
    require_finite_number(
        boundary["start_distance_m"], "2D-MOT start distance", lo=0
    )
    return value


def _read_validated():
    return read_strict_json(
        SPECIFICATION_PATH,
        _validate,
        max_bytes=MAX_SPECIFICATION_BYTES,
        error_message="The bundled 2D-MOT operating specification is invalid.",
    )


def _load_validated_bundle(reader=_read_validated):
    value = reader()
    return freeze(value), canonical_digest(value)


MOT_2D_OPERATING_SPECIFICATION, MOT_2D_OPERATING_SPEC_SHA256 = (
    _load_validated_bundle()
)
MOT_2D_OPERATING_SPEC_VERSION = MOT_2D_OPERATING_SPECIFICATION["spec_version"]


def load_mot_2d_operating_specification():
    """Return the immutable generic 2D-MOT operating-default contract."""
    return MOT_2D_OPERATING_SPECIFICATION
