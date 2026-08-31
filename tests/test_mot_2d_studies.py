import json

import numpy as np

from utils.mot_2d_study import (
    load_production_ensembles,
    prediction_for_new_run,
    student_mean_interval,
    summarize_replicates,
)


def test_joint_followup_uses_updated_experimental_bounds():
    from studies.optimize_2d_mot_joint import (
        BOUNDS_DETUNING,
        BOUNDS_MAGNET_RADIUS_M,
        BOUNDS_S0,
    )

    assert BOUNDS_S0 == (1.4, 1.5)
    assert BOUNDS_DETUNING == (-1.55, -0.85)
    assert BOUNDS_MAGNET_RADIUS_M == (0.045, 0.051)


def test_joint_optimizer_accepts_refinement_bounds():
    from studies.optimize_2d_mot_joint import parse_args

    args = parse_args(
        [
            "--s0-bounds",
            "1.4",
            "1.5",
            "--detuning-bounds",
            "-1.32",
            "-1.10",
            "--magnet-radius-bounds-m",
            "0.0488",
            "0.0506",
            "--stochastic-solver",
            "hybrid",
            "--sampler-seed",
            "137",
        ]
    )

    assert args.s0_bounds == [1.4, 1.5]
    assert args.detuning_bounds == [-1.32, -1.10]
    assert args.magnet_radius_bounds_m == [0.0488, 0.0506]
    assert args.stochastic_solver == "hybrid"
    assert args.sampler_seed == 137


def test_hybrid_finalists_include_anchor_and_refinement_points():
    from studies.validate_2d_mot_hybrid_finalists import FINALISTS, parse_args

    assert [row["name"] for row in FINALISTS] == [
        "validated_anchor",
        "overnight_maximum",
        "overnight_lower_power",
    ]
    args = parse_args(["--finalist-index", "1", "--npools", "200"])
    assert args.finalist_index == 1
    assert args.npools == 200


def test_final_sensitivity_separates_power_response_from_local_tuning():
    from studies.validate_2d_mot_final_sensitivity import (
        POINTS,
        REFERENCE_INDEX,
        REFERENCE_PARAMETERS,
        parse_args,
    )

    local_points = [
        point for point in POINTS if point["scan_axis"] == "detuning_radius_grid"
    ]
    power_points = [
        point for point in POINTS if point["scan_axis"] == "s0_response"
    ]

    assert len(POINTS) == 13
    assert len(local_points) == 9
    assert len(power_points) == 4
    assert POINTS[REFERENCE_INDEX]["parameters"] == REFERENCE_PARAMETERS
    assert {point["parameters"]["s0"] for point in local_points} == {
        REFERENCE_PARAMETERS["s0"]
    }
    assert max(point["parameters"]["s0"] for point in POINTS) == 1.5

    args = parse_args(["--point-index", "12", "--npools", "200"])
    assert args.point_index == 12
    assert args.npools == 200
    assert np.isclose(args.particles_per_ensemble, 2_000)


def test_sensitivity_confirmation_has_only_two_actionable_candidates():
    from studies.validate_2d_mot_sensitivity_candidates import (
        CANDIDATES,
        FINAL_DT_S,
        parse_args,
    )

    assert [candidate["name"] for candidate in CANDIDATES] == [
        "shifted_tuning_selected_s0",
        "shifted_tuning_s0_1p5",
    ]
    assert CANDIDATES[0]["detuning_gamma"] == CANDIDATES[1]["detuning_gamma"]
    assert CANDIDATES[0]["magnet_radius"] == CANDIDATES[1]["magnet_radius"]
    assert CANDIDATES[1]["s0"] == 1.5
    assert np.isclose(FINAL_DT_S, 0.625e-6)

    args = parse_args(["--candidate-index", "1", "--npools", "200"])
    assert args.candidate_index == 1
    assert args.npools == 200


