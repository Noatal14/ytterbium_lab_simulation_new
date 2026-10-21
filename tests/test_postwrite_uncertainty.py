"""Write-response ambiguity never authorizes retry; no network or real scheduler."""
import importlib
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

CASES = [
    ('screening', 'Screening', 'prepare', 'transition_outcome_unknown'),
    ('refinement', 'Refinement', 'prepare', 'transition_outcome_unknown'),
    ('confirmation', 'Confirmation', 'prepare', 'transition_outcome_unknown'),
    ('sensitivity', 'Sensitivity', 'prepare', 'transition_outcome_unknown'),
    ('production', 'Production', 'prepare', 'transition_outcome_unknown'),
    ('finalization', 'Finalization', 'finalize', 'finalization_outcome_unknown'),
]


@pytest.mark.parametrize('module,label,operation,code', CASES)
@pytest.mark.parametrize('failure', ['nonzero', 'stderr', 'json', 'null', 'list', 'schema', 'timeout', 'process', 'unexpected'])
def test_write_dispatch_invalid_response_is_unknown(module, label, operation, code, failure):
    from workflow_api.pinned_ssh import PinnedSshProcessError
    mod = importlib.import_module('workflow_api.zeus_' + module)
    transport = object.__new__(getattr(mod, 'PinnedSsh' + label + 'Transport'))
    transport.profile = object()
    class Runner:
        def run(self, *args):
            if failure == 'unexpected': raise ValueError('unexpected response decoding failure')
            if failure == 'timeout': raise subprocess.TimeoutExpired('fixed SSH', 1)
            if failure == 'process': raise PinnedSshProcessError('bounded transport failed')
            return SimpleNamespace(returncode=1 if failure == 'nonzero' else 0,
                                   stderr=b'error' if failure == 'stderr' else b'',
                                   stdout={'json': b'{', 'null': b'null', 'list': b'[]', 'schema': b'{"unexpected":1}'}.get(failure, b'{}'))
    transport.runner = Runner()
    with pytest.raises(getattr(mod, 'Zeus' + label + 'Error'), match=code):
        getattr(transport, operation)(campaign='closed')


@pytest.mark.parametrize('module,label,operation,code', CASES[:5] + CASES[5:])
def test_read_parse_failure_is_not_write_unknown(module, label, operation, code):
    mod = importlib.import_module('workflow_api.zeus_' + module)
    transport = object.__new__(getattr(mod, 'PinnedSsh' + label + 'Transport'))
    transport.profile = object()
    transport.runner = SimpleNamespace(run=lambda *args: SimpleNamespace(returncode=0, stderr=b'', stdout=b'{'))
    with pytest.raises(getattr(mod, 'Zeus' + label + 'Error'), match='remote_response_invalid'):
        transport.inspect(campaign='closed')


@pytest.mark.skipif(os.name == 'nt', reason='Actual remote receiver performs POSIX directory-fsync publication')
@pytest.mark.parametrize('failure', ['lost', 'malformed', 'schema'])
def test_real_finalization_publication_then_invalid_reply_recovers_readonly_without_rewrite(tmp_path, monkeypatch, failure):
    from tests.test_finalization import _remote_finalization_fixture, _run_finalization_receiver, _finalization_prepare_request
    from workflow_api.zeus_finalization import PinnedSshFinalizationTransport, ZeusFinalizationError
    root, campaign, _, _, request = _remote_finalization_fixture(tmp_path)
    preview = json.loads(_run_finalization_receiver(root, 'inspect', request).stdout)
    prepared = _finalization_prepare_request(request, preview)
    operations = []
    class Runner:
        def run(self, operation, profile, payload):
            op = operation.value
            operations.append(op)
            result = _run_finalization_receiver(root, op, payload)
            assert result.returncode == 0, result.stderr
            if op == 'prepare':
                return SimpleNamespace(returncode=1 if failure == 'lost' else 0, stderr=b'',
                                       stdout=b'' if failure == 'lost' else b'{' if failure == 'malformed' else b'{}')
            return result
    transport = object.__new__(PinnedSshFinalizationTransport)
    transport.profile = object(); transport.runner = Runner()
    from workflow_api.zeus_finalization import ZeusFinalizationCoordinator
    from workflow_api.zeus_snapshot import ZeusProfile
    profile = ZeusProfile.parse({'username':'tal.noa','project_directory':'/home/tal.noa/ytterbium_lab_simulation_new'})
    executable = tmp_path / 'unused-executable'; executable.touch()
    coordinator = ZeusFinalizationCoordinator(root, executable, executable,
        clock=lambda:1000, token_factory=lambda:'token', transport_factory=lambda _:transport)
    manifest = json.loads((campaign/'campaign.json').read_bytes())
    monkeypatch.setattr(coordinator, '_base_plan', lambda _:('real-finalization',profile,campaign,manifest,request['commit']))
    public_request = {'campaign_id':'real-finalization','username':'tal.noa','project_directory':profile.project_directory}
    coordinator.preview(public_request, session_id='owner')
    with pytest.raises(ZeusFinalizationError, match='finalization_outcome_unknown'):
        coordinator.confirm({'preview_token':'token'}, session_id='owner')
    assert (campaign / '.mot_ui/transitions/finalization.json').is_file()
    before = {p.relative_to(campaign).as_posix(): p.read_bytes() for p in campaign.rglob('*') if p.is_file()}
    assert coordinator.status(public_request)['production']['status'] == 'campaign_complete'
    assert coordinator.status(public_request)['production']['status'] == 'campaign_complete'
    with pytest.raises(ZeusFinalizationError, match='remote_files_changed'):
        coordinator.confirm({'preview_token':'token'}, session_id='owner')
    after = {p.relative_to(campaign).as_posix(): p.read_bytes() for p in campaign.rglob('*') if p.is_file()}
    assert before == after and operations.count('prepare') == 1


