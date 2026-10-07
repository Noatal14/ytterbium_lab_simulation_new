import json
from argparse import Namespace

import numpy as np
import pytest

from studies import mot_3d_campaign
from studies.mot_3d_final_validation import RECOIL_SEEDS, merge
from studies.mot_3d_stage_integrity import sha256


def test_final_validation_merge_reports_sealed_unbiased_interval(tmp_path):
    root = tmp_path / "results"
    root.mkdir()
    campaign = tmp_path / "campaign.json"
    locked_path = tmp_path / "locked.json"
    inputs_path = tmp_path / "inputs.json"
    campaign.write_text(json.dumps({"design": {
        "production_dt_s": 0.625e-6, "solver": "RK4StHybridCustom"
    }}))
    locked_path.write_text(json.dumps({"families": {
        "angled_donut": {"candidate_id": "donut_final"}
    }}))
    inputs_path.write_text(json.dumps({
        "solver": "RK4StHybridCustom", "total_survivors": 20
    }))
    design_base = {
        "campaign_manifest_sha256": sha256(campaign),
        "locked_nominals_sha256": sha256(locked_path),
        "input_manifest_sha256": sha256(inputs_path),
        "family": "angled_donut",
        "dt_s": 0.625e-6,
        "t_max_s": 0.1,
        "solver": "RK4StHybridCustom",
        "classification": "sealed_unbiased_final_validation",
    }
    ensemble_ids = np.repeat([0, 1], 10)
    for index, seed in enumerate(RECOIL_SEEDS):
        archive = root / f"seed_{seed}.npz"
        usable = np.array(([True] * (10 + index)) + ([False] * (10 - index)))
        np.savez_compressed(
            archive, usable_at_end=usable, usable_ever=usable,
            ensemble_ids=ensemble_ids,
        )
        design = dict(design_base, recoil_seed=seed)
        (root / f"seed_{seed}.json").write_text(json.dumps({
            "kind": "mot_3d_sealed_final_validation_seed_result",
            "family": "angled_donut",
            "candidate_id": "donut_final",
            "recoil_seed": seed,
            "input_particle_count": 20,
            "outcomes_path": str(archive),
            "outcomes_sha256": sha256(archive),
            "design": design,
        }))
    output = tmp_path / "summary.json"
    args = Namespace(
        input_root=str(root), output=str(output),
        bootstrap_replicates=500, bootstrap_seed=123,
        family="angled_donut", locked_nominals=str(locked_path),
        input_manifest=str(inputs_path), campaign_manifest=str(campaign),
        dt=0.625e-6,
    )
    merge(args)
    summary = json.loads(output.read_text())
    assert summary["classification"] == "sealed_unbiased_estimate_pending_precision_gate"
    assert summary["estimand"] == "survivor-weighted conditional capture fraction"
    assert summary["ensemble_count"] == 2
    assert summary["recoil_seed_count"] == 3
    assert summary["conditional_efficiency"] == 0.55
    merge(args)  # Identical scheduler retry is a safe no-op.
    args.dt = 1.25e-6
    with pytest.raises(ValueError, match="timestep"):
        merge(args)


def test_precision_decision_rejects_falsified_small_half_width():
    with pytest.raises(ValueError, match="precision decision"):
        mot_3d_campaign._validate_precision_decision(
            [0.40, 0.44], 0.001, True
        )


def test_final_report_artifact_exists_only_after_precision_passes():
    passed = mot_3d_campaign._final_report_artifact(True)
    failed = mot_3d_campaign._final_report_artifact(False)
    assert passed == (
        "final_report.json", "mot_3d_campaign_final_report",
        "unbiased_claim_from_newly_generated_sealed_ensembles",
        "complete", "final_report",
    )
    assert failed == (
        "final_validation_status.json", "mot_3d_final_validation_extension_status",
        "unbiased_estimate_precision_target_not_met_not_final_claim",
        "final_validation_extension_required", "final_validation_status",
    )


def test_final_input_submission_preserves_whole_array_dependencies(tmp_path):
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "campaign.json").write_text(json.dumps({
        "stage": "final_validation_input_generation",
        "stages": {"final_validation_input_generation": {
            "zeeman_job": "zeeman.pbs", "mot_job": "mot.pbs", "freeze_job": "freeze.pbs",
        }},
    }))
    calls = []
    identifiers = iter(["101[].zeus", "102[].zeus", "103.zeus"])
    def fake_qsub(command):
        calls.append(command)
        return next(identifiers)
    record = mot_3d_campaign.submit_final_validation_inputs(root, qsub=fake_qsub)
    assert record["status"] == "submitted"
    assert calls[1][2] == "depend=afterok:101[].zeus"
    assert calls[2][2] == "depend=afterok:102[].zeus"
    assert record["freeze_job_id"] == "103.zeus"


def test_final_input_submission_records_partial_failure(tmp_path):
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "campaign.json").write_text(json.dumps({
        "stage": "final_validation_input_generation",
        "stages": {"final_validation_input_generation": {
            "zeeman_job": "zeeman.pbs", "mot_job": "mot.pbs", "freeze_job": "freeze.pbs",
        }},
    }))
    calls = 0
    def fake_qsub(command):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "101[].zeus"
        raise RuntimeError("submission failed")
    try:
        mot_3d_campaign.submit_final_validation_inputs(root, qsub=fake_qsub)
    except RuntimeError:
        pass
    record = json.loads(
        (root / "final_validation_input_generation_submission.json").read_text()
    )
    assert record["status"] == "partial_failure"
    assert record["zeeman_array_job_id"] == "101[].zeus"
