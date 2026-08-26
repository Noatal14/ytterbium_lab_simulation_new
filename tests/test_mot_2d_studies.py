import json

import numpy as np

from utils.mot_2d_study import (
    load_production_ensembles,
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
            "--s0-bounds", "1.4", "1.5",
            "--detuning-bounds", "-1.32", "-1.10",
            "--magnet-radius-bounds-m", "0.0488", "0.0506",
        ]
    )

    assert args.s0_bounds == [1.4, 1.5]
    assert args.detuning_bounds == [-1.32, -1.10]
    assert args.magnet_radius_bounds_m == [0.0488, 0.0506]


def test_candidate_validation_reports_paired_noninferiority():
    from studies.validate_2d_mot_candidates import paired_comparison

    def result(name, efficiencies):
        return {
            "name": name,
            "evaluation": {
                "replicates": [
                    {
                        "zeeman_seed": 3000 + index,
                        "mot_seed": 6000 + index,
                        "n_input": 10_000,
                        "subset_seed": 103_000 + index,
                        "conditional_efficiency": efficiency,
                    }
                    for index, efficiency in enumerate(efficiencies)
                ]
            },
        }

    reference = result("maximum_capture", [0.0255, 0.0256, 0.0254])
    candidate = result("low_power", [0.0252, 0.0253, 0.0251])
    comparison = paired_comparison(candidate, reference)

    assert np.isclose(comparison["mean_paired_difference_fraction"], -0.0003)
    assert comparison["passes_noninferiority_at_95_percent"]
    json.dumps(comparison)


def test_candidate_validation_accepts_array_index():
    from studies.validate_2d_mot_candidates import parse_args

    args = parse_args(["--candidate-index", "2", "--npools", "200"])

    assert args.candidate_index == 2
    assert args.npools == 200


def test_robustness_grid_has_one_center_and_expected_steps():
    from studies.validate_2d_mot_robustness import (
        CENTER_INDEX,
        OFFSETS,
        SELECTED_PARAMETERS,
        point_definition,
    )

    assert len(OFFSETS) == 27
    center = point_definition(CENTER_INDEX)
    assert center["offset_steps"] == {
        "s0": 0,
        "detuning_gamma": 0,
        "magnet_radius": 0,
    }
    assert center["parameters"] == SELECTED_PARAMETERS

    upper = point_definition(26)
    assert upper["offset_steps"] == {
        "s0": 1,
        "detuning_gamma": 1,
        "magnet_radius": 1,
    }
    assert np.isclose(
        upper["parameters"]["magnet_radius"]
        - SELECTED_PARAMETERS["magnet_radius"],
        0.01e-3,
    )


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
