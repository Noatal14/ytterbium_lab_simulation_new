import json
import io
import zipfile
from argparse import Namespace

import numpy as np
import pytest

from studies import mot_3d_campaign
from studies.mot_3d.final_validation import RECOIL_SEEDS, merge
from studies.mot_3d.integrity import sha256


def test_final_validation_merge_reports_sealed_unbiased_interval(tmp_path):
    root = tmp_path / "results"
    root.mkdir()
    campaign = tmp_path / "campaign.json"
    locked_path = tmp_path / "locked.json"
    inputs_path = tmp_path / "inputs.json"
    campaign.write_text(
        json.dumps(
            {"design": {"production_dt_s": 5e-6, "solver": "RK4StHybridCustom"}}
        )
    )
    locked_path.write_text(
        json.dumps({"families": {"angled_donut": {"candidate_id": "donut_final"}}})
    )
    inputs_path.write_text(
        json.dumps(
            {
                "solver": "RK4StHybridCustom",
                "total_survivors": 20,
                "ensembles": [{"n_survivors": 10}, {"n_survivors": 10}],
            }
        )
    )
    design_base = {
        "campaign_manifest_sha256": sha256(campaign),
        "locked_nominals_sha256": sha256(locked_path),
        "input_manifest_sha256": sha256(inputs_path),
        "family": "angled_donut",
        "dt_s": 5e-6,
        "t_max_s": 0.05,
        "solver": "RK4StHybridCustom",
        "classification": "sealed_unbiased_final_validation",
    }
    ensemble_ids = np.repeat([0, 1], 10)
    for index, seed in enumerate(RECOIL_SEEDS):
        archive = root / f"seed_{seed}.npz"
        usable = np.array(([True] * (10 + index)) + ([False] * (10 - index)))
        np.savez_compressed(
            archive,
            usable_at_end=usable,
            usable_ever=usable,
            ensemble_ids=ensemble_ids,
        )
        design = dict(design_base, recoil_seed=seed)
        (root / f"seed_{seed}.json").write_text(
            json.dumps(
                {
                    "kind": "mot_3d_sealed_final_validation_seed_result",
                    "family": "angled_donut",
                    "candidate_id": "donut_final",
                    "recoil_seed": seed,
                    "input_particle_count": 20,
                    "usable_at_end_count": int(usable.sum()),
                    "usable_ever_count": int(usable.sum()),
                    "outcomes_path": str(archive),
                    "outcomes_sha256": sha256(archive),
                    "design": design,
                }
            )
        )
    output = tmp_path / "summary.json"
    args = Namespace(
        input_root=str(root),
        output=str(output),
        bootstrap_replicates=500,
        bootstrap_seed=123,
        family="angled_donut",
        locked_nominals=str(locked_path),
        input_manifest=str(inputs_path),
        campaign_manifest=str(campaign),
        dt=5e-6,
    )
    merge(args)
    summary = json.loads(output.read_text())
    assert (
        summary["classification"] == "sealed_unbiased_estimate_pending_precision_gate"
    )
    assert summary["estimand"] == "survivor-weighted conditional capture fraction"
    assert summary["ensemble_count"] == 2
    assert summary["recoil_seed_count"] == 3
    assert summary["conditional_efficiency"] == 0.55
    merge(args)  # Identical scheduler retry is a safe no-op.
    args.dt = 1.25e-6
    with pytest.raises(ValueError, match="timestep"):
        merge(args)
    args.dt = 5e-6
    inputs_payload = json.loads(inputs_path.read_text())
    inputs_payload["ensembles"] = [{"n_survivors": 9}, {"n_survivors": 11}]
    inputs_path.write_text(json.dumps(inputs_payload))
    for seed in RECOIL_SEEDS:
        result_path = root / f"seed_{seed}.json"
        result = json.loads(result_path.read_text())
        result["design"]["input_manifest_sha256"] = sha256(inputs_path)
        result_path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="sealed input order"):
        merge(args)


