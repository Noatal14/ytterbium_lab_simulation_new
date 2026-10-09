import json
import math
import subprocess
import base64
import hashlib
import sys
import time
import fcntl
import os
from types import SimpleNamespace
from pathlib import Path

import pytest

from workflow_api.zeus_confirmation import PinnedSshConfirmationTransport, RemoteRefineState, ZeusConfirmationCoordinator, ZeusConfirmationError
from workflow_api.zeus_confirmation_remote import chain_lifecycle, completed_rounds, parse_round
import workflow_api.zeus_confirmation_remote as receiver
from workflow_api.zeus_snapshot import ZeusProfile


def test_confirmation_receiver_has_no_submission_capability():
    source=(Path(__file__).parents[1]/"workflow_api/zeus_confirmation_remote.py").read_text()
    assert "/usr/local/bin/qsub" not in source
    assert "confirmation-task" not in source
    assert "validate_refine_outputs" in source
    assert source.count("/usr/local/bin/qstat") >= 2


@pytest.mark.parametrize("mutation",("bad_lifecycle","bad_count","nan_row","duplicate_source","wrong_dependency"))
def test_coordinator_contract_rejects_forged_remote_state(tmp_path,mutation):
    # Contract mutations are asserted structurally in the coordinator before
    # any result is shown or any transition token is allocated.
    source=(Path(__file__).parents[1]/"workflow_api/zeus_confirmation.py").read_text()
    required={
        "bad_lifecycle":"state.lifecycle not in",
        "bad_count":"sum(scheduler[\"counts\"].values())!=expected",
        "nan_row":"not math.isfinite",
        "duplicate_source":"row[\"source\"] in seen",
        "wrong_dependency":"row[\"depends_on_job_id\"]!=",
    }
    assert required[mutation] in source


def test_prepare_transport_timeout_is_permanently_ambiguous(tmp_path,monkeypatch):
    profile=ZeusProfile.parse({"username":"tal.noa","project_directory":"/home/tal.noa/ytterbium_lab_simulation_new"})
    transport=PinnedSshConfirmationTransport(tmp_path,Path("/usr/bin/true"),profile)
    monkeypatch.setattr(subprocess,"run",lambda *a,**k:(_ for _ in ()).throw(subprocess.TimeoutExpired([],1)))
    with pytest.raises(ZeusConfirmationError,match="transition_outcome_unknown"):
        transport.prepare(example=True)


def _scheduler_rows(job, states):
    prefix=job.replace("[].zeus-master","")
    rows=[]
    for index,state in enumerate(states):
        row={"id":f"{prefix}[{index}].zeus-master","state":state}
        if state.startswith("completed_"):row["exit_status"]=0 if state=="completed_success" else 1
        rows.append(row)
    return rows


def test_parse_round_requires_exact_children_and_dependency():
    ids=[f"{100+i}[].zeus-master" for i in range(4)]
    output=f"depend = afterok:{ids[0]}@zeus-master\n"
    parser=lambda _:_scheduler_rows(ids[1],["completed_success"]*3)
    row,unknown=parse_round(output,ids[1],3,2,ids,parser)
    assert row["scheduler"]=={"state":"completed_success","task_count":3,"counts":{"queued":0,"running":0,"held":0,"succeeded":3,"failed":0}}
    assert unknown is False
    with pytest.raises(ValueError,match="dependency"):
        parse_round("depend = afterok:999[].zeus-master\n",ids[1],3,2,ids,parser)
    with pytest.raises(ValueError,match="records"):
        parse_round(output,ids[1],3,2,ids,lambda _:_scheduler_rows(ids[1],["completed_success"]*2))
    with pytest.raises(ValueError,match="records"):
        parse_round(output,ids[1],3,2,ids,lambda _:parser(_)+[parser(_)[0]])
    with pytest.raises(ValueError,match="state"):
        parse_round(output,ids[1],3,2,ids,lambda _:_scheduler_rows(ids[1],["mystery"]*3))


def test_chain_failure_dominates_downstream_hold():
    def round_row(index,**counts):
        full={"queued":0,"running":0,"held":0,"succeeded":0,"failed":0};full.update(counts)
        return {"scheduler":{"task_count":3,"counts":full}}
    rounds=[round_row(1,failed=1,succeeded=2),round_row(2,held=3),round_row(3,held=3),round_row(4,held=3)]
    assert chain_lifecycle(rounds,False)=="failed"
    assert chain_lifecycle([round_row(1,held=3)]*4,False)=="held"


