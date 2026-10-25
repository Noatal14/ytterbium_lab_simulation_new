"""Transfer-planner context contract; explicit profile validation, no remote writes.

Structural bootstrap/upstream readers and state freezing are isolated here; the
separate lineage tests exercise the saved particle ledger.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from workflow_api.acceptance_profile import load_acceptance_profile
from workflow_api.zeus_transfer import ZeusPreparationError, ZeusPreparationService
from test_zeus_transfer_security import RecordingTransport, COMMIT


def fixture(tmp_path, monkeypatch):
    from workflow_api import zeus_transfer, zeus_discovery_submission
    from studies import mot_3d_campaign
    root=tmp_path/'repo';campaign=root/'data/optimization/mot_3d/ui_acceptance/TESTONLY_context'
    campaign.mkdir(parents=True)
    source=deepcopy(json.loads((Path(__file__).parent/'fixtures/o16-acceptance-source-authority.json').read_bytes()))
    upstream=root/'data/optimization/mot_2d/ui_acceptance/source/campaign.json'
    upstream.parent.mkdir(parents=True);upstream.write_text('{}')
    survivors=upstream.parent/'survivor_states';survivors.mkdir()
    source.update(campaign_path=upstream.relative_to(root).as_posix(), sealed_seed_pairs=[],
                  expected_survivor_design={},expected_survivor_parameters={})
    model={'kind':'mot_3d_ui_acceptance_v1','acceptance':load_acceptance_profile('ui_acceptance_v1').provenance(),
           'upstream_2d_campaign':deepcopy(source),'input_directory':survivors.relative_to(root).as_posix(),'input_roles':{k:[]for k in ('discovery','refinement','preliminary_check')}}
    (campaign/'campaign.json').write_text('{}')
    files={}
    for name in zeus_discovery_submission.FILES:
        path=campaign/name;path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():path.write_text('{}')
        files[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    receipt=campaign/'.mot_ui/transitions/discovery_bootstrap.json';receipt.parent.mkdir(parents=True);receipt.write_text('{}')
    inputs={}
    for i in range(42):
        path=root/f'data/acceptance/states/{i}.npy';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(str(i).encode());inputs[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(zeus_transfer,'_load_manifest',lambda _:model)
    monkeypatch.setattr(zeus_discovery_submission,'validate_discovery_bootstrap',lambda *_a,**_k:(COMMIT,None,files,None))
    monkeypatch.setattr(zeus_discovery_submission,'bootstrap_input_hashes',lambda _:inputs)
    monkeypatch.setattr(mot_3d_campaign,'validate_upstream_2d_campaign',lambda *_a,**_k:source)
    calls=[]
    def freeze(directory,**kwargs):
        policy=load_acceptance_profile(kwargs.get('acceptance_profile_id'))
        if kwargs.get('repository_root')!=root:raise ValueError('Missing explicit repository authority')
        assert policy.profile_id=='ui_acceptance_v1'
        calls.append((directory,deepcopy(kwargs)));return model['input_roles']
    monkeypatch.setattr(mot_3d_campaign,'freeze_inputs',freeze)
    return root,campaign,source,calls


def test_preview_plans_exact52_files_using_explicit_profile_and_repository(tmp_path,monkeypatch):
    root,campaign,source,calls=fixture(tmp_path,monkeypatch)
    before={p.relative_to(root):p.read_bytes()for p in root.rglob('*')if p.is_file()}
    transport=RecordingTransport();preview=ZeusPreparationService(root,transport).preview(campaign,session_id='session')
    assert len(preview.files)==52 and preview.git_commit==COMMIT
    assert len(calls)==1 and calls[0][1]['acceptance_profile_id']=='ui_acceptance_v1'
    assert len(transport.inspections)==1 and not transport.input_uploads and not transport.campaign_publications
    assert {p.relative_to(root):p.read_bytes()for p in root.rglob('*')if p.is_file()}==before


@pytest.mark.parametrize('missing',['acceptance_profile_id','repository_root'])
def test_missing_forwarded_context_fails_before_remote_inspection(tmp_path,monkeypatch,missing):
    from studies import mot_3d_campaign
    root,campaign,_,_=fixture(tmp_path,monkeypatch)
    validated_freeze=mot_3d_campaign.freeze_inputs
    def omit_context(directory,**kwargs):
        kwargs.pop(missing,None)
        return validated_freeze(directory,**kwargs)
    monkeypatch.setattr(mot_3d_campaign,'freeze_inputs',omit_context)
    transport=RecordingTransport()
    with pytest.raises(ZeusPreparationError,match='campaign_manifest_invalid'):
        ZeusPreparationService(root,transport).preview(campaign,session_id='session')
    assert not transport.inspections and not transport.input_uploads and not transport.campaign_publications


def test_changed_frozen_input_fails_before_remote_inspection(tmp_path,monkeypatch):
    root,campaign,_,_=fixture(tmp_path,monkeypatch)
    next((root/'data/acceptance/states').glob('*')).write_bytes(b'changed')
    transport=RecordingTransport()
    with pytest.raises(ZeusPreparationError,match='campaign_manifest_invalid'):
        ZeusPreparationService(root,transport).preview(campaign,session_id='session')
    assert not transport.inspections and not transport.input_uploads and not transport.campaign_publications
