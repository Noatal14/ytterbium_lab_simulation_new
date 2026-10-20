"""Pinned SSH returns bytes; the Discovery transport must preserve that boundary."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from workflow_api.mot_3d_discovery_transition import (
    PinnedSshMot3DDiscoveryTransitionTransport, Mot3DDiscoveryTransitionError,
)
from workflow_api.pinned_ssh import PinnedSshRunner
from workflow_api.zeus_snapshot import ZeusProfile


def _transport(monkeypatch, raw):
    root = Path(__file__).resolve().parents[1]
    def run(self, operation, profile, payload):
        return subprocess.CompletedProcess([], 0, raw, b'')
    monkeypatch.setattr(PinnedSshRunner, 'run', run)
    profile = ZeusProfile.parse({'username': 'tal.noa',
                                'project_directory': '/home/tal.noa/ytterbium_lab_simulation_ui_acceptance'})
    return PinnedSshMot3DDiscoveryTransitionTransport(root, Path(shutil.which('ssh')), profile)


def test_actual_bytes_runner_response_is_parsed(monkeypatch):
    value = {'lifecycle': 'not_submitted', 'branch': 'main',
             'chain': {'angled_donut': [], 'single_pass': []},
             'receipt': None, 'bundle': None, 'chunk': None}
    state = _transport(monkeypatch, json.dumps(value).encode()).inspect()
    assert state.lifecycle == value['lifecycle']
    assert state.chain == {'angled_donut': (), 'single_pass': ()}


@pytest.mark.parametrize('raw', [b'\xff', b'{', b'{}', b'{"x":1,"x":2}', b'null'])
def test_malformed_bytes_remain_closed(monkeypatch, raw):
    with pytest.raises(Mot3DDiscoveryTransitionError, match='remote_response_invalid'):
        _transport(monkeypatch, raw).inspect()
