import base64
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace

import pytest
from studies.mot_3d_campaign import _validate_final_validation_submission

from workflow_api.mot_3d_final_validation_submission import (
    CODE_FILES,
    FILES,
    Mot3DFinalValidationSubmissionCoordinator,
    Mot3DFinalValidationSubmissionError,
)
from workflow_api.mot_3d_preliminary_submission import RemotePreliminarySubmissionState
from workflow_api.zeus_snapshot import ZeusProfile
from workflow_api.mot_3d_final_validation_submission_remote import DESCRIPTOR, SCIENCE
from workflow_api import mot_3d_final_validation_submission_remote as receiver
from workflow_api.mot_3d_selection_submission_remote import ReceiverDescriptor
from workflow_api.mot_3d_stage_topology import (
    FINAL_VALIDATION_SCIENTIFIC_DESIGN,
    FINAL_VALIDATION_TOPOLOGY,
    FAMILIES,
)


def test_final_validation_submission_descriptor_is_exact():
    assert FINAL_VALIDATION_TOPOLOGY.jobs == {
        family: {
            "array": f"jobs/final_validation/{family}_array.pbs",
            "merge": f"jobs/final_validation/{family}_merge.pbs",
        }
        for family in FAMILIES
    }
    assert FINAL_VALIDATION_TOPOLOGY.array_tasks == 3
    assert (
        FINAL_VALIDATION_TOPOLOGY.array_ncpus,
        FINAL_VALIDATION_TOPOLOGY.array_memory_gb,
        FINAL_VALIDATION_TOPOLOGY.array_walltime,
    ) == (200, 64, "24:00:00")
    assert (
        FINAL_VALIDATION_TOPOLOGY.merge_ncpus,
        FINAL_VALIDATION_TOPOLOGY.merge_memory_gb,
        FINAL_VALIDATION_TOPOLOGY.merge_walltime,
    ) == (1, 8, "02:00:00")
    assert FILES == {
        "campaign.json",
        "selection/locked_nominals.json",
        "final_validation_inputs/input_manifest.json",
        *(
            path
            for row in FINAL_VALIDATION_TOPOLOGY.jobs.values()
            for path in row.values()
        ),
    }
    assert (
        DESCRIPTOR.transition_receipt
        == "final_validation_inputs_to_final_validation.json"
    )
    assert DESCRIPTOR.transition_status == "final_validation_prepared"
    assert DESCRIPTOR.files == FILES
    assert DESCRIPTOR.dt_design_key == "production_dt_s"


def test_final_validation_submission_science_is_frozen():
    policy = FINAL_VALIDATION_SCIENTIFIC_DESIGN
    assert SCIENCE == {
        "classification": "sealed_unbiased_final_validation",
        "candidates_per_family": 1,
        "input_ensembles": 20,
        "recoil_seeds": [44001, 44002, 44003],
        "dt_s": None,
        "t_max_s": 0.05,
        "solver": None,
        "npools": 200,
        "bootstrap_replicates": 20_000,
        "bootstrap_seed": 92_001,
    }
    assert policy.dt_s == 5e-6


@pytest.mark.parametrize(
    "change",
    [
        {"transition_receipt": "final_validation.json"},
        {"dt_design_key": "screening_dt_s"},
        {"files": frozenset({"campaign.json"})},
        {"science": {**SCIENCE, "recoil_seeds": [44001, 44002]}},
        {"non_job_files": frozenset({"campaign.json"})},
    ],
)
def test_final_validation_descriptor_drift_fails_closed(change):
    with pytest.raises(ValueError):
        replace(DESCRIPTOR, **change)


