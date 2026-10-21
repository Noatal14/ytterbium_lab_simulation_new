"""The real acceptance bootstrap stays inspectable without scientific promotion."""
from copy import deepcopy
import json
import os

import pytest

from studies.mot_3d_campaign import build_campaign_manifest
from workflow_api.acceptance_profile import assert_scientific_source, load_acceptance_profile
from workflow_api.discovery import build_registry, get_campaign, list_campaigns
from workflow_api.mot_3d import read_campaign


def _model(root, *, acceptance=True):
    (root / '.git').mkdir(exist_ok=True)
    name = 'TESTONLY_catalog' if acceptance else 'ordinary'
    campaign = root / 'data/optimization/mot_3d' / ('ui_acceptance' if acceptance else '') / name
    campaign.mkdir(parents=True)
    manifest = build_campaign_manifest(
        name=name, input_directory='data/acceptance/survivors', upstream={}, roles={},
        revision='a' * 40, physical_model_sha256='b' * 64,
        acceptance_profile_id='ui_acceptance_v1' if acceptance else None,
    )
    (campaign / 'campaign.json').write_text(json.dumps(manifest))
    return campaign, manifest


def test_acceptance_reader_uses_profile_counts_without_changing_physical_design(tmp_path):
    campaign, manifest = _model(tmp_path)
    before = (campaign / 'campaign.json').read_bytes()
    summary = read_campaign(campaign)
    profile = load_acceptance_profile()
    expected = sum(sum(profile.family('mot_3d')['discovery_targets'][f]) for f in summary.families)
    discovery = next(row for row in summary.progress if row.stage == 'discovery')
    assert discovery.expected == expected == 24 and discovery.completed == 0
    assert summary.kind == 'mot_3d_ui_acceptance_v1'
    assert manifest['design']['optimization_bounds']['angled_donut']['total_discovery_trials'] == 350
    assert (campaign / 'campaign.json').read_bytes() == before
    with pytest.raises(ValueError, match='cannot be promoted'):
        assert_scientific_source(manifest)


def test_scientific_reader_keeps_original_counts_and_bytes(tmp_path):
    campaign, _ = _model(tmp_path, acceptance=False)
    before = (campaign / 'campaign.json').read_bytes()
    summary = read_campaign(campaign)
    assert summary.kind == 'mot_3d_campaign_v2'
    assert next(row for row in summary.progress if row.stage == 'discovery').expected == 950
    assert (campaign / 'campaign.json').read_bytes() == before


@pytest.mark.parametrize('attack', ['profile_sha', 'physical_identity', 'solver', 'horizon', 'kind_marker', 'missing_marker'])
def test_acceptance_reader_rejects_tampered_profile_or_physics(tmp_path, attack):
    campaign, manifest = _model(tmp_path)
    if attack == 'profile_sha':
        manifest['acceptance']['profile_sha256'] = '0' * 64
    elif attack == 'physical_identity':
        manifest['acceptance']['physical_identity']['numerical_policy_sha256'] = '0' * 64
    elif attack == 'solver':
        manifest['design']['solver'] = 'other'
    elif attack == 'horizon':
        manifest['design']['t_max_s'] = .001
    elif attack == 'kind_marker':
        manifest['kind'] = 'mot_3d_campaign_v2'
    else:
        del manifest['acceptance']
    (campaign / 'campaign.json').write_text(json.dumps(manifest))
    before = (campaign / 'campaign.json').read_bytes()
    with pytest.raises(ValueError):
        read_campaign(campaign)
    catalog = list_campaigns(tmp_path)
    assert catalog['invalid_count'] == 1 and catalog['campaigns'] == []
    assert (campaign / 'campaign.json').read_bytes() == before


