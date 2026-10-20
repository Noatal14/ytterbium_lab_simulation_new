from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflow_api.zeus_confirmation_submission import (
    PinnedSshConfirmationSubmissionTransport,
    RemoteConfirmationSubmissionState,
    ZeusConfirmationSubmissionCoordinator,
    ZeusConfirmationSubmissionError,
)
from workflow_api.zeus_confirmation_submission_remote import scheduler_state
import workflow_api.zeus_confirmation_submission_remote as receiver
from workflow_api.zeus_snapshot import ZeusProfile


class _Transport:
    def __init__(self):
        self.submits = 0
        self.state = RemoteConfirmationSubmissionState("eligible", "main")
    def inspect(self, **_payload): return self.state
    def submit(self, **payload):
        self.submits += 1
        self.state = RemoteConfirmationSubmissionState(
            "submitted", "main", "123[].zeus-master", payload["nonce"], 1_800_000_000
        )
        return self.state
    def status(self, **_payload): return self.state


def _coordinator(tmp_path, monkeypatch, *, clock=lambda: 1_700_000_000, s0_values=(1.3,)):
    root = tmp_path / "repo"; root.mkdir()
    ssh = tmp_path / "ssh"; ssh.write_text("")
    git = tmp_path / "git"; git.write_text("")
    transport = _Transport()
    coordinator = ZeusConfirmationSubmissionCoordinator(
        root, ssh, git, clock=clock, token_factory=lambda: "token",
        transport_factory=lambda _profile: transport,
    )
    campaign = root / "data/optimization/mot_2d/campaign"; campaign.mkdir(parents=True)
    profile = ZeusProfile.parse({"username":"tal.noa","project_directory":"/home/tal.noa/ytterbium_lab_simulation_new"})
    files = {"refined_candidates.json":"1"*64,"confirmation/tasks.json":"2"*64,
             "jobs/04_confirmation.pbs":"3"*64,"campaign.json":"4"*64}
    plan = ("campaign-id", profile, campaign, {"name":"Campaign","s0_values":list(s0_values)},
            "a"*40, files, "b"*32, "d"*64, "c"*64)
    monkeypatch.setattr(coordinator, "_plan", lambda _request: plan)
    return coordinator, transport, profile


def test_confirmation_submission_is_explicit_session_bound_and_replay_safe(tmp_path, monkeypatch):
    coordinator, transport, profile = _coordinator(tmp_path, monkeypatch)
    request = {"campaign_id":"campaign-id","username":profile.username,
               "project_directory":profile.project_directory}
    preview = coordinator.preview(request, session_id="owner")
    assert preview["job"] == {
        "file":"jobs/04_confirmation.pbs","kind":"array","task_count":5,
        "array_throttle":3,"queue":"zeus_combined_q","cores_per_task":200,
        "memory_per_task_bytes":68719476736,"walltime_seconds":36000,
    }
    assert transport.submits == 0
    with pytest.raises(ZeusConfirmationSubmissionError) as caught:
        coordinator.confirm({"preview_token":"token"}, session_id="intruder")
    assert caught.value.code == "confirmation_invalid"
    first = coordinator.confirm({"preview_token":"token"}, session_id="owner")
    second = coordinator.confirm({"preview_token":"token"}, session_id="owner")
    assert first == second
    assert first["job_id"] == "123[].zeus-master"
    assert transport.submits == 1


def test_unknown_remote_outcome_blocks_preview_retry(tmp_path, monkeypatch):
    coordinator, transport, profile = _coordinator(tmp_path, monkeypatch)
    transport.state = RemoteConfirmationSubmissionState("ambiguous", "main", nonce="f"*32)
    with pytest.raises(ZeusConfirmationSubmissionError) as caught:
        coordinator.preview({"campaign_id":"campaign-id","username":profile.username,
                             "project_directory":profile.project_directory}, session_id="owner")
    assert caught.value.code == "confirmation_submission_outcome_unknown"


def test_confirmation_revalidates_transition_evidence_before_any_submit(tmp_path, monkeypatch):
    coordinator, transport, profile = _coordinator(tmp_path, monkeypatch)
    request={"campaign_id":"campaign-id","username":profile.username,
             "project_directory":profile.project_directory}
    coordinator.preview(request, session_id="owner")
    original = coordinator._plan(request)
    changed = list(original)
    changed[5] = {**original[5], "campaign.json": "9"*64}
    monkeypatch.setattr(coordinator, "_plan", lambda _request: tuple(changed))
    with pytest.raises(ZeusConfirmationSubmissionError) as caught:
        coordinator.confirm({"preview_token":"token"}, session_id="owner")
    assert caught.value.code == "local_files_changed"
    assert transport.submits == 0


