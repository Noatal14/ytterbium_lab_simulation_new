"""Execute the actual Python bootstrap, rather than only inspecting SSH argv."""
import json
from pathlib import Path
import shlex
import subprocess
import sys

import pytest
from workflow_api.platform_io import executable
from workflow_api.pinned_ssh import PinnedSshPolicy, PinnedSshRunner, ReceiverOperation
from workflow_api.zeus_snapshot import ZeusProfile


@pytest.mark.parametrize('factory', ['zeeman_individual', 'mot_2d_individual', 'mot_3d_individual'])
def test_individual_bootstrap_preserves_all_four_receiver_arguments(tmp_path, monkeypatch, factory):
    original_read = Path.read_bytes
    original_run = subprocess.run
    receiver = b'import base64,json,sys\noperation,username,project,payload=sys.argv[1:]\nvalue=json.load(sys.stdin) if payload=="-" else json.loads(base64.urlsafe_b64decode(payload))\nprint(json.dumps([operation,username,project,value]))\n'
    names = {'zeeman_zeus_remote.py', 'mot_2d_zeus_remote.py', 'mot_3d_zeus_remote.py'}
    monkeypatch.setattr(Path, 'read_bytes', lambda path: receiver if path.name in names else original_read(path))

    def local_bootstrap(argv, **kwargs):
        remote = shlex.split(argv[-1])
        start = remote.index('-c')
        return original_run([sys.executable, *remote[start:]], stdout=subprocess.PIPE, stderr=subprocess.PIPE, input=kwargs.get('input'), check=False)

    monkeypatch.setattr('workflow_api.pinned_ssh._bounded_run', local_bootstrap)
    policy = getattr(PinnedSshPolicy, factory)(tmp_path, executable('ssh'), timeout=90)
    profile = ZeusProfile('tal.noa', '/home/tal.noa/ytterbium_lab_simulation_new')
    result = PinnedSshRunner(policy).run(ReceiverOperation.INSPECT, profile, {'probe': 'arguments'})
    assert result.returncode == 0, result.stderr.decode()
    operation, username, project, encoded = json.loads(result.stdout)
    assert (operation, username, project) == ('inspect', profile.username, profile.project_directory)
    assert encoded == {'probe': 'arguments'}
