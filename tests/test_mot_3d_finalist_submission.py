from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest

from workflow_api.mot_3d_finalist_submission import (
    CODE_FILES,
    FILES,
    Mot3DFinalistSubmissionCoordinator,
    Mot3DFinalistSubmissionError,
)
from workflow_api.mot_3d_finalist_submission_remote import DESCRIPTOR
from workflow_api import mot_3d_finalist_submission_remote as receiver
from workflow_api.mot_3d_preliminary_submission import RemotePreliminarySubmissionState
from workflow_api.mot_3d_stage_topology import FINALIST_SELECTION_TOPOLOGY


def _state(lifecycle, jobs, nonce=None, submitted=None, arrays=0, merges=0):
    return RemotePreliminarySubmissionState(
        lifecycle, "main", jobs, nonce, submitted, arrays, merges
    )


def test_descriptor_binds_exact_finalist_stage_contract():
    assert DESCRIPTOR.stage == "finalist_selection"
    assert DESCRIPTOR.transition_receipt == "closure_to_finalist_selection.json"
    assert DESCRIPTOR.input_role == (
        "discovery",
        "refinement",
        "preliminary_check",
    )
    assert DESCRIPTOR.files == FILES
    assert DESCRIPTOR.code_names == CODE_FILES
    assert DESCRIPTOR.jobs == FINALIST_SELECTION_TOPOLOGY.jobs
    assert DESCRIPTOR.science == {
        "classification": "final_candidate_selection_not_unbiased_validation",
        "candidates_per_family": 3,
        "input_ensembles": 20,
        "recoil_seeds": (43001, 43002, 43003),
        "dt_s": None,
        "t_max_s": 0.05,
        "solver": None,
        "npools": 200,
        "bootstrap_replicates": 10000,
        "bootstrap_seed": 82001,
    }


@pytest.mark.parametrize("operation", ["inspect", "status", "submit"])
def test_partial_and_ambiguous_prefixes_remain_manual(operation):
    prefix = {
        "angled_donut": {"array": "100[].zeus-master", "merge": None},
        "single_pass": {"array": None, "merge": None},
    }
    Mot3DFinalistSubmissionCoordinator._validate(
        _state("outcome_unknown", prefix, "a" * 32), operation
    )
    # Partial is a truthful durable state, not permission to retry: the
    # coordinator accepts it for reporting and maps it to manual inspection.
    Mot3DFinalistSubmissionCoordinator._validate(
        _state("partial", prefix, "a" * 32), operation
    )


def test_duplicate_job_ids_fail_closed():
    jobs = {
        "angled_donut": {
            "array": "100[].zeus-master",
            "merge": "100.zeus-master",
        },
        "single_pass": {
            "array": "102[].zeus-master",
            "merge": "103.zeus-master",
        },
    }
    with pytest.raises(Mot3DFinalistSubmissionError):
        Mot3DFinalistSubmissionCoordinator._validate(
            _state("submitted", jobs, "a" * 32, 1), "status"
        )


def test_code_ledger_contains_direct_scientific_dependencies():
    assert {
        "studies/mot_3d/finalists/run.py",
        "studies/mot_3d/finalists/merge.py",
        "studies/mot_3d/finalists/select.py",
        "studies/mot_3d/discovery/optimize.py",
        "workflow_api/mot_3d_closure_transition.py",
        "workflow_api/mot_3d_finalist_submission_remote.py",
    } <= CODE_FILES


def test_exact_seven_frozen_submission_files():
    assert len(FILES) == 7
    assert "campaign.json" in FILES
    for family in ("angled_donut", "single_pass"):
        assert f"selection/finalists/{family}.json" in FILES
        assert f"jobs/finalist_selection/{family}_array.pbs" in FILES
        assert f"jobs/finalist_selection/{family}_merge.pbs" in FILES


def _realistic_repository(tmp_path):
    root = tmp_path / "remote"
    campaign = root / "data/optimization/mot_3d/campaign"
    (campaign / ".mot_ui/transitions").mkdir(parents=True)
    manifest = {
        "name": "campaign",
        "stage": "finalist_selection",
        "provenance": {"git_commit": "a" * 40, "physical_model_sha256": "1" * 64},
        "upstream_2d_campaign": {
            "campaign_sha256": "2" * 64,
            "final_report_sha256": "3" * 64,
        },
        "design": {
            "screening_dt_s": 1e-5,
            "solver": "RK4StHybridCustom",
            "timestep_evidence": {"policy_sha256": "4" * 64},
        },
        "stages": {
            "finalist_selection": {
                "classification": "final_candidate_selection_not_unbiased_validation",
                "input_roles": ["discovery", "refinement", "preliminary_check"],
            }
        },
    }
    frozen = {"campaign.json": json.dumps(manifest, sort_keys=True).encode()}
    for family in receiver.FAMILIES:
        frozen[f"selection/finalists/{family}.json"] = b"{}\n"
        frozen[receiver.JOBS[family]["array"]] = f"array-{family}\n".encode()
        frozen[receiver.JOBS[family]["merge"]] = f"merge-{family}\n".encode()
    for name, raw in frozen.items():
        target = campaign / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    transition = {
        "status": "finalist_selection_prepared",
        "transition_key": "5" * 64,
        "bundle": {"bundle_sha256": "6" * 64},
    }
    transition_raw = receiver.canonical(transition) + b"\n"
    (campaign / ".mot_ui/transitions/closure_to_finalist_selection.json").write_bytes(
        transition_raw
    )
    code_files = {}
    for name in CODE_FILES:
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
        "science": {
            **dict(DESCRIPTOR.science),
            "recoil_seeds": list(DESCRIPTOR.science["recoil_seeds"]),
            "dt_s": 1e-5,
            "solver": "RK4StHybridCustom",
        },
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


