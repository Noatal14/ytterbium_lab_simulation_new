import json
from pathlib import Path

import numpy as np
import pytest

from studies.zeeman import generate_ensembles as generation
from workflow_api import acceptance_inputs as inputs
from workflow_api.acceptance_profile import load_acceptance_profile
from workflow_api.manifest_codec import decode_manifest, ManifestCodecError


@pytest.fixture
def planned(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(inputs, 'code_identity', lambda root: {'git_commit': 'a' * 40, 'files': {'physical.py': 'b' * 64}})
    destination = tmp_path / 'data/acceptance/initial/input_generation.json'
    output = tmp_path / 'data/particle_states/after_zeeman/ui_acceptance/initial'
    plan = inputs.save_input_generation_plan(tmp_path, destination, output)
    return destination, output, plan


def physical_stub(monkeypatch):
    calls = []
    def simulate(path, **kwargs):
        from simulations.zeeman import write_zeeman_metadata
        calls.append(kwargs)
        states = np.zeros((2, 6), dtype=np.float64)
        np.save(path, states)
        metadata = write_zeeman_metadata(path, states, kwargs, 1.0)
        value = json.loads(metadata.read_text())
        value['software']['git_commit'] = 'a' * 40
        value['software']['tracked_worktree_was_dirty'] = False
        metadata.write_text(json.dumps(value))
    monkeypatch.setattr(generation, 'run_and_save_zeeman', simulate)
    return calls


def test_initial_plan_is_not_a_campaign_and_freezes_full_registry(planned):
    path, output, value = planned
    assert value['kind'] == inputs.KIND
    assert value['generation']['seeds'] == list(range(3000, 3035))
    assert value['generation']['n_initial_atoms'] == 32
    assert value['generation']['npools'] == 1
    assert value['purpose'] == 'physical_initial_inputs_not_a_campaign'
    assert inputs.validate_input_generation_plan(path, Path.cwd(), output_directory=output, seed=3000) == value
    with pytest.raises(ManifestCodecError):
        decode_manifest(path.read_bytes())
    with pytest.raises(FileExistsError):
        inputs.save_input_generation_plan(Path.cwd(), path, output)


@pytest.mark.parametrize('attack', ['seed', 'workers', 'output', 'physics', 'code', 'kind', 'extra'])
def test_plan_changes_and_unsafe_worker_requests_fail_before_physics(planned, monkeypatch, attack):
    path, output, value = planned
    seed, pools = 3000, 1
    if attack == 'seed': seed = 3035
    if attack == 'workers': pools = 200
    if attack == 'output': output = Path.cwd() / 'data/particle_states/after_zeeman/science'
    if attack == 'physics': value['generation']['dt_s'] = 1e-3
    if attack == 'code': monkeypatch.setattr(inputs, 'code_identity', lambda root: {'git_commit': 'c' * 40, 'files': {}})
    if attack == 'kind': value['kind'] = 'mot_2d_ui_acceptance_v1'
    if attack == 'extra': value['allow_scientific_promotion'] = True
    path.write_text(json.dumps(value))
    def forbidden(*args, **kwargs): raise AssertionError('Unsafe request reached physics')
    monkeypatch.setattr(generation, 'run_and_save_zeeman', forbidden)
    with pytest.raises(ValueError):
        generation.run(seed, pools, output, acceptance_profile='ui_acceptance_v1', input_generation_plan=path)
    assert not output.exists()


def test_initial_generation_uses_normal_physics_and_resumes_verified_pair(planned, monkeypatch):
    plan, output, _ = planned
    calls = physical_stub(monkeypatch)
    path = generation.run(3000, 1, output, acceptance_profile='ui_acceptance_v1', input_generation_plan=plan)
    assert path.name == 'production_zeeman_n32_dt40us_seed3000.npy'
    assert calls[0]['N_particles'] == 32 and calls[0]['seed'] == 3000
    assert calls[0]['dt'] == 4e-5 and calls[0]['stochastic'] is True
    assert calls[0]['zeeman_field_config'] == generation.corrected_field()
    metadata = inputs.read_record(path.with_suffix('.json'))
    assert metadata['input_generation']['plan_file_sha256'] == inputs.file_digest(plan)
    generation.run(3000, 1, output, acceptance_profile='ui_acceptance_v1', input_generation_plan=plan)
    assert len(calls) == 1
    receipt = inputs.read_record(plan.parent / 'generation_receipts/seed_3000.json')
    assert receipt['metadata_sha256'] == inputs.file_digest(path.with_suffix('.json'))
    assert receipt['input_record_sha256'] == inputs.file_digest(plan)


@pytest.mark.parametrize('attack', ['array', 'metadata', 'receipt', 'missing_receipt', 'partial'])
def test_resume_rejects_corruption_without_running_again(planned, monkeypatch, attack):
    plan, output, _ = planned
    calls = physical_stub(monkeypatch)
    path = generation.run(3000, 1, output, acceptance_profile='ui_acceptance_v1', input_generation_plan=plan)
    receipt = plan.parent / 'generation_receipts/seed_3000.json'
    if attack == 'array':
        np.save(path, np.ones((2, 6)))
    if attack == 'metadata':
        value = json.loads(path.with_suffix('.json').read_text())
        value['created_utc'] = 'changed'
        path.with_suffix('.json').write_text(json.dumps(value))
    if attack == 'receipt': receipt.write_text('{}')
    if attack == 'missing_receipt': receipt.unlink()
    if attack == 'partial': path.with_suffix('.json').unlink()
    with pytest.raises((ValueError, OSError)):
        generation.run(3000, 1, output, acceptance_profile='ui_acceptance_v1', input_generation_plan=plan)
    assert len(calls) == 1


def test_generation_authorities_are_mutually_exclusive(planned):
    plan, output, _ = planned
    with pytest.raises(ValueError, match='either'):
        generation.run(3000, 1, output, acceptance_profile='ui_acceptance_v1', input_generation_plan=plan, input_manifest=plan)
    with pytest.raises(SystemExit):
        generation.parse_args(['--seed', '3000', '--input-manifest', str(plan), '--input-generation-plan', str(plan)])
    with pytest.raises(ValueError):
        generation.run(3000, 1, output, input_generation_plan=plan)


@pytest.mark.parametrize('commit', [None, '', 'bad', 'g' * 40])
def test_campaign_generation_requires_valid_frozen_commit_before_physics(tmp_path, monkeypatch, commit):
    from studies.mot_3d_campaign import build_campaign_manifest
    monkeypatch.chdir(tmp_path)
    campaign = tmp_path / 'data/optimization/mot_3d/ui_acceptance/fresh/campaign.json'
    campaign.parent.mkdir(parents=True)
    model = build_campaign_manifest(name='fresh', input_directory='.', upstream={}, roles={}, revision=commit, physical_model_sha256='b' * 64, acceptance_profile_id='ui_acceptance_v1')
    campaign.write_text(json.dumps(model))
    def forbidden(*args, **kwargs): raise AssertionError('Missing provenance reached physics')
    monkeypatch.setattr(generation, 'run_and_save_zeeman', forbidden)
    target = tmp_path / 'data/particle_states/after_zeeman/ui_acceptance/fresh'
    with pytest.raises(ValueError, match='Git commit'):
        generation.run(3035, 1, target, acceptance_profile='ui_acceptance_v1', input_manifest=campaign)
    assert not target.exists()
