import numpy as np

from studies.run_zeeman_magnet_impact import PROFILE_NAME, corrected_field
from config import ZEEMAN_MAGNET_PROFILES


def test_corrected_profile_is_exactly_19_complete_rings():
    profile = ZEEMAN_MAGNET_PROFILES[PROFILE_NAME]
    assert [len(values) for values in profile] == [19, 19, 19]
    field = corrected_field()
    assert set(field) == {"radii_m", "positions_m", "tilt_angles_deg"}
    assert np.all(np.diff(field["positions_m"]) > 0)


def test_corrected_profile_does_not_replace_historical_active_profile():
    assert PROFILE_NAME != "active"
    assert len(ZEEMAN_MAGNET_PROFILES["active"][0]) == 20
