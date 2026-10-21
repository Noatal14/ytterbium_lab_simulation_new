"""Operational new-work guards; canonical historical read contracts stay unchanged."""
import importlib
from types import SimpleNamespace

import pytest

import workflow_api.run_specification as policy
from workflow_api.run_records import RunRecordStore
from workflow_api.run_discovery import inspect_run
from workflow_api.run_execution import IndividualRunExecutionCoordinator, issue_execution_authority
from test_mot_2d_local_execution import _plan as plan2, Engine as Engine2
from test_mot_3d_local_execution import _plan as plan3, Engine as Engine3, _analysis


@pytest.fixture(autouse=True)
def isolated_operational_host_detector(monkeypatch):
    """Only this policy dependency simulates a host; real os.cpu_count is untouched."""
    original = policy.os
    class Host:
        def cpu_count(self): return 16
        def __getattr__(self, name): return getattr(original, name)
    monkeypatch.setattr(policy, "os", Host())


@pytest.mark.parametrize('detected', [None, True, 1.5, 0, -1])
def test_bad_cpu_detector_falls_back_to_one(monkeypatch, detected):
    monkeypatch.setattr(policy, 'os', SimpleNamespace(cpu_count=lambda: detected))
    assert policy.local_worker_maximum(20) == 1


@pytest.mark.parametrize('count,cpus,expected', [(1,16,1),(20,4,4),(1000,512,256),(2,1,1)])
def test_budget_is_per_host_and_particle_count(count,cpus,expected):
    assert policy.local_worker_maximum(count,available_cpus=cpus)==expected


def make_plan(root, monkeypatch, family, *, workers=4, count=None):
    if family=='2d':
        import test_mot_2d_local_execution as f
        original=f._request
        monkeypatch.setattr(f,'_request',lambda source_id,retained=True:{**original(source_id,retained=retained),'npools':workers,**({'particle_count':count}if count is not None else{})})
        return plan2(root)
    import test_mot_3d_local_execution as f
    original=f.build_mot_3d_run_plan
    monkeypatch.setattr(f,'build_mot_3d_run_plan',lambda request,**kwargs:original({**request,'npools':workers},**kwargs))
    return plan3(root,monkeypatch,count=8 if count is None else count)


@pytest.mark.parametrize('family',['2d','3d'])
def test_new_explicit_over_budget_rejected_before_any_source_resolution(tmp_path,monkeypatch,family):
    mod=importlib.import_module(f'workflow_api.mot_{family}_run_plan')
    maximum=lambda count,maximum=256:min(count,maximum,2)
    monkeypatch.setattr(policy,'local_worker_maximum',maximum)
    monkeypatch.setattr(mod,'local_worker_maximum',maximum)
    with pytest.raises(ValueError,match='CPU or particle-count'):
        make_plan(tmp_path,monkeypatch,family,workers=3)
    assert not (tmp_path/'data/runs').exists()


@pytest.mark.parametrize('family',['2d','3d'])
def test_legacy_structural_request_parser_is_not_host_admission(tmp_path,monkeypatch,family):
    mod=importlib.import_module(f'workflow_api.mot_{family}_run_plan')
    plan=make_plan(tmp_path,monkeypatch,family,workers=4)
    # Construct the public request from a real admitted plan, preserving all controls.
    request=vars(plan.request).copy()
    if family=='3d':request['parameters']=dict(request['parameters'])
    request.update(particle_count=1,npools=256)
    assert getattr(mod,f'validate_mot_{family}_run_request')(request).npools==256
    with pytest.raises(ValueError,match='CPU or particle-count'):
        getattr(mod,f'build_mot_{family}_run_plan')(request,repository_root=tmp_path,run_id='legacy-check',git_revision='b'*40,created_utc='2026-10-11T10:00:00+00:00')


@pytest.mark.parametrize('family',['2d','3d'])
def test_start_rejects_authentic_configured_run_without_enqueue_or_byte_change(tmp_path,monkeypatch,family):
    plan=make_plan(tmp_path,monkeypatch,family,workers=4)
    records=plan.storage_records();store=RunRecordStore(tmp_path)
    try:store.create(records["run"],records["configuration"],records["inputs"],records["status"])
    finally:store.close()
    before={str(p.relative_to(tmp_path)):p.read_bytes()for p in tmp_path.rglob('*')if p.is_file()}
    calls=[]
    local=SimpleNamespace(submit=lambda *args:calls.append(args))
    cls=getattr(importlib.import_module(f'workflow_api.mot_{family}_individual_api'),f'IndividualMot{family.upper()}Api')
    api=cls(tmp_path,SimpleNamespace(),local,SimpleNamespace())
    monkeypatch.setattr(policy,'local_worker_maximum',lambda count,maximum=256:1)
    with pytest.raises(ValueError,match='CPU or particle-count'):api.start_local({'run_id':plan.run['run_id']},session_id='owner')
    assert calls==[]
    assert {str(p.relative_to(tmp_path)):p.read_bytes()for p in tmp_path.rglob('*')if p.is_file()}==before


