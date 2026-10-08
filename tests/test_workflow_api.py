import json
import subprocess
import sys

import pytest

from workflow_api import list_workflows, read_campaign
from workflow_api.__main__ import main


def test_workflow_catalog_exposes_stable_ui_capabilities():
    workflows = {item.workflow_id: item for item in list_workflows()}

    mot_2d = workflows["mot_2d_fixed_s0"]
    assert mot_2d.maturity == "active"
    assert "inspect" in mot_2d.capabilities
    mot_3d = workflows["mot_3d_optimization"]
    assert mot_3d.maturity == "active"
    assert mot_3d.entrypoint == "studies.mot_3d_campaign"
    assert mot_3d.capabilities == ()
    assert workflows["zeeman_validation"].capabilities == ()


def test_read_campaign_is_side_effect_free_and_reports_progress(tmp_path):
    root = tmp_path / "campaign"
    (root / "jobs").mkdir(parents=True)
    (root / "smoke" / "s0_1p300000").mkdir(parents=True)
    (root / "screen" / "s0_1p300000" / "worker0" / "trials").mkdir(
        parents=True
    )
    job = root / "jobs" / "02_screen.pbs"
    job.write_text("#!/bin/bash\n", encoding="utf-8")
    (root / "smoke" / "s0_1p300000" / "summary.json").write_text("{}")
    for number in range(2):
        path = root / "screen" / "s0_1p300000" / "worker0" / "trials"
        (path / f"trial_{number:04d}.json").write_text("{}")
    manifest = {
        "kind": "mot_2d_s0_campaign",
        "name": "example",
        "stage": "screen",
        "s0_values": [1.3],
        "stages": {"screen": {"tasks": 3, "job_file": str(job)}},
        "fixed_design": {"trial_budgets": {"screen_per_worker": 17}},
        "provenance": {"git_commit": "abc123"},
        "ensemble_source": {"zeeman_profile": "corrected"},
    }
    campaign_path = root / "campaign.json"
    campaign_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = campaign_path.read_bytes()

    summary = read_campaign(root)

    assert campaign_path.read_bytes() == before
    assert summary.name == "example"
    assert summary.git_commit == "abc123"
    assert summary.next_plan.command == ("qsub", str(job.resolve()))
    assert not summary.next_plan.submission_enabled
    progress = {item.stage: item for item in summary.progress}
    assert progress["smoke"].status == "complete"
    assert progress["screen"].completed == 2
    assert progress["screen"].expected == 51
    assert progress["screen"].status == "in-progress"


def test_read_campaign_warns_for_legacy_incomplete_manifest(tmp_path):
    path = tmp_path / "campaign.json"
    path.write_text(
        json.dumps(
            {
                "kind": "mot_2d_s0_campaign",
                "name": "legacy",
                "stage": "screen",
                "s0_values": [1.3],
                "stages": {},
            }
        ),
        encoding="utf-8",
    )

    summary = read_campaign(path)

    assert len(summary.warnings) == 3
    assert any("pinned Git revision" in item for item in summary.warnings)
    assert any("Zeeman profile" in item for item in summary.warnings)
    assert any("no recorded job artifact" in item for item in summary.warnings)


def test_read_campaign_rejects_unrelated_manifest(tmp_path):
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps({"kind": "other"}), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported campaign kind"):
        read_campaign(path)


