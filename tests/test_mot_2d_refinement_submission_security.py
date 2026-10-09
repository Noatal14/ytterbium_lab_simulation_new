import json
import base64
import hashlib
import sys
import subprocess
from pathlib import Path

import pytest

from workflow_api.zeus_refinement_submission import (
    PinnedSshRefinementSubmissionTransport,
    RemoteChainState,
    ZeusRefinementSubmissionCoordinator,
    ZeusRefinementSubmissionError,
)
from workflow_api.zeus_snapshot import ZeusProfile


def _transport(tmp_path: Path) -> PinnedSshRefinementSubmissionTransport:
    return PinnedSshRefinementSubmissionTransport(
        tmp_path, Path("/usr/bin/true"),
        ZeusProfile.parse({"username": "tal.noa", "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new"}),
    )


def _completed(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, json.dumps(payload).encode(), b"")


@pytest.mark.parametrize("payload", [
    {"status":"eligible","branch":"main","job_ids":["1[].zeus-master"],"nonce":None,"completed_unix_s":None},
    {"status":"submitted","branch":"main","job_ids":["1[].zeus-master"]*4,"nonce":"a"*32,"completed_unix_s":1},
    {"status":"partial","branch":"main","job_ids":[],"nonce":None,"completed_unix_s":None},
    {"status":"submitted","branch":"main","job_ids":["1[].zeus-master","2[].zeus-master","3[].zeus-master","4[].zeus-master"],"nonce":"a"*32,"completed_unix_s":True},
])
def test_transport_rejects_incoherent_chain_responses(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _completed(payload))
    with pytest.raises(ZeusRefinementSubmissionError, match="remote_response_invalid"):
        _transport(tmp_path).inspect(example=True)


def test_remote_receiver_has_only_fixed_qsub_and_never_runs_chain_script():
    source=(Path(__file__).parents[1]/"workflow_api/zeus_refinement_submission_remote.py").read_text()
    assert 'argv=["/usr/local/bin/qsub"]' in source
    assert '"-W","depend=afterok:"+previous' in source
    assert "shell=True" not in source
    assert "03_submit_refinement_chain.sh\")" not in source
    assert source.count("write_record(step_pending[index-1]") == 1
    assert source.index("write_record(step_pending[index-1]") < source.index("subprocess.run(argv,input=data")


def test_remote_receiver_revalidates_before_every_qsub_and_binds_receipts():
    source=(Path(__file__).parents[1]/"workflow_api/zeus_refinement_submission_remote.py").read_text()
    assert "current=verify()[index-1]" in source
    assert "record[\"nonce\"]!=receipt_nonce" in source
    assert "job in ids" in source
    assert "verify()\n        response(\"submitted\"" in source


