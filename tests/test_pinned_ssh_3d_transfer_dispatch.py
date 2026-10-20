"""3D transfer selects a fixed modern runtime without moving payload to argv."""
import base64,hashlib,io,json,shlex,subprocess,sys
import pytest
from workflow_api import zeus_transfer
from workflow_api.pinned_ssh import PinnedSshPolicy,PinnedSshRunner,TransferOperation
from workflow_api.zeus_snapshot import ZeusProfile

@pytest.mark.parametrize('acceptance',[False,True])
@pytest.mark.parametrize('operation',[TransferOperation.INSPECT,TransferOperation.CAMPAIGN])
def test_3d_modern_runtime_real_stdin_bootstrap(tmp_path,monkeypatch,acceptance,operation):
    from workflow_api.platform_io import executable
    namespace='ui_acceptance/' if acceptance else ''
    prefix='data/optimization/mot_3d/'+namespace+'n'*128+'/'
    paths=tuple(prefix+'d'*128+'/'+'f'*(512-len(prefix)-128-1-10)+f'{index:05}.json' for index in range(72))
    assert all(len(name.encode())==512 for name in paths)
    profile=ZeusProfile.parse({'username':'tal.noa','project_directory':'/home/tal.noa/ytterbium_lab_simulation_'+('ui_acceptance' if acceptance else 'new')})
    monkeypatch.setattr(zeus_transfer,'_REMOTE_TRANSFER_SCRIPT',"import sys,json,hashlib;data=sys.stdin.buffer.read();print(json.dumps({'argv':sys.argv[1:],'sha':hashlib.sha256(data).hexdigest()}))")
    native=subprocess.Popen;seen={}
    def child(argv,**kwargs):
        seen['length']=len(subprocess.list2cmdline(argv));parts=shlex.split(argv[-1]);seen['parts']=parts
        return native([sys.executable,'-c',parts[parts.index('-c')+1]],**kwargs)
    monkeypatch.setattr('workflow_api.pinned_ssh.subprocess.Popen',child)
    runner=PinnedSshRunner(PinnedSshPolicy.transfer(tmp_path,executable('ssh'),timeout=10))
    payload=b'\x00\xff\n[untrusted]'
    status,raw,stderr=runner.transfer(operation,profile,paths,'a'*40,payload)
    assert status==0 and not stderr
    assert json.loads(raw)['sha']==hashlib.sha256(payload).hexdigest()
    assert json.loads(base64.urlsafe_b64decode(json.loads(raw)['argv'][3]))==list(paths)
    parts=seen['parts'];assert parts[:4]==['cd','--',profile.project_directory,'&&']
    assert parts[parts.index('-c')-1]=='/home/tal.noa/venvs/'+('atomsmltr-ui-test' if acceptance else 'atomsmltr')+'/bin/python'
    assert seen['length']<4096

@pytest.mark.parametrize('other',['foreign/file','data/optimization/mot_2d/other/campaign.json','data/optimization/mot_3d/ui_acceptance/campaign/file','data/optimization/mot_3d/campaign/../foreign'])
def test_3d_mixed_campaign_or_foreign_paths_reject_before_spawn(tmp_path,monkeypatch,other):
    from workflow_api.platform_io import executable
    monkeypatch.setattr('workflow_api.pinned_ssh.subprocess.Popen',lambda *a,**k:pytest.fail('must not spawn'))
    profile=ZeusProfile.parse({'username':'tal.noa','project_directory':'/home/tal.noa/ytterbium_lab_simulation_new'})
    runner=PinnedSshRunner(PinnedSshPolicy.transfer(tmp_path,executable('ssh'),timeout=10))
    with pytest.raises(ValueError):runner.transfer(TransferOperation.CAMPAIGN,profile,('data/optimization/mot_3d/campaign/campaign.json',other),'a'*40,b'')