def test_read_only_cli_prints_json(capsys):
    main(["list"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["api_version"] == 1
    assert payload["data"][0]["workflow_id"] == "mot_2d_fixed_s0"


def test_relative_job_path_is_resolved_from_repository_not_cwd(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repository"
    (repository / ".git").mkdir(parents=True)
    root = repository / "data" / "optimization" / "campaign"
    job = root / "jobs" / "02_screen.pbs"
    job.parent.mkdir(parents=True)
    job.write_text("#!/bin/bash\n", encoding="utf-8")
    recorded = job.relative_to(repository)
    (root / "campaign.json").write_text(
        json.dumps(
            {
                "kind": "mot_2d_s0_campaign",
                "name": "paths",
                "stage": "screen",
                "s0_values": [1.3],
                "stages": {"screen": {"tasks": 1, "job_file": str(recorded)}},
                "provenance": {"git_commit": "abc"},
                "ensemble_source": {"zeeman_profile": "corrected"},
            }
        ),
        encoding="utf-8",
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    summary = read_campaign(root)

    assert summary.next_plan.command == ("qsub", str(job.resolve()))
    assert summary.next_plan.artifacts[0].exists


def test_complete_campaign_has_no_submission_plan(tmp_path):
    root = tmp_path / "campaign"
    (root / "jobs").mkdir(parents=True)
    (root / "jobs" / "99_stale.pbs").write_text("stale", encoding="utf-8")
    (root / "campaign.json").write_text(
        json.dumps(
            {
                "kind": "mot_2d_s0_campaign",
                "stage": "complete",
                "stages": {},
                "provenance": {"git_commit": "abc"},
                "ensemble_source": {"zeeman_profile": "corrected"},
            }
        ),
        encoding="utf-8",
    )

    summary = read_campaign(root)

    assert summary.next_plan is None
    assert not any("job artifact" in warning for warning in summary.warnings)


def test_missing_stage_record_does_not_infer_stale_job(tmp_path):
    root = tmp_path / "campaign"
    (root / "jobs").mkdir(parents=True)
    (root / "jobs" / "99_stale.pbs").write_text("stale", encoding="utf-8")
    (root / "campaign.json").write_text(
        json.dumps(
            {
                "kind": "mot_2d_s0_campaign",
                "stage": "screen",
                "stages": {},
                "provenance": {"git_commit": "abc"},
                "ensemble_source": {"zeeman_profile": "corrected"},
            }
        ),
        encoding="utf-8",
    )

    summary = read_campaign(root)

    assert summary.next_plan is None
    assert any("no recorded job artifact" in item for item in summary.warnings)


def test_production_progress_counts_only_replicate_tasks(tmp_path):
    root = tmp_path / "campaign"
    replicates = root / "production" / "s0_1p300000" / "replicates"
    replicates.mkdir(parents=True)
    (root / "production" / "tasks.json").write_text("[]", encoding="utf-8")
    (root / "production" / "summary.json").write_text("{}", encoding="utf-8")
    (replicates / "zeeman_seed3015.json").write_text("{}", encoding="utf-8")
    (root / "campaign.json").write_text(
        json.dumps(
            {
                "kind": "mot_2d_s0_campaign",
                "stage": "production",
                "s0_values": [1.3],
                "stages": {"production": {"tasks": 1}},
                "provenance": {"git_commit": "abc"},
                "ensemble_source": {"zeeman_profile": "corrected"},
            }
        ),
        encoding="utf-8",
    )

    summary = read_campaign(root)
    progress = {item.stage: item for item in summary.progress}

    assert progress["production"].completed == 1
    assert progress["production"].status == "complete"


def test_refinement_plan_reports_chain_and_every_round(tmp_path):
    root = tmp_path / "campaign"
    jobs = root / "jobs"
    jobs.mkdir(parents=True)
    chain = jobs / "03_submit_refinement_chain.sh"
    rounds = [jobs / f"03_refine_round_{index:02d}.pbs" for index in (1, 2)]
    for path in (chain, *rounds):
        path.write_text("", encoding="utf-8")
    (root / "campaign.json").write_text(
        json.dumps(
            {
                "kind": "mot_2d_s0_campaign",
                "stage": "refine",
                "stages": {
                    "refine": {
                        "tasks": 1,
                        "submit_chain": str(chain),
                        "round_job_files": [str(path) for path in rounds],
                    }
                },
                "provenance": {"git_commit": "abc"},
                "ensemble_source": {"zeeman_profile": "corrected"},
            }
        ),
        encoding="utf-8",
    )

    summary = read_campaign(root)

    assert summary.next_plan.command == ("bash", str(chain.resolve()))
    assert [item.kind for item in summary.next_plan.artifacts] == [
        "submission-script",
        "pbs",
        "pbs",
    ]
    assert all(item.exists for item in summary.next_plan.artifacts)


def test_null_optional_mappings_degrade_to_warnings(tmp_path):
    path = tmp_path / "campaign.json"
    path.write_text(
        json.dumps(
            {
                "kind": "mot_2d_s0_campaign",
                "stage": "screen",
                "provenance": None,
                "ensemble_source": None,
                "stages": None,
                "fixed_design": None,
            }
        ),
        encoding="utf-8",
    )

    summary = read_campaign(path)

    assert summary.next_plan is None
    assert len(summary.warnings) == 4


@pytest.mark.parametrize("s0_values", ["1.3", [0], [-1], ["nan"], ["bad"]])
def test_invalid_s0_values_raise_clear_error(tmp_path, s0_values):
    path = tmp_path / "campaign.json"
    path.write_text(
        json.dumps(
            {
                "kind": "mot_2d_s0_campaign",
                "stage": "screen",
                "s0_values": s0_values,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="s0_values"):
        read_campaign(path)


def test_importing_workflow_api_does_not_import_submit_modules():
    code = (
        "import sys; import workflow_api; "
        "assert not any(name.startswith('studies.submit_') for name in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
