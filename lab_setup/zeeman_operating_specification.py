"""Strict immutable loader for the versioned Zeeman operating point."""

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
    Path(__file__).with_name("specifications") / "zeeman_operating_v1.json"
)


def _validate(value):
    require_exact_keys(
        value,
        {"spec_version", "laser", "propagation_boundary"},
        "Zeeman operating specification",
    )
    if value["spec_version"] != "zeeman-operating-v1":
        raise ValueError("Invalid Zeeman operating specification version.")

    laser = value["laser"]
    require_exact_keys(
        laser, {"s0", "detuning_gamma"}, "Zeeman laser operating point"
    )
    require_finite_number(laser["s0"], "Zeeman laser s0", lo=0)
    require_finite_number(laser["detuning_gamma"], "Zeeman laser detuning", hi=0)

    boundary = value["propagation_boundary"]
    require_exact_keys(
        boundary,
        {"start_distance_m", "cutoff_distance_m"},
        "Zeeman propagation boundary",
    )
    require_finite_number(
        boundary["start_distance_m"], "Zeeman start distance", lo=0
    )
    require_finite_number(
        boundary["cutoff_distance_m"], "Zeeman cutoff distance", lo=0
    )
    if boundary["start_distance_m"] <= boundary["cutoff_distance_m"]:
        raise ValueError("Zeeman start distance must exceed the cutoff distance.")
    return value


def _read_validated():
    return read_strict_json(
        SPECIFICATION_PATH,
        _validate,
        max_bytes=16 * 1024,
        error_message="The bundled Zeeman operating specification is invalid.",
    )


def _load_validated_bundle(reader=_read_validated):
    value = reader()
    return freeze(value), canonical_digest(value)


ZEEMAN_OPERATING_SPECIFICATION, ZEEMAN_OPERATING_SPEC_SHA256 = (
    _load_validated_bundle()
)
ZEEMAN_OPERATING_SPEC_VERSION = ZEEMAN_OPERATING_SPECIFICATION["spec_version"]


def load_zeeman_operating_specification():
    return ZEEMAN_OPERATING_SPECIFICATION
