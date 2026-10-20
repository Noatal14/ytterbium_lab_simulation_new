"""Preserve frozen binary64 radii without changing the legacy mm CLI."""
from types import SimpleNamespace

import pytest

from studies.mot_2d.production import parameters_from_args, parse_args


REQUIRED = ['--zeeman-seeds', '3015', '--mot-seeds', '43015', '--s0', '1.3', '--detuning-gamma', '-1.0']


def test_explicit_si_radius_preserves_frozen_binary64_and_old_mm_conversion():
    radius = 0.048772914725133266
    si = parameters_from_args(parse_args(REQUIRED + ['--magnet-radius-m', str(radius)]))
    mm_text = str(1000 * radius)
    legacy = parameters_from_args(parse_args(REQUIRED + ['--magnet-radius-mm', mm_text]))
    assert si['magnet_radius'].hex() == radius.hex()
    assert legacy['magnet_radius'] == float(mm_text) * 1e-3
    assert legacy['magnet_radius'] != radius  # This actual campaign value exposed the transport bug.
    direct_old_args = SimpleNamespace(s0=1.3, detuning_gamma=-1.0, magnet_radius_mm=float(mm_text))
    assert parameters_from_args(direct_old_args) == legacy


def test_radius_units_are_mutually_exclusive_and_one_is_required_for_execution():
    with pytest.raises(SystemExit): parse_args(REQUIRED)
    with pytest.raises(SystemExit): parse_args(REQUIRED + ['--magnet-radius-m', '0.05', '--magnet-radius-mm', '50'])
    args = parse_args(['--summarize-only'])
    assert args.magnet_radius_m is None and args.magnet_radius_mm is None
