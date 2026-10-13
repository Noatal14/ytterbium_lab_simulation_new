import json

from studies.mot_3d_campaign import (
    prepare_finalist_selection,
    render_finalist_selection_transition,
)


PARAMETERS = {
    "angled_donut": {
        "green_s0": 18.0,
        "green_detuning_gamma": -18.0,
        "green_waist_m": 0.0065,
        "blue_s0": 1.4,
        "blue_waist_m": 0.0074,
        "magnetic_gradient_G_cm": 5.5,
        "blue_detuning_gamma": -0.8,
        "core_shell_split_radius_m": 0.0026,
    },
    "single_pass": {
        "green_s0": 38.0,
        "green_detuning_gamma": -25.0,
        "green_waist_m": 0.0074,
        "blue_s0": 0.2,
        "blue_waist_m": 0.0073,
        "magnetic_gradient_G_cm": 2.3,
        "blue_detuning_anchor_gamma": -2.5,
        "blue_crossing_angle_deg": 46.0,
        "blue_crossing_z_offset_m": -0.046,
    },
}


def test_finalist_renderer_is_portable_exact_and_has_no_submission_side_effect(
    tmp_path,
):
    manifest = {
        "stage": "closure",
        "provenance": {"git_commit": "a" * 40},
        "design": {"screening_dt_s": 1e-5},
        "stages": {},
    }
    summaries = {
        family: {
            "family": family,
            "ranked_candidates": [
                {
                    "candidate_id": f"{family}_closure_{index:02d}",
                    "closure_role": f"role{index}",
                    "mean_usable_fraction": 0.2 - index / 100,
                    "bootstrap_95_ci": [0.1, 0.3],
                    "simultaneous_95_ci": [0.1 - index / 100, 0.3],
                    "parameters": dict(PARAMETERS[family]),
                }
                for index in range(3)
            ],
        }
        for family in PARAMETERS
    }
    artifacts, updated = render_finalist_selection_transition(
        "data/optimization/mot_3d/example", manifest, summaries
    )
    assert set(artifacts) == {
        "campaign.json",
        "selection/finalists/angled_donut.json",
        "selection/finalists/single_pass.json",
        "jobs/finalist_selection/angled_donut_array.pbs",
        "jobs/finalist_selection/angled_donut_merge.pbs",
        "jobs/finalist_selection/single_pass_array.pbs",
        "jobs/finalist_selection/single_pass_merge.pbs",
    }
    assert updated["stage"] == "finalist_selection"
    assert manifest["stage"] == "closure"
    assert all(b"/home/" not in raw for raw in artifacts.values())
    root = tmp_path / "data" / "optimization" / "mot_3d" / "example"
    root.mkdir(parents=True)
    for family, summary in summaries.items():
        destination = root / "closure" / family / "merged"
        destination.mkdir(parents=True)
        (destination / "refinement_summary.json").write_text(json.dumps(summary))
    mutable = json.loads(json.dumps(manifest))
    prepare_finalist_selection(root, mutable)
    assert {
        relative: (root / relative).read_bytes() for relative in artifacts
    } == artifacts
    assert mutable == updated