def _repository(tmp_path):
    root = tmp_path / "remote"
    campaign = root / "data/optimization/mot_3d/campaign"
    (campaign / ".mot_ui/transitions").mkdir(parents=True)
    manifest = {
        "name": "campaign",
        "stage": "final_validation",
        "provenance": {"git_commit": "a" * 40, "physical_model_sha256": "1" * 64},
        "upstream_2d_campaign": {
            "campaign_sha256": "2" * 64,
            "final_report_sha256": "3" * 64,
        },
        "design": {
            "production_dt_s": 5e-6,
            "solver": "RK4StHybridCustom",
            "timestep_evidence": {"policy_sha256": "4" * 64},
        },
        "stages": {
            "final_validation": {"classification": "sealed_unbiased_final_validation"}
        },
    }
    frozen = {"campaign.json": json.dumps(manifest, sort_keys=True).encode()}
    frozen["selection/locked_nominals.json"] = b"{}\n"
    frozen["final_validation_inputs/input_manifest.json"] = b"{}\n"
    for family in FAMILIES:
        frozen[receiver.JOBS[family]["array"]] = f"array-{family}\n".encode()
        frozen[receiver.JOBS[family]["merge"]] = f"merge-{family}\n".encode()
    for name, raw in frozen.items():
        target = campaign / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    transition = {
        "status": "final_validation_prepared",
        "transition_key": "5" * 64,
        "bundle": {"bundle_sha256": "6" * 64},
    }
    (
        campaign
        / ".mot_ui/transitions/final_validation_inputs_to_final_validation.json"
    ).write_bytes(receiver.canonical(transition) + b"\n")
    code_files = {}
    for name in DESCRIPTOR.code_names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(name.encode())
        code_files[name] = hashlib.sha256(name.encode()).hexdigest()
    identity = {
        "campaign_sha256": hashlib.sha256(frozen["campaign.json"]).hexdigest(),
        "local_transition_receipt_sha256": "7" * 64,
        "transition_key": "5" * 64,
        "remote_transition_receipt_sha256": hashlib.sha256(
            receiver.canonical(transition)
        ).hexdigest(),
        "bundle_sha256": "6" * 64,
        "files": {
            name: hashlib.sha256(raw).hexdigest() for name, raw in frozen.items()
        },
        "science": {**SCIENCE, "dt_s": 5e-6, "solver": "RK4StHybridCustom"},
        "physical_model_sha256": "1" * 64,
        "upstream_campaign_sha256": "2" * 64,
        "upstream_final_report_sha256": "3" * 64,
        "timestep_policy_sha256": "4" * 64,
        "code_files": code_files,
    }
    payload = {
        "campaign": "data/optimization/mot_3d/campaign",
        "commit": "a" * 40,
        "identity": identity,
    }
    payload["submission_key"] = receiver.digest(
        {"campaign": payload["campaign"], "commit": payload["commit"], **identity}
    )
    return root, campaign, payload, frozen


def _invoke(monkeypatch, root, operation, payload, run):
    encoded = base64.urlsafe_b64encode(receiver.canonical(payload)).decode()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "receiver",
            operation,
            "tal.noa",
            "/home/tal.noa/ytterbium_lab_simulation_new",
            encoded,
        ],
    )
    monkeypatch.setattr(receiver, "run", run)
    receiver.main(trusted_root_override=root)


