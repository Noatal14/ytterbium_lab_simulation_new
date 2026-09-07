from studies.select_3d_mot_scan_points import select_points


def _record(s0, detuning, eligible, slow, speed, gradient=10.0):
    return {
        "s0": s0,
        "detuning_gamma": detuning,
        "gradient_G_cm": gradient,
        "capture_eligible_ever_count": eligible,
        "peak_capture_eligible_count": eligible,
        "minimum_residence_met_count": eligible,
        "slow_inside_count": slow,
        "entered_capture_region_count": 10,
        "weighted_mean_of_shard_medians_minimum_speed_inside_m_s": speed,
    }


def test_selection_prioritizes_full_capture_over_partial_slowing():
    captured = _record(1.2, -5.0, eligible=1, slow=1, speed=10.0)
    merely_slow = _record(1.0, -5.0, eligible=0, slow=10, speed=1.0)

    assert select_points({"records": [merely_slow, captured]}) == [captured]


def test_unique_blue_pairs_keep_best_gradient_for_each_pair():
    worse = _record(1.2, -5.0, eligible=0, slow=1, speed=10.0, gradient=5.0)
    better = _record(1.2, -5.0, eligible=1, slow=1, speed=10.0, gradient=10.0)
    other = _record(1.0, -5.0, eligible=0, slow=2, speed=9.0, gradient=10.0)

    selected = select_points(
        {"records": [worse, better, other]}, top_n=2, unique_blue_pairs=True
    )

    assert selected == [better, other]
