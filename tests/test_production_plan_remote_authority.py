"""Actual platform drift is accepted only as a closed authenticated remote plan."""
import base64
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from workflow_api.mot_2d_plan import encode_production_plan
from workflow_api.zeus_production import (
    _validated_production_plan, ZeusProductionError, PinnedSshProductionTransport,
    ZeusProductionCoordinator, RemoteSensitivityState,
)

FIXTURE = Path(__file__).parent/'fixtures/production_plan_actual_o16_drift.json'


def fixture(tmp_path):
    source=json.loads(FIXTURE.read_bytes())
    root=tmp_path/'repo';root.mkdir()
    campaign=root/source['payload']['campaign'];campaign.mkdir(parents=True)
    rendered={name:base64.b64decode(row['raw_base64'],validate=True) for name,row in source['rendered'].items()}
    bundle=encode_production_plan(source['payload'],rendered,source['confirmation_rows'],source['sensitivity_rows'])
    return source,root,campaign,rendered,bundle


def validate(parts,bundle=None):
    s,root,campaign,raw,original=parts
    return _validated_production_plan(original if bundle is None else bundle,s['payload'],s['manifest'],campaign,root,s['confirmation_rows'],s['sensitivity_rows'])


def test_genuine_27_field_platform_drift_does_not_require_local_scipy(tmp_path,monkeypatch):
    parts=fixture(tmp_path);s,_,_,rendered,_=parts
    local=base64.b64decode(s['local_summary']['raw_base64']);remote=rendered['sensitivity_summary.json']
    assert hashlib.sha256(remote).hexdigest()==s['rendered']['sensitivity_summary.json']['sha256']
    differences=[]
    def compare(a,b):
        if isinstance(a,dict):
            assert a.keys()==b.keys()
            for key in a:compare(a[key],b[key])
        elif isinstance(a,list):
            assert len(a)==len(b)
            for x,y in zip(a,b):compare(x,y)
        elif a!=b:
            assert type(a)is type(b)is float
            differences.append(abs(a-b))
    compare(json.loads(local),json.loads(remote))
    assert len(differences)==27 and max(differences)<=4.5e-16
    def forbidden(*args,**kwargs):raise AssertionError('Client must not recompute scientific intervals')
    monkeypatch.setattr('workflow_api.mot_2d_late_stage.derive_production_transition',forbidden)
    assert validate(parts)==rendered


@pytest.mark.parametrize('attack',[
    'missing_plan','extra_field','version_bool','wrong_source','wrong_confirmation','wrong_rows',
    'missing_file','extra_file','base64','file_hash','nonfinite','point_parameters','point_offset',
    'point_count','comparison_bool','comparison_difference','selected_parameters','selected_reason',
    'confidence','tasks_seed','pbs_resource','manifest_design','summary_unknown','duplicate_json',
])
def test_actual_remote_plan_tampering_rejected_even_with_rehashed_file(tmp_path,attack):
    parts=fixture(tmp_path);s,root,campaign,rendered,bundle=parts
    b=copy.deepcopy(bundle)
    if attack=='missing_plan':b=None
    elif attack=='extra_field':b['unreviewed']=True
    elif attack=='version_bool':b['version']=True
    elif attack=='wrong_source':b['source_digest']='0'*64
    elif attack=='wrong_confirmation':b['confirmation_rows_digest']='0'*64
    elif attack=='wrong_rows':b['sensitivity_rows_digest']='0'*64
    elif attack=='missing_file':b['files'].pop('campaign.json')
    elif attack=='extra_file':b['files']['jobs/evil.pbs']=b['files']['jobs/06_production.pbs']
    elif attack=='base64':b['files']['campaign.json']['base64']='%%%'
    elif attack=='file_hash':b['files']['campaign.json']['sha256']='0'*64
    else:
        name='sensitivity_summary.json';v=json.loads(rendered[name]);entry=next(iter(v.values()));point=entry['points'][0]
        if attack=='nonfinite':point['comparison_to_reference']['95_ci_half_width_fraction']=float('nan')
        elif attack=='point_parameters':point['parameters']['detuning_gamma']=-9.0
        elif attack=='point_offset':point['offsets']['detuning_gamma']=9.0
        elif attack=='point_count':entry['points'].pop()
        elif attack=='comparison_bool':point['comparison_to_reference']['mean_difference_fraction']=True
        elif attack=='comparison_difference':point['comparison_to_reference']['differences_fraction'][0]=9.0
        elif attack=='selected_parameters':entry['production_selection']['parameters']['detuning_gamma']=-9.0
        elif attack=='selected_reason':entry['production_selection']['selection_reason']='fabricated'
        elif attack=='confidence':entry['production_selection']['familywise_confidence_per_comparison']=.95
        elif attack=='summary_unknown':entry['unreviewed']=True
        elif attack=='tasks_seed':
            name='production/tasks.json';v=json.loads(rendered[name]);v[0]['zeeman_seed']+=1
        elif attack=='manifest_design':
            name='campaign.json';v=json.loads(rendered[name]);v['fixed_design']['final_dt_s']=1.0
        elif attack=='pbs_resource':
            name='jobs/06_production.pbs';v=None
        raw=(rendered[name].replace(b'ncpus=24',b'ncpus=25') if attack=='pbs_resource' else (json.dumps(v,indent=2,sort_keys=True)+'\n').encode())
        if attack=='pbs_resource':assert raw!=rendered[name]
        if attack=='duplicate_json':raw=raw.replace(b'"reference":',b'"reference": {}, "reference":',1)
        b['files'][name]={'sha256':hashlib.sha256(raw).hexdigest(),'base64':base64.b64encode(raw).decode()}
    with pytest.raises(ZeusProductionError,match='remote_response_invalid'):
        _validated_production_plan(b,s['payload'],s['manifest'],campaign,root,s['confirmation_rows'],s['sensitivity_rows'])


