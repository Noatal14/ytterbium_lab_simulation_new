import hashlib
import json
import subprocess
import sys

import pytest

from workflow_api import list_workflows, read_campaign, read_3d_campaign
from workflow_api.__main__ import main


def test_workflow_catalog_exposes_stable_ui_capabilities():
    workflows = {item.workflow_id: item for item in list_workflows()}

    mot_2d = workflows["mot_2d_fixed_s0"]
    assert mot_2d.maturity == "active"
    assert "inspect" in mot_2d.capabilities
    mot_3d = workflows["mot_3d_optimization"]
    assert mot_3d.maturity == "active"
    assert mot_3d.entrypoint == "studies.mot_3d_campaign"
    assert mot_3d.capabilities == ("inspect",)
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


def test_2d_campaign_rejects_job_artifact_outside_repository(tmp_path):
    repository = tmp_path / "repository"
    (repository / ".git").mkdir(parents=True)
    root = repository / "data" / "optimization" / "mot_2d" / "campaign"
    root.mkdir(parents=True)
    outside = tmp_path / "outside.pbs"
    outside.write_text("", encoding="utf-8")
    (root / "campaign.json").write_text(json.dumps({
        "kind": "mot_2d_s0_campaign", "name": "unsafe", "stage": "screen",
        "s0_values": [1.3], "stages": {"screen": {"tasks": 1, "job_file": str(outside)}},
        "provenance": {"git_commit": "abc"}, "ensemble_source": {"zeeman_profile": "profile"},
    }))

    summary = read_campaign(root)

    assert summary.next_plan is None
    assert any("outside the trusted repository" in warning for warning in summary.warnings)


def test_2d_campaign_rejects_artifact_through_parent_symlink(tmp_path):
    repository = tmp_path / "repository"; (repository / ".git").mkdir(parents=True)
    root = repository / "data" / "optimization" / "mot_2d" / "campaign"; root.mkdir(parents=True)
    outside = tmp_path / "outside"; outside.mkdir(); (outside / "job.pbs").write_text("")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    (root / "campaign.json").write_text(json.dumps({
        "kind": "mot_2d_s0_campaign", "name": "unsafe", "stage": "screen", "s0_values": [1.3],
        "stages": {"screen": {"tasks": 1, "job_file": "linked/job.pbs"}},
        "provenance": {"git_commit": "abc"}, "ensemble_source": {"zeeman_profile": "profile"},
    }))

    summary = read_campaign(root)

    assert summary.next_plan is None
    assert any("outside the trusted repository" in warning for warning in summary.warnings)


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