@pytest.mark.parametrize('attack', ['acceptance_outside', 'scientific_inside', 'name_alias'])
def test_acceptance_reader_rejects_namespace_crossing(tmp_path, attack):
    campaign, manifest = _model(tmp_path)
    if attack == 'acceptance_outside':
        destination = tmp_path / 'data/optimization/mot_3d/TESTONLY_catalog'
        campaign.rename(destination)
        campaign = destination
    elif attack == 'scientific_inside':
        manifest['kind'] = 'mot_3d_campaign_v2'
        del manifest['acceptance']
        (campaign / 'campaign.json').write_text(json.dumps(manifest))
    else:
        manifest['name'] = 'other'
        (campaign / 'campaign.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        read_campaign(campaign)
    assert list_campaigns(tmp_path)['invalid_count'] == 1


@pytest.mark.skipif(os.name == 'nt', reason='Real upstream receiver fixture uses POSIX Zeus scheduler scripts; portable reader attacks run natively')
def test_genuine_bootstrap_is_in_catalog_and_detail_without_mutation_or_submission(tmp_path, monkeypatch):
    from tests.test_mot_3d_receiver_protocol_chain import _completed_upstream
    from studies import mot_3d_campaign
    from workflow_api.mot_3d_bootstrap import Mot3DDiscoveryBootstrapService

    chain = _completed_upstream(tmp_path, monkeypatch)
    # Keep the actual finished upstream bytes and validator lineage. As in the
    # existing protocol test, provision those bytes into its independent clone.
    import shutil
    shutil.copytree(chain.remote / 'data', chain.local / 'data', dirs_exist_ok=True)
    with monkeypatch.context() as scoped:
        scoped.chdir(chain.local)
        scoped.setattr(mot_3d_campaign, '__file__', str(chain.local / 'studies/mot_3d_campaign.py'))
        service = Mot3DDiscoveryBootstrapService(chain.local, acceptance_profile_id='ui_acceptance_v1')
        source = service.status({})['sources'][0]
        preview = service.preview({'source_id': source['source_id'], 'campaign_name': 'TESTONLY_catalog_real'}, session_id='catalog')
        result = service.confirm({'preview_token': preview['preview_token']}, session_id='catalog')
    assert result['lifecycle'] == 'discovery_prepared' and result['submitted_to_zeus'] is False
    before = {p.relative_to(chain.local): p.read_bytes() for p in (chain.local / 'data').rglob('*') if p.is_file()}
    calls = tuple(chain.qsub_calls)
    registry = build_registry(chain.local)
    entry = next(e for e in registry.values() if e.family == 'mot_3d')
    catalog = list_campaigns(chain.local)
    assert catalog['invalid_count'] == 0
    row = next(r for r in catalog['campaigns'] if r['id'] == entry.campaign_id)
    assert row == get_campaign(chain.local, entry.campaign_id)
    assert row['kind'] == 'mot_3d_ui_acceptance_v1' and row['scientific_role'] == 'acceptance-only'
    assert row['trust'] == 'trusted-current' and row['remote_preparation']['status'] == 'ready'
    assert row['stage'] == 'discovery' and row['families'] == ['angled_donut', 'single_pass']
    assert next(p for p in row['progress'] if p['stage'] == 'discovery')['expected'] == 24
    assert any('TEST ONLY' in warning['message'] for warning in row['warnings'])
    _assert_closed_producer_contract_rejects_mutations(chain.local, entry, json.loads(entry.manifest.read_bytes()))
    assert tuple(chain.qsub_calls) == calls and len(calls) == 9
    assert {p.relative_to(chain.local): p.read_bytes() for p in (chain.local / 'data').rglob('*') if p.is_file()} == before


def test_normal_scientific_bootstrap_matches_catalog_contract(tmp_path):
    """Use the established validated-handoff fixture shape, not a relabelled acceptance manifest."""
    from tests.test_mot_3d_campaign import _write_ensemble
    from workflow_api.mot_3d_bootstrap import Mot3DDiscoveryBootstrapService

    (tmp_path / '.git').mkdir()
    inputs = tmp_path / 'data/particle_states/after_2d_mot/inputs'
    inputs.mkdir(parents=True)
    seeds = list(range(3015, 3035))
    for seed in seeds:
        state = _write_ensemble(inputs, seed, mot_seed=40000 + seed)
        sidecar = state.with_suffix('.json')
        metadata = json.loads(sidecar.read_bytes())
        metadata['design'].update(npools=150, uses_all_available_particles=True)
        sidecar.write_text(json.dumps(metadata))
    design = metadata['design']
    upstream = tmp_path / 'data/optimization/mot_2d/upstream'
    upstream.mkdir(parents=True)
    laboratory = {k: design[k] for k in ('laboratory_spec_version', 'laboratory_spec_sha256', 'zeeman_profile_sha256')}
    (upstream / 'campaign.json').write_text(json.dumps({
        'kind': 'mot_2d_s0_campaign', 'stage': 'complete', 's0_values': [1.3],
        'seed_roles': {'sealed_validation': seeds},
        'mot_seeds': {'sealed_validation': [40000 + seed for seed in seeds]},
        'provenance': {'git_commit': design['git_commit'], 'physical_model_sha256': 'b' * 64},
        'stages': {'final_report': str(upstream / 'final_report.json')},
        'fixed_design': {'final_dt_s': design['dt_s'], 'solver': design['stochastic_solver']},
        'ensemble_source': {'directory': design['ensemble_dir'], 'zeeman_profile': design['zeeman_profile'], **laboratory},
        'input_ensembles': {'sealed_validation': [{'zeeman_seed': seed, **laboratory} for seed in seeds]},
    }))
    (upstream / 'final_report.json').write_text(json.dumps({
        'kind': 'mot_2d_s0_campaign_final_report',
        'results': [{'s0': 1.3, 'survivor_states_directory': str(inputs),
                     'recommended_parameters': metadata['parameters']}],
    }))
    service = Mot3DDiscoveryBootstrapService(tmp_path, revision_provider=lambda: 'a' * 40,
        physical_hash_provider=lambda: 'b' * 64, dirty_provider=lambda: ())
    source = service.status({})['sources'][0]
    preview = service.preview({'source_id': source['source_id'], 'campaign_name': 'normal_bootstrap'}, 'scientific')
    service.confirm({'preview_token': preview['preview_token']}, 'scientific')
    entry = next(e for e in build_registry(tmp_path).values() if e.family == 'mot_3d')
    row = get_campaign(tmp_path, entry.campaign_id)
    assert row['kind'] == 'mot_3d_campaign_v2' and row['scientific_role'] == 'candidate-selection'
    assert row['trust'] == 'trusted-current' and row['remote_preparation']['status'] == 'ready'
    assert next(p for p in row['progress'] if p['stage'] == 'discovery')['expected'] == 950
    manifest_path = entry.manifest
    original = manifest_path.read_bytes()
    model = json.loads(original)
    _assert_closed_producer_contract_rejects_mutations(tmp_path, entry, model)
    assert manifest_path.read_bytes() == original


def _assert_closed_producer_contract_rejects_mutations(root, entry, model):
    from workflow_api.mot_3d_provenance import input_registry_digest
    original = entry.manifest.read_bytes()
    record = model['input_roles']['discovery'][0]
    metadata_path = root / record['metadata_path']
    original_metadata = metadata_path.read_bytes()
    cases = ('npools', 'npools_bool', 'uses_all', 'uses_all_int', 'unknown_extra',
             'required_design', 'metadata_design', 'coordinated_npools', 'coordinated_unknown',
             'jobs_missing', 'jobs_foreign', 'jobs_extra')
    if 'acceptance' in model:
        cases += ('extra_profile',)
    try:
        for attack in cases:
            changed = deepcopy(model)
            row = changed['input_roles']['discovery'][0]
            if attack == 'npools':
                row['source_design']['npools'] += 1
            elif attack == 'npools_bool':
                row['source_design']['npools'] = True
            elif attack == 'uses_all':
                row['source_design']['uses_all_available_particles'] = False
            elif attack == 'uses_all_int':
                row['source_design']['uses_all_available_particles'] = 1
            elif attack == 'unknown_extra':
                row['source_design']['unknown'] = 1
            elif attack == 'required_design':
                row['source_design']['dt_s'] *= 2
            elif attack == 'extra_profile':
                row['source_design']['acceptance']['profile_sha256'] = '0' * 64
            elif attack in {'coordinated_npools', 'coordinated_unknown'}:
                if attack == 'coordinated_npools':
                    row['source_design']['npools'] += 1
                else:
                    row['source_design']['unknown'] = 1
                metadata = json.loads(original_metadata)
                metadata['design'] = deepcopy(row['source_design'])
                metadata_path.write_text(json.dumps(metadata))
                import hashlib
                row['metadata_sha256'] = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
            elif attack == 'metadata_design':
                metadata = json.loads(original_metadata)
                metadata['design']['npools'] += 1
                metadata_path.write_text(json.dumps(metadata))
                import hashlib
                row['metadata_sha256'] = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
            elif attack == 'jobs_missing':
                changed['jobs']['discovery_rounds']['single_pass'].pop()
            elif attack == 'jobs_foreign':
                changed['jobs']['smoke']['angled_donut'] = changed['jobs']['smoke']['single_pass']
            else:
                changed['jobs']['unknown'] = 'jobs/foreign.pbs'
            changed['design']['timestep_evidence']['source_handoff']['input_registry_sha256'] = input_registry_digest(changed['input_roles'])
            entry.manifest.write_text(json.dumps(changed))
            result = get_campaign(root, entry.campaign_id)
            assert result['trust'] == 'legacy-incomplete', attack
            assert result['remote_preparation']['status'] == 'unavailable', attack
            assert result['next_plan'] is None, attack
            metadata_path.write_bytes(original_metadata)
    finally:
        entry.manifest.write_bytes(original)
        metadata_path.write_bytes(original_metadata)
