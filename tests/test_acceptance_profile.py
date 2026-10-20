import copy
import json
from pathlib import Path

import pytest

from workflow_api.acceptance_profile import (
    ACCEPTANCE_KINDS, PROFILE_ID, assert_acceptance_path,
    assert_same_acceptance_lineage, assert_scientific_source,
    load_acceptance_profile, policy_for_manifest, stage_policy,
)


def manifest(family='mot_2d'):
    profile = load_acceptance_profile()
    return {'kind': ACCEPTANCE_KINDS[family], 'acceptance': profile.provenance()}


def test_policy_is_deeply_immutable_and_versioned():
    profile = load_acceptance_profile()
    with pytest.raises(TypeError):
        profile.family('mot_2d')['stages']['screen']['npools'] = 10
    assert profile.family('mot_2d')['refinement_cumulative_targets'] == (1, 2, 3, 4)
    assert profile.family('mot_3d')['discovery_targets']['angled_donut'] == (4, 4, 4)
    with pytest.raises(ValueError):
        load_acceptance_profile('../ui_acceptance_v1')


def test_policy_preserves_role_partition_handoff_and_selection_cardinality():
    profile = load_acceptance_profile()
    two = profile.family('mot_2d')
    three = profile.family('mot_3d')
    assert sum((tuple(seeds) for seeds in two['role_seeds'].values()), ()) == tuple(range(3000, 3035))
    assert sum((tuple(seeds) for seeds in three['role_seeds'].values()), ()) == two['role_seeds']['sealed_validation']
    assert stage_policy(manifest('mot_3d'), 'preliminary_check')['candidates_per_family'] >= 7
    assert stage_policy(manifest('mot_3d'), 'refinement')['candidates_per_family'] == 16
    assert set(three['final_validation_zeeman_seeds']).isdisjoint(two['role_seeds']['sealed_validation'])


def test_policy_authenticates_physics_and_full_identity():
    value = manifest()
    assert policy_for_manifest(value).profile_id == PROFILE_ID
    for change in ('profile_sha256', 'suitability', 'physical_identity'):
        changed = copy.deepcopy(value)
        changed['acceptance'][change] = 'tampered'
        with pytest.raises(ValueError):
            policy_for_manifest(changed)
    with pytest.raises(ValueError):
        policy_for_manifest({'kind': ACCEPTANCE_KINDS['mot_2d']})


def test_reviewed_policy_file_tampering_is_rejected(monkeypatch):
    original = Path.read_text
    def tamper(path, *args, **kwargs):
        raw = original(path, *args, **kwargs)
        if path.name == 'ui_acceptance_v1.json':
            value = json.loads(raw)
            value['mot_2d']['stages']['screen']['npools'] = 100
            return json.dumps(value)
        return raw
    monkeypatch.setattr(Path, 'read_text', tamper)
    with pytest.raises(ValueError, match='reviewed immutable'):
        load_acceptance_profile()


def test_scientific_defaults_remain_separate_and_promotion_fails_closed():
    scientific = {'kind': 'mot_2d_s0_campaign'}
    assert policy_for_manifest(scientific) is None
    assert stage_policy(scientific, 'screen') is None
    assert_scientific_source(scientific)
    with pytest.raises(ValueError):
        policy_for_manifest({**scientific, 'acceptance': manifest()['acceptance']})
    with pytest.raises(ValueError):
        assert_scientific_source({'upstream': [manifest()]})
    with pytest.raises(ValueError):
        assert_same_acceptance_lineage(manifest(), scientific)
    assert_same_acceptance_lineage(manifest(), manifest('mot_3d'))


def test_acceptance_paths_reject_science_escape_and_symlinks(tmp_path):
    allowed = tmp_path / 'data/optimization/mot_2d/ui_acceptance/run1'
    assert assert_acceptance_path(allowed, tmp_path) == allowed
    for target in ('data/optimization/mot_2d/science', '../elsewhere', 'data/acceptance'):
        with pytest.raises(ValueError):
            assert_acceptance_path(target, tmp_path)
    link = tmp_path / 'data/acceptance/run1'
    link.parent.mkdir(parents=True)
    link.symlink_to(tmp_path / 'science')
    with pytest.raises(ValueError):
        assert_acceptance_path(link, tmp_path)