@pytest.mark.parametrize('family',['2d','3d'])
def test_queued_host_reduction_never_invokes_engine_and_publishes_truthful_failure(tmp_path,monkeypatch,family):
    plan=make_plan(tmp_path,monkeypatch,family,workers=4)
    records=plan.storage_records();store=RunRecordStore(tmp_path)
    try:store.create(records["run"],records["configuration"],records["inputs"],records["status"])
    finally:store.close()
    mod=importlib.import_module(f'workflow_api.mot_{family}_local_execution')
    engine=Engine2()if family=='2d'else Engine3()
    cls=getattr(mod,f'Mot{family.upper()}LocalWorker')
    worker=cls(tmp_path,engine=engine,**({'analyzer':_analysis}if family=='3d'else{}))
    monkeypatch.setattr(policy,'local_worker_maximum',lambda count,maximum=256:1)
    coordinator=IndividualRunExecutionCoordinator(tmp_path,worker,issue_execution_authority())
    result=coordinator.execute('mot_'+family,plan.run['run_id'])
    assert result['state']=='failed'
    assert engine.calls==[]
    inspected=inspect_run(tmp_path,'mot_'+family,plan.run['run_id'])
    assert inspected.state=='failed' and inspected.results is None


@pytest.mark.parametrize('family',['2d','3d'])
def test_completed_legacy_high_worker_record_still_reads_on_smaller_host(tmp_path,monkeypatch,family):
    plan=make_plan(tmp_path,monkeypatch,family,workers=4)
    records=plan.storage_records();store=RunRecordStore(tmp_path)
    try:store.create(records["run"],records["configuration"],records["inputs"],records["status"])
    finally:store.close()
    mod=importlib.import_module(f'workflow_api.mot_{family}_local_execution')
    engine=Engine2()if family=='2d'else Engine3()
    worker=getattr(mod,f'Mot{family.upper()}LocalWorker')(tmp_path,engine=engine,**({'analyzer':_analysis}if family=='3d'else{}))
    coordinator=IndividualRunExecutionCoordinator(tmp_path,worker,issue_execution_authority())
    coordinator.execute('mot_'+family,plan.run['run_id'])
    before={str(p.relative_to(tmp_path)):p.read_bytes()for p in tmp_path.rglob('*')if p.is_file()}
    monkeypatch.setattr(policy,'local_worker_maximum',lambda count,maximum=256:1)
    inspected=inspect_run(tmp_path,'mot_'+family,plan.run['run_id'])
    assert inspected.state=='succeeded' and inspected.results is not None
    assert inspected.configuration['resolved']['execution']['workers']==4
    assert {str(p.relative_to(tmp_path)):p.read_bytes()for p in tmp_path.rglob('*')if p.is_file()}==before

@pytest.mark.parametrize('family',['2d','3d'])
@pytest.mark.parametrize('count',[1,8])
def test_omitted_workers_cap_only_new_implicit_default_and_exact_budget_passes(tmp_path,monkeypatch,family,count):
    plan=make_plan(tmp_path,monkeypatch,family,workers=4)
    mod=importlib.import_module(f'workflow_api.mot_{family}_run_plan')
    maximum=lambda n,maximum=256:min(n,maximum,4)
    monkeypatch.setattr(policy,'local_worker_maximum',maximum)
    monkeypatch.setattr(mod,'local_worker_maximum',maximum)
    request=vars(plan.request).copy()
    if family=='3d':request['parameters']=dict(request['parameters'])
    request.update(particle_count=count);request.pop('npools')
    kwargs=dict(repository_root=tmp_path,run_id='at-budget',git_revision='b'*40,created_utc='2026-10-11T10:00:00+00:00')
    result=getattr(mod,f'build_mot_{family}_run_plan')(request,**kwargs)
    assert result.request.npools==min(4,count)
    exact=getattr(mod,f'build_mot_{family}_run_plan')({**request,'npools':min(4,count)},**kwargs)
    assert exact.request.npools==min(4,count)
    assert getattr(mod,f'validate_mot_{family}_run_request')(request).npools==8
    zeus=getattr(mod,f'build_mot_{family}_run_plan')({**request,'execution_mode':'zeus','npools':200},**kwargs)
    assert zeus.request.npools==200


