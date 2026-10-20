"""Completion forwards the authenticated full campaign namespace unchanged."""
import json
from pathlib import PurePosixPath

import pytest

from workflow_api import mot_3d_preliminary_transition_remote as core
from workflow_api.mot_3d_final_validation_completion_remote import DESCRIPTOR


@pytest.mark.parametrize('acceptance', [False, True])
def test_completion_result_validator_receives_exact_namespace(monkeypatch, acceptance):
    from workflow_api import mot_3d_final_validation_results as results
    project = PurePosixPath('/home/tal.noa') / (
        'ytterbium_lab_simulation_ui_acceptance' if acceptance else 'ytterbium_lab_simulation_new')
    relative = 'data/optimization/mot_3d/' + ('ui_acceptance/' if acceptance else '') + 'campaign'
    captured = {}
    monkeypatch.setattr(results, 'validate_final_validation_result_bytes',
                        lambda **kwargs: captured.update(kwargs))
    selections = {key: b'{}' for key in ('locked_nominals', 'input_manifest',
                  'generation_submission', 'submission', 'job_files', 'input_files')}
    with core.descriptor_scope(DESCRIPTOR):
        core._validate_results(json.dumps({'name':'campaign'}).encode(), selections, {},
                               project, project / relative)
    assert captured['logical_campaign_root'] == relative
    assert captured['campaign_absolute_path'] == str(project / relative)


@pytest.mark.parametrize('acceptance', [False, True])
def test_completion_captures_manifest_exact_fresh_zeeman_registry(monkeypatch, acceptance):
    from studies.mot_3d_campaign import build_campaign_manifest
    manifest = build_campaign_manifest(name='campaign', input_directory='data/source', upstream={}, roles={},
        revision='a'*40, physical_model_sha256='b'*64,
        acceptance_profile_id='ui_acceptance_v1' if acceptance else None)
    manifest['stage'] = 'final_validation'
    raw = json.dumps(manifest).encode()
    reads = []
    def read(fd, name, *limits):
        reads.append(name)
        return raw if name == 'campaign.json' else b'{}'
    monkeypatch.setattr(core, 'read_relative_at', read)
    monkeypatch.setattr(core, '_validate_results', lambda *args: (manifest, {}))
    project = PurePosixPath('/home/tal.noa') / ('ytterbium_lab_simulation_ui_acceptance' if acceptance else 'ytterbium_lab_simulation_new')
    relative = 'data/optimization/mot_3d/' + ('ui_acceptance/' if acceptance else '') + 'campaign'
    with core.descriptor_scope(DESCRIPTOR):
        core._capture(0, project, project / relative, raw)
    particles = 32 if acceptance else 50000
    zeeman = [name for name in reads if name.startswith('final_validation_inputs/after_zeeman/')]
    assert len(zeeman) == 40
    assert all(f'production_zeeman_n{particles}_dt40us_seed' in name for name in zeeman)