@pytest.mark.parametrize('failure', ['state', 'receipt', 'exception'])
def test_finalization_coordinator_postdispatch_validation_is_unknown_and_readonly_recovers(tmp_path, monkeypatch, failure):
    from workflow_api.zeus_finalization import ZeusFinalizationCoordinator, ZeusFinalizationError
    from workflow_api.zeus_snapshot import ZeusProfile
    from tests.test_finalization import _Transport
    root = tmp_path / 'repo'; root.mkdir()
    campaign = root / 'data/optimization/mot_2d/campaign'; campaign.mkdir(parents=True)
    ssh = tmp_path / 'ssh'; ssh.touch()
    git = tmp_path / 'git'; git.touch()
    profile = ZeusProfile.parse({'username':'tal.noa', 'project_directory':'/home/tal.noa/ytterbium_lab_simulation_new'})
    transport = _Transport()
    coordinator = ZeusFinalizationCoordinator(root, ssh, git, clock=lambda:1000,
        token_factory=lambda:'token', transport_factory=lambda _:transport)
    manifest = {'name':'Campaign', 's0_values':[1.3], 'stages':{}}
    monkeypatch.setattr(coordinator, '_base_plan', lambda _:('campaign-id',profile,campaign,manifest,'d'*40))
    request = {'campaign_id':'campaign-id','username':'tal.noa','project_directory':profile.project_directory}
    coordinator.preview(request, session_id='owner')
    original = transport.finalize
    def invalid_reply(**payload):
        state = original(**payload)
        if failure == 'exception': raise ValueError('reply decoding failed')
        from dataclasses import replace
        return replace(state, lifecycle='invalid') if failure == 'state' else replace(state, receipt={})
    transport.finalize = invalid_reply
    with pytest.raises(ZeusFinalizationError, match='finalization_outcome_unknown'):
        coordinator.confirm({'preview_token':'token'},session_id='owner')
    assert transport.finalizes == 1
    assert coordinator.status(request)['production']['status'] == 'campaign_complete'
    with pytest.raises(ZeusFinalizationError, match='remote_files_changed'):
        coordinator.confirm({'preview_token':'token'},session_id='owner')
    assert transport.finalizes == 1
    with pytest.raises(ZeusFinalizationError, match='confirmation_invalid'):
        coordinator.confirm({'preview_token':'unknown'},session_id='owner')
    assert transport.finalizes == 1


@pytest.mark.parametrize('module,label,operation,code', CASES)
def test_known_coordinator_presend_validation_is_preserved(module, label, operation, code):
    mod = importlib.import_module('workflow_api.zeus_' + module)
    coordinator = object.__new__(getattr(mod, 'Zeus' + label + 'Coordinator'))
    # No transport or preview registry exists: invalid request must fail first.
    with pytest.raises(getattr(mod, 'Zeus' + label + 'Error'), match='request_invalid'):
        coordinator.confirm({}, session_id='owner')
