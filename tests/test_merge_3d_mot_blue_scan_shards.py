from studies.merge_3d_mot_blue_scan_shards import merge_reports


def _report(
    shard_index, entered, slow, speed, gradient=None, green_point=None
):
    row = {
        "profile": "angled_sequential",
        "detuning_gamma": -2.0,
        "s0": 1.0,
        "entered_capture_region_count": entered,
        "slow_inside_count": slow,
        "minimum_residence_met_count": 1,
        "capture_eligible_ever_count": 1,
        "peak_capture_eligible_count": 1,
        "blue_exposed_particle_count": 2,
        "median_minimum_speed_inside_m_s": speed,
        "median_maximum_blue_relative_intensity": 0.5,
        "median_blue_exposure_time_s": 0.001,
        "median_delta_vz_during_blue_exposure_m_s": -10.0,
    }
    if gradient is not None:
        row["gradient_G_cm"] = gradient
    if green_point is not None:
        row["green_s0"], row["green_detuning_gamma"] = green_point
    return {
        "num_shards": 2,
        "shard_index": shard_index,
        "profiles": ["angled_sequential"],
        "detuning_gamma_values": [-2.0],
        "s0_values": [1.0],
        "input_particle_count": 5,
        "records": [row],
        "gradient_G_cm_values": [gradient] if gradient is not None else None,
        "green_s0_values": [green_point[0]] if green_point is not None else None,
        "green_detuning_gamma_values": (
            [green_point[1]] if green_point is not None else None
        ),
    }


def test_merge_reports_sums_counts_and_labels_shard_median_statistics():
    row = merge_reports([_report(0, 3, 1, 4.0), _report(1, 4, 2, 6.0)])[0]

    assert row["input_particle_count"] == 10
    assert row["entered_capture_region_count"] == 7
    assert row["slow_inside_count"] == 3
    assert row["weighted_mean_of_shard_medians_minimum_speed_inside_m_s"] == 5.0
    assert row["minimum_shard_median_minimum_speed_inside_m_s"] == 4.0
    assert row["maximum_shard_median_minimum_speed_inside_m_s"] == 6.0


def test_merge_reports_keeps_gradient_as_part_of_point_identity():
    row = merge_reports(
        [_report(0, 3, 1, 4.0, gradient=7.5), _report(1, 4, 2, 6.0, gradient=7.5)]
    )[0]

    assert row["gradient_G_cm"] == 7.5


def test_merge_reports_keeps_green_parameters_as_part_of_point_identity():
    kwargs = {"gradient": 10.0, "green_point": (5.0, -10.0)}
    row = merge_reports(
        [_report(0, 3, 1, 4.0, **kwargs), _report(1, 4, 2, 6.0, **kwargs)]
    )[0]

    assert row["green_s0"] == 5.0
    assert row["green_detuning_gamma"] == -10.0


def test_merge_keeps_selected_geometry_without_requiring_geometry_stage_checks():
    reports = [_report(0, 3, 1, 4.0), _report(1, 4, 2, 6.0)]
    for report in reports:
        report["records"][0].update(
            blue_waist_mm=3.0,
            green_exclusion_radius_mm=10.0,
            crossing_distance_mm=20.0,
        )

    row = merge_reports(reports)[0]

    assert row["blue_waist_mm"] == 3.0
    assert row["green_exclusion_radius_mm"] == 10.0
    assert row["crossing_distance_mm"] == 20.0
    assert "summed_blue_intensity_at_mot_center_W_m2" not in row
