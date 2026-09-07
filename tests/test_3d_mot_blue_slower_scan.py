from studies.scan_3d_mot_blue_slower import _matrix, slowing_rank_key


def _record(detuning, s0, slow, eligible, residence, speed):
    return {
        "profile": "profile",
        "detuning_gamma": detuning,
        "s0": s0,
        "entered_capture_region_count": 10,
        "slow_inside_count": slow,
        "minimum_residence_met_count": residence,
        "capture_eligible_ever_count": eligible,
        "median_minimum_speed_inside_m_s": speed,
    }


def test_slowing_rank_prioritizes_capture_then_slow_count_then_speed():
    records = [
        _record(-1.0, 0.3, slow=8, eligible=0, residence=0, speed=4.0),
        _record(-2.0, 0.3, slow=1, eligible=1, residence=1, speed=8.0),
    ]
    assert max(records, key=slowing_rank_key) is records[1]


def test_scan_matrix_maps_sorted_physical_axes_to_rows_and_columns():
    records = [
        _record(-2.0, 0.3, slow=1, eligible=0, residence=0, speed=8.0),
        _record(-1.0, 0.3, slow=2, eligible=0, residence=0, speed=7.0),
        _record(-2.0, 1.0, slow=3, eligible=0, residence=0, speed=6.0),
        _record(-1.0, 1.0, slow=4, eligible=0, residence=0, speed=5.0),
    ]
    matrix = _matrix(
        records,
        "profile",
        (-2.0, -1.0),
        (0.3, 1.0),
        "slow_inside_count",
    )
    assert matrix.tolist() == [[1.0, 2.0], [3.0, 4.0]]