def _invoke(monkeypatch, root, operation, payload, fake_run):
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
    monkeypatch.setattr(receiver, "run", fake_run)
    receiver.main(trusted_root_override=root)


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_real_receiver_exact_chain_restart_and_stage_specific_mutations(
    tmp_path, monkeypatch, capsys
):
    root, campaign, payload, frozen = _realistic_repository(tmp_path)
    submitted = {**payload, "nonce": "8" * 32}
    calls = []
    ids = iter(
        [
            b"810[].zeus-master\n",
            b"811.zeus-master\n",
            b"812[].zeus-master\n",
            b"813.zeus-master\n",
        ]
    )

    def fake_run(argv, input_data=None, limit=None):
        if argv[0:2] == ["/usr/bin/git", "-C"] and argv[3] == "rev-parse":
            return 0, b"a" * 40 + b"\n", b""
        if argv[0:2] == ["/usr/bin/git", "-C"] and argv[3] == "branch":
            return 0, b"main\n", b""
        if argv[0:2] == ["/usr/bin/git", "-C"] and argv[3] == "status":
            return 0, b"", b""
        if argv[0] == "/usr/local/bin/qsub":
            calls.append((argv, input_data))
            return 0, next(ids), b""
        raise AssertionError(argv)

    _invoke(monkeypatch, root, "submit", submitted, fake_run)
    assert json.loads(capsys.readouterr().out)["lifecycle"] == "submitted"
    assert [row[0][1:] for row in calls] == [
        ["-J", "0-2:1"],
        ["-W", "depend=afterok:810[].zeus-master"],
        ["-J", "0-2:1"],
        ["-W", "depend=afterok:812[].zeus-master"],
    ]
    assert [row[1] for row in calls] == [
        frozen[receiver.JOBS["angled_donut"]["array"]],
        frozen[receiver.JOBS["angled_donut"]["merge"]],
        frozen[receiver.JOBS["single_pass"]["array"]],
        frozen[receiver.JOBS["single_pass"]["merge"]],
    ]
    inspect = {key: value for key, value in submitted.items() if key != "nonce"}
    _invoke(monkeypatch, root, "inspect", inspect, fake_run)
    assert json.loads(capsys.readouterr().out)["lifecycle"] == "submitted"
    assert len(calls) == 4

    # A fresh repository proves the newly introduced tuple-role admission is
    # exact and fails before qsub when order drifts.
    root2, campaign2, payload2, _ = _realistic_repository(tmp_path / "mutation")
    manifest_path = campaign2 / "campaign.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["stages"]["finalist_selection"]["input_roles"].reverse()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    with pytest.raises(SystemExit):
        _invoke(monkeypatch, root2, "inspect", payload2, fake_run)


@pytest.mark.parametrize(
    "mutation",
    ["science", "code", "selection", "pbs", "transition", "role_order"],
)
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_real_receiver_rejects_every_new_finalist_identity_surface_before_qsub(
    tmp_path, monkeypatch, mutation
):
    root, campaign, payload, _ = _realistic_repository(tmp_path)
    if mutation == "science":
        payload["identity"]["science"]["bootstrap_seed"] += 1
    elif mutation == "code":
        payload["identity"]["code_files"]["studies/mot_3d/finalists/run.py"] = "0" * 64
    elif mutation == "selection":
        (campaign / "selection/finalists/angled_donut.json").write_bytes(
            b'{"changed":true}\n'
        )
    elif mutation == "pbs":
        (campaign / receiver.JOBS["single_pass"]["merge"]).write_bytes(b"changed\n")
    elif mutation == "transition":
        (
            campaign / ".mot_ui/transitions/closure_to_finalist_selection.json"
        ).write_bytes(b"{}\n")
    else:
        manifest_path = campaign / "campaign.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["stages"]["finalist_selection"]["input_roles"].reverse()
        manifest_path.write_text(json.dumps(manifest, sort_keys=True))

    qsubs = []

    def fake_run(argv, input_data=None, limit=None):
        if argv[0:2] == ["/usr/bin/git", "-C"] and argv[3] == "rev-parse":
            return 0, b"a" * 40 + b"\n", b""
        if argv[0:2] == ["/usr/bin/git", "-C"] and argv[3] == "branch":
            return 0, b"main\n", b""
        if argv[0:2] == ["/usr/bin/git", "-C"] and argv[3] == "status":
            return 0, b"", b""
        if argv[0] == "/usr/local/bin/qsub":
            qsubs.append(argv)
        raise AssertionError(argv)

    with pytest.raises(SystemExit):
        _invoke(monkeypatch, root, "inspect", payload, fake_run)
    assert qsubs == []
