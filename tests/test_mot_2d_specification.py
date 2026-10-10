from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import json

import pytest

from workflow_api.mot_2d_plan import (
    render_campaign_files,
    render_confirmation_transition,
    render_refine_transition,
    render_screen_transition,
)
from workflow_api.mot_2d_spec import FIXED_DESIGN, ROLE_SEEDS
from workflow_api.mot_2d_specification import (
    MOT_2D_SPECIFICATION,
    _validate,
    render_typescript_specification,
)


def _manifest(stage: str) -> dict:
    return {
        "kind": "mot_2d_s0_campaign",
        "name": "campaign",
        "stage": stage,
        "s0_values": [1.3],
        "stages": {},
        "provenance": {"git_commit": "a" * 40},
        "fixed_design": FIXED_DESIGN,
    }


def _directives(data: bytes) -> set[str]:
    return {line for line in data.decode().splitlines() if line.startswith("#PBS")}


def test_v1_design_matches_scientific_authority_and_is_deeply_immutable():
    spec = MOT_2D_SPECIFICATION
    design = spec["design"]
    assert spec["stage_order"] == (
        "smoke",
        "screen",
        "refine",
        "confirmation",
        "sensitivity",
        "production",
    )
    assert design["solver"] == FIXED_DESIGN["solver"]
    assert design["working_dt_s"] == FIXED_DESIGN["working_dt_s"]
    assert design["final_dt_s"] == FIXED_DESIGN["final_dt_s"]
    assert design["ensemble_count"] == sum(map(len, ROLE_SEEDS.values())) == 35
    assert design["prepared_file_count"] == 72
    assert (
        design["screen_trials_per_worker"]
        == FIXED_DESIGN["trial_budgets"]["screen_per_worker"]
    )
    assert (
        design["refine_trials_per_worker"]
        == FIXED_DESIGN["trial_budgets"]["refine_per_worker"]
    )
    with pytest.raises(TypeError):
        spec["design"]["solver"] = "other"


def test_v1_stage_artifacts_and_resources_match_canonical_renderers(tmp_path: Path):
    root = tmp_path
    campaign = root / "data/optimization/mot_2d/campaign"
    campaign.mkdir(parents=True)
    stages = MOT_2D_SPECIFICATION["stages"]
    smoke = render_campaign_files(_manifest("smoke"), campaign, root)
    screen = render_screen_transition(_manifest("smoke"), campaign, root)
    screen_rows = [
        {
            "s0": 1.3,
            "detuning_gamma": -1.0 - index * 0.02,
            "magnet_radius": 0.047 + index * 0.0001,
            "mean_conditional_efficiency": 1 - index * 0.1,
            "source": f"s{index}",
        }
        for index in range(3)
    ]
    refine = render_refine_transition(_manifest("screen"), campaign, root, screen_rows)
    refine_rows = [
        {
            "s0": 1.3,
            "detuning_gamma": -1.0 - index * 0.02,
            "magnet_radius": 0.047 + index * 0.0001,
            "mean_conditional_efficiency": 1 - index * 0.1,
            "source": f"r{index}",
        }
        for index in range(5)
    ]
    confirmation = render_confirmation_transition(
        _manifest("refine"), campaign, root, refine_rows
    )
    rendered = {
        "smoke": smoke,
        "screen": screen,
        "refine": refine,
        "confirmation": confirmation,
    }
    for stage in rendered:
        assert set(rendered[stage]) == set(stages[stage]["artifacts"])
    jobs = {
        "smoke": smoke["jobs/01_smoke.pbs"],
        "screen": screen["jobs/02_screen.pbs"],
        "confirmation": confirmation["jobs/04_confirmation.pbs"],
    }
    for stage, data in jobs.items():
        spec = stages[stage]
        directives = _directives(data)
        assert f"#PBS -l select=1:ncpus={spec['cores_per_task']}:mem=64gb" in directives
        assert spec["memory_per_task_bytes"] == 64 * 1024**3
        hours, remain = divmod(spec["walltime_seconds"], 3600)
        minutes, seconds = divmod(remain, 60)
        assert f"#PBS -l walltime={hours:02d}:{minutes:02d}:{seconds:02d}" in directives
    for index, name in enumerate(stages["refine"]["round_job_files"], 1):
        directives = _directives(refine[name])
        assert (
            "#PBS -l select=1:ncpus=200:mem=64gb" in directives
            and "#PBS -l walltime=20:00:00" in directives
        )
        assert (
            f"--target-trials {stages['refine']['cumulative_trial_targets'][index-1]}"
            in refine[name].decode()
        )
    chain = refine[stages["refine"]["submit_chain"]].decode()
    assert (
        chain.count("depend=afterok:") == 3
        and stages["refine"]["dependency"] == "afterok"
    )
    assert all(
        f"/jobs/03_refine_round_{index:02d}.pbs" in chain for index in range(1, 5)
    )
    assert "#PBS -J" not in smoke["jobs/01_smoke.pbs"].decode()
    assert "#PBS -J 0-2%3" in screen["jobs/02_screen.pbs"].decode()
    assert all(
        "#PBS -J 0-2%3" in refine[name].decode()
        for name in stages["refine"]["round_job_files"]
    )
    assert "#PBS -J 0-4%3" in confirmation["jobs/04_confirmation.pbs"].decode()
    assert (
        len(json.loads(screen["screen/tasks.json"]))
        == MOT_2D_SPECIFICATION["design"]["workers_per_s0"]
    )
    assert (
        len(json.loads(refine["refine/tasks.json"]))
        == MOT_2D_SPECIFICATION["design"]["screen_candidates_per_s0"]
    )
    assert (
        len(json.loads(confirmation["confirmation/tasks.json"]))
        == MOT_2D_SPECIFICATION["design"]["confirmation_candidates_per_s0"]
    )