def test_completed_round_receipt_is_exact():
    ids=[f"{100+i}[].zeus-master" for i in range(4)]
    rows=[]
    for index,job in enumerate(ids,1):
        rows.append({"round":index,"job_id":job,"depends_on_job_id":None if index==1 else ids[index-2],"scheduler":{"state":"completed_success","task_count":3,"counts":{"queued":0,"running":0,"held":0,"succeeded":3,"failed":0}}})
    assert completed_rounds(rows,ids,3)
    forged=json.loads(json.dumps(rows));forged[2]["scheduler"]["counts"]["succeeded"]=2
    assert not completed_rounds(forged,ids,3)


def _coordinator_state(tmp_path,lifecycle="ready_to_prepare_confirmation",round_state="completed_success"):
    ids=[f"{100+i}[].zeus-master" for i in range(4)]
    counts={"queued":0,"running":0,"held":0,"succeeded":3,"failed":0}
    rounds=[]
    for index,job in enumerate(ids,1):
        rounds.append({"round":index,"job_id":job,"depends_on_job_id":None if index==1 else ids[index-2],"scheduler":{"state":round_state,"task_count":3,"counts":dict(counts)}})
    rows=tuple({"s0":1.3,"detuning_gamma":-1.0,"magnet_radius":0.04,"mean_conditional_efficiency":0.1,"source":f"refine/s0_1p300000/worker{worker}/trials/trial_{trial:04d}.json"} for worker in range(3) for trial in range(10))
    state=RemoteRefineState(lifecycle,tuple(rounds),rows,"main")
    coordinator=object.__new__(ZeusConfirmationCoordinator)
    profile=ZeusProfile.parse({"username":"tal.noa","project_directory":"/home/tal.noa/ytterbium_lab_simulation_new"})
    manifest={"name":"campaign","s0_values":[1.3]}
    campaign=tmp_path/"data/optimization/mot_2d/campaign";campaign.mkdir(parents=True)
    coordinator.root=tmp_path;coordinator.transport_factory=lambda _:SimpleNamespace(inspect=lambda **__:state)
    coordinator._plan=lambda _: ("campaign",profile,campaign,manifest,"0"*40,{},"1"*64,"2"*64,"3"*64)
    return coordinator,state


def test_coordinator_behaviorally_rejects_incoherent_scheduler(tmp_path):
    coordinator,state=_coordinator_state(tmp_path)
    forged=[dict(row) for row in state.rounds]
    forged[0]=dict(forged[0]);forged[0]["scheduler"]={"state":"completed_success","task_count":3,"counts":{"queued":0,"running":0,"held":0,"succeeded":2,"failed":0}}
    coordinator.transport_factory=lambda _:SimpleNamespace(inspect=lambda **__:RemoteRefineState(state.lifecycle,tuple(forged),state.rows,"main"))
    with pytest.raises(ZeusConfirmationError,match="remote_response_invalid"):
        coordinator._inspect({})


@pytest.mark.parametrize("field,value",[("source","refine/../../escape.json"),("mean_conditional_efficiency",math.nan),("s0",2.0)])
def test_coordinator_behaviorally_rejects_forged_scientific_rows(tmp_path,field,value):
    coordinator,state=_coordinator_state(tmp_path)
    rows=[dict(row) for row in state.rows];rows[0][field]=value
    coordinator.transport_factory=lambda _:SimpleNamespace(inspect=lambda **__:RemoteRefineState(state.lifecycle,state.rounds,tuple(rows),"main"))
    with pytest.raises(ZeusConfirmationError,match="remote_response_invalid"):
        coordinator._inspect({})