@pytest.mark.parametrize('family',['2d','3d'])
def test_confirmation_revalidates_reduced_host_budget_without_records_or_replay(tmp_path,monkeypatch,family):
    plan=make_plan(tmp_path,monkeypatch,family,workers=4)
    mod=importlib.import_module(f'workflow_api.mot_{family}_run_creation')
    from workflow_api.repository_snapshot import RepositorySnapshot
    snapshots=SimpleNamespace(capture=lambda:RepositorySnapshot('b'*40))
    creator=getattr(mod,f'Mot{family.upper()}RunCreationService')(tmp_path,snapshots,run_id_factory=lambda:'new-budget-run',created_utc_factory=lambda:'2026-10-11T10:00:00+00:00')
    request=vars(plan.request).copy()
    if family=='3d':request['parameters']=dict(request['parameters'])
    preview=creator.preview(request,'owner')
    assert preview['plan']['locked_settings']['workers']==4
    before={str(p.relative_to(tmp_path)):p.read_bytes()for p in tmp_path.rglob('*')if p.is_file()}
    monkeypatch.setattr(policy,'local_worker_maximum',lambda count,maximum=256:1)
    with pytest.raises(ValueError,match='CPU or particle-count'):creator.confirm(preview['preview_token'],'owner')
    with pytest.raises(RuntimeError,match='no longer'):creator.confirm(preview['preview_token'],'owner')
    assert {str(p.relative_to(tmp_path)):p.read_bytes()for p in tmp_path.rglob('*')if p.is_file()}==before
    assert not (tmp_path/'data/runs').exists()

@pytest.mark.parametrize('family',['2d','3d'])
def test_maximum_particle_new_plan_uses_capped_implicit_default(tmp_path,monkeypatch,family):
    from dataclasses import replace
    plan=make_plan(tmp_path,monkeypatch,family)
    mod=importlib.import_module(f'workflow_api.mot_{family}_run_plan')
    source=getattr(mod,f'resolve_individual_mot_{family}_source')(tmp_path,plan.request.source_id)
    # Planner-only resolver seam. No worker or artifact-file validation is claimed here.
    record={**source.records[0],'shape':[1000,6],'survivor_count':1000}
    source=replace(source,pooled_particle_count=1000,records=(record,))
    monkeypatch.setattr(mod,f'resolve_individual_mot_{family}_source',lambda *_:source)
    maximum=lambda n,maximum=256:min(n,maximum,4)
    monkeypatch.setattr(policy,'local_worker_maximum',maximum);monkeypatch.setattr(mod,'local_worker_maximum',maximum)
    request=vars(plan.request).copy()
    if family=='3d':request['parameters']=dict(request['parameters'])
    request.update(particle_count=1000);request.pop('npools')
    result=getattr(mod,f'build_mot_{family}_run_plan')(request,repository_root=tmp_path,run_id='max-count',git_revision='b'*40,created_utc='2026-10-11T10:00:00+00:00')
    assert result.request.npools==4 and result.request.particle_count==1000


@pytest.mark.parametrize('family',['2d','3d'])
def test_legacy_single_particle_eight_worker_completed_package_stays_readable(tmp_path,monkeypatch,family):
    planning=importlib.import_module(f'workflow_api.mot_{family}_run_plan')
    execution=importlib.import_module(f'workflow_api.mot_{family}_local_execution')
    # Explicit historical-admission producer seam ONLY. Actual canonical writers,
    # output validators and every read below remain unpatched.
    with monkeypatch.context() as historical:
        historical.setattr(planning,'require_local_worker_budget',lambda *_args,**_kwargs:None)
        historical.setattr(execution,'require_local_worker_budget',lambda *_args,**_kwargs:None)
        plan=make_plan(tmp_path,historical,family,workers=8,count=1)
        records=plan.storage_records();store=RunRecordStore(tmp_path)
        try:store.create(records['run'],records['configuration'],records['inputs'],records['status'])
        finally:store.close()
        engine=Engine2(survivors=1)if family=='2d'else Engine3()
        worker=getattr(execution,f'Mot{family.upper()}LocalWorker')(tmp_path,engine=engine,**({'analyzer':_analysis}if family=='3d'else{}))
        assert IndividualRunExecutionCoordinator(tmp_path,worker,issue_execution_authority()).execute('mot_'+family,plan.run['run_id'])['state']=='succeeded'
    before={str(p.relative_to(tmp_path)):p.read_bytes()for p in tmp_path.rglob('*')if p.is_file()}
    monkeypatch.setattr(policy,'local_worker_maximum',lambda count,maximum=256:1)
    inspected=inspect_run(tmp_path,'mot_'+family,plan.run['run_id'])
    assert inspected.state=='succeeded' and inspected.results is not None
    assert inspected.configuration['resolved']['execution']['workers']==8
    assert inspected.run['particle_count']==1
    assert {str(p.relative_to(tmp_path)):p.read_bytes()for p in tmp_path.rglob('*')if p.is_file()}==before


def test_native_host_gate_includes_exact_shared_admission_module():
    import ast
    from pathlib import Path
    import re
    script=Path(__file__).resolve().parents[1]/'scripts/check_host_compatibility.py'
    assignment=next(node for node in ast.parse(script.read_text()).body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='PATTERN'for target in node.targets))
    pattern=eval(compile(ast.Expression(assignment.value),'<host-selection-expression>','eval'),{'re':re})
    assert pattern.match('test_mot_local_worker_admission')
    assert not pattern.match('test_mot_local_worker_admission_unrelated')
    assert pattern.match('test_mot_2d_local_execution') and pattern.match('test_mot_3d_run_creation')
    assert not pattern.match('test_screening_prepared_recovery')