def two_d_manifest():
    from workflow_api.mot_2d_spec import build_manifest
    return build_manifest(name='UI acceptance', s0_values=[1.3], ensemble_directory='data/particle_states/after_zeeman/ui_acceptance/source', zeeman_profile='corrected', frozen_inputs={}, git_commit='a' * 40, physical_model_sha256='b' * 64, hashed_files=[], acceptance_profile_id=PROFILE_ID)


def test_two_d_renderer_uses_profile_resources_and_four_checkpoint_boundaries(tmp_path):
    from workflow_api.mot_2d_plan import render_campaign_files, render_refine_transition
    value = two_d_manifest()
    destination = tmp_path / 'data/optimization/mot_2d/ui_acceptance/run1'
    initial = render_campaign_files(value, destination, tmp_path)
    assert b'ncpus=1:mem=4gb' in initial['jobs/01_smoke.pbs']
    assert b'ytterbium_lab_simulation_ui_acceptance' in initial['jobs/01_smoke.pbs']
    assert b'${HOME}/venvs/atomsmltr-ui-test/bin/activate' in initial['jobs/01_smoke.pbs']
    assert b'${HOME}/venvs/atomsmltr/bin/activate' not in initial['jobs/01_smoke.pbs']
    assert b'${HOME}/ytterbium_lab_simulation_new' not in initial['jobs/01_smoke.pbs']
    value['stage'] = 'screen'
    rows = [{'s0': 1.3, 'mean_conditional_efficiency': 0.5, 'detuning_gamma': -1.4 + 0.1 * index, 'magnet_radius': 0.047, 'source': f'screen/{index}.json'} for index in range(3)]
    files = render_refine_transition(value, destination, tmp_path, rows)
    for index in range(1, 5):
        script = files[f'jobs/03_refine_round_{index:02d}.pbs']
        assert f'--target-trials {index}'.encode() in script
        assert b'ncpus=10:mem=8gb:vnode=gd002' in script
    updated = json.loads(files['campaign.json'])
    assert updated['stages']['refine']['cumulative_trial_targets'] == [1, 2, 3, 4]
    assert updated['acceptance'] == value['acceptance']


def test_two_d_policy_rejects_unreviewed_workloads_and_scientific_destination(tmp_path):
    from workflow_api.mot_2d_spec import validate_campaign_policy
    from workflow_api.mot_2d_plan import render_campaign_files
    value = two_d_manifest()
    value['fixed_design']['particle_counts']['screen'] = 2000
    with pytest.raises(ValueError, match='frozen design'):
        validate_campaign_policy(value)
    with pytest.raises(ValueError):
        render_campaign_files(two_d_manifest(), tmp_path / 'data/optimization/mot_2d/science', tmp_path)


@pytest.mark.parametrize('receiver', [
    'zeus_screening_remote', 'zeus_screen_submission_remote', 'zeus_refinement_remote',
    'zeus_refinement_submission_remote', 'zeus_confirmation_remote',
    'zeus_confirmation_submission_remote', 'zeus_sensitivity_remote',
    'zeus_sensitivity_submission_remote', 'zeus_production_remote',
    'zeus_production_submission_remote', 'zeus_finalization_remote',
])
@pytest.mark.parametrize('acceptance_on_science', [True, False])
def test_remote_receiver_rejects_crossed_identity_before_mutation(tmp_path, receiver, acceptance_on_science):
    import importlib
    module = importlib.import_module(f'workflow_api.{receiver}')
    value = two_d_manifest() if acceptance_on_science else {'kind': 'mot_2d_s0_campaign'}
    checkout = 'ytterbium_lab_simulation_new' if acceptance_on_science else 'ytterbium_lab_simulation_ui_acceptance'
    root = tmp_path / checkout
    campaign = root / 'data/optimization/mot_2d/ui_acceptance/run1'
    campaign.mkdir(parents=True)
    (campaign / 'campaign.json').write_text(json.dumps(value))
    before = sorted(path.relative_to(root).as_posix() for path in root.rglob('*'))
    with pytest.raises(SystemExit):
        module._authorize_acceptance_campaign(campaign, root)
    assert sorted(path.relative_to(root).as_posix() for path in root.rglob('*')) == before


