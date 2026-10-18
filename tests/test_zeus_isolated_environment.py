"""Isolation applies to profile identity, PBS cwd, Python and receiver paths."""
import base64
import json
from pathlib import Path
import subprocess
import sys

import pytest
from workflow_api.zeus_snapshot import ZeusProfile
from workflow_api.zeeman_zeus_execution import _render_pbs as zeeman_pbs
from workflow_api.mot_2d_zeus_execution import _render_pbs as mot2d_pbs
from workflow_api.mot_3d_zeus_execution import _render_pbs as mot3d_pbs

TEST_PROJECT='/home/tal.noa/ytterbium_lab_simulation_ui_test'

@pytest.mark.parametrize('render', [zeeman_pbs,mot2d_pbs,mot3d_pbs])
def test_isolated_jobs_use_only_the_test_checkout_and_python(render):
    profile=ZeusProfile.parse({'username':'tal.noa','project_directory':TEST_PROJECT})
    pbs=render({'run_id':'isolated-test','git_revision':'a'*40},'b'*64,profile.project_directory).decode()
    assert 'cd /home/${USER}/ytterbium_lab_simulation_ui_test' in pbs
    assert '/venvs/atomsmltr-ui-test/bin/activate' in pbs
    assert 'ytterbium_lab_simulation_new' not in pbs
    assert '/venvs/atomsmltr/' not in pbs
    assert '#PBS -l select=1:ncpus=200:mem=64gb' in pbs
    assert 'git rev-parse HEAD' in pbs
    assert 'OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1' in pbs

@pytest.mark.parametrize('path', ['/home/tal.noa/other','/home/other/ytterbium_lab_simulation_ui_test','/home/tal.noa/ytterbium_lab_simulation_ui_test/../ytterbium_lab_simulation_new','/home//tal.noa/ytterbium_lab_simulation_ui_test'])
def test_profile_rejects_other_or_noncanonical_paths(path):
    with pytest.raises(ValueError):ZeusProfile.parse({'username':'tal.noa','project_directory':path})

@pytest.mark.parametrize('family', ['zeeman','mot_2d','mot_3d'])
def test_receiver_rejects_test_directory_alias_to_production(tmp_path,family):
    home=tmp_path/'home';user=home/'tal.noa';user.mkdir(parents=True)
    production=user/'ytterbium_lab_simulation_new';production.mkdir()
    isolated=user/'ytterbium_lab_simulation_ui_test'
    try:isolated.symlink_to(production,target_is_directory=True)
    except PermissionError:pytest.skip('Creating symlinks requires Windows privileges')
    source=Path(__file__).parents[1].joinpath(f'workflow_api/{family}_zeus_remote.py').read_text().replace('Path("/home")',f'Path({str(home)!r})')
    receiver=tmp_path/'receiver.py';receiver.write_text(source)
    completed=subprocess.run([sys.executable,str(receiver),'inspect','tal.noa',str(isolated),base64.urlsafe_b64encode(b'{}').decode()],capture_output=True,text=True)
    assert completed.returncode!=0
    assert json.loads(completed.stdout)=={'error':'remote_project_missing'}
    assert not (production/'.workflow').exists()
