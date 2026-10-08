import numpy as np

from studies.zeeman.generate_ensembles import (
    PROFILE_NAME,
    corrected_field,
    output_path,
)


def test_corrected_production_profile_and_filename_are_unambiguous(tmp_path):
    field = corrected_field()
    assert PROFILE_NAME == "corrected_projectant_19ring_20261005"
    assert [
        len(field[key]) for key in ("radii_m", "positions_m", "tilt_angles_deg")
    ] == [
        19,
        19,
        19,
    ]
    assert np.all(np.diff(field["positions_m"]) > 0.0)
    assert output_path(3007, tmp_path).name == (
        "production_zeeman_n50000_dt40us_seed3007.npy"
    )
