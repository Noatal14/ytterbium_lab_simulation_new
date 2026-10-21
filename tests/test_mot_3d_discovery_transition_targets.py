"""Real receiver routing/authentication before any transition publication."""
import base64
from copy import deepcopy
import json
import io
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from studies.mot_3d_campaign import build_campaign_manifest
from workflow_api import mot_3d_discovery_transition_remote as receiver


class Authenticated(Exception):
    pass


def _invoke(tmp_path, monkeypatch, *, acceptance, target_acceptance=None, attack=None, race=False, stdin=False):
    if target_acceptance is None:
        target_acceptance = acceptance
    checkout = 'ytterbium_lab_simulation_ui_acceptance' if target_acceptance else 'ytterbium_lab_simulation_new'
    project = tmp_path / checkout
    project.mkdir()
    git = shutil.which('git')
    for args in (['init', '-q'], ['-c', 'user.name=Receiver test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'Frozen receiver fixture']):
        subprocess.run([git, '-C', str(project), *args], check=True)
    commit = subprocess.check_output([git, '-C', str(project), 'rev-parse', 'HEAD'], text=True).strip()
    model = build_campaign_manifest(name='routing', input_directory='data/acceptance/source', upstream={}, roles={},
                                   revision=commit, physical_model_sha256='a' * 64,
                                   acceptance_profile_id='ui_acceptance_v1' if acceptance else None)
    relative = 'data/optimization/mot_3d/' + ('ui_acceptance/' if acceptance else '') + 'routing'
    if attack == 'namespace':
        relative = 'data/optimization/mot_3d/routing' if acceptance else 'data/optimization/mot_3d/ui_acceptance/routing'
    if attack == 'missing_marker':
        model.pop('acceptance', None)
    elif attack == 'wrong_hash':
        model['acceptance']['profile_sha256'] = '0' * 64
    elif attack == 'cross_kind':
        model['kind'] = 'mot_2d_ui_acceptance_v1'
    path = project / relative / 'campaign.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(model))
    payload = {'campaign': relative, 'commit': commit, 'bootstrap_digest': 'a' * 64,
               'bootstrap_key': 'b' * 64, 'submission_key': 'c' * 64}
    if race:
        payload['nonce'] = 'd' * 32
    logical = '/home/tal.noa/' + checkout
    def mapped(value='.'):
        text = str(value)
        prefix = '/home/tal.noa/'
        if text.startswith(prefix) and '/' not in text[len(prefix):]:
            return tmp_path / text[len(prefix):]
        return Path(value)
    monkeypatch.setattr(receiver, 'Path', mapped)
    monkeypatch.setattr(sys, 'argv', ['receiver', 'prepare' if race else 'inspect', 'tal.noa', logical,
                                    base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()])
    if stdin:
        from workflow_api.pinned_ssh import PinnedSshPolicy, PinnedSshRunner, ReceiverOperation
        from workflow_api.zeus_snapshot import ZeusProfile
        captured = {}
        def capture(_argv, **kwargs):
            captured['input'] = kwargs['input']
            return subprocess.CompletedProcess(_argv, 0, b'', b'')
        monkeypatch.setattr('workflow_api.pinned_ssh._bounded_run', capture)
        policy = PinnedSshPolicy.mot_3d_discovery_transition(project, Path(sys.executable), timeout=10)
        PinnedSshRunner(policy).run(ReceiverOperation.INSPECT,
            ZeusProfile.parse({'username': 'tal.noa', 'project_directory': logical}), payload)
        header, raw_payload = captured['input'].split(b'\n', 1)
        source, argv = json.loads(header)
        assert base64.urlsafe_b64decode(source) == Path(receiver.__file__).read_bytes()
        assert argv[1:] == ['inspect', 'tal.noa', logical, '-']
        monkeypatch.setattr(sys, 'argv', argv)
        monkeypatch.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(raw_payload)))
    if not race:
        def authenticated(*args):
            raise Authenticated
        monkeypatch.setattr(receiver, 'discovery_receipts', authenticated)
    else:
        chain = {'angled_donut': ['1[].zeus-master', '2[].zeus-master'],
                 'single_pass': ['3[].zeus-master', '4[].zeus-master', '5[].zeus-master']}
        monkeypatch.setattr(receiver, 'discovery_receipts', lambda *args: ({}, {}, chain))
        monkeypatch.setattr(receiver, 'scheduler_lifecycle', lambda *args: 'completed_success_unvalidated')
        monkeypatch.setattr(receiver, 'validate_outputs', lambda *args: 'ready_to_advance')
        original_lock = receiver.fcntl.flock
        def changed_under_lock(fd, operation):
            result = original_lock(fd, operation)
            if operation & receiver.fcntl.LOCK_EX:
                changed = deepcopy(model)
                changed.pop('acceptance', None)
                path.write_text(json.dumps(changed))
            return result
        monkeypatch.setattr(receiver.fcntl, 'flock', changed_under_lock)
    return project / relative


@pytest.mark.parametrize('stdin', [False, True], ids=['legacy-base64', 'pinned-stdin'])
@pytest.mark.parametrize('acceptance', [False, True], ids=['scientific', 'TEST-ONLY'])
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_exact_target_reaches_authenticated_receipt_boundary(tmp_path, monkeypatch, acceptance, stdin):
    campaign = _invoke(tmp_path, monkeypatch, acceptance=acceptance, stdin=stdin)
    with pytest.raises(Authenticated):
        receiver.main()
    assert not (campaign / '.mot_ui').exists()


@pytest.mark.parametrize('acceptance', [False, True], ids=['scientific', 'TEST-ONLY'])
def test_cross_target_is_rejected_before_receipts_or_publication(tmp_path, monkeypatch, acceptance):
    campaign = _invoke(tmp_path, monkeypatch, acceptance=acceptance, target_acceptance=not acceptance)
    with pytest.raises(SystemExit):
        receiver.main()
    assert not (campaign / '.mot_ui').exists()


@pytest.mark.parametrize('attack', ['missing_marker', 'wrong_hash', 'cross_kind', 'namespace'])
def test_acceptance_authentication_remains_exact(tmp_path, monkeypatch, attack):
    campaign = _invoke(tmp_path, monkeypatch, acceptance=True, attack=attack)
    with pytest.raises(SystemExit):
        receiver.main()
    assert not (campaign / '.mot_ui').exists()


def test_changed_profile_under_lock_cannot_publish_pending(tmp_path, monkeypatch):
    campaign = _invoke(tmp_path, monkeypatch, acceptance=True, race=True)
    with pytest.raises(SystemExit):
        receiver.main()
    assert not list(campaign.rglob('*pending*'))
    assert not list(campaign.rglob('*.gz'))
    assert not (campaign / '.mot_ui/transitions/discovery_to_preliminary.json').exists()
