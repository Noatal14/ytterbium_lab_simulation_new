import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from config import Geometry, MOT_3D_FINALIST_STABILITY_CONFIG
from studies.compare_3d_mot_finalist_stability import (
    active_trajectory_counts,
    finalist_profiles,
)
from studies.analyze_3d_mot_five_beam_velocity import (
    sampled_longitudinal_velocities,
)
from studies.merge_3d_mot_five_beam_velocity import plot_velocity
from studies.merge_3d_mot_finalist_stability import (
    _validate_reports,
    historical_donut_curve,
    merge_direct_curves,
    run_merge,
)


def test_finalist_profiles_reproduce_selected_operating_points():
    profiles = finalist_profiles()
    five = profiles["five_beam_best"]
    assert five["magnetic_gradient_G_cm"] == 1.4
    assert five["556"]["s0"] == 10.0
    assert five["556"]["s0_by_axis"] == {"+X": 2.5}
    assert five["556"]["detuning_gamma"] == -20.0

    four = profiles["four_blue_gate_best"]
    assert four["399"]["s0"] == 0.75
    assert four["399"]["detuning_gamma"] == -2.0
    assert four["399"]["waist_m"] == 15e-3
    entrance, backstop = four["399"]["beam_groups"]
    center_z = Geometry.MOT_3D_CENTER_M[2]
    assert entrance["axis_tags"] == ("-XZ_1", "-XZ_2")
    assert entrance["center_offset_m"][2] == -20e-3
    assert entrance["maximum_lab_z_m"] == center_z - 10e-3
    assert backstop["center_offset_m"][2] == 35e-3
    assert backstop["minimum_lab_z_m"] == center_z + 10e-3
    assert backstop["maximum_lab_z_m"] == center_z + 55e-3


def test_production_resources_use_three_200_core_nodes():
    settings = MOT_3D_FINALIST_STABILITY_CONFIG
    assert settings["num_shards"] == 3
    assert settings["pbs_ncpus_per_shard"] == 200
    assert settings["pbs_memory_per_shard"] == "64gb"
    assert settings["pbs_walltime"] == "24:00:00"
    assert settings["t_max_s"] == 0.4


def test_active_counts_drop_after_a_trajectory_terminates():
    trajectories = [
        SimpleNamespace(t=np.array([0.0, 1.0, 2.0])),
        SimpleNamespace(t=np.array([0.0, 1.0])),
    ]
    counts = active_trajectory_counts(trajectories, np.array([0.0, 1.0, 2.0]))
    assert counts.tolist() == [2, 2, 1]


def _retention_report(counts):
    return {
        "time_points_s": [0.0, 0.1],
        "results": {"angled_donut": {"capture_eligible_counts": counts}},
    }


def test_historical_donut_curve_joins_at_100ms_without_duplicate(tmp_path):
    initial = tmp_path / "initial.json"
    continuation = tmp_path / "continuation.json"
    initial.write_text(json.dumps(_retention_report([0, 10])))
    continuation.write_text(json.dumps(_retention_report([10, 9])))

    time_s, counts = historical_donut_curve(initial, continuation)

    np.testing.assert_allclose(time_s, [0.0, 0.1, 0.2])
    np.testing.assert_allclose(counts, [0, 10, 9])


def test_direct_curve_merge_adds_disjoint_shards(tmp_path):
    report_paths = []
    for index, usable in enumerate(([1, 2], [3, 4])):
        shard = tmp_path / f"shard_{index}"
        shard.mkdir()
        report = shard / "finalist_stability_shard.json"
        report.write_text("{}")
        report_paths.append(report)
        np.savez_compressed(
            shard / "five_beam_best_curves.npz",
            time_s=[0.0, 1.0],
            active_counts=[5, 4],
            inside_counts=[2, 1],
            usable_counts=usable,
        )

    merged = merge_direct_curves(report_paths, "five_beam_best")

    assert merged["usable_counts"].tolist() == [4, 6]
    assert merged["active_counts"].tolist() == [10, 8]


def test_report_validation_requires_all_shards():
    reports = [
        {
            "num_shards": 3,
            "shard_index": index,
            "profiles": ["a"],
            "dt_s": 1e-5,
            "t_max_s": 0.4,
            "selected_particle_count_before_sharding": 9,
        }
        for index in (0, 2)
    ]
    try:
        _validate_reports(reports)
    except ValueError as error:
        assert "Expected shards" in str(error)
    else:
        raise AssertionError("Missing shard should be rejected")


def test_end_to_end_merge_writes_summary_and_graph(tmp_path):
    root = tmp_path / "run"
    for index in range(3):
        shard = root / f"shard_{index}"
        shard.mkdir(parents=True)
        report = {
            "num_shards": 3,
            "shard_index": index,
            "profiles": ["five_beam_best", "four_blue_gate_best"],
            "dt_s": 0.1,
            "t_max_s": 0.4,
            "selected_particle_count_before_sharding": 6,
            "input_particle_count": 2,
        }
        (shard / "finalist_stability_shard.json").write_text(json.dumps(report))
        for profile in report["profiles"]:
            np.savez_compressed(
                shard / f"{profile}_curves.npz",
                time_s=[0.0, 0.1, 0.2, 0.3, 0.4],
                active_counts=[2, 2, 2, 1, 1],
                inside_counts=[0, 2, 2, 1, 1],
                usable_counts=[0, 2, 2, 1, 1],
            )
    initial = tmp_path / "initial.json"
    continuation = tmp_path / "continuation.json"
    initial.write_text(json.dumps(_retention_report([0, 6])))
    continuation.write_text(json.dumps(_retention_report([6, 6])))
    output = root / "merged"
    graph = tmp_path / "comparison.png"

    summary = run_merge(root, output, initial, continuation, graph)

    assert graph.exists()
    assert (output / "finalist_stability_summary.json").exists()
    assert summary["input_particle_count"] == 6
    assert summary["results"]["five_beam_best"]["usable_at_400ms_count"] == 3


def test_velocity_sampling_marks_terminated_trajectory_with_nan():
    complete = SimpleNamespace(
        t=np.array([0.0, 0.1, 0.2]),
        y=np.vstack([np.zeros((5, 3)), [3.0, 2.0, 1.0]]),
    )
    terminated = SimpleNamespace(
        t=np.array([0.0, 0.1]),
        y=np.vstack([np.zeros((5, 2)), [4.0, 3.0]]),
    )
    times, velocities = sampled_longitudinal_velocities(
        [complete, terminated], np.array([0.0, 0.1, 0.2]), 0.1
    )

    np.testing.assert_allclose(times, [0.0, 0.1, 0.2])
    np.testing.assert_allclose(velocities[0], [3.0, 2.0, 1.0])
    np.testing.assert_allclose(velocities[1, :2], [4.0, 3.0])
    assert np.isnan(velocities[1, 2])


def test_five_beam_velocity_plot_is_created(tmp_path):
    output = tmp_path / "velocity.png"
    plot_velocity(
        {
            "time_s": np.array([0.0, 0.1]),
            "vz_m_s": np.array([[10.0, 0.0], [20.0, 5.0]]),
            "initial_vz_m_s": np.array([10.0, 20.0]),
            "usable_ever": np.array([True, False]),
        },
        output,
    )
    assert output.exists()
