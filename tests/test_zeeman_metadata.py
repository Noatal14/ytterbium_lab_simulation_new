import hashlib
import json

import numpy as np
import pytest

from config import ZEEMAN_MAGNET_PROFILES
from simulations.zeeman import (
    _resolved_run_parameters, write_zeeman_metadata, zeeman_simulation,
)
from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
)


def test_zeeman_metadata_records_shape_parameters_and_file_hash(tmp_path):
    states = np.arange(18, dtype=float).reshape(3, 6)
    output = tmp_path / "survivors.npy"
    np.save(output, states)

    metadata_path = write_zeeman_metadata(
        output,
        states,
        {
            "N_particles": 10,
            "seed": 123,
            "dt": 4e-5,
            "npools": 2,
            "stochastic": True,
        },
        elapsed_seconds=1.25,
    )

    metadata = json.loads(metadata_path.read_text())
    expected_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    assert metadata["shape"] == [3, 6]
    assert metadata["n_survivors"] == 3
    assert metadata["survival_fraction"] == 0.3
    assert metadata["parameters"]["seed"] == 123
    assert metadata["parameters"]["dt_s"] == 4e-5
    assert metadata["output_sha256"] == expected_hash
    assert metadata["laboratory_spec_version"] == LABORATORY_SPEC_VERSION
    assert metadata["laboratory_spec_sha256"] == LABORATORY_SPEC_SHA256
    assert metadata["zeeman_profile_sha256"] == CANONICAL_ZEEMAN_PROFILE_SHA256


def test_resolved_parameters_identify_explicit_corrected_magnet_profile():
    profile_name = "corrected_projectant_19ring_20261005"
    radii, positions, tilts = ZEEMAN_MAGNET_PROFILES[profile_name]

    parameters = _resolved_run_parameters(
        {
            "zeeman_field_config": {
                "radii_m": radii,
                "positions_m": positions,
                "tilt_angles_deg": tilts,
            }
        }
    )

    assert parameters["resolved_zeeman_magnet_profile"] == profile_name


def test_resolved_parameters_reject_noncanonical_field_arrays():
    radii, positions, tilts = ZEEMAN_MAGNET_PROFILES[
        "corrected_projectant_19ring_20261005"
    ]
    changed = [list(radii), list(positions), list(tilts)]
    changed[0][0] += 1e-6
    with pytest.raises(ValueError, match="canonical magnet profile"):
        _resolved_run_parameters({"zeeman_field_config": {
            "radii_m": changed[0], "positions_m": changed[1],
            "tilt_angles_deg": changed[2],
        }})
    with pytest.raises(ValueError, match="canonical magnet profile"):
        zeeman_simulation(N_particles=0, zeeman_field_config={
            "radii_m": changed[0], "positions_m": changed[1],
            "tilt_angles_deg": changed[2],
        })