def test_precision_decision_rejects_falsified_small_half_width():
    with pytest.raises(ValueError, match="precision decision"):
        mot_3d_campaign._validate_precision_decision([0.40, 0.44], 0.001, True)


@pytest.mark.parametrize("stored_decision", [0, 1, "yes", None])
def test_precision_decision_requires_a_real_boolean(stored_decision):
    with pytest.raises(ValueError, match="precision decision"):
        mot_3d_campaign._validate_precision_decision(
            [0.40, 0.41], 0.005, stored_decision
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("extra_member", "Invalid outcome archive"),
        ("integer_mask", "boolean dtype"),
        ("usable_subset", "ever-usable"),
        ("negative_group", "non-negative integers"),
    ],
)
def test_final_validation_archive_rejects_semantic_corruption(
    tmp_path, mutation, message
):
    from studies.mot_3d.integrity import validate_outcome_archive

    path = tmp_path / "outcomes.npz"
    usable_at_end = np.array([True, False], dtype=bool)
    usable_ever = np.array([True, True], dtype=bool)
    ensemble_ids = np.array([0, 1], dtype=np.int64)
    values = {
        "usable_at_end": usable_at_end,
        "usable_ever": usable_ever,
        "ensemble_ids": ensemble_ids,
    }
    if mutation == "extra_member":
        values["foreign"] = np.array([1])
    elif mutation == "integer_mask":
        values["usable_at_end"] = usable_at_end.astype(np.int8)
    elif mutation == "usable_subset":
        values["usable_ever"] = np.array([False, True], dtype=bool)
    elif mutation == "negative_group":
        values["ensemble_ids"] = np.array([-1, 1], dtype=np.int64)
    np.savez(path, **values)
    with pytest.raises(ValueError, match=message):
        validate_outcome_archive(path, 2)


def test_final_validation_archive_rejects_duplicate_zip_member(tmp_path):
    from studies.mot_3d.integrity import validate_outcome_archive

    path = tmp_path / "duplicate.npz"
    member = io.BytesIO()
    np.lib.format.write_array(member, np.array([True], dtype=bool))
    group = io.BytesIO()
    np.lib.format.write_array(group, np.array([0], dtype=np.int64))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("usable_at_end.npy", member.getvalue())
        archive.writestr("usable_at_end.npy", member.getvalue())
        archive.writestr("usable_ever.npy", member.getvalue())
        archive.writestr("ensemble_ids.npy", group.getvalue())
    with pytest.raises(ValueError, match="Invalid outcome archive"):
        validate_outcome_archive(path, 1)


def test_outcome_validation_uses_the_same_bytes_after_preflight(tmp_path, monkeypatch):
    from studies.mot_3d.integrity import validate_outcome_archive
    import workflow_api.mot_3d_preliminary_results as strict_npz

    path = tmp_path / "outcomes.npz"
    np.savez(
        path,
        usable_at_end=np.array([True], dtype=bool),
        usable_ever=np.array([True], dtype=bool),
        ensemble_ids=np.array([0], dtype=np.int64),
    )
    original_preflight = strict_npz.validate_npz_container_bytes

    def mutate_after_preflight(raw, **kwargs):
        original_preflight(raw, **kwargs)
        np.savez(
            path,
            usable_at_end=np.array([False], dtype=bool),
            usable_ever=np.array([False], dtype=bool),
            ensemble_ids=np.array([99], dtype=np.int64),
        )

    monkeypatch.setattr(
        strict_npz, "validate_npz_container_bytes", mutate_after_preflight
    )
    usable, _, groups = validate_outcome_archive(path, 1)
    assert usable.tolist() == [True]
    assert groups.tolist() == [0]


@pytest.mark.parametrize(
    "counts",
    [[True], [0], [-1], [1.0], ["1"], [], None],
)
def test_expected_ensemble_ids_rejects_coerced_or_empty_counts(counts):
    from studies.mot_3d.integrity import expected_ensemble_ids

    with pytest.raises(ValueError, match="positive integers"):
        expected_ensemble_ids(counts)


