import json
import base64
import hashlib
import sys
import subprocess
import threading
from pathlib import Path

import pytest

from workflow_api.zeus_refinement_submission import (
    MAX_PENDING_PREVIEWS,
    PinnedSshRefinementSubmissionTransport,
    RemoteChainState,
    ZeusRefinementSubmissionCoordinator,
    ZeusRefinementSubmissionError,
)
from workflow_api.zeus_refinement import RefinementInspection, RemoteScreenState
from workflow_api.zeus_snapshot import ZeusProfile


class _CoordinatorTransport:
    def __init__(self):
        self.inspections = []
        self.submissions = []

    def inspect(self, **payload):
        self.inspections.append(payload)
        return RemoteChainState("eligible", "main")

    def submit(self, **payload):
        self.submissions.append(payload)
        return RemoteChainState(
            "submitted",
            "main",
            tuple(f"{index}[].zeus-master" for index in range(1, 5)),
            str(payload["nonce"]),
            100,
        )


def _submission_coordinator(tmp_path, transport, *, clock=lambda: 100.0, token_factory=None):
    campaign = tmp_path / "data/optimization/mot_2d/campaign"
    campaign.mkdir(parents=True, exist_ok=True)
    profile = ZeusProfile.parse({
        "username": "tal.noa",
        "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
    })
    manifest = {"name": "campaign", "s0_values": [1.3]}
    files = {f"artifact-{index}": f"{index:064x}" for index in range(8)}
    coordinator = ZeusRefinementSubmissionCoordinator(
        tmp_path,
        Path(sys.executable),
        Path(sys.executable),
        clock=clock,
        token_factory=token_factory,
        transport_factory=lambda _profile: transport,
    )
    coordinator._plan = lambda _request: (
        "campaign-id", profile, campaign, manifest, "a" * 40, dict(files),
        "b" * 64, "c" * 64, "d" * 64,
    )
    return coordinator


def _submission_request():
    return {
        "campaign_id": "campaign-id",
        "username": "tal.noa",
        "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
    }


def _error_code(call):
    with pytest.raises(ZeusRefinementSubmissionError) as caught:
        call()
    return caught.value.code


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


def test_public_prepared_chain_plan_and_legacy_wrapper_are_exact_and_immutable(tmp_path, monkeypatch):
    executable=Path(sys.executable);coordinator=ZeusRefinementSubmissionCoordinator(tmp_path,executable,executable)
    campaign=tmp_path/"data/optimization/mot_2d/campaign";campaign.mkdir(parents=True)
    profile=ZeusProfile.parse({"username":"tal.noa","project_directory":"/home/tal.noa/ytterbium_lab_simulation_new"})
    manifest={"name":"campaign","s0_values":[1.3]};remote_manifest={"stage":"screen"};rows=({"source":"trial"},)
    canonical=(campaign,manifest,remote_manifest,"a"*40,{}, {},"b"*64,"c"*64)
    state=RemoteScreenState("refinement_prepared","1[].zeus-master","F",0,3,{"queued":0,"running":0,"held":0,"succeeded":3,"failed":0},rows,"main")
    evidence=RefinementInspection("id",profile,canonical,state)
    monkeypatch.setattr("workflow_api.zeus_refinement.ZeusRefinementCoordinator.inspect_evidence",lambda self,request:evidence)
    names=(*("jobs/03_refine_round_%02d.pbs"%i for i in range(1,5)),"campaign.json","screening_candidates.json","refine/tasks.json","jobs/03_submit_refinement_chain.sh")
    rendered={name:(name+"\n").encode() for name in names}
    monkeypatch.setattr("workflow_api.mot_2d_plan.render_refine_transition",lambda *args:rendered)

    public=coordinator.prepare_chain_plan({"campaign_id":"id","username":"tal.noa","project_directory":profile.project_directory})
    legacy=coordinator._plan({"campaign_id":"id","username":"tal.noa","project_directory":profile.project_directory})

    assert legacy==(public.campaign_id,public.profile,public.campaign,public.manifest,public.commit,dict(public.refine_files),public.chain_key,public.screen_digest,public.screening_submission_key)
    assert dict(public.refine_files)=={name:hashlib.sha256(content).hexdigest() for name,content in rendered.items()}
    changed=public.manifest;changed["name"]="mutated";assert public.manifest==manifest
    with pytest.raises(TypeError):public.refine_files["x"]="y"


def test_remote_receiver_revalidates_before_every_qsub_and_binds_receipts():
    source=(Path(__file__).parents[1]/"workflow_api/zeus_refinement_submission_remote.py").read_text()
    assert "current=verify()[index-1]" in source
    assert "record[\"nonce\"]!=receipt_nonce" in source
    assert "job in ids" in source
    assert "verify()\n        response(\"submitted\"" in source


