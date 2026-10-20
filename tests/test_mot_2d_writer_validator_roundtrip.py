"""Real Optuna/JSON writers roundtrip through strict campaign validators.

Only the physical trajectory solver and input loading are isolated; production
writers, SQLite study attributes and every validator run unchanged.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from studies.mot_2d import optimization
from workflow_api.mot_2d_spec import build_manifest, ROLE_SEEDS
from workflow_api.mot_2d_smoke import validate_smoke_outputs, SmokeValidationError
from workflow_api.mot_2d_screen import validate_screen_outputs, validate_refine_outputs, ScreenValidationError
from workflow_api.mot_2d_plan import render_refine_transition


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def _fixture(tmp_path, monkeypatch, acceptance):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(optimization, '__file__', str(tmp_path / 'studies/mot_2d/optimization.py'))
    monkeypatch.setattr(optimization.subprocess, 'check_output', lambda *args, **kwargs: 'a' * 40)
    available = 32 if acceptance else 40_000
    initial = 32 if acceptance else 50_000
    relative = 'data/particle_states/after_zeeman/' + ('ui_acceptance/source' if acceptance else 'source')
    frozen = {role: [{'zeeman_seed': seed, 'path': f'{relative}/production_zeeman_seed{seed}.npy',
                      'survivor_count': available, 'generation': {'n_initial_atoms': initial}}
                     for seed in seeds] for role, seeds in ROLE_SEEDS.items()}
    manifest = build_manifest(name='writer_roundtrip', s0_values=[1.3], ensemble_directory=relative,
                              zeeman_profile='corrected_projectant_19ring_20261005', frozen_inputs=frozen,
                              git_commit='a' * 40, physical_model_sha256='b' * 64, hashed_files=[],
                              acceptance_profile_id='ui_acceptance_v1' if acceptance else None)
    root = tmp_path / 'data/optimization/mot_2d' / ('ui_acceptance' if acceptance else '') / manifest['name']
    _write(root / 'campaign.json', manifest)
    def load(**kwargs):
        particles = kwargs['particles_per_ensemble'] or available
        return [{'path': Path(relative) / f'production_zeeman_seed{seed}.npy', 'zeeman_seed': seed,
                 'states': np.zeros((particles, 6)), 'n_available': available,
                 'selection_method': 'deterministic_random_without_replacement' if particles < available else 'all_particles',
                 'subset_seed': 100_000 + seed, 'zeeman_survival_fraction': available / initial}
                for seed in kwargs['zeeman_seeds']]
    monkeypatch.setattr(optimization, 'load_production_ensembles', load)
    monkeypatch.setattr(optimization, 'mot_simulation_paired_ensembles',
                        lambda **kwargs: [([], 0, np.empty((0, 6))) for _ in kwargs['survivor_state_ensembles']])
    return root, manifest


def _run(root, manifest, stage):
    manifest['stage'] = stage
    _write(root / 'campaign.json', manifest)
    role = 'refinement' if stage == 'refine' else 'discovery'
    seeds = manifest['seed_roles'][role][:1] if stage == 'smoke' else manifest['seed_roles'][role]
    mot_seeds = manifest['mot_seeds'][role][:1] if stage == 'smoke' else manifest['mot_seeds'][role]
    tasks = [{'s0': 1.3, 'worker': worker} for worker in range(3)] if stage == 'screen' else (
        json.loads((root / 'refine/tasks.json').read_text()) if stage == 'refine' else [{'s0': 1.3, 'worker': 0}])
    if stage == 'screen':
        _write(root / 'screen/tasks.json', tasks)
    for task in tasks:
        worker = task['worker']
        directory = root / stage / 's0_1p300000'
        if stage != 'smoke':
            directory /= f'worker{worker}'
        count = 1 if stage == 'smoke' else manifest['fixed_design']['trial_budgets'][f'{stage}_per_worker']
        particles = 2 if stage == 'smoke' else manifest['fixed_design']['particle_counts'][stage]
        pools = (1 if stage == 'smoke' else 10) if 'acceptance' in manifest else 1
        arguments = ['--fixed-s0', '1.3', '--n-trials', str(count), '--n-ensembles', str(len(seeds)),
                     '--particles-per-ensemble', str(particles), '--npools', str(pools), '--dt', '1.25e-6',
                     '--stochastic-solver', 'hybrid', '--ensemble-dir', manifest['ensemble_source']['directory'],
                     '--ensemble-identity', manifest['ensemble_source']['directory'],
                     '--zeeman-seeds', *map(str, seeds), '--mot-seeds', *map(str, mot_seeds),
                     '--mot-seed-start', '4000' if stage == 'smoke' else '24000',
                     '--sampler-seed', str(42 if stage == 'smoke' else (137 if stage == 'screen' else 701) + worker),
                     '--campaign-design-id', 'b' * 64,
                     '--study-name', 'smoke' if stage == 'smoke' else f"{manifest['name']}_{stage}_s0_1p300000_w{worker}",
                     '--output-dir', str(directory)]
        if stage == 'refine':
            arguments += ['--detuning-bounds', *map(str, task['bounds']['detuning']),
                          '--magnet-radius-bounds-m', *map(str, task['bounds']['radius'])]
        if 'acceptance' in manifest:
            arguments += ['--acceptance-profile', 'ui_acceptance_v1', '--input-manifest', str(root / 'campaign.json')]
        optimization.optimize_mot(optimization.parse_args(arguments))


@pytest.mark.parametrize('acceptance', [False, True], ids=['scientific', 'TEST-ONLY'])
@pytest.mark.parametrize('stage', ['smoke', 'screen', 'refine'])
def test_real_optimizer_writer_roundtrips_exact_designs(tmp_path, monkeypatch, acceptance, stage):
    root, manifest = _fixture(tmp_path, monkeypatch, acceptance)
    if stage == 'refine':
        _run(root, manifest, 'screen')
        rows = validate_screen_outputs(root, manifest)
        rendered = render_refine_transition(manifest, root, tmp_path, rows)
        for name, raw in rendered.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        manifest = json.loads((root / 'campaign.json').read_text())
    _run(root, manifest, stage)
    validator = {'smoke': validate_smoke_outputs, 'screen': validate_screen_outputs, 'refine': validate_refine_outputs}[stage]
    assert validator(root, manifest)
    paths = [root / stage / 's0_1p300000' / ('trials/trial_0000.json' if stage == 'smoke' else 'worker0/trials/trial_0000.json'),
             root / stage / 's0_1p300000' / ('summary.json' if stage == 'smoke' else 'worker0/summary.json')]
    if not acceptance:
        assert all('acceptance' not in json.loads(path.read_bytes())['design'] for path in paths)
        return
    for path in paths:
        original = path.read_bytes()
        for attack in ['missing', 'wrong_hash', 'wrong_profile', 'marker_extra', 'extra']:
            value = json.loads(original)
            if attack == 'missing':
                value['design'].pop('acceptance')
            elif attack == 'wrong_hash':
                value['design']['acceptance']['profile_sha256'] = '0' * 64
            elif attack == 'wrong_profile':
                value['design']['acceptance']['profile_id'] = 'unreviewed_profile'
            elif attack == 'marker_extra':
                value['design']['acceptance']['unreviewed'] = True
            else:
                value['design']['unreviewed'] = True
            _write(path, value)
            with pytest.raises((SmokeValidationError, ScreenValidationError)):
                validator(root, manifest)
        path.write_bytes(original)
        assert validator(root, manifest)


@pytest.mark.parametrize('acceptance', [False, True], ids=['scientific', 'TEST-ONLY'])
@pytest.mark.parametrize('stage', ['confirmation', 'sensitivity'])
def test_campaign_evaluation_writer_keeps_exact_acceptance_marker(tmp_path, monkeypatch, acceptance, stage):
    from studies import mot_2d_s0_campaign as campaign
    from workflow_api.mot_2d_validation import _validated_evaluation
    root, manifest = _fixture(tmp_path, monkeypatch, acceptance)
    manifest['stage'] = stage
    _write(root / 'campaign.json', manifest)
    task = {'s0': 1.3, 'parameters': {'s0': 1.3, 'detuning_gamma': -1.0, 'magnet_radius': 0.05},
            ('candidate_index' if stage == 'confirmation' else 'point_index'): 0}
    if stage == 'sensitivity':
        task.update(offsets={}, requested_offsets={})
    _write(root / stage / 'tasks.json', [task])
    monkeypatch.setattr(campaign, 'REPOSITORY_ROOT', tmp_path)
    monkeypatch.setattr(campaign, 'assert_design', lambda manifest: None)
    monkeypatch.setattr(campaign, 'stage_ensembles', lambda value, current_stage, particles:
                        optimization.load_production_ensembles(particles_per_ensemble=particles,
                            zeeman_seeds=value['seed_roles']['held_out_confirmation']))
    campaign.evaluate_task(root, stage, 0)
    path = root / stage / 's0_1p300000/point_00.json'
    assert _validated_evaluation(path, manifest, stage, task, root)
    if acceptance:
        original = path.read_bytes()
        for attack in ['missing', 'wrong_hash', 'wrong_profile', 'marker_extra']:
            value = json.loads(original)
            if attack == 'missing':
                value['design'].pop('acceptance')
            elif attack == 'wrong_hash':
                value['design']['acceptance']['profile_sha256'] = '0' * 64
            elif attack == 'wrong_profile':
                value['design']['acceptance']['profile_id'] = 'unreviewed_profile'
            else:
                value['design']['acceptance']['unreviewed'] = True
            _write(path, value)
            with pytest.raises(ValueError, match='Acceptance result lost'):
                _validated_evaluation(path, manifest, stage, task, root)
        path.write_bytes(original)


@pytest.mark.parametrize('acceptance', [False, True], ids=['scientific', 'TEST-ONLY'])
def test_final_production_writer_roundtrips_exact_marker_without_relabeling(tmp_path, monkeypatch, acceptance):
    from studies.mot_2d import production
    from workflow_api.mot_2d_validation import _validated_production_replicate
    root, manifest = _fixture(tmp_path, monkeypatch, acceptance)
    manifest['stage'] = 'production'
    _write(root / 'campaign.json', manifest)
    monkeypatch.setattr(production, 'load_production_ensembles', optimization.load_production_ensembles)
    output = root / 'production/s0_1p300000'
    arguments = ['--zeeman-seeds', '3015', '--mot-seeds', '43015', '--s0', '1.3', '--detuning-gamma', '-1.0',
                 '--magnet-radius-mm', '50', '--npools', '100' if acceptance else '150',
                 '--ensemble-dir', manifest['ensemble_source']['directory'],
                 '--ensemble-identity', manifest['ensemble_source']['directory'],
                 '--expected-zeeman-profile', manifest['ensemble_source']['zeeman_profile'],
                 '--expected-git-commit', 'a' * 40, '--output-dir', str(output),
                 '--states-dir', str(root / 'survivor_states/s0_1.3')]
    if acceptance:
        arguments += ['--acceptance-profile', 'ui_acceptance_v1', '--input-manifest', str(root / 'campaign.json')]
    production.run_seeds(production.parse_args(arguments))
    path = output / 'replicates/zeeman_seed3015.json'
    task = {'zeeman_seed': 3015, 'mot_seed': 43015,
            'parameters': {'s0': 1.3, 'detuning_gamma': -1.0, 'magnet_radius': 0.05}}
    assert _validated_production_replicate(path, manifest, task, root)
    original = path.read_bytes()
    if not acceptance:
        assert 'acceptance' not in json.loads(original)['design']
        return
    for attack in ['missing', 'wrong_hash', 'wrong_profile', 'marker_extra']:
        value = json.loads(original)
        if attack == 'missing':
            value['design'].pop('acceptance')
        elif attack == 'wrong_hash':
            value['design']['acceptance']['profile_sha256'] = '0' * 64
        elif attack == 'wrong_profile':
            value['design']['acceptance']['profile_id'] = 'unreviewed_profile'
        else:
            value['design']['acceptance']['unreviewed'] = True
        _write(path, value)
        with pytest.raises(ValueError):
            _validated_production_replicate(path, manifest, task, root)
    path.write_bytes(original)
