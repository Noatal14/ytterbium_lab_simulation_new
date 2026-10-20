"""Review hashes and workload use the same bytes before descriptors close."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from studies.mot_3d_campaign import build_campaign_manifest
from workflow_api import mot_3d_final_validation_transition as stage


@pytest.mark.parametrize('acceptance', [False, True])
@pytest.mark.parametrize('changed', [False, True], ids=['same-frozen-manifest', 'changed-between-base-and-capture'])
def test_plan_captures_manifest_once_with_live_descriptor(tmp_path, monkeypatch, acceptance, changed):
    root = tmp_path / 'repository'
    relative = 'data/optimization/mot_3d/' + ('ui_acceptance/' if acceptance else '') + 'campaign'
    campaign = root / relative
    manifest = build_campaign_manifest(name='campaign', input_directory='data/source', upstream={}, roles={},
        revision='a'*40, physical_model_sha256='b'*64,
        acceptance_profile_id='ui_acceptance_v1' if acceptance else None)
    manifest = json.loads(json.dumps(manifest))
    manifest['stage'] = 'final_validation_input_generation'
    raw = json.dumps({**manifest, **({'unreviewed':True} if changed else {})}).encode()
    for name in stage.FILES:
        path = campaign / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw if name == 'campaign.json' else b'frozen source bytes')
    for name in stage.CODE_PATHS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'frozen code bytes')
    identity = {'local_transition_receipt_sha256':'b'*64,
                'remote_transition_receipt_sha256':'c'*64, 'bundle_sha256':'d'*64}
    base = ('mot_3d-id', None, campaign, manifest, 'a'*40, identity, 'e'*64, relative)
    monkeypatch.setattr(stage, 'Mot3DFinalInputSubmissionCoordinator',
                        lambda *args, **kwargs: SimpleNamespace(_plan=lambda request:base))
    coordinator = object.__new__(stage.Mot3DFinalValidationTransitionCoordinator)
    coordinator.root, coordinator.ssh, coordinator.git = root, root/'ssh', root/'git'
    native_read = stage._read_relative
    reads = []
    def checked(fd, name):
        stage.os.fstat(fd)
        reads.append((fd, name))
        return native_read(fd, name)
    monkeypatch.setattr(stage, '_read_relative', checked)
    if changed:
        with pytest.raises(stage.Mot3DFinalValidationTransitionError):
            coordinator._plan({})
    else:
        plan = coordinator._plan({})
        assert plan[5]['source_files']['campaign.json'] == hashlib.sha256(raw).hexdigest()
        assert len(plan[-1]) == 107
    assert sum(name == 'campaign.json' for _, name in reads) == 1
    for fd in {fd for fd, _ in reads}:
        with pytest.raises(OSError):
            stage.os.fstat(fd)