def _write_3d_manifest(root, *, stage="discovery", stages=None):
    root.mkdir(parents=True, exist_ok=True)
    evidence = root / "dt_evidence.json"
    evidence.write_text('{"status": "approved"}', encoding="utf-8")
    evidence_sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    manifest = {
        "kind": "mot_3d_campaign_v2",
        "name": "3d-example",
        "stage": stage,
        "provenance": {"git_commit": "abc123"},
        "upstream_2d_campaign": {"campaign_path": "/archive/2d/campaign.json"},
        "design": {
            "families": ["angled_donut", "single_pass"],
            "timestep_status": "approved_by_paired_convergence_validation",
            "timestep_evidence": {"path": str(evidence), "sha256": evidence_sha},
            "optimization_bounds": {
                "angled_donut": {"total_discovery_trials": 3},
                "single_pass": {"total_discovery_trials": 3},
            },
        },
        "stages": stages or {},
    }
    (root / "campaign.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_read_3d_campaign_reports_discovery_progress_and_safe_plan(tmp_path):
    repository = tmp_path / "repository"
    (repository / ".git").mkdir(parents=True)
    root = repository / "data" / "optimization" / "mot_3d" / "campaign"
    chain = root / "jobs" / "02_submit_discovery_chain.sh"
    chain.parent.mkdir(parents=True)
    chain.write_text("#!/bin/bash\n", encoding="utf-8")
    manifest = _write_3d_manifest(root)
    manifest["jobs"] = {
        "discovery_submit_chain": str(chain.relative_to(repository))
    }
    (root / "campaign.json").write_text(json.dumps(manifest), encoding="utf-8")
    for family in ("angled_donut", "single_pass"):
        trial = root / "discovery" / family / "worker_0" / "trials" / "trial_0000.json"
        trial.parent.mkdir(parents=True)
        trial.write_text(
            json.dumps(
                {
                    "kind": "mot_3d_full_optuna_trial",
                    "family": family,
                    "worker_index": 0,
                    "trial_number": 0,
                }
            ),
            encoding="utf-8",
        )

    summary = read_3d_campaign(root)

    assert summary.name == "3d-example"
    assert summary.families == ("angled_donut", "single_pass")
    assert summary.upstream_2d_campaign == "/archive/2d/campaign.json"
    progress = {item.stage: item for item in summary.progress}
    assert progress["dt_validation"].status == "complete"
    assert progress["discovery"].completed == 2
    assert progress["discovery"].expected == 6
    assert progress["discovery"].status == "in-progress"
    assert summary.next_plan.command == (
        "python", "-m", "studies.mot_3d_campaign", "submit-discovery",
        "--campaign", str(root.resolve()),
    )
    assert not summary.next_plan.submission_enabled
    assert summary.next_plan.artifacts[0].path == chain.resolve()


def test_generic_dispatch_and_cli_inspect_3d(tmp_path, capsys):
    root = tmp_path / "campaign"
    _write_3d_manifest(root, stage="dt_validation_required")

    assert read_campaign(root).kind == "mot_3d_campaign_v2"
    main(["inspect-3d", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["kind"] == "mot_3d_campaign_v2"
    assert payload["data"]["stage"] == "dt_validation_required"
    assert payload["data"]["next_plan"] is None
    assert any("timestep validation" in item for item in payload["data"]["warnings"])


def test_read_3d_selection_stage_lists_all_job_artifacts(tmp_path):
    root = tmp_path / "campaign"
    jobs = root / "jobs" / "refinement"
    jobs.mkdir(parents=True)
    workers = {}
    merges = {}
    for family in ("angled_donut", "single_pass"):
        worker = jobs / f"{family}_array.pbs"
        merge = jobs / f"{family}_merge.pbs"
        worker.write_text("", encoding="utf-8")
        merge.write_text("", encoding="utf-8")
        workers[family] = str(worker)
        merges[family] = str(merge)
    _write_3d_manifest(
        root,
        stage="refinement",
        stages={
            "refinement": {
                "worker_jobs": workers,
                "merge_jobs": merges,
            }
        },
    )

    summary = read_3d_campaign(root)

    assert summary.next_plan.command[3] == "submit-stage"
    assert len(summary.next_plan.artifacts) == 4
    assert all(item.exists for item in summary.next_plan.artifacts)


def test_read_3d_complete_campaign_has_no_plan(tmp_path):
    root = tmp_path / "campaign"
    _write_3d_manifest(root, stage="complete")

    summary = read_3d_campaign(root)

    assert summary.next_plan is None
    assert summary.warnings == ()


@pytest.mark.parametrize("status", ["submitting", "partial_failure"])
def test_read_3d_never_resubmits_reserved_discovery(tmp_path, status):
    root = tmp_path / "campaign"
    manifest = _write_3d_manifest(root)
    manifest["jobs"] = {"discovery_submit_chain": str(root / "jobs" / "chain.sh")}
    (root / "campaign.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "discovery_submission.json").write_text(
        json.dumps({"kind": "mot_3d_discovery_submission", "status": status}),
        encoding="utf-8",
    )

    summary = read_3d_campaign(root)

    assert summary.next_plan is None
    expected = "still being recorded" if status == "submitting" else "failed partially"
    assert any(expected in warning for warning in summary.warnings)


def test_read_3d_submitted_incomplete_stage_requires_monitoring(tmp_path):
    root = tmp_path / "campaign"
    _write_3d_manifest(root, stage="refinement", stages={"refinement": {}})
    (root / "refinement_submission.json").write_text(
        json.dumps(
            {
                "kind": "mot_3d_selection_stage_submission",
                "status": "submitted",
                "stage": "refinement",
            }
        ),
        encoding="utf-8",
    )

    summary = read_3d_campaign(root)

    assert summary.next_plan is None
    assert any("monitor" in warning for warning in summary.warnings)


def test_read_3d_completed_selection_stage_proposes_advance(tmp_path):
    root = tmp_path / "campaign"
    _write_3d_manifest(root, stage="refinement", stages={"refinement": {}})
    (root / "refinement_submission.json").write_text(
        json.dumps(
            {
                "kind": "mot_3d_selection_stage_submission",
                "status": "submitted",
                "stage": "refinement",
            }
        ),
        encoding="utf-8",
    )
    for family in ("angled_donut", "single_pass"):
        summary_path = root / "refinement" / family / "merged" / "refinement_summary.json"
        summary_path.parent.mkdir(parents=True)
        summary_path.write_text(
            json.dumps(
                {
                    "kind": "merged_mot_3d_focused_refinement",
                    "family": family,
                }
            ),
            encoding="utf-8",
        )

    summary = read_3d_campaign(root)

    assert summary.next_plan.command[3] == "advance"
    assert not summary.next_plan.submission_enabled


def test_read_3d_final_input_generation_tracks_submission_and_advance(tmp_path):
    root = tmp_path / "campaign"
    input_manifest = root / "final_validation_inputs" / "input_manifest.json"
    stages = {
        "final_validation_input_generation": {
            "zeeman_seeds": [3035, 3036],
            "input_manifest": str(input_manifest),
        }
    }
    _write_3d_manifest(root, stage="final_validation_input_generation", stages=stages)
    (root / "final_validation_input_generation_submission.json").write_text(
        json.dumps(
            {
                "kind": "mot_3d_final_validation_input_submission",
                "status": "submitted",
            }
        ),
        encoding="utf-8",
    )
    input_manifest.parent.mkdir(parents=True)
    input_manifest.write_text(
        json.dumps(
            {
                "kind": "mot_3d_final_validation_inputs",
                "ensembles": [
                    {"zeeman_seed": 3035},
                    {"zeeman_seed": 3036},
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = read_3d_campaign(root)

    assert summary.next_plan.command[3] == "advance"
    progress = {item.stage: item for item in summary.progress}
    assert progress["final_validation_inputs"].status == "complete"


def test_read_3d_completed_final_validation_proposes_advance(tmp_path):
    root = tmp_path / "campaign"
    _write_3d_manifest(root, stage="final_validation", stages={"final_validation": {}})
    (root / "final_validation_submission.json").write_text(
        json.dumps(
            {
                "kind": "mot_3d_selection_stage_submission",
                "status": "submitted",
                "stage": "final_validation",
            }
        ),
        encoding="utf-8",
    )
    for family in ("angled_donut", "single_pass"):
        summary_path = root / "final_validation" / family / "final_validation_summary.json"
        summary_path.parent.mkdir(parents=True)
        summary_path.write_text(
            json.dumps(
                {
                    "kind": "mot_3d_sealed_final_validation_summary",
                    "family": family,
                }
            ),
            encoding="utf-8",
        )

    summary = read_3d_campaign(root)

    assert summary.next_plan.command[3] == "advance"


def test_read_3d_precision_extension_is_a_known_manual_decision(tmp_path):
    root = tmp_path / "campaign"
    _write_3d_manifest(root, stage="final_validation_extension_required")

    summary = read_3d_campaign(root)

    assert summary.next_plan is None
    assert any("precision target was not met" in item for item in summary.warnings)
    assert not any("unknown 3D campaign stage" in item for item in summary.warnings)


@pytest.mark.parametrize(
    "status,evidence",
    [
        ("provisional_pending_3d_validation", True),
        ("approved_by_paired_convergence_validation", False),
    ],
)
def test_read_3d_does_not_forge_timestep_completion(tmp_path, status, evidence):
    root = tmp_path / "campaign"
    manifest = _write_3d_manifest(root)
    manifest["design"]["timestep_status"] = status
    if not evidence:
        manifest["design"]["timestep_evidence"]["path"] = str(root / "missing.json")
    (root / "campaign.json").write_text(json.dumps(manifest), encoding="utf-8")

    summary = read_3d_campaign(root)
    progress = {item.stage: item for item in summary.progress}

    assert progress["dt_validation"].status == "not-started"


@pytest.mark.parametrize("outside", ["../../outside.json", "/tmp/outside.json"])
def test_read_3d_does_not_dereference_untrusted_manifest_paths(tmp_path, outside):
    root = tmp_path / "campaign"
    stages = {
        "final_validation_input_generation": {
            "zeeman_seeds": [3035],
            "input_manifest": outside,
        }
    }
    _write_3d_manifest(root, stage="final_validation_input_generation", stages=stages)

    summary = read_3d_campaign(root)
    progress = {item.stage: item for item in summary.progress}

    assert progress["final_validation_inputs"].completed == 0
    assert summary.next_plan is None
    assert any("outside the trusted repository" in item for item in summary.warnings)


def test_read_3d_withholds_plan_for_incomplete_family_job_registry(tmp_path):
    root = tmp_path / "campaign"
    job = root / "jobs" / "refinement" / "angled_donut.pbs"
    job.parent.mkdir(parents=True)
    job.write_text("", encoding="utf-8")
    _write_3d_manifest(
        root,
        stage="refinement",
        stages={
            "refinement": {
                "worker_jobs": {"angled_donut": str(job)},
                "merge_jobs": {"angled_donut": str(job)},
            }
        },
    )

    summary = read_3d_campaign(root)

    assert summary.next_plan is None
    assert any("registry is incomplete" in item for item in summary.warnings)


def test_read_3d_withholds_plan_when_discovery_chain_is_missing(tmp_path):
    root = tmp_path / "campaign"
    manifest = _write_3d_manifest(root)
    manifest["jobs"] = {"discovery_submit_chain": str(root / "missing.sh")}
    (root / "campaign.json").write_text(json.dumps(manifest), encoding="utf-8")

    summary = read_3d_campaign(root)

    assert summary.next_plan is None
    assert any("missing locally" in item for item in summary.warnings)


def test_read_3d_does_not_count_foreign_summary_as_complete(tmp_path):
    root = tmp_path / "campaign"
    _write_3d_manifest(root, stage="refinement", stages={"refinement": {}})
    (root / "refinement_submission.json").write_text(
        json.dumps(
            {
                "kind": "mot_3d_selection_stage_submission",
                "status": "submitted",
                "stage": "refinement",
            }
        ),
        encoding="utf-8",
    )
    for family in ("angled_donut", "single_pass"):
        path = root / "refinement" / family / "merged" / "refinement_summary.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"kind": "foreign", "family": family}), encoding="utf-8")

    summary = read_3d_campaign(root)
    progress = {item.stage: item for item in summary.progress}

    assert progress["refinement"].status == "not-started"
    assert summary.next_plan is None
    assert any("monitor" in item for item in summary.warnings)


def test_read_3d_does_not_count_empty_discovery_trials_as_complete(tmp_path):
    root = tmp_path / "campaign"
    _write_3d_manifest(root)
    (root / "discovery_submission.json").write_text(
        json.dumps(
            {"kind": "mot_3d_discovery_submission", "status": "submitted"}
        ),
        encoding="utf-8",
    )
    for family in ("angled_donut", "single_pass"):
        for trial_number in range(3):
            path = (
                root
                / "discovery"
                / family
                / "worker_0"
                / "trials"
                / f"trial_{trial_number:04d}.json"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")

    summary = read_3d_campaign(root)
    progress = {item.stage: item for item in summary.progress}

    assert progress["discovery"].status == "not-started"
    assert summary.next_plan is None
    assert any("monitor" in item for item in summary.warnings)


def test_read_3d_rejects_submission_record_for_wrong_stage(tmp_path):
    root = tmp_path / "campaign"
    _write_3d_manifest(root, stage="refinement", stages={"refinement": {}})
    (root / "refinement_submission.json").write_text(
        json.dumps(
            {
                "kind": "mot_3d_selection_stage_submission",
                "status": "submitted",
                "stage": "closure",
            }
        ),
        encoding="utf-8",
    )

    summary = read_3d_campaign(root)

    assert summary.next_plan is None
    assert any("identity does not match" in item for item in summary.warnings)
