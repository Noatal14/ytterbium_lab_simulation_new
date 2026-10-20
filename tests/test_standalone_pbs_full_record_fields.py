"""Standalone receivers parse genuine PBS field/wrapping shapes conservatively.

The captured J11 record shapes are retained, while closed IDs, array cardinality
and states are deliberately controlled for each receiver. No scheduler is called.
"""
from pathlib import Path
import re
import pytest
from workflow_api import zeus_confirmation_submission_remote as confirmation
from workflow_api import zeus_discovery_submission_remote as discovery
from workflow_api import mot_3d_selection_submission_remote as selection

CAPTURE = Path(__file__).parent / 'fixtures/pbs_sensitivity_mac_live_qstat.txt'
JOB = '4809862[].zeus-master'


def records(count):
    chunks = re.split(rb'(?m)^Job Id: ', CAPTURE.read_bytes())[1:count + 2]
    assert len(chunks) == count + 1
    result = []
    for index, chunk in enumerate(chunks):
        identifier = JOB if index == 0 else f'4809862[{index - 1}].zeus-master'
        _, body = chunk.split(b'\n', 1)
        body = re.sub(rb'(?m)^(    job_state =) .+$', rb'\1 F', body)
        body = re.sub(rb'(?m)^    Exit_status = .*\n', b'', body)
        body = body.rstrip() + b'\n    Exit_status = 0\n\n'
        result.append(b'Job Id: ' + identifier.encode() + b'\n' + body)
    raw = b''.join(result)
    assert b'Resource_List.ncpus' in raw and b'\tPBS_O_' in raw
    # PBS permits digits in site-defined resource field names.
    return raw.replace(b'    Resource_List.mem', b'    resources_used.custom2 = 0\n    Resource_List.mem')


@pytest.fixture(params=['confirmation', 'discovery', 'selection'])
def receiver(request, monkeypatch):
    count = 5 if request.param == 'confirmation' else 3
    if request.param == 'confirmation':
        parse = lambda raw: confirmation.scheduler_state(raw, JOB, count)
    elif request.param == 'discovery':
        parse = lambda raw: discovery.scheduler_state(raw, JOB)
    else:
        def parse(raw):
            def run(argv, **kwargs):
                assert argv == ['/opt/pbs/bin/qstat', '-x', '-t', '-f', JOB]
                return 0, raw, b''
            monkeypatch.setattr(selection, 'run', run)
            return selection.scheduler(JOB, 'array')[0]
    return parse, count


def test_real_pbs_full_record_shape_is_completed(receiver):
    parse, count = receiver
    assert parse(records(count)) == 'completed_success'


@pytest.mark.parametrize('state,exit_status,expected', [
    ('R', None, 'running'), ('Q', None, 'queued'), ('H', None, 'held'),
    ('F', '7', 'completed_failed'), ('F', None, 'status_unknown'),
    ('Z', '0', 'status_unknown'),
])
def test_full_record_state_guards_unchanged(receiver, state, exit_status, expected):
    parse, count = receiver
    raw = records(count)
    child = raw.index(b'Job Id: 4809862[0]')
    head, tail = raw[:child], raw[child:]
    tail = tail.replace(b'    job_state = F', f'    job_state = {state}'.encode(), 1)
    if exit_status is None:
        tail = tail.replace(b'    Exit_status = 0\n', b'', 1)
    else:
        tail = tail.replace(b'    Exit_status = 0', f'    Exit_status = {exit_status}'.encode(), 1)
    assert parse(head + tail) == expected


@pytest.mark.parametrize('attack', [
    'foreign_child', 'missing_child', 'duplicate_record', 'duplicate_state',
    'duplicate_exit', 'malformed_field', 'orphan_continuation', 'critical_continuation',
    'invalid_utf8', 'leading_noise',
])
def test_full_record_attacks_still_fail_closed(receiver, attack):
    parse, count = receiver
    raw = records(count)
    if attack == 'foreign_child':
        raw = raw.replace(b'4809862[0].zeus-master', b'9999999[0].zeus-master')
    elif attack == 'missing_child':
        raw = raw[:raw.rindex(b'Job Id: ')]
    elif attack == 'duplicate_record':
        raw += raw[raw.rindex(b'Job Id: '):]
    elif attack == 'duplicate_state':
        raw = raw.replace(b'    job_state = F', b'    job_state = F\n    job_state = R', 1)
    elif attack == 'duplicate_exit':
        raw = raw.replace(b'    Exit_status = 0', b'    Exit_status = 0\n    Exit_status = 7', 1)
    elif attack == 'malformed_field':
        raw = raw.replace(b'    Resource_List.ncpus', b'    Resource-List.ncpus', 1)
    elif attack == 'orphan_continuation':
        raw = raw.replace(b'\n    Job_Name', b'\n\torphan\n    Job_Name', 1)
    elif attack == 'critical_continuation':
        raw = raw.replace(b'    job_state = F', b'    job_state = F\n\tR', 1)
    elif attack == 'invalid_utf8':
        raw += b'\xff'
    else:
        raw = b'untrusted diagnostics\n' + raw
    assert parse(raw) == 'status_unknown'