def test_finalist_expected_groups_bind_manifest_hash_registry_and_order(tmp_path):
    import hashlib
    from studies.mot_3d.finalists.merge import _expected_frozen_ensemble_ids

    records = [
        {"n_survivors": index + 1, "zeeman_seed": 3015 + index} for index in range(20)
    ]
    manifest = {
        "input_roles": {
            "discovery": records[:12],
            "refinement": records[12:16],
            "preliminary_check": records[16:],
        }
    }
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(manifest))
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":"))
    design = {
        "campaign_manifest_path": str(path),
        "campaign_manifest_sha256": sha256(path),
        "input_role_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }
    observed = _expected_frozen_ensemble_ids(design)
    assert observed.tolist() == [
        ensemble_id
        for ensemble_id, row in enumerate(records)
        for _ in range(row["n_survivors"])
    ]
    manifest["input_roles"]["discovery"][0]["n_survivors"] = 999
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="campaign manifest"):
        _expected_frozen_ensemble_ids(design)


@pytest.mark.parametrize("particle_count", [True, 0, -1, 2.0, "2"])
def test_final_validation_archive_rejects_coerced_particle_count(
    tmp_path, particle_count
):
    from studies.mot_3d.integrity import validate_outcome_archive

    path = tmp_path / "outcomes.npz"
    np.savez(
        path,
        usable_at_end=np.array([True, False]),
        usable_ever=np.array([True, False]),
        ensemble_ids=np.array([0, 1]),
    )
    with pytest.raises(ValueError, match="positive integer"):
        validate_outcome_archive(path, particle_count)


def test_final_report_artifact_exists_only_after_precision_passes():
    passed = mot_3d_campaign._final_report_artifact(True)
    failed = mot_3d_campaign._final_report_artifact(False)
    assert passed == (
        "final_report.json",
        "mot_3d_campaign_final_report",
        "unbiased_claim_from_newly_generated_sealed_ensembles",
        "complete",
        "final_report",
    )
    assert failed == (
        "final_validation_status.json",
        "mot_3d_final_validation_extension_status",
        "unbiased_estimate_precision_target_not_met_not_final_claim",
        "final_validation_extension_required",
        "final_validation_status",
    )


