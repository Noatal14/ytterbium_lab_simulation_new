"""Actual PBS per-record dependency grammar, with a captured test-job response."""
from pathlib import Path
import pytest
from workflow_api.zeus_confirmation_remote import parse_round
from workflow_api.zeus_snapshot import _parse_qstat

RAW=(Path(__file__).parent/'fixtures/pbs_refinement_round2_qstat.txt').read_text()
IDS=[f'{4809119+i}[].zeus-master' for i in range(4)]

def test_actual_folded_parent_and_children_dependencies_are_not_global_duplicates():
    row,unknown=parse_round(RAW,IDS[1],3,2,IDS,_parse_qstat)
    assert row['scheduler']=={'state':'queued','task_count':3,'counts':{'queued':3,'running':0,'held':0,'succeeded':0,'failed':0}}
    assert unknown is False

@pytest.mark.parametrize('index',[1,2,3,4])
def test_every_round_validates_its_own_predecessor_and_optional_successor(index):
    dependency=[]
    if index>1:dependency.append('afterok:'+IDS[index-2]+'@zeus-master')
    if index<4:dependency.append('beforeok:'+IDS[index]+'@zeus-master')
    prefix=IDS[index-1].split('[]')[0]
    raw=''.join(f'Job Id: {prefix}[{child}].zeus-master\n    job_state = R\n'+('    depend = '+',\n\t'.join(dependency)+'\n' if dependency else '') for child in range(3))
    row,_=parse_round(raw,IDS[index-1],3,index,IDS,_parse_qstat)
    assert row['scheduler']['state']=='running'
    assert row['scheduler']['counts']['running']==3

@pytest.mark.parametrize('bad',[
    lambda s:s.replace('afterok:4809119[]','afterok:999[]',1),
    lambda s:s.replace('beforeok:4809121[]','beforeok:999[]',1),
    lambda s:s.replace('afterok:4809119[].zeus-master@zeus-master,\n\t','',1),
    lambda s:s.replace('beforeok:','afterany:',1),
    lambda s:s.replace('beforeok:4809121[].zeus-master@zeus-master','beforeok:4809121[].zeus-master@foreign',1),
    lambda s:s.replace('beforeok:4809121[].zeus-master@zeus-master','beforeok:4809121[].zeus-master@zeus-master,',1),
    lambda s:s.replace('beforeok:4809121[].zeus-master@zeus-master','afterok:4809119[].zeus-master@zeus-master',1),
])
def test_missing_foreign_or_malformed_record_dependency_is_closed(bad):
    with pytest.raises(ValueError,match='dependency'):parse_round(bad(RAW),IDS[1],3,2,IDS,_parse_qstat)


def _captured_arrays():
    import re
    raw=(Path(__file__).parent/'fixtures/pbs_refinement_eight_arrays_qstat.txt').read_text()
    records=re.split(r'(?=^Job Id:)',raw,flags=re.MULTILINE)
    groups={}
    for record in records:
        if not record.strip():continue
        identifier=record.splitlines()[0].split(':',1)[1].strip()
        prefix=identifier.split('[')[0]
        groups[prefix]=groups.get(prefix,'')+record
    return groups


def test_actual_two_known_chains_accept_released_dependency_absence_without_false_completion():
    arrays=_captured_arrays()
    observed=[]
    for first in (4809119,4809134):
        ids=[f'{first+i}[].zeus-master' for i in range(4)]
        previous=None
        for index,job in enumerate(ids,1):
            row,_=parse_round(arrays[job.split('[')[0]],job,3,index,ids,_parse_qstat,dependency_receipts_verified=True,predecessor_completed=previous=='completed_success')
            previous=row['scheduler']['state']
            observed.append(previous)
    assert observed==['completed_success','running','queued','queued','running','queued','queued','queued']


@pytest.mark.parametrize('state',['R','F'])
def test_removed_afterok_requires_verified_durable_chain(state):
    raw=''.join(f'Job Id: 4809120[{i}].zeus-master\n    job_state = {state}\n'+('    Exit_status = 0\n' if state=='F' else '') for i in range(3))
    with pytest.raises(ValueError,match='dependency'):parse_round(raw,IDS[1],3,2,IDS,_parse_qstat)
    row,_=parse_round(raw,IDS[1],3,2,IDS,_parse_qstat,dependency_receipts_verified=True,predecessor_completed=True)
    assert row['scheduler']['state']==('running' if state=='R' else 'completed_success')


@pytest.mark.parametrize('state',['Q','H','?'])
def test_missing_dependency_requires_independently_successful_predecessor(state):
    raw=''.join(f'Job Id: 4809120[{i}].zeus-master\n    job_state = {state}\n' for i in range(3))
    with pytest.raises(ValueError,match='dependency'):parse_round(raw,IDS[1],3,2,IDS,_parse_qstat,dependency_receipts_verified=True)


def test_foreign_dependency_is_rejected_even_after_release_with_receipts():
    raw=''.join(f'Job Id: 4809120[{i}].zeus-master\n    job_state = R\n    depend = afterok:999[].zeus-master\n' for i in range(3))
    with pytest.raises(ValueError,match='dependency'):parse_round(raw,IDS[1],3,2,IDS,_parse_qstat,dependency_receipts_verified=True,predecessor_completed=True)


@pytest.mark.parametrize('previous',['running','completed_failed','queued','held'])
def test_mixed_running_queued_released_array_requires_successful_predecessor(previous):
    raw='Job Id: 4809120[].zeus-master\n    job_state = B\n'+''.join(f'Job Id: 4809120[{i}].zeus-master\n    job_state = {"R" if i==0 else "Q"}\n' for i in range(3))
    with pytest.raises(ValueError,match='dependency'):
        parse_round(raw,IDS[1],3,2,IDS,_parse_qstat,dependency_receipts_verified=True,predecessor_completed=previous=='completed_success')
    row,_=parse_round(raw,IDS[1],3,2,IDS,_parse_qstat,dependency_receipts_verified=True,predecessor_completed=True)
    assert row['scheduler']['state']=='running'
    assert row['scheduler']['counts']=={'queued':2,'running':1,'held':0,'succeeded':0,'failed':0}


def test_predecessor_success_alone_never_authorizes_missing_dependency_without_receipts():
    raw=''.join(f'Job Id: 4809120[{i}].zeus-master\n    job_state = Q\n' for i in range(3))
    with pytest.raises(ValueError,match='dependency'):
        parse_round(raw,IDS[1],3,2,IDS,_parse_qstat,predecessor_completed=True)
