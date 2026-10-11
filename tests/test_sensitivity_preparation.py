from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

import workflow_api.zeus_sensitivity_remote as remote
from workflow_api.zeus_sensitivity_remote import scheduler_snapshot
from workflow_api.zeus_sensitivity import (
    RemoteConfirmationState, ZeusSensitivityCoordinator, ZeusSensitivityError,
)
from workflow_api.zeus_snapshot import ZeusProfile


def _manifest(commit="a" * 40):
    return {
        "kind": "mot_2d_s0_campaign", "name": "campaign", "stage": "confirmation",
        "s0_values": [1.3], "provenance": {"git_commit": commit},
    }


def _scheduler():
    return {
        "state": "completed_success", "task_count": 5,
        "counts": {"queued": 0, "running": 0, "held": 0,
                   "succeeded": 5, "failed": 0},
        "job_id": "123[].zeus-master", "submission_nonce": "b" * 32,
    }


class _Transport:
    def __init__(self, rows):
        self.rows = rows; self.prepares = []

    def inspect(self, **payload):
        return RemoteConfirmationState(
            "ready_to_prepare_sensitivity", _scheduler(), tuple(self.rows), "main", None,
        )

    def prepare(self, **payload):
        self.prepares.append(payload)
        receipt = {
            "status": "sensitivity_prepared", "nonce": payload["nonce"],
            "transition_key": payload["transition_key"], "commit": "a" * 40,
            "confirmation_submission_key": payload["confirmation_submission_key"],
            "confirmation_submission_nonce": "b" * 32,
            "confirmation_job_id": "123[].zeus-master",
            "rows_digest": payload["rows_digest"], "rows": self.rows,
            "files": payload["sensitivity_files"], "scheduler": _scheduler(),
            "completed_unix_s": 1,
        }
        return RemoteConfirmationState(
            "sensitivity_prepared", _scheduler(), tuple(self.rows), "main", receipt,
        )