def test_checked_in_ts_artifact_contract_is_deterministic():
    # P8 frontend generation target: a checked-in JSON-compatible const module.
    assert MOT_2D_SPECIFICATION["spec_version"] == "mot_2d-v1"
    assert tuple(MOT_2D_SPECIFICATION["stages"]) == MOT_2D_SPECIFICATION["stage_order"]
    first = render_typescript_specification()
    second = render_typescript_specification()
    assert first == second
    assert first.startswith(
        "// Generated from workflow_api/specifications/mot_2d_v1.json; do not edit.\n"
    )
    assert first.endswith(" as const;\n")


def test_checked_in_typescript_artifact_matches_generator_exactly():
    generated = Path("ui/src/generated/mot2dSpec.v1.ts")
    assert generated.is_file() and not generated.is_symlink()
    assert generated.read_bytes() == render_typescript_specification().encode("utf-8")


def test_ui_production_code_does_not_duplicate_migrated_canonical_facts():
    domain = Path("ui/src/api/schema/domain.ts").read_text()
    creation = Path("ui/src/components/CampaignCreation.tsx").read_text()
    smoke_flow = Path("ui/src/features/campaign/SmokeFlow.tsx").read_text()
    for duplicate in (
        "campaign.s0_values.length * 3 * 17",
        "campaign.s0_values.length * 30",
        "const targets = [3, 6, 9, 10]",
        'job.file !== "jobs/04_confirmation.pbs"',
        "job.memory_per_task_bytes !== 68719476736",
        "artifacts.created !== 2",
        "artifacts.created !== 7",
        "artifacts.created !== 3",
        "artifacts.updated !== 1",
        "updated: 1",
        "Number(scheduler.task_count) / 3",
        "worker[012]",
        "round_job_ids: [string, string, string, string]",
        'JSON.stringify(["campaign.json"])',
    ):
        assert duplicate not in domain
    assert "RK4StHybridCustom" not in creation
    assert "all 35 validated Zeeman ensembles" not in creation
    assert "1 CPU core · 64 GB memory" not in smoke_flow
    assert "20 minutes" not in smoke_flow


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["design"].__setitem__("ensemble_count", 35.0),
        lambda value: value["design"].__setitem__("workers_per_s0", True),
        lambda value: value["stages"]["screen"].__setitem__(
            "artifacts", ["screen/tasks.json", 7]
        ),
        lambda value: value["stages"]["screen"].__setitem__(
            "artifacts", ["same", "same"]
        ),
        lambda value: value["stages"]["smoke"].__setitem__("job_file", "../escape.pbs"),
        lambda value: value["stages"]["refine"].__setitem__("dependency", "afterany"),
        lambda value: value["stages"]["refine"].__setitem__(
            "cumulative_trial_targets", [3, 3, 9, 10]
        ),
        lambda value: value["stages"]["production"].__setitem__("label", ""),
    ],
)
def test_v1_schema_rejects_ambiguous_or_unsafe_mutations(mutation):
    value = json.loads(Path("workflow_api/specifications/mot_2d_v1.json").read_text())
    mutation(value)
    with pytest.raises(ValueError, match="Invalid 2D-MOT specification"):
        _validate(value)