def test_physical_two_d_stage_refuses_acceptance_manifest_on_scientific_path(tmp_path):
    from studies.mot_2d_s0_campaign import read_stage_manifest
    campaign = tmp_path / 'data/optimization/mot_2d/science'
    campaign.mkdir(parents=True)
    (campaign / 'campaign.json').write_text(json.dumps(two_d_manifest()))
    with pytest.raises(ValueError, match='dedicated acceptance'):
        read_stage_manifest(campaign)


def test_review_resources_and_pbs_use_identical_optional_node(monkeypatch):
    from types import SimpleNamespace
    from workflow_api import mot_2d_spec, mot_2d_plan
    policy = {'ncpus': 10, 'memory_gb': 4, 'walltime_seconds': 3600}
    profile = SimpleNamespace(policy={'scheduler': {'vnode': 'gd002'}}, stage=lambda family, stage: policy)
    monkeypatch.setattr(mot_2d_spec, 'validate_campaign_policy', lambda manifest: profile)
    monkeypatch.setattr(mot_2d_plan, 'validate_campaign_policy', lambda manifest: profile)
    assert mot_2d_spec.reviewed_job_resources({}, 'screen', {}) == {
        'cores_per_task': 10, 'memory_per_task_bytes': 4 * 1024**3,
        'walltime_seconds': 3600, 'vnode': 'gd002'}
    script = mot_2d_plan._acceptance_pbs({}, 'screen', b'#PBS -l select=1:ncpus=200:mem=64gb\n')
    assert script == b'#PBS -l select=1:ncpus=10:mem=4gb:vnode=gd002\n'


def test_measured_runtime_resource_revision_preserves_entire_physics_and_workload():
    import hashlib
    path = Path(__file__).resolve().parents[1] / 'workflow_api/specifications/ui_acceptance_v1.json'
    policy = json.loads(path.read_text())
    physics_hash = hashlib.sha256(json.dumps(policy['physics'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert physics_hash == '03c156054adfc0896f69216473e49dff466e6810b10d3f0508defbd5510a81e4'
    for family in ('mot_2d', 'mot_3d'):
        for stage in policy[family]['stages'].values():
            for field in ('npools', 'ncpus', 'memory_gb', 'walltime_seconds', 'merge_ncpus', 'merge_memory_gb', 'merge_walltime_seconds', 'array_throttle'):
                stage.pop(field, None)
    policy['generation'].pop('jobs')
    invariant = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert invariant == '700293772dc54b4419d6776873b4c44326d720585a61fc256e4a527a76a17746'


def test_profile_resources_fit_measured_physical_workload_without_changing_budgets():
    profile = load_acceptance_profile()
    for name, stage in profile.family('mot_2d')['stages'].items():
        expected = (1, 4) if name == 'smoke' else (24, 16) if name == 'production' else (10, 8)
        assert (stage['npools'], stage['ncpus'], stage['memory_gb'], stage['walltime_seconds']) == (expected[0], expected[0], expected[1], 3600)
    for name, stage in profile.family('mot_3d')['stages'].items():
        heavy = name in ('finalist_selection', 'final_validation')
        assert (stage['npools'], stage['ncpus'], stage['memory_gb'], stage['walltime_seconds']) == ((100, 100, 64, 3600) if heavy else (4, 4, 4, 3600))
        assert stage.get('array_throttle') == (1 if heavy else None)
        assert stage['merge_ncpus'] == 1
    assert dict(profile.policy['generation']['jobs']['mot_2d']) == {
        'npools': 10, 'ncpus': 10, 'memory_gb': 8, 'walltime_seconds': 3600}
