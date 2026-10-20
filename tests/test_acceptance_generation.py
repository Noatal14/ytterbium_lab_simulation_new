"""Acceptance workload/provenance and scientific-promotion boundaries."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from workflow_api.acceptance_profile import load_acceptance_profile
from workflow_api.manifest_codec import decode_manifest, ManifestCodecError
from studies.zeeman import generate_ensembles as generation


def manifest(root, family='mot_3d'):
    profile = load_acceptance_profile()
    path = root / f'data/optimization/{family}/ui_acceptance/canary/campaign.json'
    path.parent.mkdir(parents=True)
    from studies.mot_3d_campaign import build_campaign_manifest
    model = build_campaign_manifest(name='canary', input_directory=root / 'data/acceptance/inputs',
                                    upstream={}, roles={}, revision='a' * 40,
                                    physical_model_sha256='b' * 64,
                                    acceptance_profile_id='ui_acceptance_v1')
    path.write_text(json.dumps(model))
    return path


def test_acceptance_codec_requires_exact_marker_and_never_accepts_scientific_disguise():
    profile = load_acceptance_profile()
    for kind in ('mot_2d_ui_acceptance_v1', 'mot_3d_ui_acceptance_v1'):
        payload = {'kind': kind, 'acceptance': profile.provenance()}
        assert 'acceptance' in decode_manifest(json.dumps(payload).encode()).version
        payload['acceptance']['profile_sha256'] = '0' * 64
        with pytest.raises(ManifestCodecError):
            decode_manifest(json.dumps(payload).encode())
    with pytest.raises(ManifestCodecError):
        decode_manifest(json.dumps({'kind': 'mot_3d_campaign_v2', 'acceptance': profile.provenance()}).encode())


def test_fresh_generation_keeps_physics_and_records_actual_count(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    campaign = manifest(tmp_path)
    target = tmp_path / 'data/particle_states/after_zeeman/ui_acceptance/fresh'
    calls = []
    monkeypatch.setattr('workflow_api.acceptance_inputs.code_identity', lambda root: {'git_commit': 'a' * 40})
    monkeypatch.setattr('simulations.zeeman._git_commit', lambda: 'a' * 40)
    monkeypatch.setattr('simulations.zeeman._tracked_worktree_is_dirty', lambda: False)
    def simulate(path, **kwargs):
        calls.append(kwargs)
        from simulations.zeeman import write_zeeman_metadata
        states = np.zeros((2, 6))
        np.save(path, states)
        write_zeeman_metadata(path, states, kwargs, elapsed_seconds=1.0)
    monkeypatch.setattr(generation, 'run_and_save_zeeman', simulate)
    path = generation.run(3035, 1, target, acceptance_profile='ui_acceptance_v1', input_manifest=campaign)
    assert path.name == 'production_zeeman_n32_dt40us_seed3035.npy'
    assert calls[0]['dt'] == 4e-5
    assert calls[0]['N_particles'] == 32
    assert calls[0]['zeeman_field_config'] == generation.corrected_field()
    assert json.loads(path.with_suffix('.json').read_text())['acceptance'] == load_acceptance_profile().provenance()
    from utils.mot_2d_study import load_production_ensembles
    loaded = load_production_ensembles(directory=target, zeeman_seeds=[3035],
                                      acceptance_profile_id='ui_acceptance_v1')
    assert len(loaded) == 1
    assert loaded[0]['n_available'] == 2
    with pytest.raises(ValueError, match='TEST ONLY'):
        load_production_ensembles(directory=target, zeeman_seeds=[3035])
    generation.run(3035, 1, target, acceptance_profile='ui_acceptance_v1', input_manifest=campaign)
    assert len(calls) == 1


@pytest.mark.parametrize('attack', ['production_path', 'wrong_seed', 'workers', 'scientific_manifest'])
def test_fresh_generation_rejects_unsafe_requests_before_physics(tmp_path, monkeypatch, attack):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('workflow_api.acceptance_inputs.code_identity', lambda root: {'git_commit': 'a' * 40})
    campaign = manifest(tmp_path)
    target = tmp_path / 'data/particle_states/after_zeeman/ui_acceptance/fresh'
    seed, pools = 3035, 1
    if attack == 'production_path': target = tmp_path / 'data/particle_states/after_zeeman/science'
    if attack == 'wrong_seed': seed = 3015
    if attack == 'workers': pools = 200
    if attack == 'scientific_manifest': campaign.write_text('{"kind":"mot_3d_campaign_v2"}')
    def forbidden(*args, **kwargs): raise AssertionError('Unsafe request reached physics')
    monkeypatch.setattr(generation, 'run_and_save_zeeman', forbidden)
    with pytest.raises(ValueError):
        generation.run(seed, pools, target, acceptance_profile='ui_acceptance_v1', input_manifest=campaign)
    assert not target.exists()


def test_scientific_loader_refuses_acceptance_directory_before_reading(tmp_path):
    from utils.mot_2d_study import load_production_ensembles
    with pytest.raises(ValueError, match='TEST ONLY'):
        load_production_ensembles(directory=tmp_path / 'ui_acceptance' / 'fresh')


def test_individual_catalog_rejects_nested_acceptance_marker(tmp_path):
    from workflow_api.mot_3d_individual_sources import _bounded_json
    path = tmp_path / 'report.json'
    path.write_text(json.dumps({'design': {'acceptance': load_acceptance_profile().provenance()}}))
    with pytest.raises(ValueError, match='TEST ONLY'):
        _bounded_json(path, tmp_path)