def test_receiver_submits_four_verified_byte_streams_with_exact_dependencies(tmp_path, monkeypatch, capsys):
    source=(Path(__file__).parents[1]/"workflow_api/zeus_refinement_submission_remote.py").read_text()
    source=source.replace(' or project!=f"/home/{username}/ytterbium_lab_simulation_new"', '')
    namespace={"__name__":"receiver_under_test"};exec(compile(source,"<receiver>","exec"),namespace)
    root=tmp_path/"repo";campaign=root/"data/optimization/mot_2d/campaign";(campaign/"jobs").mkdir(parents=True);(campaign/"refine").mkdir();(campaign/".mot_ui/transitions").mkdir(parents=True)
    commit="a"*40;names=[*(f"jobs/03_refine_round_{i:02d}.pbs" for i in range(1,5)),"campaign.json","screening_candidates.json","refine/tasks.json","jobs/03_submit_refinement_chain.sh"]
    for index,name in enumerate(names):
        path=campaign/name;path.parent.mkdir(parents=True,exist_ok=True)
        content=(json.dumps({"stage":"refine","provenance":{"git_commit":commit}})+"\n").encode() if name=="campaign.json" else f"payload-{index}\n".encode();path.write_bytes(content)
    files={name:hashlib.sha256((campaign/name).read_bytes()).hexdigest() for name in names};screen_digest="b"*64;screening_key="c"*64
    transition={"status":"refinement_prepared","nonce":"d"*32,"job_id":"9[].zeus-master","rows_digest":"e"*64,"rows":[],"refine_files":files,"commit":commit,"screening_submission_key":screening_key,"screen_digest":screen_digest,"completed_unix_s":1}
    (campaign/".mot_ui/transitions/refine.json").write_text(json.dumps(transition))
    calls=[]
    def fake_run(argv,**kwargs):
        if argv[:3]==["/usr/bin/git","status","--porcelain=v1"]:return subprocess.CompletedProcess(argv,0,b"",b"")
        if argv[:3]==["/usr/bin/git","branch","--show-current"]:return subprocess.CompletedProcess(argv,0,b"main\n",b"")
        if argv[:3]==["/usr/bin/git","rev-parse","HEAD"]:return subprocess.CompletedProcess(argv,0,(commit+"\n").encode(),b"")
        calls.append((argv,kwargs["input"]));job=f"{100+len(calls)}[].zeus-master\n".encode();return subprocess.CompletedProcess(argv,0,job,b"")
    monkeypatch.setattr(namespace["subprocess"],"run",fake_run)
    payload={"campaign":"data/optimization/mot_2d/campaign","commit":commit,"refine_files":files,"chain_key":"f"*64,"screen_digest":screen_digest,"screening_submission_key":screening_key,"nonce":"1"*32}
    monkeypatch.setattr(sys,"argv",["receiver","submit","tal.noa",str(root),base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()])
    namespace["main"]();reply=json.loads(capsys.readouterr().out)
    assert reply["status"]=="submitted" and len(reply["job_ids"])==4
    assert calls[0][0]==["/usr/local/bin/qsub"]
    for index in range(1,4):assert calls[index][0]==["/usr/local/bin/qsub","-W",f"depend=afterok:{100+index}[].zeus-master"]
    assert [data for _,data in calls]==[(campaign/f"jobs/03_refine_round_{i:02d}.pbs").read_bytes() for i in range(1,5)]


@pytest.mark.parametrize("confirmed", range(5))
def test_ambiguous_status_marks_only_the_next_unresolved_round_unknown(tmp_path, monkeypatch, confirmed):
    coordinator=object.__new__(ZeusRefinementSubmissionCoordinator)
    coordinator.root=tmp_path
    ids=tuple(f"{index}[].zeus-master" for index in range(1,confirmed+1))
    state=RemoteChainState("ambiguous","main",ids,None,None)
    manifest={"name":"campaign"}
    profile=ZeusProfile.parse({"username":"tal.noa","project_directory":"/home/tal.noa/ytterbium_lab_simulation_new"})
    campaign=tmp_path/"campaign"
    monkeypatch.setattr(coordinator,"_plan",lambda request:("id",profile,campaign,manifest,"a"*40,{},"d"*64,"b"*64,"c"*64))
    class Transport:
        def inspect(self,**payload):return state
    monkeypatch.setattr(coordinator,"transport_factory",lambda value:Transport(),raising=False)
    result=coordinator.status({})
    states=[row["state"] for row in result["chain"]["rounds"]]
    assert states[:confirmed]==["submitted"]*confirmed
    if confirmed<4:
        assert states[confirmed]=="unknown"
        assert states[confirmed+1:]==["not_submitted"]*(3-confirmed)


@pytest.mark.parametrize("confirmed", (1,2,3))
def test_partial_status_never_attaches_dependencies_to_unsubmitted_rounds(tmp_path,monkeypatch,confirmed):
    coordinator=object.__new__(ZeusRefinementSubmissionCoordinator);coordinator.root=tmp_path
    ids=tuple(f"{index}[].zeus-master" for index in range(1,confirmed+1));state=RemoteChainState("partial","main",ids,None,None)
    profile=ZeusProfile.parse({"username":"tal.noa","project_directory":"/home/tal.noa/ytterbium_lab_simulation_new"});campaign=tmp_path/"campaign";manifest={"name":"campaign"}
    monkeypatch.setattr(coordinator,"_plan",lambda request:("id",profile,campaign,manifest,"a"*40,{},"d"*64,"b"*64,"c"*64))
    class Transport:
        def inspect(self,**payload):return state
    monkeypatch.setattr(coordinator,"transport_factory",lambda value:Transport(),raising=False)
    rounds=coordinator.status({})["chain"]["rounds"]
    assert all(row["depends_on_job_id"] is None for row in rounds[confirmed:])