def test_refinement_submission_registry_capacity_boundary_session_and_expiry(tmp_path):
    now = [100.0]
    tokens = iter(f"token-{index}" for index in range(MAX_PENDING_PREVIEWS + 2))
    transport = _CoordinatorTransport()
    coordinator = _submission_coordinator(
        tmp_path,
        transport,
        clock=lambda: now[0],
        token_factory=lambda: next(tokens),
    )
    for _ in range(MAX_PENDING_PREVIEWS):
        coordinator.preview(_submission_request(), session_id="owner")
    assert len(coordinator._previews) == MAX_PENDING_PREVIEWS
    assert _error_code(lambda: coordinator.preview(
        _submission_request(), session_id="owner")) == "too_many_pending_previews"
    assert transport.submissions == []

    now[0] = 400.0
    assert _error_code(lambda: coordinator.preview(
        _submission_request(), session_id="owner")) == "too_many_pending_previews"
    now[0] = 401.0
    preview = coordinator.preview(_submission_request(), session_id="owner")
    token = preview["preview_token"]
    assert token == f"token-{MAX_PENDING_PREVIEWS}"
    assert len(coordinator._previews) == 1
    assert _error_code(lambda: coordinator.confirm(
        {"preview_token": "missing"}, session_id="owner")) == "confirmation_invalid"
    assert _error_code(lambda: coordinator.confirm(
        {"preview_token": token}, session_id="other")) == "confirmation_invalid"
    now[0] = 702.0
    assert _error_code(lambda: coordinator.confirm(
        {"preview_token": token}, session_id="owner")) == "confirmation_expired"
    # Legacy semantics retain an expired token until the next preview prunes it.
    assert coordinator._previews.get(token) is not None
    assert transport.submissions == []
    next_preview = coordinator.preview(_submission_request(), session_id="owner")
    assert next_preview["preview_token"] == f"token-{MAX_PENDING_PREVIEWS + 1}"
    assert coordinator._previews.get(token) is None


def test_refinement_submission_exact_expiry_boundary_and_success_replay(tmp_path):
    now = [100.0]
    transport = _CoordinatorTransport()
    coordinator = _submission_coordinator(
        tmp_path,
        transport,
        clock=lambda: now[0],
        token_factory=lambda: "boundary-token",
    )
    token = coordinator.preview(_submission_request(), session_id="owner")["preview_token"]
    now[0] = 400.0
    first = coordinator.confirm({"preview_token": token}, session_id="owner")
    second = coordinator.confirm({"preview_token": token}, session_id="owner")
    assert first == second
    assert [row["depends_on_job_id"] for row in first["chain"]["rounds"]] == [
        None, "1[].zeus-master", "2[].zeus-master", "3[].zeus-master",
    ]
    assert len(transport.submissions) == 1