def test_preview_derives_exact_array_count_from_frozen_multi_s0_design(tmp_path, monkeypatch):
    coordinator, _, profile = _coordinator(
        tmp_path, monkeypatch, s0_values=(0.8, 1.3, 2.0)
    )
    preview = coordinator.preview({
        "campaign_id":"campaign-id", "username":profile.username,
        "project_directory":profile.project_directory,
    }, session_id="owner")
    assert preview["campaign"]["s0_values"] == [0.8, 1.3, 2.0]
    assert preview["job"]["task_count"] == 15
    assert preview["job"]["file"] == "jobs/04_confirmation.pbs"


def test_status_reports_only_closed_confirmation_operation(tmp_path, monkeypatch):
    coordinator, transport, profile = _coordinator(tmp_path, monkeypatch)
    payload={"campaign_id":"campaign-id","username":profile.username,
             "project_directory":profile.project_directory}
    assert coordinator.status(payload)["submission"] == {"status":"not_submitted","job_id":None}
    transport.state=RemoteConfirmationSubmissionState("running","main","123[].zeus-master","f"*32,1)
    assert coordinator.status(payload)["submission"] == {"status":"running","job_id":"123[].zeus-master"}


def _qstat(states):
    rows=[]
    for index,(state,exit_status) in enumerate(states):
        rows.append(f"Job Id: 123[{index}].zeus-master\n    job_state = {state}\n")
        if exit_status is not None:
            rows[-1] += f"    Exit_status = {exit_status}\n"
    return "".join(rows).encode()


@pytest.mark.parametrize(("states","expected"), [
    ([('Q',None)]*5, "queued"),
    ([('F','0')]*4+[('R',None)], "running"),
    ([('F','0')]*4+[('H',None)], "held"),
    ([('F','0')]*5, "completed_success"),
    ([('F','0')]*4+[('F','2')], "completed_failed"),
    ([('F','0')]*4+[('Z',None)], "status_unknown"),
])
def test_qstat_confirmation_array_requires_exact_children_and_uses_conservative_precedence(states, expected):
    assert scheduler_state(_qstat(states), "123[].zeus-master", 5) == expected


def test_qstat_confirmation_array_rejects_missing_duplicate_and_unrelated_records():
    assert scheduler_state(_qstat([('F','0')]*4), "123[].zeus-master", 5) == "status_unknown"
    duplicate = _qstat([('F','0')]*5) + b"Job Id: 123[0].zeus-master\n    job_state = F\n    Exit_status = 0\n"
    assert scheduler_state(duplicate, "123[].zeus-master", 5) == "status_unknown"
    unrelated = _qstat([('F','0')]*5) + b"Job Id: 999[0].zeus-master\n    job_state = F\n"
    assert scheduler_state(unrelated, "123[].zeus-master", 5) == "status_unknown"
    parent=b"Job Id: 123[].zeus-master\n    job_state = F\n"
    assert scheduler_state(parent, "123[].zeus-master", 5)=="status_unknown"
    assert scheduler_state(parent+parent+_qstat([('F','0')]*5), "123[].zeus-master", 5)=="status_unknown"
    duplicate_key=_qstat([('F','0')]*5)+b""
    duplicate_key=duplicate_key.replace(b"job_state = F",b"job_state = F\n    job_state = R",1)
    assert scheduler_state(duplicate_key,"123[].zeus-master",5)=="status_unknown"
    assert scheduler_state(b"not qstat", "123[].zeus-master",5)=="status_unknown"
    assert scheduler_state(b"x"*(4*1024*1024+1),"123[].zeus-master",5)=="status_unknown"


@pytest.mark.parametrize("output",[
    b"garbage prefix\n"+_qstat([('F','0')]*5),
    _qstat([('F','0')]*5)+b"garbage suffix\n",
    _qstat([('F','0')]*5).replace(b"    Exit_status = 0",b"malformed line",1),
])
def test_qstat_confirmation_array_rejects_non_grammar_text(output):
    assert scheduler_state(output,"123[].zeus-master",5)=="status_unknown"


def test_qstat_confirmation_array_accepts_documented_tab_continuation():
    output=_qstat([('F','0')]*5).replace(
        b"    Exit_status = 0\n",b"    comment = a long value\n\tcontinued value\n    Exit_status = 0\n",1
    )
    assert scheduler_state(output,"123[].zeus-master",5)=="completed_success"


