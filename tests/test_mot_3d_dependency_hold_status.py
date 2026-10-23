"""Captured PBS begun parents/system dependency holds; no scheduler is contacted."""
from pathlib import Path
from copy import deepcopy
import pytest
from workflow_api import mot_3d_selection_submission_remote as core
from workflow_api import mot_3d_preliminary_submission_remote as preliminary
from workflow_api import mot_3d_preliminary_transition_remote as transition

RAW = (Path(__file__).parent/'fixtures/p45_preliminary_dependency_hold_qstat.txt').read_bytes()
JOBS={'angled_donut':{'array':'4819160[].zeus-master','merge':'4819161.zeus-master'},'single_pass':{'array':'4819162[].zeus-master','merge':'4819163.zeus-master'}}
def outputs(records):
    result={}
    for jobs in JOBS.values():
        for kind,job in jobs.items():
            ids=[job]+([job.replace('[]',f'[{i}]')for i in range(3)]if kind=='array'else[])
            result[job]=''.join('Job Id: '+key+'\n'+''.join(f'    {name} = {value}\n'for name,value in records[key].items())for key in ids if key in records).encode()
    return result
@pytest.fixture(params=['submission','transition'])
def observe(request,monkeypatch):
    def inspect(records):
        raw=outputs(records);calls=[]
        def run(argv,**kwargs):
            assert argv[:4]==['/opt/pbs/bin/qstat','-x','-t','-f'];assert kwargs['limit']==4*1024*1024;calls.append(tuple(argv));return 0,raw[argv[-1]],b''
        monkeypatch.setattr(core,'run',run);monkeypatch.setattr(preliminary,'run',run)
        result=core.scheduler_chain(JOBS)if request.param=='submission'else transition._scheduler(JOBS)
        assert len(calls)==4
        return result
    return inspect

def test_actual_captured_begun_arrays_and_system_hold_are_running(observe):
    records=core.qstat_fields(RAW);before=deepcopy(records)
    assert observe(records)==('running',4,0)
    assert records==before

@pytest.mark.parametrize('hold',['u','o','su','us','n','','unknown'])
def test_manual_mixed_and_unknown_holds_remain_visible(observe,hold):
    records=core.qstat_fields(RAW);records[JOBS['angled_donut']['merge']]['Hold_Types']=hold
    assert observe(records)[0]=='held'

@pytest.mark.parametrize('attack',['foreign','other_family','extra','beforeok','missing','no_server','suspended','exit_nonzero','hold_missing'])
def test_dependency_exemption_is_exact_and_closed(observe,attack):
    records=core.qstat_fields(RAW);row=records[JOBS['angled_donut']['merge']]
    if attack=='foreign':row['depend']='afterok:999[].zeus-master@zeus-master'
    elif attack=='other_family':row['depend']='afterok:4819162[].zeus-master@zeus-master'
    elif attack=='extra':row['depend']+=',afterok:999.zeus-master@zeus-master'
    elif attack=='beforeok':row['depend']=row['depend'].replace('afterok','beforeok')
    elif attack=='missing':row.pop('depend')
    elif attack=='no_server':row['depend']=row['depend'].replace('@zeus-master','')
    elif attack=='suspended':row['job_state']='S'
    elif attack=='exit_nonzero':row['Exit_status']='1'
    else:row.pop('Hold_Types')
    assert observe(records)[0]=='held'

@pytest.mark.parametrize('state,exit_status,expected',[('H',None,'held'),('Z',None,'status_unknown'),('F','1','completed_failed')])
def test_untrusted_or_failed_predecessor_never_suppresses_hold(observe,state,exit_status,expected):
    records=core.qstat_fields(RAW);child=records['4819160[2].zeus-master'];child['job_state']=state
    if exit_status is not None:child['Exit_status']=exit_status
    # A still-held successor keeps the original hold precedence, except failure.
    assert observe(records)[0]==('completed_failed'if expected=='completed_failed'else'held')

@pytest.mark.parametrize('attack',['all_complete','parent_hold','parent_exit','not_array','missing_child','foreign_child','unknown_child','wrong_range','range_missing','parent_hold_missing'])
def test_begun_parent_is_not_global_success_or_unknown_mask(observe,attack):
    records=core.qstat_fields(RAW);parent=records[JOBS['angled_donut']['array']]
    if attack=='all_complete':records['4819160[2].zeus-master'].update(job_state='F',Exit_status='0')
    elif attack=='parent_hold':parent['Hold_Types']='u'
    elif attack=='parent_exit':parent['Exit_status']='1'
    elif attack=='not_array':parent['array']='False'
    elif attack=='wrong_range':parent['array_indices_submitted']='0-99:1'
    elif attack=='range_missing':parent.pop('array_indices_submitted')
    elif attack=='parent_hold_missing':parent.pop('Hold_Types')
    elif attack=='missing_child':records.pop('4819160[2].zeus-master')
    elif attack=='foreign_child':records['999[2].zeus-master']=records.pop('4819160[2].zeus-master')
    else:records['4819160[2].zeus-master']['job_state']='Z'
    assert observe(records)[0]=='held' # No dependency exemption from unknown predecessor.

@pytest.mark.parametrize('field',['Hold_Types','depend'])
def test_folded_critical_hold_fields_rejected(field):
    raw=b'Job Id: 1.zeus-master\n    job_state = H\n    '+field.encode()+b' = s\n        extra\n'
    assert core.qstat_fields(raw)is None

def test_scalar_b_and_unpaired_system_hold_remain_conservative(monkeypatch):
    row=b'Job Id: 1.zeus-master\n    job_state = B\n'
    monkeypatch.setattr(core,'run',lambda *a,**k:(0,row,b''));assert core.scheduler('1.zeus-master','merge')==('status_unknown',0)
    row=b'Job Id: 1.zeus-master\n    job_state = H\n    Hold_Types = s\n    depend = afterok:4819160[].zeus-master@zeus-master\n'
    assert core.scheduler('1.zeus-master','merge')==('held',0)

def test_all_terminal_counts_unchanged(observe):
    records=core.qstat_fields(RAW)
    for row in records.values():row.update(job_state='F',Exit_status='0')
    result=observe(records);assert result[0]in('completed_success','completed_success_unvalidated')and result[1:]==(6,2)

def test_queued_predecessors_report_queued_without_merge_execution(observe):
    records=core.qstat_fields(RAW)
    for job,row in records.items():
        if '['in job and '[]'not in job:row['job_state']='Q';row.pop('Exit_status',None)
    assert observe(records)==('queued',0,0)