def test_refinement_submission_barrier_performs_one_chain_submit(tmp_path):
    transport = _CoordinatorTransport()
    coordinator = _submission_coordinator(
        tmp_path,
        transport,
        token_factory=lambda: "barrier-token",
    )
    token = coordinator.preview(_submission_request(), session_id="owner")["preview_token"]
    barrier = threading.Barrier(9)
    results = []

    def confirm():
        barrier.wait()
        results.append(coordinator.confirm({"preview_token": token}, session_id="owner"))

    threads = [threading.Thread(target=confirm) for _ in range(8)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 8 and all(result == results[0] for result in results)
    assert len(transport.submissions) == 1


@pytest.mark.parametrize("code", [
    "refinement_submission_outcome_unknown",
    "refinement_already_started",
    "remote_response_invalid",
])
def test_refinement_submission_terminal_error_is_never_retried(tmp_path, code):
    class TerminalTransport(_CoordinatorTransport):
        def submit(self, **payload):
            self.submissions.append(payload)
            raise ZeusRefinementSubmissionError(code)

    transport = TerminalTransport()
    coordinator = _submission_coordinator(
        tmp_path,
        transport,
        token_factory=lambda: "terminal-token",
    )
    token = coordinator.preview(_submission_request(), session_id="owner")["preview_token"]
    request = {"preview_token": token}
    assert _error_code(lambda: coordinator.confirm(request, session_id="owner")) == code
    assert _error_code(lambda: coordinator.confirm(request, session_id="owner")) == code
    assert len(transport.submissions) == 1
    record = coordinator._previews.get(token)
    assert record is not None and record.value.terminal_error == code
    assert record.value.nonce == transport.submissions[0]["nonce"]


@pytest.mark.parametrize("code", [
    "refinement_submission_busy",
    "refinement_not_prepared",
    "remote_checkout_mismatch",
    "remote_preparation_invalid",
])
def test_refinement_submission_pre_effect_error_remains_retryable(tmp_path, code):
    class RecoveringTransport(_CoordinatorTransport):
        def submit(self, **payload):
            self.submissions.append(payload)
            if len(self.submissions) == 1:
                raise ZeusRefinementSubmissionError(code)
            return RemoteChainState(
                "submitted", "main",
                tuple(f"{index}[].zeus-master" for index in range(1, 5)),
                str(payload["nonce"]), 100,
            )

    transport = RecoveringTransport()
    coordinator = _submission_coordinator(
        tmp_path,
        transport,
        token_factory=lambda: "retryable-token",
    )
    token = coordinator.preview(_submission_request(), session_id="owner")["preview_token"]
    request = {"preview_token": token}
    assert _error_code(lambda: coordinator.confirm(request, session_id="owner")) == code
    assert coordinator._previews.get(token).value.terminal_error is None
    assert coordinator.confirm(request, session_id="owner")["status"] == "submitted"
    assert len(transport.submissions) == 2
    assert transport.submissions[0]["nonce"] == transport.submissions[1]["nonce"]


@pytest.mark.parametrize("state", [
    RemoteChainState("partial", "main", ("1[].zeus-master", "3[].zeus-master")),
    RemoteChainState("ambiguous", "main", tuple(
        f"{index}[].zeus-master" for index in range(1, 5)
    )),
    RemoteChainState("submitted", "main", (
        "1[].zeus-master", "2[].zeus-master", "2[].zeus-master", "4[].zeus-master",
    ), "a" * 32, 100),
    RemoteChainState("submitted", "main", tuple(
        f"{index}[].zeus-master" for index in range(1, 5)
    ), "f" * 32, 100),
])
def test_refinement_submission_wrong_or_noncontiguous_chain_is_terminal(tmp_path, state):
    class StateTransport(_CoordinatorTransport):
        def submit(self, **payload):
            self.submissions.append(payload)
            return state

    transport = StateTransport()
    coordinator = _submission_coordinator(
        tmp_path,
        transport,
        token_factory=lambda: "bad-chain-token",
    )
    token = coordinator.preview(_submission_request(), session_id="owner")["preview_token"]
    request = {"preview_token": token}
    assert _error_code(lambda: coordinator.confirm(
        request, session_id="owner")) == "refinement_submission_outcome_unknown"
    assert _error_code(lambda: coordinator.confirm(
        request, session_id="owner")) == "refinement_submission_outcome_unknown"
    assert len(transport.submissions) == 1


@pytest.mark.parametrize("status,confirmed", [
    *[("partial", count) for count in range(1, 4)],
    *[("ambiguous", count) for count in range(5)],
])
def test_refinement_submission_every_incomplete_chain_shape_is_terminal(
    tmp_path, status, confirmed,
):
    ids = tuple(f"{index}[].zeus-master" for index in range(1, confirmed + 1))

    class StateTransport(_CoordinatorTransport):
        def submit(self, **payload):
            self.submissions.append(payload)
            return RemoteChainState(status, "main", ids, None, None)

    transport = StateTransport()
    coordinator = _submission_coordinator(
        tmp_path,
        transport,
        token_factory=lambda: "incomplete-token",
    )
    token = coordinator.preview(_submission_request(), session_id="owner")["preview_token"]
    request = {"preview_token": token}
    assert _error_code(lambda: coordinator.confirm(
        request, session_id="owner")) == "refinement_submission_outcome_unknown"
    assert _error_code(lambda: coordinator.confirm(
        request, session_id="owner")) == "refinement_submission_outcome_unknown"
    assert len(transport.submissions) == 1


@pytest.mark.parametrize("timestamp", [True, -1, 253402300800])
def test_refinement_submission_bad_completion_timestamp_is_terminal(tmp_path, timestamp):
    class StateTransport(_CoordinatorTransport):
        def submit(self, **payload):
            self.submissions.append(payload)
            return RemoteChainState(
                "submitted", "main",
                tuple(f"{index}[].zeus-master" for index in range(1, 5)),
                str(payload["nonce"]), timestamp,
            )

    transport = StateTransport()
    coordinator = _submission_coordinator(
        tmp_path,
        transport,
        token_factory=lambda: "timestamp-token",
    )
    token = coordinator.preview(_submission_request(), session_id="owner")["preview_token"]
    request = {"preview_token": token}
    assert _error_code(lambda: coordinator.confirm(
        request, session_id="owner")) == "refinement_submission_outcome_unknown"
    assert _error_code(lambda: coordinator.confirm(
        request, session_id="owner")) == "refinement_submission_outcome_unknown"
    assert len(transport.submissions) == 1


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
