"""Unmodified read-only PBS captures from the two owned TESTONLY J11 arrays."""
from pathlib import Path
import pytest
from workflow_api.zeus_sensitivity_submission_remote import scheduler_state as sensitivity_state
from workflow_api.zeus_production_submission_remote import scheduler_state as production_state

FIXTURES=Path(__file__).parent/'fixtures'

@pytest.mark.parametrize('parser',[sensitivity_state,production_state],ids=['sensitivity','production'])
@pytest.mark.parametrize('name,job_id',[
    ('pbs_sensitivity_mac_live_qstat.txt','4809461[].zeus-master'),
    ('pbs_sensitivity_windows_live_qstat.txt','4809468[].zeus-master'),
])
def test_actual_pbs_dotted_fields_preserve_running_authority(parser,name,job_id):
    raw=(FIXTURES/name).read_bytes()
    assert raw.count(b'Job Id: ')==18
    assert b'Resource_List.mem = 8gb' in raw
    assert parser(raw,job_id,17)=='running'
    other=next(path for path in FIXTURES.glob('pbs_sensitivity_*_live_qstat.txt') if path.name!=name).read_bytes()
    assert parser(raw+other,job_id,17)=='status_unknown'
    assert parser(raw+raw,job_id,17)=='status_unknown'
    assert parser(raw,job_id,18)=='status_unknown'