def test_completed_final_report_binds_all_final_validation_provenance(
    tmp_path, monkeypatch
):
    root = tmp_path / "campaign"
    root.mkdir()
    locked = root / "locked.json"
    inputs = root / "inputs.json"
    locked.write_text(
        json.dumps(
            {
                "families": {
                    "angled_donut": {"candidate_id": "donut_final"},
                    "single_pass": {"candidate_id": "single_final"},
                }
            }
        )
    )
    inputs.write_text(json.dumps({"total_survivors": 20, "ensembles": [{}, {}]}))
    manifest = {
        "name": "campaign-123",
        "stage": "final_validation",
        "provenance": {"git_commit": "a" * 40, "physical_model_sha256": "b" * 64},
        "design": {"production_dt_s": 5e-6, "solver": "RK4StHybridCustom"},
        "stages": {
            "final_validation": {
                "locked_nominals": str(locked),
                "input_manifest": str(inputs),
                "worker_jobs": {},
                "merge_jobs": {},
            }
        },
    }
    campaign_path = root / "campaign.json"
    campaign_path.write_text(json.dumps(manifest))
    for family in mot_3d_campaign.FAMILIES:
        worker = root / f"{family}_worker.pbs"
        merger = root / f"{family}_merge.pbs"
        worker.write_text("worker")
        merger.write_text("merge")
        manifest["stages"]["final_validation"]["worker_jobs"][family] = str(worker)
        manifest["stages"]["final_validation"]["merge_jobs"][family] = str(merger)
    campaign_path.write_text(json.dumps(manifest))
    submission = root / "final_validation_submission.json"
    submission.write_text(
        json.dumps(
            {
                "kind": "mot_3d_selection_stage_submission",
                "stage": "final_validation",
                "status": "submitted",
                "dependency": "afterok",
                "families": {
                    "angled_donut": {
                        "array_job_id": "101[].zeus",
                        "merge_job_id": "102.zeus",
                    },
                    "single_pass": {
                        "array_job_id": "103[].zeus",
                        "merge_job_id": "104.zeus",
                    },
                },
                "campaign_manifest_sha256": sha256(campaign_path),
                "worker_job_sha256": {
                    family: sha256(
                        manifest["stages"]["final_validation"]["worker_jobs"][family]
                    )
                    for family in mot_3d_campaign.FAMILIES
                },
                "merge_job_sha256": {
                    family: sha256(
                        manifest["stages"]["final_validation"]["merge_jobs"][family]
                    )
                    for family in mot_3d_campaign.FAMILIES
                },
            }
        )
    )
    monkeypatch.setattr(
        mot_3d_campaign,
        "validate_final_validation_inputs",
        lambda *_: {"total_survivors": 20, "ensembles": [{}, {}]},
    )
    summaries = {}
    for family, candidate in (
        ("angled_donut", "donut_final"),
        ("single_pass", "single_final"),
    ):
        destination = root / "final_validation" / family
        destination.mkdir(parents=True)
        summary = {
            "kind": "mot_3d_sealed_final_validation_summary",
            "classification": "sealed_unbiased_estimate_pending_precision_gate",
            "family": family,
            "candidate_id": candidate,
            "estimand": "survivor-weighted conditional capture fraction",
            "input_particle_count": 20,
            "ensemble_count": 2,
            "recoil_seed_count": 3,
            "conditional_efficiency": 0.5,
            "bootstrap_95_ci": [0.495, 0.505],
            "ci_half_width": 0.005,
            "target_half_width": 0.0075,
            "precision_target_met": True,
            "expected_usable_per_10m_2d_survivors": 5_000_000.0,
            "expected_usable_per_10m_95_ci": [4_950_000.0, 5_050_000.0],
            "new_ensemble_rate_sd": 0.01,
            "new_equivalent_ensemble_predictive_95_interval": [0.4, 0.6],
            "predictive_method": "empirical random-effects bootstrap of ensemble and recoil effects plus finite-particle binomial variation",
            "bootstrap_method": "crossed ensemble/recoil bootstrap with within-ensemble particle resampling",
            "bootstrap_replicates": 20_000,
            "bootstrap_seed": 92_001,
            "design": {
                "campaign_manifest_sha256": sha256(campaign_path),
                "locked_nominals_sha256": sha256(locked),
                "input_manifest_sha256": sha256(inputs),
                "family": family,
                "dt_s": 5e-6,
                "t_max_s": 0.05,
                "solver": "RK4StHybridCustom",
                "classification": "sealed_unbiased_final_validation",
            },
        }
        (destination / "final_validation_summary.json").write_text(json.dumps(summary))
        summaries[family] = summary
    monkeypatch.setattr(
        mot_3d_campaign,
        "_recompute_final_validation_summary",
        lambda _root, family, _stage: summaries[family],
    )
    mot_3d_campaign.complete_final_validation(root, manifest)
    report = json.loads((root / "final_report.json").read_text())
    assert report["provenance"] == {
        "campaign_name": "campaign-123",
        "campaign_manifest_sha256": summary["design"]["campaign_manifest_sha256"],
        "git_commit": "a" * 40,
        "physical_model_sha256": "b" * 64,
        "locked_nominals_sha256": sha256(locked),
        "input_manifest_sha256": sha256(inputs),
        "final_validation_submission_sha256": sha256(submission),
        "production_dt_s": 5e-6,
        "solver": "RK4StHybridCustom",
    }


