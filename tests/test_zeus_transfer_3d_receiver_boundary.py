"""Real embedded receiver rejects invalid3D namespace/registry before publication."""
import base64,hashlib,json,struct,subprocess,sys
import pytest
from workflow_api.zeus_transfer import _REMOTE_TRANSFER_SCRIPT
from workflow_api.zeus_discovery_submission import FILES
from tests.test_zeus_transfer_security import initialize_git_repository


def invoke(project,commit,operation,files):
    script=_REMOTE_TRANSFER_SCRIPT.replace("home = pathlib.Path('/home') / username","home = project.resolve().parent")
    paths=tuple(files)
    payload=b''.join(struct.pack('!Q',len(raw))+hashlib.sha256(raw).hexdigest().encode()+raw for raw in files.values())
    encoded=base64.urlsafe_b64encode(json.dumps(paths).encode()).decode()
    return subprocess.run([sys.executable,'-c',script,operation,'tester',str(project),encoded,commit],input=b'' if operation=='inspect' else payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)


@pytest.mark.parametrize('attack',['missing','extra','mixed_family','missing_kind','acceptance_kind_in_scientific','test_namespace_in_scientific','inputs_bypass'])
def test_invalid_3d_transfer_never_publishes(tmp_path,attack):
    project=tmp_path/'project';project.mkdir();commit=initialize_git_repository(project)
    prefix='data/optimization/mot_3d/campaign'
    files={prefix+'/'+name:b'{}' for name in sorted(FILES|{'.mot_ui/transitions/discovery_bootstrap.json'})}
    operation='campaign'
    if attack=='missing':files.pop(prefix+'/jobs/single_pass/round_03.pbs')
    elif attack=='extra':files[prefix+'/extra.json']=b'{}'
    elif attack=='mixed_family':files['data/optimization/mot_2d/foreign/campaign.json']=b'{}'
    elif attack=='acceptance_kind_in_scientific':files[prefix+'/campaign.json']=b'{"kind":"mot_3d_ui_acceptance_v1"}'
    elif attack=='test_namespace_in_scientific':files={name.replace('/mot_3d/','/mot_3d/ui_acceptance/'):raw for name,raw in files.items()}
    elif attack=='inputs_bypass':operation='inputs'
    result=invoke(project,commit,operation,files)
    assert result.returncode!=0
    assert not (project/prefix).exists()
    assert not result.stderr


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires Unix directory descriptors, locking or shell fixtures")
def test_closed_scientific_campaign_cannot_be_replaced(tmp_path):
    project=tmp_path/'project';project.mkdir();commit=initialize_git_repository(project)
    prefix='data/optimization/mot_3d/mot_3d_s0_1p3_search10us_20261012_v1'
    target=project/prefix;target.mkdir(parents=True);(target/'campaign.json').write_bytes(b'protected-scientific-sentinel')
    files={prefix+'/'+name:b'{}' for name in FILES|{'.mot_ui/transitions/discovery_bootstrap.json'}}
    result=invoke(project,commit,'campaign',files)
    assert result.returncode==23
    assert (target/'campaign.json').read_bytes()==b'protected-scientific-sentinel'
    assert len(list(target.iterdir()))==1


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires Unix directory descriptors, locking or shell fixtures")
def test_sealed_2d_inputs_use_existing_exclusive_input_transport(tmp_path):
    project=tmp_path/'project';project.mkdir();commit=initialize_git_repository(project)
    name='data/particle_states/after_2d_mot/source/seed.npy';files={name:b'exact frozenbytes'}
    result=invoke(project,commit,'inputs',files)
    assert result.returncode==0 and json.loads(result.stdout)=={'ok':True}
    assert (project/name).read_bytes()==files[name]
    result=invoke(project,commit,'inputs',{name:b'changed'})
    assert result.returncode==23 and (project/name).read_bytes()==files[name]
