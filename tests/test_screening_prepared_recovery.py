"""Real writer + embedded submit + screening prepare/recovery on temporary roots.

Physical solver/input loading and scheduler/git process results are isolated;
all receipt writers, policy checks, renderers, validators and receivers are real.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_mot_2d_writer_validator_roundtrip import _fixture, _run
from workflow_api.mot_2d_plan import render_campaign_files, render_screen_transition
from workflow_api.mot_2d_smoke import validate_smoke_outputs
from workflow_api import acceptance_remote
from workflow_api import zeus_screening_remote as receiver
from workflow_api.zeus_submission import _REMOTE_SCRIPT


def digest(raw): return hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('operation', ['inspect','prepare'])
@pytest.mark.parametrize('acceptance', [False, True])
@pytest.mark.parametrize('mutation', [None,'manifest','receipt','missing_receipt','input','transition_file','later_stage','later_mutated_predecessor','manifest_whitespace'])
def test_actual_prepare_then_inspect_is_exact_and_read_only(tmp_path, monkeypatch, capsys, acceptance, mutation, operation):
    project=tmp_path/'home/tal.noa'/('ytterbium_lab_simulation_ui_acceptance' if acceptance else 'ytterbium_lab_simulation_new')
    project.mkdir(parents=True)
    campaign,manifest=_fixture(project,monkeypatch,acceptance)
    initial=render_campaign_files(manifest,campaign,project)
    for name,raw in initial.items():
        target=campaign/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    prepared={}
    for seed in range(3000,3035):
        for suffix in ('npy','json'):
            target=project/manifest['ensemble_source']['directory']/f'production_zeeman_seed{seed}.{suffix}'
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(f'frozen-{seed}-{suffix}'.encode())
            prepared[target.relative_to(project).as_posix()]=digest(target.read_bytes())
    relative=campaign.relative_to(project).as_posix()
    prepared.update({relative+'/'+name:digest(raw) for name,raw in initial.items()})
    assert len(prepared)==72
    commit='a'*40
    key=digest(json.dumps({'campaign':relative,'commit':commit,'manifest':prepared[relative+'/campaign.json'],'pbs':prepared[relative+'/jobs/01_smoke.pbs']},sort_keys=True,separators=(',',':')).encode())
    original_authorize=acceptance_remote.assert_campaign_target
    def authorize(value,user,root,target=None):
        if Path(root)==project:
            target=target if isinstance(target,str) and target.startswith('data/') else Path(target).relative_to(project).as_posix()
            return original_authorize(value,user,'/home/'+user+'/'+project.name,target)
        return original_authorize(value,user,root,target)
    monkeypatch.setattr(acceptance_remote,'assert_campaign_target',authorize)
    calls=[]
    def process(argv,**kwargs):
        calls.append(tuple(argv))
        if argv[0]=='/usr/local/bin/qsub': return subprocess.CompletedProcess(argv,0,b'12345.zeus-master\n',b'')
        if Path(argv[0]).name=='git':
            value=(commit+'\n') if 'rev-parse' in argv else 'main\n' if 'branch' in argv else ''
            return subprocess.CompletedProcess(argv,0,value if kwargs.get('text') else value.encode(),'' if kwargs.get('text') else b'')
        if Path(argv[0]).name=='qstat': return subprocess.CompletedProcess(argv,0,'Job Id: 12345.zeus-master\n    job_state = F\n    Exit_status = 0\n','')
        raise AssertionError(argv)
    monkeypatch.setattr(subprocess,'run',process)
    request={'files':prepared,'campaign':relative,'job_file':relative+'/jobs/01_smoke.pbs','commit':commit,'submission_key':key,'nonce':'1'*32}
    monkeypatch.setattr(sys,'argv',['receiver','submit','tal.noa',str(project),base64.urlsafe_b64encode(json.dumps(request).encode()).decode()])
    embedded=_REMOTE_SCRIPT.replace("home=pathlib.Path('/home')/username",'home=project.parent')
    embedded=embedded.replace('assert_campaign_target(manifest,username,project,campaign_path)',"assert_campaign_target(manifest,username,'/home/'+username+'/'+project.name,campaign_pure.as_posix())")
    exec(compile(embedded,'<actual-embedded-smoke>','exec'),{'__name__':'__main__'})
    submitted=json.loads(capsys.readouterr().out.splitlines()[-1]);assert submitted['status']=='submitted'
    assert sum(Path(row[0]).name=='qsub' for row in calls)==1
    _run(campaign,manifest,'smoke')
    # The writer test helper serializes its fixture manifest; real workers do
    # not change the frozen campaign file. Preserve its original exact bytes.
    (campaign/'campaign.json').write_bytes(initial['campaign.json'])
    capsys.readouterr()
    points=validate_smoke_outputs(campaign,manifest)
    transition=render_screen_transition(manifest,campaign,project)
    payload={'campaign':relative,'commit':commit,'prepared_files':prepared,'submission_key':key,'transition_files':{name:digest(raw) for name,raw in transition.items()}}
    original_path=Path
    monkeypatch.setattr(receiver,'Path',lambda value:project.parent.parent if value=='/home' else original_path(value))
    def invoke(operation,body):
        monkeypatch.setattr(sys,'argv',['receiver',operation,'tal.noa',str(project),base64.urlsafe_b64encode(json.dumps(body).encode()).decode()])
        receiver.main()
        return json.loads(capsys.readouterr().out.splitlines()[-1])
    prepared_state=invoke('prepare',{**payload,'smoke_digest':digest(json.dumps(points,sort_keys=True).encode()),'nonce':'2'*32})
    assert prepared_state['lifecycle']=='screen_prepared'
    for name,raw in transition.items(): assert (campaign/name).read_bytes()==raw
    receipt=campaign/'.mot_ui/transitions/screen.json'
    later=mutation in {'later_stage','later_mutated_predecessor'}
    if later:
        # Controlled manifest fixture for the historical read-only boundary;
        # the separate full protocol chain exercises real later-stage writers.
        value=json.loads((campaign/'campaign.json').read_text())
        value['stage']='refine';value.setdefault('stages',{})['refine']={'fixture':'later stage'}
        if mutation=='later_mutated_predecessor':value['name']='altered'
        (campaign/'campaign.json').write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    if mutation=='manifest_whitespace':
        target=campaign/'campaign.json';target.write_bytes(target.read_bytes()+b' ')
    elif mutation=='manifest':
        value=json.loads((campaign/'campaign.json').read_text());value['name']='altered';(campaign/'campaign.json').write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    elif mutation=='receipt':
        value=json.loads(receipt.read_text());value['commit']='b'*40;receipt.write_text(json.dumps(value))
    elif mutation=='missing_receipt': receipt.unlink()
    elif mutation=='input':
        name=next(name for name in prepared if name.endswith('.npy'));(project/name).write_bytes(b'changed')
    elif mutation=='transition_file': (campaign/'screen/tasks.json').write_bytes(b'[]')
    before={path.relative_to(campaign).as_posix():path.read_bytes() for path in campaign.rglob('*') if path.is_file()}
    scheduler_before=len(calls)
    recovery_payload=payload if operation=='inspect' else {**payload,'smoke_digest':digest(json.dumps(points,sort_keys=True).encode()),'nonce':'2'*32}
    if mutation and not (mutation=='later_stage' and operation=='inspect'):
        with pytest.raises(SystemExit) as blocked: invoke(operation,recovery_payload)
        assert blocked.value.code==20
        error=json.loads(capsys.readouterr().out.splitlines()[-1])
        assert error['error'] in {'remote_preparation_invalid','transition_conflict','transition_outcome_unknown','campaign_not_smoke'}
    else:
        recovered=invoke(operation,recovery_payload)
        assert recovered['lifecycle']=='screen_prepared'
        assert recovered['points']==points and recovered['artifact_count']==3
    after={path.relative_to(campaign).as_posix():path.read_bytes() for path in campaign.rglob('*') if path.is_file()}
    assert after==before
    assert all(Path(row[0]).name not in {'qsub','qstat'} for row in calls[scheduler_before:])
    assert sum(Path(row[0]).name=='qsub' for row in calls)==1
