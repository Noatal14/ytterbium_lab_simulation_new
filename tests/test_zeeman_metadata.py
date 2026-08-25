import hashlib
import json

import numpy as np

from simulations.zeeman import write_zeeman_metadata


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