def test_completed_final_validation_rejects_extra_summary_field(tmp_path):
    path = tmp_path / "summary.json"
    payload = {key: None for key in mot_3d_campaign.FINAL_VALIDATION_SUMMARY_KEYS}
    payload["unexpected"] = True
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="summary schema"):
        mot_3d_campaign._validate_final_validation_summary_schema(payload, path)


@pytest.mark.parametrize(
    "mutation",
    ["extra", "wrong_campaign", "bool_job", "wrong_job_hash", "wrong_stage"],
)
def test_final_validation_submission_receipt_fails_closed(tmp_path, mutation):
    root = tmp_path / "campaign"
    root.mkdir()
    campaign = root / "campaign.json"
    campaign.write_text("{}")
    stage = {"worker_jobs": {}, "merge_jobs": {}}
    families = {}
    worker_hashes = {}
    merge_hashes = {}
    for index, family in enumerate(mot_3d_campaign.FAMILIES):
        worker = root / f"{family}.pbs"
        merger = root / f"{family}_merge.pbs"
        worker.write_text("worker")
        merger.write_text("merge")
        stage["worker_jobs"][family] = str(worker)
        stage["merge_jobs"][family] = str(merger)
        families[family] = {
            "array_job_id": f"{101 + index * 2}[].zeus",
            "merge_job_id": f"{102 + index * 2}.zeus",
        }
        worker_hashes[family] = sha256(worker)
        merge_hashes[family] = sha256(merger)
    payload = {
        "kind": "mot_3d_selection_stage_submission",
        "stage": "final_validation",
        "status": "submitted",
        "dependency": "afterok",
        "families": families,
        "campaign_manifest_sha256": sha256(campaign),
        "worker_job_sha256": worker_hashes,
        "merge_job_sha256": merge_hashes,
    }
    if mutation == "extra":
        payload["extra"] = True
    elif mutation == "wrong_campaign":
        payload["campaign_manifest_sha256"] = "0" * 64
    elif mutation == "bool_job":
        payload["families"]["angled_donut"]["array_job_id"] = True
    elif mutation == "wrong_job_hash":
        payload["worker_job_sha256"]["angled_donut"] = "0" * 64
    else:
        payload["stage"] = "closure"
    receipt = root / "final_validation_submission.json"
    receipt.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="Final validation"):
        mot_3d_campaign._validate_final_validation_submission(root, {}, stage, receipt)


def test_final_report_schema_rejects_extra_or_coerced_boolean():
    payload = {key: None for key in mot_3d_campaign.FINAL_REPORT_KEYS}
    payload.update(
        {
            "precision_target_met_for_both_families": 1,
            "selection_data_excluded_from_claim": True,
            "provenance": {
                key: None for key in mot_3d_campaign.FINAL_REPORT_PROVENANCE_KEYS
            },
        }
    )
    with pytest.raises(ValueError, match="report schema"):
        mot_3d_campaign._validate_final_report_schema(payload)
    payload["precision_target_met_for_both_families"] = True
    payload["extra"] = None
    with pytest.raises(ValueError, match="report schema"):
        mot_3d_campaign._validate_final_report_schema(payload)


def test_final_input_submission_preserves_whole_array_dependencies(tmp_path):
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "campaign.json").write_text(
        json.dumps(
            {
                "kind": "mot_3d_campaign_v2",
                "stage": "final_validation_input_generation",
                "stages": {
                    "final_validation_input_generation": {
                        "zeeman_job": "zeeman.pbs",
                        "mot_job": "mot.pbs",
                        "freeze_job": "freeze.pbs",
                    }
                },
            }
        )
    )
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
    (root / "campaign.json").write_text(
        json.dumps(
            {
                "kind": "mot_3d_campaign_v2",
                "stage": "final_validation_input_generation",
                "stages": {
                    "final_validation_input_generation": {
                        "zeeman_job": "zeeman.pbs",
                        "mot_job": "mot.pbs",
                        "freeze_job": "freeze.pbs",
                    }
                },
            }
        )
    )
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
