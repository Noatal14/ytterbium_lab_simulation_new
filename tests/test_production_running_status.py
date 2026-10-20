"""Coordinator-only transport fixtures: monitor committed work without authority to prepare."""
from types import SimpleNamespace
import pytest
from workflow_api.zeus_production import ZeusProductionCoordinator, ZeusProductionError, RemoteSensitivityState
from workflow_api.zeus_sensitivity_submission import ZeusSensitivitySubmissionCoordinator
from workflow_api.zeus_snapshot import ZeusProfile

@pytest.mark.parametrize('submission,lifecycle,scheduler_state,count_key',[
    ('queued','queued','queued','queued'),
    ('running','running','running','running'),
    ('held','held','held','held'),
    ('completed_failed','failed','completed_failed','failed'),
    ('status_unknown','status_unknown','unknown',None),
])
def test_committed_sensitivity_can_be_monitored_but_not_prepared(tmp_path,monkeypatch,submission,lifecycle,scheduler_state,count_key):
    root=tmp_path/'repo';root.mkdir();campaign=root/'data/optimization/mot_2d/campaign';campaign.mkdir(parents=True)
    executable=tmp_path/'executable';executable.touch()
    profile=ZeusProfile.parse({'username':'tal.noa','project_directory':'/home/tal.noa/ytterbium_lab_simulation_new'})
    manifest={'name':'Campaign','s0_values':[1.3],'stages':{'sensitivity':{'tasks':17}}}
    plan=('campaign-id',profile,campaign,manifest,'a'*40,{'campaign.json':'1'*64},'2'*32,'3'*64,'4'*64)
    durable=SimpleNamespace(status=submission,job_id='123[].zeus-master',nonce='b'*32)
    monkeypatch.setattr(ZeusSensitivitySubmissionCoordinator,'_plan',lambda self,request:plan)
    monkeypatch.setattr(ZeusSensitivitySubmissionCoordinator,'_remote',lambda self,*args:(SimpleNamespace(status=lambda **kwargs:durable),{}))
    counts=dict.fromkeys(['queued','running','held','succeeded','failed'],0)
    if count_key:counts[count_key]=17
    scheduler={'state':scheduler_state,'task_count':17,'counts':counts,'job_id':durable.job_id,'submission_nonce':durable.nonce}
    calls=[]
    def inspect(**payload):
        calls.append(payload)
        return RemoteSensitivityState(lifecycle,scheduler,(),'main',None)
    transport=SimpleNamespace(inspect=inspect,prepare=lambda **kwargs:pytest.fail('Monitoring must not prepare'))
    coordinator=ZeusProductionCoordinator(root,executable,executable,transport_factory=lambda p:transport)
    monkeypatch.setattr(coordinator,'_confirmation_rows',lambda *args:pytest.fail('No output rendering before completion'))
    result=coordinator.status({})
    assert result['sensitivity']['status']==lifecycle
    assert result['validation']=={'status':'not_ready','completed_points':0,'expected_points':17}
    assert result['next_action']=='wait'
    assert result['sensitivity']['job_id']==durable.job_id
    assert calls[0]['sensitivity_submission_nonce']==durable.nonce
    assert calls[0]['sensitivity_job_id']==durable.job_id
    with pytest.raises(ZeusProductionError,match='sensitivity_not_complete'):
        coordinator.preview({},session_id='session')
    assert len(calls)==1
    for missing in ['job_id','nonce']:
        old=getattr(durable,missing);setattr(durable,missing,None)
        with pytest.raises(ZeusProductionError,match='sensitivity_not_complete'):
            coordinator.status({})
        setattr(durable,missing,old)
    for uncommitted in ['eligible','ambiguous']:
        durable.status=uncommitted
        with pytest.raises(ZeusProductionError,match='sensitivity_not_complete'):
            coordinator.status({})