def test_final_production_prediction_uses_conservative_variance():
    from studies.run_2d_mot_final_production import final_prediction, parse_args

    replicates = [
        {
            "n_input": 30_000,
            "captured": captured,
            "conditional_efficiency": captured / 30_000,
            "estimated_total_efficiency": captured / 60_000,
        }
        for captured in (720, 750, 780, 810)
    ]
    prediction = final_prediction(replicates)

    assert prediction["simulated_zeeman_survivors"] == 120_000
    assert prediction["simulated_captured_atoms"] == 3_060
    assert prediction["selected_mean_variance"] >= prediction["binomial_mean_variance"]
    assert prediction["selected_mean_variance"] >= 0
    assert prediction["predicted_95_captured_atoms_interval"][0] < 255_000
    assert prediction["predicted_95_captured_atoms_interval"][1] > 255_000

    args = parse_args(
        [
            "--zeeman-seeds",
            "3000",
            "3001",
            "--s0",
            "1.5",
            "--detuning-gamma",
            "-1.2",
            "--magnet-radius-mm",
            "49.3",
            "--npools",
            "200",
        ]
    )
    assert args.zeeman_seeds == [3000, 3001]
    assert args.s0 == 1.5
    assert args.magnet_radius_mm == 49.3


def test_student_interval_requires_replicates():
    mean, low, high, half_width = student_mean_interval([0.25])
    assert mean == 0.25
    assert low is high is half_width is None


def test_replicate_summary_reports_conditional_and_total_uncertainty():
    result = summarize_replicates(
        [
            {"conditional_efficiency": 0.20, "estimated_total_efficiency": 0.10},
            {"conditional_efficiency": 0.22, "estimated_total_efficiency": 0.11},
            {"conditional_efficiency": 0.21, "estimated_total_efficiency": 0.105},
        ]
    )
    assert result["n_replicates"] == 3
    assert np.isclose(result["mean_conditional_efficiency"], 0.21)
    assert np.isclose(result["mean_estimated_total_efficiency"], 0.105)
    assert result["conditional_95_ci_half_width"] > 0


def test_prediction_for_new_run_reports_count_and_interval():
    replicates = [
        {"conditional_efficiency": value} for value in (0.024, 0.025, 0.026, 0.0255)
    ]
    result = prediction_for_new_run(replicates, reporting_survivors=1_000_000)

    assert result["reporting_zeeman_survivors"] == 1_000_000
    assert result["expected_captured_atoms"] == 25_125
    assert result["predicted_95_interval_fraction"][0] < 0.025125
    assert result["predicted_95_interval_fraction"][1] > 0.025125


def test_load_production_ensembles_uses_ordered_fixed_subsets(tmp_path):
    for seed, size in [(3001, 20), (3000, 20)]:
        path = tmp_path / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
        states = np.column_stack(
            (np.arange(size), np.full((size, 5), seed, dtype=float))
        )
        np.save(path, states)
        path.with_suffix(".json").write_text(
            json.dumps(
                {
                    "parameters": {"seed": seed, "n_initial_atoms": 50000},
                    "survival_fraction": size / 50000,
                }
            ),
            encoding="utf-8",
        )
    ensembles = load_production_ensembles(2, 5, directory=tmp_path)
    repeated = load_production_ensembles(2, 5, directory=tmp_path)
    assert [row["zeeman_seed"] for row in ensembles] == [3000, 3001]
    assert [len(row["states"]) for row in ensembles] == [5, 5]
    assert all(
        row["selection_method"] == "deterministic_random_without_replacement"
        for row in ensembles
    )
    assert all(
        np.array_equal(first["states"], second["states"])
        for first, second in zip(ensembles, repeated)
    )
    assert not np.array_equal(ensembles[0]["states"][:, 0], np.arange(5))


def test_load_production_ensembles_can_select_explicit_seed_order(tmp_path):
    for seed in (3000, 3001, 3002):
        path = tmp_path / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
        np.save(path, np.full((4, 6), seed, dtype=float))
        path.with_suffix(".json").write_text(
            json.dumps(
                {
                    "parameters": {"seed": seed, "n_initial_atoms": 50000},
                    "survival_fraction": 4 / 50000,
                }
            ),
            encoding="utf-8",
        )

    ensembles = load_production_ensembles(
        particles_per_ensemble=None,
        directory=tmp_path,
        zeeman_seeds=[3002, 3000],
    )

    assert [row["zeeman_seed"] for row in ensembles] == [3002, 3000]