@pytest.mark.parametrize("array_range", ["0-2:1", "0-2:1%1"])
def test_real_receiver_submits_exact_chain_and_restart_is_idempotent(
    tmp_path, monkeypatch, capsys, array_range
):
    from workflow_api import mot_3d_workload
    # Policy authentication is covered by acceptance workload tests; exercise
    # the actual receiver command boundary with both authorized task ranges.
    monkeypatch.setattr(mot_3d_workload, "array_range", lambda manifest, stage: array_range)
    root, _campaign, payload, frozen = _repository(tmp_path)
    submitted = {**payload, "nonce": "8" * 32}
    calls = []
    ids = iter(
        [
            b"910[].zeus-master\n",
            b"911.zeus-master\n",
            b"912[].zeus-master\n",
            b"913.zeus-master\n",
        ]
    )

    def run(argv, input_data=None, limit=None):
        if argv[:2] == ["/usr/bin/git", "-C"]:
            if argv[3] == "rev-parse":
                return 0, b"a" * 40 + b"\n", b""
            if argv[3] == "branch":
                return 0, b"main\n", b""
            if argv[3] == "status":
                return 0, b"", b""
        if argv[0] == "/usr/local/bin/qsub":
            calls.append((argv, input_data))
            return 0, next(ids), b""
        raise AssertionError(argv)

    _invoke(monkeypatch, root, "submit", submitted, run)
    assert json.loads(capsys.readouterr().out)["lifecycle"] == "submitted"
    assert [row[0][1:] for row in calls] == [
        ["-J", array_range],
        ["-W", "depend=afterok:910[].zeus-master"],
        ["-J", array_range],
        ["-W", "depend=afterok:912[].zeus-master"],
    ]
    assert [row[1] for row in calls] == [
        frozen[receiver.JOBS["angled_donut"]["array"]],
        frozen[receiver.JOBS["angled_donut"]["merge"]],
        frozen[receiver.JOBS["single_pass"]["array"]],
        frozen[receiver.JOBS["single_pass"]["merge"]],
    ]
    compatibility = json.loads(
        (
            root / "data/optimization/mot_3d/campaign/final_validation_submission.json"
        ).read_text()
    )
    assert set(compatibility) == {
        "kind",
        "stage",
        "status",
        "dependency",
        "families",
        "campaign_manifest_sha256",
        "worker_job_sha256",
        "merge_job_sha256",
    }
    assert (
        compatibility["campaign_manifest_sha256"]
        == hashlib.sha256(frozen["campaign.json"]).hexdigest()
    )
    assert compatibility["worker_job_sha256"] == {
        family: hashlib.sha256(frozen[receiver.JOBS[family]["array"]]).hexdigest()
        for family in FAMILIES
    }
    campaign = root / "data/optimization/mot_3d/campaign"
    stage = {
        "worker_jobs": {
            family: str(campaign / receiver.JOBS[family]["array"])
            for family in FAMILIES
        },
        "merge_jobs": {
            family: str(campaign / receiver.JOBS[family]["merge"])
            for family in FAMILIES
        },
    }
    assert (
        _validate_final_validation_submission(
            campaign, {}, stage, campaign / "final_validation_submission.json"
        )
        == compatibility
    )
    _invoke(monkeypatch, root, "inspect", payload, run)
    assert json.loads(capsys.readouterr().out)["lifecycle"] == "submitted"
    assert len(calls) == 4
    # Feed the actual receiver's compatibility writer into the completion reader.
    import os
    from workflow_api import mot_3d_preliminary_transition_remote as proof
    from workflow_api.mot_3d_final_validation_completion_remote import DESCRIPTOR as completion_descriptor
    record = campaign / "final_validation_submission.json"
    original = record.read_bytes()
    source_sha = hashlib.sha256(frozen["campaign.json"]).hexdigest()
    fd = os.open(campaign, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with proof.descriptor_scope(completion_descriptor):
            final, jobs = proof._exact_stage2(fd, payload["submission_key"], "a" * 40, source_sha)
            assert final["jobs"] == jobs
            for attack in ("missing", "extra", "manifest", "worker", "merge", "job", "legacy"):
                changed = json.loads(original)
                if attack == "missing": changed.pop("campaign_manifest_sha256")
                elif attack == "extra": changed["unreviewed"] = True
                elif attack == "manifest": changed["campaign_manifest_sha256"] = "0" * 64
                elif attack == "worker": changed["worker_job_sha256"]["angled_donut"] = "0" * 64
                elif attack == "merge": changed["merge_job_sha256"]["single_pass"] = "0" * 64
                elif attack == "job": changed["families"]["angled_donut"]["array_job_id"] = "999[].zeus-master"
                else: changed["submission_key"] = payload["submission_key"]
                record.write_text(json.dumps(changed))
                with pytest.raises(SystemExit):
                    proof._exact_stage2(fd, payload["submission_key"], "a" * 40, source_sha)
                record.write_bytes(original)
            with pytest.raises(SystemExit):
                proof._exact_stage2(fd, payload["submission_key"], "a" * 40, "0" * 64)
    finally:
        record.write_bytes(original)
        os.close(fd)
    assert len(calls) == 4


@pytest.mark.parametrize("surface", ["science", "code", "locked", "pbs", "transition"])
def test_real_receiver_rejects_identity_mutation_before_qsub(
    tmp_path, monkeypatch, surface
):
    root, campaign, payload, _ = _repository(tmp_path)
    if surface == "science":
        payload["identity"]["science"]["bootstrap_seed"] = 1
    elif surface == "code":
        (root / next(iter(DESCRIPTOR.code_names))).write_bytes(b"changed")
    elif surface == "locked":
        (campaign / "selection/locked_nominals.json").write_bytes(b"changed")
    elif surface == "pbs":
        (campaign / receiver.JOBS["angled_donut"]["array"]).write_bytes(b"changed")
    else:
        path = (
            campaign
            / ".mot_ui/transitions/final_validation_inputs_to_final_validation.json"
        )
        path.write_bytes(b"{}\n")
    qsubs = []

    def run(argv, input_data=None, limit=None):
        if argv[:2] == ["/usr/bin/git", "-C"]:
            if argv[3] == "rev-parse":
                return 0, b"a" * 40 + b"\n", b""
            if argv[3] == "branch":
                return 0, b"main\n", b""
            if argv[3] == "status":
                return 0, b"", b""
        if argv[0] == "/usr/local/bin/qsub":
            qsubs.append(argv)
        raise AssertionError(argv)

    with pytest.raises(SystemExit):
        _invoke(monkeypatch, root, "inspect", payload, run)
    assert qsubs == []


def test_real_coordinator_status_and_preview_accept_only_production_dt(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_3d/campaign"
    campaign.mkdir(parents=True)
    profile = ZeusProfile.parse(
        {
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
    )
    manifest = {
        "name": "campaign",
        "stage": "final_validation",
        "provenance": {"physical_model_sha256": "1" * 64},
        "upstream_2d_campaign": {
            "campaign_sha256": "2" * 64,
            "final_report_sha256": "3" * 64,
        },
        "design": {
            "production_dt_s": 5e-6,
            "solver": "RK4StHybridCustom",
            "timestep_evidence": {"policy_sha256": "4" * 64},
        },
    }
    for name in FILES:
        target = campaign / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            json.dumps(manifest).encode() if name == "campaign.json" else name.encode()
        )
    for name in CODE_FILES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(name.encode())
    expected_sync = frozenset({"campaign.json"})

    class Authority:
        def __init__(self, *args, **kwargs):
            pass

        def _recovery_plan(self, request):
            return (
                "campaign-id",
                profile,
                campaign,
                manifest,
                "a" * 40,
                None,
                None,
                None,
                None,
                expected_sync,
            )

    sync = {
        "transition_key": "5" * 64,
        "remote_receipt_sha256": "6" * 64,
        "bundle_sha256": "7" * 64,
    }
    monkeypatch.setattr(
        Mot3DFinalValidationSubmissionCoordinator, "authority_class", Authority
    )
    monkeypatch.setattr(
        "workflow_api.mot_3d_closure_submission.validate_prior_transition_sync",
        lambda *_args: (sync, b"sync"),
    )
    monkeypatch.setattr(
        "workflow_api.mot_3d_closure_submission.subprocess.run",
        lambda argv, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=("a" * 40 + "\n") if "rev-parse" in argv else "",
            stderr="",
        ),
    )
    coordinator = Mot3DFinalValidationSubmissionCoordinator(
        root,
        Path(sys.executable),
        Path(sys.executable),
        transport_factory=lambda _p: None,
    )
    eligible = RemotePreliminarySubmissionState(
        "eligible",
        "main",
        {family: {"array": None, "merge": None} for family in FAMILIES},
        None,
        None,
        0,
        0,
    )
    monkeypatch.setattr(coordinator, "_remote", lambda *_args: eligible)
    request = {
        "campaign_id": "campaign-id",
        "username": profile.username,
        "project_directory": profile.project_directory,
    }
    assert coordinator.status(request)["campaign"]["stage"] == "final_validation"
    preview = coordinator.preview(request, session_id="session")
    assert preview["science"]["dt_s"] == 5e-6
    assert preview["resources"]["merge"] == {
        "ncpus": 1,
        "memory_gb": 8,
        "walltime": "02:00:00",
    }
    manifest["design"]["production_dt_s"] = 1e-5
    with pytest.raises(Mot3DFinalValidationSubmissionError) as caught:
        coordinator.status(request)
    assert caught.value.code == "final_validation_preparation_invalid"
