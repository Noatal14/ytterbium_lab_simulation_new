from studies.scan_zeeman_capture_velocity import summarize_capture_boundary


def test_capture_boundary_uses_adjacent_slowed_and_unslowed_speeds():
    rows = [
        {"requested_initial_speed_m_s": 312.0, "slowed_below_exit_threshold": True},
        {"requested_initial_speed_m_s": 314.0, "slowed_below_exit_threshold": False},
        {"requested_initial_speed_m_s": 313.0, "slowed_below_exit_threshold": True},
    ]

    boundary = summarize_capture_boundary(rows)

    assert boundary["boundary_bracket_m_s"] == [313.0, 314.0]
    assert boundary["capture_is_monotonic_over_sampled_speeds"] is True


def test_nonmonotonic_capture_is_reported_without_false_boundary_bracket():
    rows = [
        {"requested_initial_speed_m_s": 329.0, "slowed_below_exit_threshold": True},
        {"requested_initial_speed_m_s": 329.1, "slowed_below_exit_threshold": False},
        {"requested_initial_speed_m_s": 329.2, "slowed_below_exit_threshold": True},
    ]

    boundary = summarize_capture_boundary(rows)

    assert boundary["capture_is_monotonic_over_sampled_speeds"] is False
    assert boundary["boundary_bracket_m_s"] is None
    assert len(boundary["outcome_transitions"]) == 2