def test_remote_receiver_contains_only_the_frozen_confirmation_array_qsub():
    source=(Path(__file__).parents[1]/"workflow_api/zeus_confirmation_submission_remote.py").read_text()
    assert source.count('run_captured(["/usr/local/bin/qsub"]') == 1
    assert source.count('run_captured(["/opt/pbs/bin/qstat","-x","-t","-f",done["job_id"]]') == 1
    assert 'if operation in {"inspect","status"}: respond("eligible",branch);return' in source
    assert source.index('submissions.mkdir(parents=True,exist_ok=True)') > source.index('if operation in {"inspect","status"}')
    assert "qdel" not in source and "afterok" not in source
    assert "jobs/04_confirmation.pbs" in source
    assert '"status","--porcelain=v1","-z","--untracked-files=all"' in source


def _receiver_fixture(tmp_path, monkeypatch):
    root=tmp_path/"repo";campaign=root/"data/optimization/mot_2d/campaign"
    (campaign/"jobs").mkdir(parents=True);(campaign/"confirmation").mkdir()
    (campaign/".mot_ui/transitions").mkdir(parents=True)
    artifacts={
        "refined_candidates.json":b"{}\n", "confirmation/tasks.json":b"[]\n",
        "jobs/04_confirmation.pbs":b"#!/bin/bash\n", "campaign.json":json.dumps({"stage":"confirmation","name":"C","s0_values":[1.3],"provenance":{"git_commit":"a"*40}}).encode(),
    }
    files={name:hashlib.sha256(data).hexdigest() for name,data in artifacts.items()}
    for name,data in artifacts.items():(campaign/name).write_bytes(data)
    record={"status":"confirmation_prepared","nonce":"b"*32,"chain_key":"chain","commit":"a"*40,"rows_digest":"c"*64,"rows":[{"x":1}],"files":files,"rounds":[{"round":1}],"completed_unix_s":1}
    receipt=campaign/".mot_ui/transitions/confirmation.json";receipt.write_text(json.dumps(record))
    digest=hashlib.sha256(json.dumps(record,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    relative="data/optimization/mot_2d/campaign"
    key=hashlib.sha256(json.dumps({"campaign":relative,"commit":"a"*40,"transition_nonce":"b"*32,"transition_digest":digest,"files":files,"job_file":"jobs/04_confirmation.pbs"},sort_keys=True,separators=(",",":")).encode()).hexdigest()
    payload={"campaign":relative,"commit":"a"*40,"confirmation_files":files,"transition_nonce":"b"*32,"transition_digest":digest,"submission_key":key,"nonce":"d"*32}
    monkeypatch.setattr(receiver,"Path",lambda _value:root)
    def git_run(argv,**_kwargs):
        if argv[1:]==["rev-parse","HEAD"]:return SimpleNamespace(returncode=0,stdout=b"a"*40+b"\n",stderr=b"")
        if argv[1:]==["branch","--show-current"]:return SimpleNamespace(returncode=0,stdout=b"main\n",stderr=b"")
        return SimpleNamespace(returncode=0,stdout=b"",stderr=b"")
    monkeypatch.setattr(receiver.subprocess,"run",git_run)
    return root,campaign,receipt,record,payload


def _invoke_receiver(monkeypatch,payload,operation,capsys):
    encoded=base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    monkeypatch.setattr(sys,"argv",["receiver",operation,"tal.noa","/home/tal.noa/ytterbium_lab_simulation_new",encoded])
    receiver.main();return json.loads(capsys.readouterr().out)


def test_receiver_inspect_and_unsubmitted_status_are_zero_write(tmp_path,monkeypatch,capsys):
    root,campaign,_,_,payload=_receiver_fixture(tmp_path,monkeypatch)
    before=sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    assert _invoke_receiver(monkeypatch,payload,"inspect",capsys)["status"]=="eligible"
    assert _invoke_receiver(monkeypatch,payload,"status",capsys)["status"]=="eligible"
    assert sorted(str(path.relative_to(root)) for path in root.rglob("*"))==before
    assert not (campaign/".mot_ui/submissions").exists()


@pytest.mark.parametrize("field",["chain_key","rows_digest","rows","rounds"])
def test_receiver_rejects_full_transition_receipt_drift_before_qsub(tmp_path,monkeypatch,capsys,field):
    _,_,receipt,record,payload=_receiver_fixture(tmp_path,monkeypatch);calls=[]
    changed=dict(record);changed[field]=[] if field in {"rows","rounds"} else "changed"
    receipt.write_text(json.dumps(changed))
    monkeypatch.setattr(receiver,"run_captured",lambda *args,**kwargs:calls.append(args) or (0,b"1[].zeus-master\n",b""))
    with pytest.raises(SystemExit):_invoke_receiver(monkeypatch,payload,"submit",capsys)
    capsys.readouterr()
    assert calls==[]


def test_receiver_submit_ledger_and_targeted_status_are_at_most_once(tmp_path,monkeypatch,capsys):
    _,campaign,_,_,payload=_receiver_fixture(tmp_path,monkeypatch);calls=[]
    def captured(argv,**_kwargs):
        calls.append(argv)
        if argv[0].endswith("qsub"):return 0,b"123[].zeus-master\n",b""
        return 0,_qstat([('F','0')]*5),b""
    monkeypatch.setattr(receiver,"run_captured",captured)
    assert _invoke_receiver(monkeypatch,payload,"submit",capsys)["status"]=="submitted"
    assert _invoke_receiver(monkeypatch,payload,"submit",capsys)["status"]=="submitted"
    assert len([call for call in calls if call[0].endswith("qsub")])==1
    status=_invoke_receiver(monkeypatch,payload,"status",capsys)
    assert status["status"]=="completed_success"
    assert calls[-1]==["/opt/pbs/bin/qstat","-x","-t","-f","123[].zeus-master"]
    done=json.loads((campaign/".mot_ui/submissions/confirmation.json").read_text())
    assert done["transition_digest"]==payload["transition_digest"]


@pytest.mark.parametrize("bad_output",[
    b"garbage prefix\n"+_qstat([('F','0')]*5),
    _qstat([('F','0')]*5)+b"garbage suffix\n",
    _qstat([('F','0')]*5).replace(b"    job_state = F",b"malformed line",1),
])
def test_receiver_status_maps_non_grammar_qstat_to_unknown_with_targeted_query(tmp_path,monkeypatch,capsys,bad_output):
    _,_,_,_,payload=_receiver_fixture(tmp_path,monkeypatch);calls=[]
    def captured(argv,**_kwargs):
        calls.append(argv)
        return (0,b"123[].zeus-master\n",b"") if argv[0].endswith("qsub") else (0,bad_output,b"")
    monkeypatch.setattr(receiver,"run_captured",captured)
    assert _invoke_receiver(monkeypatch,payload,"submit",capsys)["status"]=="submitted"
    assert _invoke_receiver(monkeypatch,payload,"status",capsys)["status"]=="status_unknown"
    assert calls[-1]==["/opt/pbs/bin/qstat","-x","-t","-f","123[].zeus-master"]


def test_receiver_qsub_crash_leaves_ambiguous_durable_intent_and_blocks_retry(tmp_path,monkeypatch,capsys):
    _,campaign,_,_,payload=_receiver_fixture(tmp_path,monkeypatch);calls=[]
    def crash(argv,**_kwargs):calls.append(argv);raise TimeoutError("uncertain")
    monkeypatch.setattr(receiver,"run_captured",crash)
    with pytest.raises(SystemExit):_invoke_receiver(monkeypatch,payload,"submit",capsys)
    capsys.readouterr()
    pending=campaign/".mot_ui/submissions/confirmation.pending.json"
    assert pending.is_file()
    assert json.loads(pending.read_text())["transition_digest"]==payload["transition_digest"]
    assert _invoke_receiver(monkeypatch,payload,"submit",capsys)["status"]=="ambiguous"
    assert len(calls)==1


def test_transport_rejects_operation_inappropriate_plain_submitted_status(tmp_path,monkeypatch):
    coordinator,transport,profile=_coordinator(tmp_path,monkeypatch)
    transport.state=RemoteConfirmationSubmissionState("submitted","main","123[].zeus-master","f"*32,1)
    # Coordinator maps no unverified plain submitted state from a STATUS operation.
    with pytest.raises(ZeusConfirmationSubmissionError) as caught:
        coordinator.status({"campaign_id":"campaign-id","username":profile.username,"project_directory":profile.project_directory})
    assert caught.value.code=="remote_response_invalid"


@pytest.mark.parametrize(("operation","status"),[("status","submitted"),("inspect","running"),("submit","eligible")])
def test_pinned_transport_enforces_operation_specific_receiver_states(operation,status):
    transport=object.__new__(PinnedSshConfirmationSubmissionTransport)
    transport.profile=SimpleNamespace()
    response={"status":status,"branch":"main","job_id":None,"nonce":None,"completed_unix_s":None}
    transport.runner=SimpleNamespace(run=lambda *_args,**_kwargs:SimpleNamespace(returncode=0,stderr=b"",stdout=json.dumps(response).encode()))
    with pytest.raises(ZeusConfirmationSubmissionError) as caught:
        transport._call(operation,{"nonce":None})
    assert caught.value.code=="remote_response_invalid"
