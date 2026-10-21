"""Cross-feature handoff of genuine remote bytes into the canonical read gate.

No physics/scheduler/network: captured original O16 raw rows/bytes are reused.
Only prior evaluation-file admission is isolated (covered by complete protocols).
The alternate expected numerical summary is a genuine Mac capture, not invented
or rounded values. Product code is never modified during this test.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest

from workflow_api.mot_2d_plan import encode_production_plan
from workflow_api.zeus_production import _validated_production_plan, ZeusProductionError
from workflow_api import mot_2d_validation as validation


def test_remote_plan_bytes_pass_canonical_statistical_read_and_tampering_fails_closed(tmp_path, monkeypatch):
    fixture = json.loads((Path(__file__).parent/'fixtures/production_plan_actual_o16_drift.json').read_bytes())
    manifest = fixture['manifest']; original_manifest = copy.deepcopy(manifest)
    root = tmp_path/'repo'; campaign = root/fixture['payload']['campaign']; campaign.mkdir(parents=True)
    remote_bytes = {name: base64.b64decode(item['raw_base64'], validate=True) for name,item in fixture['rendered'].items()}
    plan = encode_production_plan(fixture['payload'], remote_bytes, fixture['confirmation_rows'], fixture['sensitivity_rows'])
    checked = _validated_production_plan(plan, fixture['payload'], manifest, campaign, root, fixture['confirmation_rows'], fixture['sensitivity_rows'])
    assert checked == remote_bytes
    for name,raw in checked.items():
        path=campaign/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    before={name:hashlib.sha256((campaign/name).read_bytes()).hexdigest() for name in checked}
    observed = json.loads(remote_bytes['sensitivity_summary.json'])
    local_captured = json.loads(base64.b64decode(fixture['local_summary']['raw_base64'],validate=True))
    assert local_captured != observed
    tasks = json.loads(remote_bytes['production/tasks.json'])
    # Genuine prior rows were already physically/identity validated on the donor;
    # this seam avoids manufacturing hundreds of earlier-stage result files.
    monkeypatch.setattr(validation,'validated_evaluation_outputs',lambda path, design, stage:fixture[stage+'_rows'])
    actual_derive = validation.derive_production_transition
    for expected in [actual_derive(manifest,fixture['confirmation_rows'],fixture['sensitivity_rows'])[0], local_captured]:
        monkeypatch.setattr(validation,'derive_production_transition',lambda *args, expected=expected:(expected,tasks))
        result,registry=validation.validated_production_transition(campaign,manifest)
        assert result == observed and registry == tasks
        assert {name:hashlib.sha256((campaign/name).read_bytes()).hexdigest() for name in checked} == before
        assert manifest == original_manifest
    # CI-only portability must not admit any non-CI change, even if the local
    # file is syntactically valid and its sender recomputes a transport hash.
    changed=copy.deepcopy(observed);next(iter(changed.values()))['production_selection']['parameters']['detuning_gamma']=-9.0
    raw=(json.dumps(changed,indent=2,sort_keys=True)+'\n').encode()
    (campaign/'sensitivity_summary.json').write_bytes(raw)
    with pytest.raises(ValueError):validation.validated_production_transition(campaign,manifest)
    tampered=copy.deepcopy(plan);tampered['files']['sensitivity_summary.json']={'sha256':hashlib.sha256(raw).hexdigest(),'base64':base64.b64encode(raw).decode()}
    with pytest.raises(ZeusProductionError):_validated_production_plan(tampered,fixture['payload'],manifest,campaign,root,fixture['confirmation_rows'],fixture['sensitivity_rows'])
    assert manifest == original_manifest
    assert not (campaign/'.mot_ui').exists()
