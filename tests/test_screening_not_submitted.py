"""A prepared but unsubmitted Screening is an authenticated read-only observation."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from workflow_api import zeus_refinement_remote as remote
from workflow_api.campaign_deployment import SCIENTIFIC_CHECKOUT, campaign_checkout_paths
from workflow_api.zeus_refinement import PinnedSshRefinementTransport, ZeusRefinementError

H = lambda raw: hashlib.sha256(raw).hexdigest()


def prepared(tmp_path, monkeypatch):
    root = tmp_path / SCIENTIFIC_CHECKOUT
    relative = 'data/optimization/mot_2d/prepared'
    campaign = root / relative
    for name in ('screen', 'jobs', '.mot_ui/transitions', '.mot_ui/submissions'):
        (campaign / name).mkdir(parents=True, exist_ok=True)
    commit = 'a' * 40
    manifest = {'kind': 'mot_2d_s0_campaign', 'stage': 'screen', 's0_values': [1.3]}
    files = {'campaign.json': json.dumps(manifest).encode(), 'screen/tasks.json': b'[]', 'jobs/02_screen.pbs': b'pbs'}
    for name, raw in files.items(): (campaign / name).write_bytes(raw)
    original = {relative + '/campaign.json': 'b' * 64}
    for i in range(71):
        name = relative + ('/jobs/01_smoke.pbs' if i == 0 else f'/inputs/{i}.json')
        path = root / name; path.parent.mkdir(exist_ok=True); path.write_bytes(str(i).encode())
        original[name] = H(path.read_bytes())
    screen = {name: H(raw) for name, raw in files.items()}
    key = H(json.dumps({'campaign': relative, 'commit': commit, 'manifest': original[relative+'/campaign.json'], 'pbs': original[relative+'/jobs/01_smoke.pbs']}, sort_keys=True, separators=(',', ':')).encode())
    smoke = {'version': 1, 'submission_key': key, 'nonce': 'c'*32, 'job_file': relative+'/jobs/01_smoke.pbs', 'commit': commit, 'created_unix_s': 1, 'status': 'submitted', 'job_id': '123.zeus-master', 'completed_unix_s': 2}
    points = [{'s0': 1.3}]
    transition = {'status': 'screening_prepared', 'nonce': 'd'*32, 'job_id': smoke['job_id'], 'smoke_digest': H(json.dumps(points, sort_keys=True).encode()), 'points': points, 'artifact_count': 3, 'commit': commit, 'submission_key': key, 'transition_files': screen, 'completed_unix_s': 3}
    (campaign/'.mot_ui/submissions/smoke.json').write_text(json.dumps(smoke))
    (campaign/'.mot_ui/transitions/screen.json').write_text(json.dumps(transition))
    payload = {'campaign': relative, 'commit': commit, 'prepared_files': original, 'screen_files': screen, 'screen_digest': H(json.dumps(screen, sort_keys=True).encode()), 'screening_submission_key': 'e'*64}
    monkeypatch.setattr(remote, 'campaign_checkout_paths', lambda username: frozenset(tmp_path/p.name for p in campaign_checkout_paths(username)))
    calls = []
    def process(argv, **kwargs):
        calls.append(argv)
        assert Path(argv[0]).name == 'git', 'No qstat or qsub before an actual submission'
        value = commit+'\n' if 'rev-parse' in argv else 'main\n' if 'branch' in argv else ''
        return subprocess.CompletedProcess(argv, 0, value if kwargs.get('text') else value.encode(), '' if kwargs.get('text') else b'')
    monkeypatch.setattr(remote.subprocess, 'run', process)
    return root, campaign, payload, calls


@pytest.mark.skipif(os.name == 'nt', reason='POSIX Zeus receiver directory descriptors')
@pytest.mark.parametrize('fault', [None, 'pending', 'lock', 'malformed', 'symlink', 'parent_symlink', 'missing_parent', 'outputs', 'input_hash', 'smoke', 'transition', 'wrong_root'])
def test_normal_receiver_only_classifies_exact_prepared_absence(tmp_path, monkeypatch, capsys, fault):
    root, campaign, payload, calls = prepared(tmp_path, monkeypatch)
    submissions = campaign/'.mot_ui/submissions'
    if fault == 'pending': (submissions/'screening.pending.json').write_text('{}')
    elif fault == 'lock': (submissions/'screening.lock').mkdir()
    elif fault == 'malformed': (submissions/'screening.json').write_text('{bad')
    elif fault == 'symlink': (submissions/'screening.json').symlink_to(submissions/'missing')
    elif fault == 'parent_symlink':
        submissions.rename(campaign/'real-submissions'); submissions.symlink_to(campaign/'real-submissions', target_is_directory=True)
    elif fault == 'missing_parent':
        (submissions/'smoke.json').unlink(); submissions.rmdir()
    elif fault == 'outputs': (campaign/'screen/worker0').mkdir()
    elif fault == 'input_hash': (root/next(name for name in payload['prepared_files'] if '/inputs/' in name)).write_text('changed')
    elif fault in ('smoke', 'transition'):
        target = submissions/'smoke.json' if fault == 'smoke' else campaign/'.mot_ui/transitions/screen.json'
        value = json.loads(target.read_text()); value['nonce'] = 'bad'; target.write_text(json.dumps(value))
    elif fault == 'wrong_root': monkeypatch.setattr(remote, 'campaign_checkout_paths', lambda _: frozenset())
    before = {str(p): p.read_bytes() for p in campaign.rglob('*') if p.is_file() and not p.is_symlink()}
    monkeypatch.setattr(sys, 'argv', ['receiver', 'inspect', 'tal.noa', str(root), base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()])
    with pytest.raises(SystemExit) as stopped: remote.main()
    assert stopped.value.code == 20
    error = json.loads(capsys.readouterr().out)['error']
    assert (error == 'screen_not_submitted') is (fault is None)
    assert {str(p): p.read_bytes() for p in campaign.rglob('*') if p.is_file() and not p.is_symlink()} == before
    assert all(Path(argv[0]).name == 'git' for argv in calls)


@pytest.mark.parametrize('rc,raw,stderr,operation,expected', [
    (20, b'{"error":"screen_not_submitted"}', b'', 'inspect', 'screen_not_submitted'),
    (20, b'{"error":"screen_not_submitted"}', b'', 'prepare', 'transition_outcome_unknown'),
    (1, b'{"error":"screen_not_submitted"}', b'', 'inspect', 'remote_response_invalid'),
    (20, b'{"error":"screen_not_submitted"}', b'warning', 'inspect', 'remote_response_invalid'),
    (20, b'{"error":"other","error":"screen_not_submitted"}', b'', 'inspect', 'remote_response_invalid'),
    (20, b'[["error","screen_not_submitted"]]', b'', 'inspect', 'remote_response_invalid'),
    (20, b'{"error":"transition_conflict"}', b'', 'inspect', 'remote_response_invalid'),
])
def test_transport_classifies_only_exact_readonly_error(rc, raw, stderr, operation, expected):
    transport = object.__new__(PinnedSshRefinementTransport)
    transport.profile = None
    transport.runner = type('Runner', (), {'run': lambda *_: subprocess.CompletedProcess([], rc, raw, stderr)})()
    with pytest.raises(ZeusRefinementError) as error: transport._call(operation, {})
    assert error.value.code == expected