def _coordinator(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir()
    campaign = root / "data/optimization/mot_2d/campaign"; campaign.mkdir(parents=True)
    ssh = tmp_path / "ssh"; ssh.write_text("")
    git = tmp_path / "git"; git.write_text("")
    initial_manifest = _manifest(); initial_manifest["stage"] = "smoke"
    manifest = _manifest()
    confirmation_manifest = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    files = {"refined_candidates.json": "1" * 64,
             "confirmation/tasks.json": "2" * 64,
             "jobs/04_confirmation.pbs": "3" * 64,
             "campaign.json": hashlib.sha256(confirmation_manifest).hexdigest()}
    confirmation_receipt = {
        "status": "confirmation_prepared", "nonce": "d" * 32,
        "chain_key": "f" * 64, "commit": "a" * 40,
        "rows_digest": "0" * 64, "rows": [], "files": files,
        "rounds": [], "completed_unix_s": 1,
    }
    monkeypatch.setattr(
        "workflow_api.zeus_sensitivity.ZeusConfirmationCoordinator._inspect",
        lambda _self, _request: ((
            "campaign-id", ZeusProfile("tal.noa", "/home/tal.noa/repo"), campaign,
            initial_manifest, "a" * 40, {}, "f" * 64, "0" * 64, "1" * 64,
        ), type("State", (), {"lifecycle": "confirmation_prepared",
                              "receipt": confirmation_receipt})()),
    )
    monkeypatch.setattr(
        "workflow_api.zeus_sensitivity.ZeusConfirmationCoordinator._remote_manifest",
        lambda *_args: {**initial_manifest, "stage": "refine"},
    )
    monkeypatch.setattr(
        "workflow_api.zeus_sensitivity.render_confirmation_transition",
        lambda *_args: {
            "refined_candidates.json": b"{}\n", "confirmation/tasks.json": b"[]\n",
            "jobs/04_confirmation.pbs": b"pbs\n", "campaign.json": confirmation_manifest,
        },
    )
    rendered = {"winners.json": b"{}\n", "sensitivity/tasks.json": b"[{}]\n",
                "jobs/05_sensitivity.pbs": b"pbs\n", "campaign.json": b"{}\n"}
    monkeypatch.setattr(
        "workflow_api.zeus_sensitivity.render_sensitivity_transition",
        lambda *_args: rendered,
    )
    rows = [{"candidate_index": index} for index in range(5)]
    transport = _Transport(rows)
    coordinator = ZeusSensitivityCoordinator(
        root, ssh, git, clock=lambda: 10, token_factory=lambda: "token",
        transport_factory=lambda _profile: transport,
    )
    return coordinator, transport


def test_status_preview_and_confirm_are_no_submit_and_identity_bound(tmp_path, monkeypatch):
    coordinator, transport = _coordinator(tmp_path, monkeypatch)
    request = {"campaign_id": "campaign-id", "username": "tal.noa",
               "project_directory": "/home/tal.noa/repo"}
    status = coordinator.status(request)
    assert status["validation"] == {"status": "valid", "completed_points": 5,
                                    "expected_points": 5}
    assert status["next_action"] == "review_sensitivity_preparation"
    preview = coordinator.preview(request, session_id="owner")
    assert preview["effects"] == {
        "prepare_sensitivity": True, "submit_sensitivity": False,
        "start_simulation": False, "overwrite_existing": False,
    }
    assert preview["job"]["task_count"] == 1
    result = coordinator.confirm({"preview_token": "token"}, session_id="owner")
    assert result["status"] == "sensitivity_prepared"
    assert result["submitted_to_zeus"] is False
    assert result["simulation_started"] is False
    assert len(transport.prepares) == 1
    assert set(transport.prepares[0]["sensitivity_files"]) == {
        "winners.json", "sensitivity/tasks.json", "jobs/05_sensitivity.pbs", "campaign.json",
    }


def test_confirm_rejects_session_and_changed_evidence(tmp_path, monkeypatch):
    coordinator, transport = _coordinator(tmp_path, monkeypatch)
    request = {"campaign_id": "campaign-id", "username": "tal.noa",
               "project_directory": "/home/tal.noa/repo"}
    coordinator.preview(request, session_id="owner")
    with pytest.raises(ZeusSensitivityError, match="confirmation_invalid"):
        coordinator.confirm({"preview_token": "token"}, session_id="other")
    transport.rows[0] = {"candidate_index": 99}
    with pytest.raises(ZeusSensitivityError, match="local_files_changed"):
        coordinator.confirm({"preview_token": "token"}, session_id="owner")
    assert transport.prepares == []


def test_transport_response_rejects_missing_or_partial_rows(tmp_path, monkeypatch):
    coordinator, transport = _coordinator(tmp_path, monkeypatch)
    transport.rows.pop()
    request = {"campaign_id": "campaign-id", "username": "tal.noa",
               "project_directory": "/home/tal.noa/repo"}
    with pytest.raises(ZeusSensitivityError, match="remote_response_invalid"):
        coordinator.status(request)


def test_remote_preparation_has_no_scheduler_submission_surface():
    source = (Path(__file__).parents[1]
              / "workflow_api/zeus_sensitivity_remote.py").read_text()
    assert 'sys.argv[1] not in {"inspect", "prepare"}' in source
    assert '"/usr/local/bin/qstat"' in source
    assert '"/usr/local/bin/qsub"' not in source
    assert "validated_evaluation_outputs(campaign, manifest, \"confirmation\")" in source
    assert "render_sensitivity_transition(manifest, campaign, root, locked_rows)" in source


def _qstat(states):
    rows=[]
    for index,(state,exit_status) in enumerate(states):
        rows.append(f"Job Id: 123[{index}].zeus-master\n    job_state = {state}\n")
        if exit_status is not None: rows[-1]+=f"    Exit_status = {exit_status}\n"
    return "".join(rows).encode()


@pytest.mark.parametrize("bad",[
    b"garbage prefix\n"+_qstat([("F",0)]*5),
    _qstat([("F",0)]*5)+b"garbage suffix\n",
    _qstat([("F",0)]*5).replace(b"    job_state = F",b"malformed line",1),
    _qstat([("F",0)]*5)+b"Job Id: 123[0].zeus-master\n    job_state = F\n",
])
def test_preparation_qstat_parser_fails_closed_on_non_grammar_or_duplicates(bad):
    with pytest.raises(ValueError): scheduler_snapshot(bad,"123[].zeus-master",5)


def test_preparation_qstat_parser_accepts_exact_children_and_tab_continuations():
    output=_qstat([("F",0)]*5).replace(
        b"    Exit_status = 0\n",b"    comment = long\n\tcontinued\n    Exit_status = 0\n",1)
    row=scheduler_snapshot(output,"123[].zeus-master",5)
    assert row["state"]=="completed_success"
    assert row["counts"]=={"queued":0,"running":0,"held":0,"succeeded":5,"failed":0}


def _historical_remote_fixture(tmp_path,monkeypatch):
    root=tmp_path/"repo";campaign=root/"data/optimization/mot_2d/campaign"
    (campaign/"jobs").mkdir(parents=True);(campaign/"confirmation").mkdir()
    (campaign/".mot_ui/transitions").mkdir(parents=True)
    (campaign/".mot_ui/submissions").mkdir()
    commit="a"*40;relative="data/optimization/mot_2d/campaign"
    current_manifest={"stage":"sensitivity","s0_values":[1.3],"provenance":{"git_commit":commit}}
    (campaign/"campaign.json").write_text(json.dumps(current_manifest))
    historical={"refined_candidates.json":b"{}\n","confirmation/tasks.json":b"[]\n",
                "jobs/04_confirmation.pbs":b"pbs\n","campaign.json":b"historical manifest\n"}
    for name,data in historical.items():
        if name=="campaign.json":continue
        (campaign/name).write_bytes(data)
    files={name:hashlib.sha256(data).hexdigest() for name,data in historical.items()}
    transition={"status":"confirmation_prepared","nonce":"b"*32,"chain_key":"c"*64,
                "commit":commit,"rows_digest":"d"*64,"rows":[],"files":files,
                "rounds":[],"completed_unix_s":1}
    (campaign/".mot_ui/transitions/confirmation.json").write_text(json.dumps(transition))
    transition_digest=hashlib.sha256(json.dumps(transition,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    key=hashlib.sha256(json.dumps({"campaign":relative,"commit":commit,"transition_nonce":"b"*32,
        "transition_digest":transition_digest,"files":files,"job_file":"jobs/04_confirmation.pbs"},
        sort_keys=True,separators=(",",":")).encode()).hexdigest()
    submission={"version":1,"status":"submitted","submission_key":key,"transition_nonce":"b"*32,
                "transition_digest":transition_digest,"pbs_sha256":files["jobs/04_confirmation.pbs"],
                "nonce":"e"*32,"job_file":f"{relative}/jobs/04_confirmation.pbs","commit":commit,
                "created_unix_s":1,"job_id":"123[].zeus-master","completed_unix_s":2}
    (campaign/".mot_ui/submissions/confirmation.json").write_text(json.dumps(submission))
    payload={"campaign":relative,"commit":commit,"confirmation_files":files,
             "confirmation_transition_nonce":"b"*32,"confirmation_transition_digest":transition_digest,
             "confirmation_submission_key":key}
    def captured(argv,**_kwargs):
        if argv[1:]==["rev-parse","HEAD"]:return 0,(commit+"\n").encode(),b""
        if argv[1:]==["branch","--show-current"]:return 0,b"main\n",b""
        return 0,b"",b""
    monkeypatch.setattr(remote,"run_captured",captured)
    return root,campaign,payload


def test_historical_confirmation_revalidation_still_hashes_non_manifest_artifacts(tmp_path,monkeypatch):
    root,campaign,payload=_historical_remote_fixture(tmp_path,monkeypatch)
    remote.validate_static(payload,root)
    (campaign/"confirmation/tasks.json").write_text("tampered")
    with pytest.raises(SystemExit):remote.validate_static(payload,root)


def test_invalid_inspect_does_not_create_transition_directories(tmp_path,monkeypatch):
    root=tmp_path/"repo";campaign=root/"data/optimization/mot_2d/campaign";campaign.mkdir(parents=True)
    commit="a"*40;(campaign/"campaign.json").write_text(json.dumps({"stage":"confirmation","provenance":{"git_commit":commit}}))
    def captured(argv,**_kwargs):
        if argv[1:]==["rev-parse","HEAD"]:return 0,(commit+"\n").encode(),b""
        if argv[1:]==["branch","--show-current"]:return 0,b"main\n",b""
        return 0,b"",b""
    monkeypatch.setattr(remote,"run_captured",captured)
    payload={"campaign":"data/optimization/mot_2d/campaign","commit":commit,
             "confirmation_files":{},"confirmation_transition_nonce":"b"*32,
             "confirmation_transition_digest":"c"*64,"confirmation_submission_key":"d"*64}
    with pytest.raises(SystemExit):remote.validate_static(payload,root)
    assert not (campaign/".mot_ui").exists()


def test_bounded_reader_rejects_symlinks(tmp_path):
    target=tmp_path/"target.json";target.write_text("{}")
    link=tmp_path/"link.json";link.symlink_to(target)
    with pytest.raises(SystemExit):remote.bounded(link)
