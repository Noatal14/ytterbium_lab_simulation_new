"""Versioned TESTONLY input ordering; all capture measurements remain fixture-only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from studies.mot_3d_campaign import build_campaign_manifest
from studies.mot_3d.discovery.select import select_candidates
from studies.mot_3d.discovery.optimize import build_profile_from_parameters
from workflow_api import mot_3d_workload as workload
from workflow_api.acceptance_profile import (
    load_acceptance_profile, policy_for_manifest, policy_for_marker,
    source_profile_for_consumer, assert_scientific_source,
)

FIXTURES = Path(__file__).parent / 'fixtures'


def model(profile='ui_acceptance_v2'):
    return build_campaign_manifest(name='TESTONLY_v2', input_directory='data/acceptance/source',
        upstream={}, roles={}, revision='a'*40, physical_model_sha256='b'*64,
        acceptance_profile_id=profile)


def source_summary(family):
    # Only genuine captured Discovery values carried into the P45 Preliminary
    # summary are projected; recomputed laser profiles are deterministic inputs.
    captured = json.loads((FIXTURES/'p45-preliminary-boundary-summaries.json').read_bytes())[family]
    rows=[]
    for row in sorted(captured['ranked_candidates'],key=lambda x:x['discovery_rank']):
        profile,parameters,derived=build_profile_from_parameters(family,row['parameters'])
        rows.append({'worker_index':row['worker_index'],'trial_number':row['trial_number'],
            'usable_at_end_fraction':row['discovery_usable_at_end_fraction'],
            'usable_at_end_count':row['discovery_usable_at_end_count'],
            'parameters':parameters,'derived_parameters':derived,'resolved_profile':profile})
    return {'ranked_trials':rows}


def test_both_immutable_profiles_preserve_all_physics_workloads_and_v1_bytes():
    path=Path(__file__).parents[1]/'workflow_api/specifications/ui_acceptance_v1.json'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == '001cc9d89ddc291522bc0ded876b58ebb9b6dae86c24f28963fe2ca0bc09952f'
    old=load_acceptance_profile();new=load_acceptance_profile('ui_acceptance_v2')
    assert old.sha256=='f4f666548ada90aab2938878822dfe5173a140496cadbd7baba68144ad873148'
    for key in ('physics','mot_2d','scheduler','generation'):
        assert old.policy[key]==new.policy[key]
    actual=dict(new.family('mot_3d'));actual.pop('discovery_candidate_permutation');actual.pop('accepted_upstream')
    assert actual==dict(old.family('mot_3d'))
    assert policy_for_manifest(model()).profile_id=='ui_acceptance_v2'
    with pytest.raises(TypeError):new.family('mot_3d')['accepted_upstream']['survivor_files']['x']='x'


@pytest.mark.parametrize('family',['angled_donut','single_pass'])
def test_only_v2_permutates_new_input_ids_without_changing_source_rows(family):
    summary=source_summary(family);before=deepcopy(summary)
    science=select_candidates(summary,family,count=12)
    assert workload.discovery_selection(model(None),summary,family)==science
    assert workload.discovery_selection(model('ui_acceptance_v1'),summary,family)==science
    actual=workload.discovery_selection(model(),summary,family)
    order=list(range(12)) if family=='angled_donut' else [2,1,0,*range(3,12)]
    for i,j in enumerate(order):
        assert actual['candidates'][i] == {**science['candidates'][j],'candidate_id':f'{family}_{i:02d}'}
    assert summary==before
    workload.validate_discovery_selection(model(),summary,family,actual)
    if family=='single_pass':
        assert actual['candidates'][0]['parameters']['blue_crossing_z_offset_m']==-.045
        with pytest.raises(ValueError):workload.validate_discovery_selection(model(),summary,family,science)


@pytest.mark.parametrize('attack',['missing','duplicate','wrong_id','extra'])
def test_versioned_validator_rejects_changed_selected_inputs(attack):
    summary=source_summary('single_pass');selected=workload.discovery_selection(model(),summary,'single_pass')
    if attack=='missing':selected['candidates'].pop()
    elif attack=='duplicate':selected['candidates'][1]=deepcopy(selected['candidates'][0])
    elif attack=='wrong_id':selected['candidates'][0]['candidate_id']='wrong'
    else:selected['unexpected']=True
    with pytest.raises(ValueError):workload.validate_discovery_selection(model(),summary,'single_pass',selected)


def authority():return json.loads((FIXTURES/'o16-acceptance-source-authority.json').read_bytes())


def test_only_reviewed_o16_source_crosses_profile_boundary():
    source=source_profile_for_consumer('ui_acceptance_v2',authority())
    assert source.provenance()==load_acceptance_profile().provenance()
    files=load_acceptance_profile('ui_acceptance_v2').family('mot_3d')['accepted_upstream']['survivor_files']
    assert len(files)==40 and sum(name.endswith('.npy') for name in files)==20
    assert source_profile_for_consumer('ui_acceptance_v1').profile_id=='ui_acceptance_v1'


@pytest.mark.parametrize('attack',['campaign','report','s0','missing'])
def test_source_authority_tampering_is_rejected(attack):
    value=authority()
    if attack=='campaign':value['campaign_sha256']='0'*64
    elif attack=='report':value['final_report_sha256']='0'*64
    elif attack=='s0':value['selected_result']['s0']=2.0
    else:value=None
    with pytest.raises(ValueError):source_profile_for_consumer('ui_acceptance_v2',value)


@pytest.mark.parametrize('attack',['sha','physical','extra','unknown','scientific'])
def test_profiles_cannot_be_mixed_or_promoted(attack):
    value=model()
    if attack=='sha':value['acceptance']['profile_sha256']=load_acceptance_profile().sha256
    elif attack=='physical':value['acceptance']['physical_identity']['numerical_policy_sha256']='0'*64
    elif attack=='extra':value['acceptance']['extra']=True
    elif attack=='unknown':value['acceptance']['profile_id']='unreviewed'
    else:value['kind']='mot_3d_campaign_v2'
    with pytest.raises(ValueError):policy_for_manifest(value)
    with pytest.raises(ValueError):assert_scientific_source({'nested':[model()]})


def test_marker_lookup_keeps_old_and_new_report_identity_strict():
    for name in ('ui_acceptance_v1','ui_acceptance_v2'):
        marker=load_acceptance_profile(name).provenance()
        assert policy_for_marker(marker).profile_id==name
        marker['profile_sha256']='0'*64
        with pytest.raises(ValueError):policy_for_marker(marker)


@pytest.mark.parametrize('attack',['missing','duplicate','wrong_id'])
def test_v2_producer_rejects_noncanonical_selection_input(monkeypatch, attack):
    import studies.mot_3d.discovery.select as selector
    selected=select_candidates(source_summary('single_pass'),'single_pass')
    if attack=='missing':selected['candidates'].pop()
    elif attack=='duplicate':selected['candidates'][1]['candidate_id']=selected['candidates'][0]['candidate_id']
    else:selected['candidates'][0]['candidate_id']='foreign'
    monkeypatch.setattr(selector,'select_candidates',lambda *_args,**_kwargs:selected)
    with pytest.raises(ValueError,match='exact canonical twelve'):
        workload.discovery_selection(model(),{},'single_pass')


@pytest.mark.parametrize('attack',['empty','changed','extra','symlink'])
def test_v2_freeze_rejects_any_changed_original_survivor_registry(tmp_path, attack):
    from studies.mot_3d_campaign import freeze_inputs
    directory=tmp_path/'data/acceptance/survivors';directory.mkdir(parents=True)
    if attack=='changed':(directory/'mot_2d_survivors_zeeman_seed3015_mot_seed43015.npy').write_bytes(b'changed')
    elif attack=='extra':(directory/'unregistered').write_bytes(b'x')
    elif attack=='symlink':
        target=tmp_path/'foreign';target.write_bytes(b'x');(directory/'alias').symlink_to(target)
    with pytest.raises(ValueError,match='original'):
        freeze_inputs(directory,acceptance_profile_id='ui_acceptance_v2',acceptance_upstream=authority(),repository_root=tmp_path)


def test_v2_specification_tampering_is_not_a_new_implicit_profile(monkeypatch):
    original=Path.read_text
    def tamper(path,*args,**kwargs):
        raw=original(path,*args,**kwargs)
        if path.name=='ui_acceptance_v2.json':
            value=json.loads(raw);value['mot_3d']['discovery_candidate_permutation']['single_pass']=list(range(12))
            return json.dumps(value)
        return raw
    monkeypatch.setattr(Path,'read_text',tamper)
    with pytest.raises(ValueError,match='immutable'):load_acceptance_profile('ui_acceptance_v2')


def test_both_profile_specific_read_validators_reproduce_the_producer():
    value=model();files={}
    for family in ('angled_donut','single_pass'):
        summary=source_summary(family)
        files[f'discovery/{family}/merged/merged_summary.json']=summary
        files[f'selection/discovery/{family}.json']=workload.discovery_selection(value,summary,family)
    workload.validate_versioned_discovery_files(value,files.__getitem__)
    files['selection/discovery/single_pass.json']['candidates'][0]['parameters']['blue_crossing_z_offset_m']=-.05
    with pytest.raises(ValueError):workload.validate_versioned_discovery_files(value,files.__getitem__)
