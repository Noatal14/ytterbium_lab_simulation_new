"""Genuine P45 summary-only fixture; no tokens, paths, job IDs, or invented outcomes."""
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from studies.mot_3d.refinement.select import DuplicateRefinementPointError, select_from_summary
from workflow_api import mot_3d_preliminary_transition as local
from workflow_api import mot_3d_preliminary_transition_remote as remote
from workflow_api.preview_registry import PreviewRegistry
from tests.test_mot_3d_preliminary_transition_remote import _harness, _invoke
from tests.test_mot_3d_preliminary_transition_local import fixture, NOW


def summaries():
    return json.loads((Path(__file__).parent / 'fixtures/p45-preliminary-boundary-summaries.json').read_bytes())


def test_genuine_boundary_summary_preserves_design_rejection():
    captured = summaries()
    assert len(select_from_summary('angled_donut', captured['angled_donut'])['candidates']) == 16
    with pytest.raises(DuplicateRefinementPointError, match='crossing_z_upstream'):
        select_from_summary('single_pass', captured['single_pass'])


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX receiver directory descriptors')
@pytest.mark.parametrize('operation', ['inspect', 'status', 'prepare'])
def test_genuine_duplicate_rejected_before_ready_or_any_publication(tmp_path, monkeypatch, capsys, operation):
    root, campaign, payload = _harness(tmp_path, monkeypatch)
    from studies.mot_3d_campaign import render_refinement_transition
    monkeypatch.setattr(remote, 'render_refinement_transition', render_refinement_transition)
    monkeypatch.setattr(remote, '_capture', lambda *_: (
        {'stage': 'preliminary_check'}, {}, SimpleNamespace(summaries=summaries(), evidence_sha256='e'*64)))
    before = {p.relative_to(campaign).as_posix(): p.read_bytes() for p in campaign.rglob('*') if p.is_file()}
    with pytest.raises(SystemExit) as error:
        _invoke(monkeypatch, root, (dict(payload, nonce='1'*32) if operation == 'prepare' else payload), operation)
    assert error.value.code == 20
    assert json.loads(capsys.readouterr().out) == {'error': 'refinement_design_duplicate'}
    assert before == {p.relative_to(campaign).as_posix(): p.read_bytes() for p in campaign.rglob('*') if p.is_file()}
    assert not (campaign / '.mot_ui/transitions/refinement.lock').exists()
    assert not (campaign / '.mot_ui/transitions/refinement.pending.json').exists()


@pytest.mark.parametrize('operation,expected', [('inspect','refinement_design_duplicate'), ('status','refinement_design_duplicate'), ('prepare','transition_outcome_unknown')])
def test_only_exact_read_rejection_becomes_actionable(operation, expected):
    transport = object.__new__(local.PinnedSshMot3DPreliminaryTransitionTransport)
    transport.profile = None
    transport.runner = SimpleNamespace(run=lambda *_: SimpleNamespace(returncode=20, stdout=b'{"error":"refinement_design_duplicate"}', stderr=b''))
    with pytest.raises(local.Mot3DPreliminaryTransitionError) as error:
        transport._call(operation, {})
    assert error.value.code == expected


def test_preview_and_stale_confirmation_reinspect_reject_without_prepare(tmp_path, monkeypatch):
    coordinator, plan, transport, state, _, _ = fixture(tmp_path, monkeypatch)
    coordinator._previews = PreviewRegistry(clock=lambda: NOW, token_factory=lambda: 'token')
    coordinator._confirm_lock = threading.Lock()
    coordinator._inspect = lambda *_: (plan, transport, state)
    coordinator.preview({}, session_id='owner')
    def blocked(*_):
        raise local.Mot3DPreliminaryTransitionError('refinement_design_duplicate')
    coordinator._inspect = blocked
    transport.prepare = lambda **_: pytest.fail('PREPARE must not run')
    before = {p.relative_to(plan[2]).as_posix(): p.read_bytes() for p in plan[2].rglob('*') if p.is_file()}
    for call in [lambda: coordinator.preview({}, session_id='owner'), lambda: coordinator.confirm({'preview_token':'token'}, session_id='owner')]:
        with pytest.raises(local.Mot3DPreliminaryTransitionError) as error:
            call()
        assert error.value.code == 'refinement_design_duplicate'
    assert before == {p.relative_to(plan[2]).as_posix(): p.read_bytes() for p in plan[2].rglob('*') if p.is_file()}


@pytest.mark.parametrize('stdout,stderr,returncode', [
    (b'{"error":"refinement_design_duplicate","extra":1}', b'', 20),
    (b'{"error":"other","error":"refinement_design_duplicate"}', b'', 20),
    (b'{"error":', b'', 20),
    (b'[["error","refinement_design_duplicate"]]', b'', 20),
    (b'{"error":"refinement_design_duplicate"}', b'warning', 20),
    (b'{"error":"refinement_design_duplicate"}', b'', 1),
])
def test_ambiguous_read_errors_are_not_relabelled(stdout, stderr, returncode):
    transport = object.__new__(local.PinnedSshMot3DPreliminaryTransitionTransport)
    transport.profile = None
    transport.runner = SimpleNamespace(run=lambda *_: SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr))
    with pytest.raises(local.Mot3DPreliminaryTransitionError) as error:
        transport._call('status', {})
    assert error.value.code == 'remote_response_invalid'


def test_duplicate_catalog_is_actionable_without_claiming_campaign_success():
    from workflow_api.error_catalog import resolve_error
    error = resolve_error('mot_3d_preliminary_transition', 'refinement_design_duplicate')
    assert error.status == 412
    assert error.code == 'refinement_design_duplicate'
    assert 'duplicate parameter points' in error.message
    assert 'Keep the existing results' in error.message
    assert 'retrying this action will not resolve it' in error.message