def test_transport_requires_explicit_plan_field_and_strict_json():
    transport=object.__new__(PinnedSshProductionTransport);transport.profile=object()
    good={'lifecycle':'running','scheduler':{},'rows':[],'branch':'test','receipt':None,'production_plan':None}
    class Runner:
        def run(self,*args):return SimpleNamespace(returncode=0,stderr=b'',stdout=self.raw)
    runner=Runner();transport.runner=runner
    for raw in [json.dumps({k:v for k,v in good.items() if k!='production_plan'}).encode(),json.dumps(good).replace('"receipt": null','"receipt": null,"receipt": null').encode(),json.dumps(good).replace('"production_plan": null','"production_plan": NaN').encode()]:
        runner.raw=raw
        with pytest.raises(ZeusProductionError):transport.inspect()
    runner.raw=json.dumps(good).encode();assert transport.inspect().production_plan is None


@pytest.mark.parametrize('attack',['short','long','seed','mot_seed','n_input','subset_seed','bool_seed'])
def test_rebound_plan_cannot_hide_unpaired_or_wrong_frozen_replicate_identity(tmp_path,attack):
    parts=fixture(tmp_path);s,root,campaign,rendered,bundle=parts
    rows=copy.deepcopy(s['sensitivity_rows']);rep=rows[0]['evaluation']['replicates']
    if attack=='short':rep.pop()
    elif attack=='long':rep.append(copy.deepcopy(rep[-1]))
    elif attack=='bool_seed':rep[0]['zeeman_seed']=True
    else:rep[0][{'seed':'zeeman_seed'}.get(attack,attack)]+=1
    # Rebind the sender-controlled plan digest, proving rejection is semantic.
    b=encode_production_plan(s['payload'],rendered,s['confirmation_rows'],rows)
    with pytest.raises(ZeusProductionError,match='remote_response_invalid'):
        _validated_production_plan(b,s['payload'],s['manifest'],campaign,root,s['confirmation_rows'],rows)


@pytest.mark.parametrize('stdout,stderr,code',[
    (b'{broken',b'',0),(b'{}',b'',0),(b'{"error":"transition_conflict"}',b'',20),
    (b'{}',b'Unexpected warning',0),
])
def test_write_capable_prepare_response_uncertainty_never_claims_safe_retry(stdout,stderr,code):
    t=object.__new__(PinnedSshProductionTransport);t.profile=object()
    t.runner=SimpleNamespace(run=lambda *args:SimpleNamespace(stdout=stdout,stderr=stderr,returncode=code))
    with pytest.raises(ZeusProductionError,match='transition_outcome_unknown'):t.prepare()


