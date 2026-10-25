"""Genuine O16 frozen source ledger across strictly versioned 3D consumers.

No simulated outcomes, filesystem donor mutation, SSH, or scientific admission.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from studies.mot_3d_campaign import build_campaign_manifest
from workflow_api.acceptance_profile import load_acceptance_profile
from workflow_api.mot_3d_preliminary_results import (
    PreliminaryResultError, expected_preliminary_particle_selection, expected_selection_particle_provenance,
)
from workflow_api.mot_3d_finalist_results import FinalistResultError, _all_particle_provenance

PROJECT='/home/tal.noa/ytterbium_lab_simulation_ui_acceptance'
FIXTURE=Path(__file__).parent/'fixtures/o16-frozen-role-ledger.json'


def manifest(profile='ui_acceptance_v2'):
    value=json.loads(FIXTURE.read_bytes())
    roles={role:[{**row,**deepcopy(value['shared_record_fields'])}for row in rows]
           for role,rows in value['input_roles'].items()}
    assert hashlib.sha256(json.dumps(roles,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()==value['expanded_input_roles_sha256']
    return build_campaign_manifest(name='TESTONLY_versioned_source_lineage',input_directory='data/acceptance/source',
        upstream=value['upstream_2d_campaign'],roles=roles,revision='a'*40,physical_model_sha256='b'*64,
        acceptance_profile_id=profile)


def preliminary(value):return expected_preliminary_particle_selection(value,project_directory=PROJECT)
def finalist(value):return _all_particle_provenance(value,PROJECT)
def focused(value,stage):
    from workflow_api.mot_3d_workload import scientific_design
    design=scientific_design(value,stage)
    return expected_selection_particle_provenance(value,project_directory=PROJECT,
        input_role='refinement',input_ensembles=4,particles_per_ensemble=design.particles_per_ensemble,
        selection_seed=design.selection_seed,expected_zeeman_seeds=tuple(range(3027,3031)))
def refinement(value):return focused(value,'refinement')
def closure(value):return focused(value,'closure')


def test_genuine_compatible_source_is_exact_original_pinned20_ensemble_ledger():
    value=manifest();rows=[r for records in value['input_roles'].values()for r in records]
    pins=load_acceptance_profile('ui_acceptance_v2').family('mot_3d')['accepted_upstream']['survivor_files']
    assert len(rows)==20 and len(pins)==40
    assert {r['zeeman_seed']for r in rows}==set(range(3015,3035))
    for row in rows:
        assert pins[Path(row['path']).name]==row['sha256']
        assert pins[Path(row['metadata_path']).name]==row['metadata_sha256']
        assert row['source_design']['acceptance']==load_acceptance_profile().provenance()


@pytest.mark.parametrize('profile',['ui_acceptance_v1','ui_acceptance_v2'])
def test_preliminary_and_finalist_accept_unchanged_genuine_compatible_source(profile):
    value=manifest(profile);before=deepcopy(value)
    chosen=preliminary(value)
    assert len(chosen)==4 and [r['zeeman_seed']for r in chosen]==list(range(3031,3035))
    assert all(len(r['selected_indices'])==1 for r in chosen)
    for validator in (refinement,closure):
        selected=validator(value)
        assert [r['zeeman_seed']for r in selected]==list(range(3027,3031))
        assert all(len(r['selected_indices'])==1 for r in selected)
    rows,all_particles=finalist(value)
    assert len(rows)==len(all_particles)==20
    assert [r['zeeman_seed']for r in rows]==list(range(3015,3035))
    assert sum(r['particle_count']for r in all_particles)==367
    assert value==before


@pytest.mark.parametrize('validator',[preliminary,refinement,closure,finalist])
@pytest.mark.parametrize('attack',['campaign_hash','report_hash','s0','missing_authority','source_marker','source_digest','consumer_digest','scientific_promotion'])
def test_changed_source_or_consumer_identity_cannot_cross_boundary(validator,attack):
    value=manifest()
    if attack=='campaign_hash':value['upstream_2d_campaign']['campaign_sha256']='0'*64
    elif attack=='report_hash':value['upstream_2d_campaign']['final_report_sha256']='0'*64
    elif attack=='s0':value['upstream_2d_campaign']['selected_result']['s0']=2
    elif attack=='missing_authority':value.pop('upstream_2d_campaign')
    elif attack=='consumer_digest':value['acceptance']['profile_sha256']='0'*64
    elif attack=='scientific_promotion':value['kind']='mot_3d_campaign_v2';value.pop('acceptance')
    else:
        for role in value['input_roles'].values():
            row=role[0]
            if attack=='source_marker':row['source_design']['acceptance']=load_acceptance_profile('ui_acceptance_v2').provenance()
            else:row['source_design']['acceptance']['profile_sha256']='0'*64
    before=deepcopy(value)
    with pytest.raises((PreliminaryResultError,FinalistResultError,ValueError)):
        validator(value)
    assert value==before