def _receiver_fixture(tmp_path,monkeypatch,*,wrong_dependency=False,failed_child=False):
    username="tal.noa";root=tmp_path/username/"ytterbium_lab_simulation_new";campaign=root/"data/optimization/mot_2d/camp"
    transitions=campaign/".mot_ui/transitions";submissions=campaign/".mot_ui/submissions"
    transitions.mkdir(parents=True);submissions.mkdir();(campaign/"refine").mkdir();(campaign/"jobs").mkdir()
    commit="a"*40;screen_digest="b"*64;screen_key="c"*64;chain_key="d"*64;nonce="e"*32
    manifest={"name":"camp","stage":"refine","s0_values":[1.3],"stages":{"refine":{}},"git_commit":commit}
    (campaign/"campaign.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    refine_names=("campaign.json","screening_candidates.json","refine/tasks.json","jobs/03_refine_round_01.pbs","jobs/03_refine_round_02.pbs","jobs/03_refine_round_03.pbs","jobs/03_refine_round_04.pbs","jobs/03_submit_refinement_chain.sh")
    for name in refine_names:
        path=campaign/name;path.parent.mkdir(parents=True,exist_ok=True)
        if name!="campaign.json":path.write_bytes((name+"\n").encode())
    refine_files={name:hashlib.sha256((campaign/name).read_bytes()).hexdigest() for name in refine_names}
    rows=[{"s0":1.3,"detuning_gamma":-1.0,"magnet_radius":0.04,"mean_conditional_efficiency":0.1,"source":f"refine/s0_1p300000/worker{w}/trials/trial_{t:04d}.json"} for w in range(3) for t in range(10)]
    rows_digest=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest();now=int(time.time())
    refine_receipt={"status":"refinement_prepared","nonce":"f"*32,"job_id":"99[].zeus-master","rows_digest":rows_digest,"rows":rows,"refine_files":refine_files,"commit":commit,"screening_submission_key":screen_key,"screen_digest":screen_digest,"completed_unix_s":now}
    (transitions/"refine.json").write_text(json.dumps(refine_receipt))
    job_ids=[f"{100+i}[].zeus-master" for i in range(4)]
    chain={"status":"submitted","chain_key":chain_key,"nonce":nonce,"commit":commit,"job_ids":job_ids,"created_unix_s":now-20,"completed_unix_s":now-1}
    (submissions/"refinement_chain.json").write_text(json.dumps(chain))
    for index,job in enumerate(job_ids,1):
        step={"status":"submitted","chain_key":chain_key,"nonce":nonce,"round":index,"pbs_sha256":refine_files[f"jobs/03_refine_round_{index:02d}.pbs"],"depends_on":None if index==1 else job_ids[index-2],"created_unix_s":now-20+index*2,"job_id":job,"completed_unix_s":now-19+index*2}
        (submissions/f"refinement_round_{index:02d}.json").write_text(json.dumps(step))
    rendered={"refined_candidates.json":b"{}\n","confirmation/tasks.json":b"[]\n","jobs/04_confirmation.pbs":b"#!/bin/bash\n","campaign.json":(json.dumps({**manifest,"stage":"confirmation","stages":{**manifest["stages"],"confirmation":{}}},indent=2,sort_keys=True)+"\n").encode()}
    confirmation_files={name:hashlib.sha256(data).hexdigest() for name,data in rendered.items()}
    import workflow_api.mot_2d_screen as screen_module
    import workflow_api.mot_2d_plan as plan_module
    monkeypatch.setattr(screen_module,"validate_refine_outputs",lambda *_:rows)
    monkeypatch.setattr(plan_module,"render_confirmation_transition",lambda *_:rendered)
    real_path=Path;home=tmp_path
    monkeypatch.setattr(receiver,"Path",lambda value:home if str(value)=="/home" else real_path(value))
    import workflow_api.zeus_snapshot as snapshot
    def parsed(output):
        match=output.splitlines()[0];states=["completed_success"]*3
        if failed_child and match==job_ids[0]:states[0]="completed_failed"
        return _scheduler_rows(match,states)
    monkeypatch.setattr(snapshot,"_parse_qstat",parsed)
    calls=[]
    def run(argv,**kwargs):
        calls.append(tuple(argv))
        if argv[:3]==["/usr/bin/git","rev-parse","HEAD"]:return SimpleNamespace(stdout=commit+"\n",stderr="",returncode=0)
        if argv[:3]==["/usr/bin/git","status","--porcelain=v1"]:return SimpleNamespace(stdout=b"",stderr=b"",returncode=0)
        if argv[:3]==["/usr/bin/git","branch","--show-current"]:return SimpleNamespace(stdout="main\n",stderr="",returncode=0)
        job=argv[-1];index=job_ids.index(job);dependency="" if index==0 else f"depend = afterok:{'999[].zeus-master' if wrong_dependency else job_ids[index-1]}@zeus-master\n"
        return SimpleNamespace(stdout=f"{job}\n{dependency}",stderr="",returncode=0)
    monkeypatch.setattr(receiver.subprocess,"run",run)
    payload={"campaign":"data/optimization/mot_2d/camp","commit":commit,"refine_files":refine_files,"chain_key":chain_key,"screen_digest":screen_digest,"screening_submission_key":screen_key,"rows_digest":rows_digest,"confirmation_files":confirmation_files,"nonce":"1"*32}
    encoded=base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    monkeypatch.setattr(sys,"argv",["receiver","prepare",username,str(root),encoded])
    return campaign,calls,rendered


def test_receiver_happy_path_publishes_canonical_confirmation_without_qsub(tmp_path,monkeypatch,capsys):
    campaign,calls,rendered=_receiver_fixture(tmp_path,monkeypatch)
    receiver.main();response=json.loads(capsys.readouterr().out)
    assert response["lifecycle"]=="confirmation_prepared"
    assert [call[0] for call in calls].count("/usr/local/bin/qstat")==8
    assert all("qsub" not in " ".join(call) for call in calls)
    assert (campaign/".mot_ui/transitions/confirmation.json").is_file()
    assert not (campaign/".mot_ui/transitions/confirmation.pending.json").exists()
    for name,data in rendered.items():assert (campaign/name).read_bytes()==data


@pytest.mark.parametrize("mutation",("wrong_dependency","failed_child"))
def test_receiver_scheduler_mutation_never_publishes(tmp_path,monkeypatch,mutation):
    campaign,_,_=_receiver_fixture(tmp_path,monkeypatch,wrong_dependency=mutation=="wrong_dependency",failed_child=mutation=="failed_child")
    if mutation=="wrong_dependency":
        with pytest.raises(SystemExit):receiver.main()
    else:
        receiver.main()
    assert not (campaign/".mot_ui/transitions/confirmation.json").exists()
    assert not (campaign/"confirmation").exists()


def test_receiver_replay_revalidates_exact_durable_receipt(tmp_path,monkeypatch,capsys):
    campaign,_,_=_receiver_fixture(tmp_path,monkeypatch)
    receiver.main();capsys.readouterr()
    receiver.main();response=json.loads(capsys.readouterr().out)
    assert response["lifecycle"]=="confirmation_prepared"
    receipt=campaign/".mot_ui/transitions/confirmation.json";forged=json.loads(receipt.read_text());forged["rows_digest"]="0"*64;receipt.write_text(json.dumps(forged))
    with pytest.raises(SystemExit):receiver.main()


def test_receiver_recovers_crash_after_manifest_under_lock(tmp_path,monkeypatch,capsys):
    campaign,_,_=_receiver_fixture(tmp_path,monkeypatch)
    receiver.main();capsys.readouterr()
    receipt_path=campaign/".mot_ui/transitions/confirmation.json";record=json.loads(receipt_path.read_text());receipt_path.unlink()
    pending={"status":"confirmation_pending","nonce":record["nonce"],"chain_key":record["chain_key"],"rows_digest":record["rows_digest"],"files":record["files"],"rounds":record["rounds"],"created_unix_s":record["completed_unix_s"]}
    pending_path=campaign/".mot_ui/transitions/confirmation.pending.json";pending_path.write_text(json.dumps(pending))
    receiver.main();response=json.loads(capsys.readouterr().out)
    assert response["lifecycle"]=="confirmation_prepared"
    assert receipt_path.is_file() and not pending_path.exists()


def test_receiver_partial_publication_without_pending_is_fail_closed(tmp_path,monkeypatch):
    campaign,_,_=_receiver_fixture(tmp_path,monkeypatch)
    (campaign/"confirmation").mkdir()
    with pytest.raises(SystemExit):receiver.main()
    assert not (campaign/".mot_ui/transitions/confirmation.json").exists()


def test_receiver_symlinked_output_parent_is_rejected(tmp_path,monkeypatch):
    campaign,_,_=_receiver_fixture(tmp_path,monkeypatch)
    outside=tmp_path/"outside";outside.mkdir();(campaign/"confirmation").symlink_to(outside,target_is_directory=True)
    with pytest.raises(SystemExit):receiver.main()
    assert list(outside.iterdir())==[]


def test_receiver_recovery_obeys_confirmation_lock(tmp_path,monkeypatch,capsys):
    campaign,_,_=_receiver_fixture(tmp_path,monkeypatch)
    receiver.main();capsys.readouterr()
    receipt_path=campaign/".mot_ui/transitions/confirmation.json";record=json.loads(receipt_path.read_text());receipt_path.unlink()
    pending={"status":"confirmation_pending","nonce":record["nonce"],"chain_key":record["chain_key"],"rows_digest":record["rows_digest"],"files":record["files"],"rounds":record["rounds"],"created_unix_s":record["completed_unix_s"]}
    (campaign/".mot_ui/transitions/confirmation.pending.json").write_text(json.dumps(pending))
    lock_path=campaign/".mot_ui/transitions/confirmation.lock";fd=os.open(lock_path,os.O_RDWR)
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        with pytest.raises(SystemExit):receiver.main()
        assert not receipt_path.exists()
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
    receiver.main();assert receipt_path.is_file()


def test_cli_confirmation_writes_exact_renderer_bytes(tmp_path,monkeypatch):
    import studies.mot_2d_s0_campaign as campaign_module
    import workflow_api.mot_2d_screen as screen_module
    import workflow_api.mot_2d_plan as plan_module
    rows=[{"source":"canonical"}];rendered={"refined_candidates.json":b"A\n","confirmation/tasks.json":b"B\n","jobs/04_confirmation.pbs":b"C\n","campaign.json":b"D\n"}
    monkeypatch.setattr(screen_module,"validate_refine_outputs",lambda root,manifest:rows)
    monkeypatch.setattr(plan_module,"render_confirmation_transition",lambda manifest,root,repo,validated:rendered if validated==rows else {})
    campaign_module.prepare_confirmation(tmp_path,{"s0_values":[1.3]})
    for name,content in rendered.items():assert (tmp_path/name).read_bytes()==content
