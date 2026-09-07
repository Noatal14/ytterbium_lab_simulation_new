from studies.merge_3d_mot_blue_scan_shards import merge_reports


def _report(shard_index, entered, slow, speed):
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
    return {
        "num_shards": 2,
        "shard_index": shard_index,
        "profiles": ["angled_sequential"],
        "detuning_gamma_values": [-2.0],
        "s0_values": [1.0],
        "input_particle_count": 5,
        "records": [row],
    }


def test_merge_reports_sums_counts_and_labels_shard_median_statistics():
    row = merge_reports([_report(0, 3, 1, 4.0), _report(1, 4, 2, 6.0)])[0]

    assert row["input_particle_count"] == 10
    assert row["entered_capture_region_count"] == 7
    assert row["slow_inside_count"] == 3
    assert row["weighted_mean_of_shard_medians_minimum_speed_inside_m_s"] == 5.0
    assert row["minimum_shard_median_minimum_speed_inside_m_s"] == 4.0
    assert row["maximum_shard_median_minimum_speed_inside_m_s"] == 6.0