def _fault_receiver(tmp_path,monkeypatch,round_number,mode):
    source=(Path(__file__).parents[1]/"workflow_api/zeus_refinement_submission_remote.py").read_text().replace(' or project!=f"/home/{username}/ytterbium_lab_simulation_new"','')
    ns={"__name__":"fault_receiver"};exec(compile(source,"<receiver>","exec"),ns)
    root=tmp_path/"repo";campaign=root/"data/optimization/mot_2d/campaign";(campaign/"jobs").mkdir(parents=True);(campaign/"refine").mkdir();state=campaign/".mot_ui/transitions";state.mkdir(parents=True)
    commit="a"*40;names=[*(f"jobs/03_refine_round_{i:02d}.pbs" for i in range(1,5)),"campaign.json","screening_candidates.json","refine/tasks.json","jobs/03_submit_refinement_chain.sh"]
    for i,name in enumerate(names):
        path=campaign/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((json.dumps({"stage":"refine","provenance":{"git_commit":commit}})+"\n").encode() if name=="campaign.json" else f"p{i}\n".encode())
    files={name:hashlib.sha256((campaign/name).read_bytes()).hexdigest() for name in names};payload={"campaign":"data/optimization/mot_2d/campaign","commit":commit,"refine_files":files,"chain_key":"f"*64,"screen_digest":"b"*64,"screening_submission_key":"c"*64,"nonce":"1"*32}
    (state/"refine.json").write_text(json.dumps({"status":"refinement_prepared","nonce":"d"*32,"job_id":"9[].zeus-master","rows_digest":"e"*64,"rows":[],"refine_files":files,"commit":commit,"screening_submission_key":"c"*64,"screen_digest":"b"*64,"completed_unix_s":1}))
    calls=[]
    def run(argv,**kwargs):
        if argv[:3]==["/usr/bin/git","status","--porcelain=v1"]:return subprocess.CompletedProcess(argv,0,b"",b"")
        if argv[:3]==["/usr/bin/git","branch","--show-current"]:return subprocess.CompletedProcess(argv,0,b"main\n",b"")
        if argv[:3]==["/usr/bin/git","rev-parse","HEAD"]:return subprocess.CompletedProcess(argv,0,(commit+"\n").encode(),b"")
        calls.append(argv)
        if len(calls)==round_number and mode=="qsub_timeout":raise subprocess.TimeoutExpired(argv,30)
        return subprocess.CompletedProcess(argv,0,f"{100+len(calls)}[].zeus-master\n".encode(),b"")
    monkeypatch.setattr(ns["subprocess"],"run",run)
    if mode=="after_qsub":
        original=ns["write_record"]
        def write(path,value):
            if path.name==f"refinement_round_{round_number:02d}.json":raise RuntimeError("crash after qsub")
            return original(path,value)
        ns["write_record"]=write
    elif mode=="after_step_receipt":
        original=Path.unlink
        def unlink(path,*args,**kwargs):
            if path.name==f"refinement_round_{round_number:02d}.pending.json":raise RuntimeError("crash after receipt")
            return original(path,*args,**kwargs)
        monkeypatch.setattr(Path,"unlink",unlink)
    encoded=base64.urlsafe_b64encode(json.dumps(payload).encode()).decode();monkeypatch.setattr(sys,"argv",["receiver","submit","tal.noa",str(root),encoded])
    return ns,calls,encoded


@pytest.mark.parametrize("round_number",(1,2,3,4))
@pytest.mark.parametrize("mode",("qsub_timeout","after_qsub","after_step_receipt"))
def test_receiver_crash_or_uncertain_qsub_blocks_every_retry(tmp_path,monkeypatch,capsys,round_number,mode):
    ns,calls,encoded=_fault_receiver(tmp_path,monkeypatch,round_number,mode)
    with pytest.raises((SystemExit,RuntimeError)):ns["main"]()
    attempted=len(calls);capsys.readouterr()
    monkeypatch.setattr(sys,"argv",["receiver","inspect","tal.noa",str(tmp_path/"repo"),encoded])
    ns["main"]();reply=json.loads(capsys.readouterr().out)
    assert reply["status"]=="ambiguous"
    assert len(calls)==attempted