def receiver_coordinator(tmp_path,monkeypatch):
    """Real receiver/publisher and pinned-transport parser; scheduler/source admission mocked.

    Full authenticated source admission is separately exercised by the genuine
    complete protocol. Here the canonical Linux renderer bytes deliberately
    differ from the actual Mac bytes for the exact same captured input rows.
    """
    import contextlib,io,sys
    from workflow_api import zeus_production_remote as remote
    from workflow_api.zeus_snapshot import ZeusProfile
    from workflow_api import mot_2d_plan, mot_2d_validation
    parts=fixture(tmp_path);source,root,campaign,rendered,bundle=parts
    transitions=campaign/'.mot_ui/transitions';transitions.mkdir(parents=True)
    submissions=campaign/'.mot_ui/submissions';submissions.mkdir()
    (campaign/'campaign.json').write_text(json.dumps(source['manifest'],indent=2,sort_keys=True)+'\n')
    transition={'rows':source['confirmation_rows']}
    (transitions/'sensitivity.json').write_text(json.dumps(transition))
    submission={'nonce':source['payload']['sensitivity_submission_nonce'],'job_id':source['payload']['sensitivity_job_id']}
    (submissions/'sensitivity.json').write_text(json.dumps(submission))
    payload=copy.deepcopy(source['payload'])
    payload['sensitivity_transition_digest']=remote.canonical_digest(transition)
    payload['sensitivity_files']={'campaign.json':hashlib.sha256((campaign/'campaign.json').read_bytes()).hexdigest()}
    scheduler={'state':'completed_success','task_count':17,'counts':{'queued':0,'running':0,'held':0,'succeeded':17,'failed':0},'job_id':submission['job_id'],'submission_nonce':submission['nonce']}
    monkeypatch.setattr(remote,'validate_static',lambda p,r:(campaign,remote.read_json(campaign/'campaign.json'),'test',submission,transition))
    monkeypatch.setattr(remote,'inspect_scheduler',lambda *a:copy.deepcopy(scheduler))
    monkeypatch.setattr(mot_2d_validation,'validated_evaluation_outputs',lambda *a:copy.deepcopy(source['sensitivity_rows']))
    monkeypatch.setattr(mot_2d_plan,'render_production_transition',lambda *a:copy.deepcopy(rendered))
    class Runner:
        lost=False
        race=None
        tamper_response=None
        operations=[]
        def run(self,operation,profile,p):
            op=operation.value;self.operations.append(op)
            if op=='prepare' and self.race:self.race()
            stdout=io.StringIO();code=0
            with monkeypatch.context() as mp:
                mp.chdir(root);mp.setattr(sys,'argv',['<production>',op]);mp.setattr(sys,'stdin',io.TextIOWrapper(io.BytesIO(json.dumps(p).encode())))
                with contextlib.redirect_stdout(stdout):
                    try:remote.main()
                    except SystemExit as error:code=error.code
            if self.lost and op=='prepare':return SimpleNamespace(returncode=1,stdout=b'',stderr=b'connection lost')
            wire=stdout.getvalue().encode()
            if self.tamper_response and op=='prepare':wire=self.tamper_response(wire)
            return SimpleNamespace(returncode=code,stdout=wire,stderr=b'')
    runner=Runner();transport=object.__new__(PinnedSshProductionTransport);transport.runner=runner
    profile=ZeusProfile.parse({'username':'tal.noa','project_directory':'/home/tal.noa/ytterbium_lab_simulation_ui_acceptance'});transport.profile=profile
    coord=ZeusProductionCoordinator(root,Path('/usr/bin/ssh'),Path('/usr/bin/git'),clock=lambda:1000,token_factory=lambda:'token',transport_factory=lambda p:transport)
    base=('actual-o16-contract',profile,campaign,source['manifest'],payload['commit'],payload['sensitivity_files'],payload['sensitivity_transition_nonce'],payload['sensitivity_transition_digest'],payload['sensitivity_submission_key'],submission['nonce'],submission['job_id'])
    monkeypatch.setattr(coord,'_base_plan',lambda request,**kw:base)
    monkeypatch.setattr(coord,'_confirmation_rows',lambda request,base:copy.deepcopy(source['confirmation_rows']))
    request={'campaign_id':base[0],'username':'tal.noa','project_directory':profile.project_directory}
    return coord,request,runner,campaign,rendered


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="Actual POSIX receiver integration uses Unix executables and directory fsync; native plan validation remains active")
def test_actual_coordinator_pinned_parser_receiver_prepare_duplicate_and_readonly_recovery(tmp_path,monkeypatch):
    coord,request,runner,campaign,raw=receiver_coordinator(tmp_path,monkeypatch)
    preview=coord.preview(request,session_id='owner');assert preview['job']['task_count']==20
    assert not (campaign/'.mot_ui/transitions/production.json').exists()
    result=coord.confirm({'preview_token':'token'},session_id='owner');assert result['status']=='production_prepared'
    before={p.relative_to(campaign).as_posix():p.read_bytes() for p in campaign.rglob('*') if p.is_file()}
    assert coord.confirm({'preview_token':'token'},session_id='owner')==result
    from workflow_api.preview_registry import PreviewRegistry
    coord._previews = PreviewRegistry()
    assert coord.status(request)['sensitivity']['status']=='production_prepared'
    after={p.relative_to(campaign).as_posix():p.read_bytes() for p in campaign.rglob('*') if p.is_file()}
    assert before==after and runner.operations.count('prepare')==1
    assert all((campaign/name).read_bytes()==data for name,data in raw.items())
    assert not (campaign/'.mot_ui/submissions/production.json').exists()


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="Actual POSIX receiver integration uses Unix executables and directory fsync; native plan validation remains active")
def test_lost_prepare_response_recovers_durable_plan_without_second_prepare(tmp_path,monkeypatch):
    coord,request,runner,campaign,raw=receiver_coordinator(tmp_path,monkeypatch)
    coord.preview(request,session_id='owner');runner.lost=True
    with pytest.raises(ZeusProductionError,match='transition_outcome_unknown'):coord.confirm({'preview_token':'token'},session_id='owner')
    assert (campaign/'.mot_ui/transitions/production.json').exists()
    assert coord.status(request)['sensitivity']['status']=='production_prepared'
    with pytest.raises(ZeusProductionError,match='local_files_changed'):coord.confirm({'preview_token':'token'},session_id='owner')
    assert runner.operations.count('prepare')==1
    assert not (campaign/'.mot_ui/submissions/production.json').exists()


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="Actual POSIX receiver integration uses Unix executables and directory fsync; native plan validation remains active")
def test_locked_source_mutation_blocks_publication(tmp_path,monkeypatch):
    from workflow_api import zeus_production_remote as remote
    coord,request,runner,campaign,raw=receiver_coordinator(tmp_path,monkeypatch)
    coord.preview(request,session_id='owner')
    original=remote.inspect_scheduler;calls=0
    def change_on_locked_read(*args):
        nonlocal calls
        calls+=1
        # Confirm INSPECT, PREPARE initial scheduler, then PREPARE locked scheduler.
        if calls==3:
            transition=campaign/'.mot_ui/transitions/sensitivity.json'
            transition.write_text('{"rows":[]}')
        return original(*args)
    monkeypatch.setattr(remote,'inspect_scheduler',change_on_locked_read)
    # A change before the lock's transition recheck is independently rejected.
    runner.race=lambda:(campaign/'.mot_ui/transitions/sensitivity.json').write_text('{"rows":[]}')
    with pytest.raises(ZeusProductionError):coord.confirm({'preview_token':'token'},session_id='owner')
    assert not (campaign/'.mot_ui/transitions/production.pending.json').exists()
    assert not (campaign/'.mot_ui/transitions/production.json').exists()
    assert not (campaign/'jobs/06_production.pbs').exists()


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="Actual POSIX receiver integration uses Unix executables and directory fsync; native plan validation remains active")
def test_postpublication_plan_validation_failure_requires_unknown_and_readonly_recovery(tmp_path,monkeypatch):
    coord,request,runner,campaign,_=receiver_coordinator(tmp_path,monkeypatch)
    coord.preview(request,session_id='owner')
    def tamper(raw):
        data=json.loads(raw);data['production_plan']['source_digest']='0'*64
        return json.dumps(data).encode()
    runner.tamper_response=tamper
    with pytest.raises(ZeusProductionError,match='transition_outcome_unknown'):
        coord.confirm({'preview_token':'token'},session_id='owner')
    assert (campaign/'.mot_ui/transitions/production.json').exists()
    assert coord.status(request)['sensitivity']['status']=='production_prepared'
    assert runner.operations.count('prepare')==1
    assert not (campaign/'.mot_ui/submissions/production.json').exists()
