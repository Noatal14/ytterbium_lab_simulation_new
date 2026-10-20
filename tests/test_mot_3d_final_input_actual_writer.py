"""Actual Zeeman metadata, 2D production and freeze writers meet byte validation.

Only the trajectory batch solver and Git observation are isolated. Input loading,
physical attestation, records, NPY writes, freeze and strict validator are real.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from tests.test_mot_3d_final_input_results import _fixture, _json
from workflow_api.mot_3d_final_input_results import validate_final_input_result_bytes, expected_paths, FinalInputResultError


def _produce(tmp_path,monkeypatch,acceptance,explicit_absolute_identity):
    from studies.mot_2d import production, optimization
    from simulations import zeeman
    from studies.zeeman.generate_ensembles import corrected_field
    from studies.mot_3d_campaign import freeze_final_validation_inputs
    from workflow_api.acceptance_profile import load_acceptance_profile
    from workflow_api.acceptance_inputs import controlled_initial_states
    old,locked,submission,_=_fixture()
    profile=load_acceptance_profile() if acceptance else None
    project=tmp_path/('acceptance-project' if acceptance else 'scientific-project');project.mkdir()
    relative='data/optimization/mot_3d/'+('ui_acceptance/' if acceptance else '')+'campaign'
    campaign=project/relative;campaign.mkdir(parents=True)
    def remap(value):
        if isinstance(value,str):return value.replace('data/optimization/mot_3d/campaign',relative)
        if isinstance(value,dict):return {k:remap(v) for k,v in value.items()}
        if isinstance(value,list):return [remap(v) for v in value]
        return value
    manifest=remap(old)
    if acceptance:
        from tests.test_mot_3d_acceptance_workload import manifest as acceptance_manifest
        current=acceptance_manifest();current.update(name='campaign',stage=manifest['stage'],stages=manifest['stages'],upstream_2d_campaign=manifest['upstream_2d_campaign'])
        manifest=current
        locked.update(acceptance=profile.provenance(),suitability='acceptance_only')
    commit=manifest['provenance']['git_commit']
    manifest_path=campaign/'campaign.json';manifest_path.write_bytes(_json(manifest))
    locked_path=campaign/'selection/locked_nominals.json';locked_path.parent.mkdir();locked_path.write_bytes(_json(locked))
    submission_path=campaign/'final_validation_input_generation_submission.json';submission_path.write_bytes(_json(submission))
    zdir=campaign/'final_validation_inputs/after_zeeman';zdir.mkdir(parents=True)
    monkeypatch.chdir(project)
    monkeypatch.setattr(zeeman,'_git_commit',lambda:commit)
    monkeypatch.setattr(zeeman,'_tracked_worktree_is_dirty',lambda:False)
    monkeypatch.setattr(production.subprocess,'check_output',lambda *a,**k:commit)
    for seed in range(3035,3055):
        initial=profile.policy['generation']['zeeman_initial_particles'] if profile else 50000
        path=zdir/f'production_zeeman_n{initial}_dt40us_seed{seed}.npy'
        states=np.zeros((2,6),dtype=np.float64);np.save(path,states)
        arguments={'N_particles':initial,'seed':seed,'dt':4e-5,'npools':1 if profile else 200,'stochastic':True,'collimation_angle_deg':1.5,'zeeman_field_config':corrected_field()}
        if profile:arguments['initial_states'],origin=controlled_initial_states(seed,profile)
        meta=zeeman.write_zeeman_metadata(path,states,arguments,.01)
        if profile:
            row=json.loads(meta.read_text());row.update(acceptance=profile.provenance(),controlled_input_origin=origin);meta.write_bytes(_json(row))
    def solver(**kwargs):
        return [(None,1,states[:1].copy()) for states in kwargs['survivor_state_ensembles']]
    monkeypatch.setattr(optimization,'mot_simulation_paired_ensembles',solver)
    params=manifest['upstream_2d_campaign']['expected_survivor_parameters']
    arguments=['--zeeman-seeds',*[str(x) for x in range(3035,3055)],'--mot-seeds',*[str(x) for x in range(43035,43055)],'--ensemble-dir',str(zdir if explicit_absolute_identity else zdir.relative_to(project)),'--expected-zeeman-profile',manifest['upstream_2d_campaign']['expected_survivor_design']['zeeman_profile'],'--expected-git-commit',commit,'--s0',str(params['s0']),'--detuning-gamma',str(params['detuning_gamma']),'--magnet-radius-m',str(params['magnet_radius']),'--npools',str(profile.policy['generation']['jobs']['mot_2d']['npools'] if profile else 200),'--output-dir',str(campaign/'final_validation_inputs/mot_2d_records'),'--save-survivor-states','--states-dir',str(campaign/'final_validation_inputs/after_2d_mot')]
    if explicit_absolute_identity:arguments+=['--ensemble-identity',str(zdir)]
    if profile:arguments+=['--acceptance-profile','ui_acceptance_v1','--input-manifest',str(manifest_path)]
    production.run_seeds(production.parse_args(arguments))
    freeze_final_validation_inputs(campaign if explicit_absolute_identity else Path(relative))
    files={name:(campaign/name).read_bytes() for name in expected_paths(manifest)}
    return manifest,locked,submission,files,project,campaign


@pytest.mark.parametrize('acceptance',[False,True])
@pytest.mark.parametrize('explicit_absolute_identity',[False,True])
def test_actual_production_writers_and_freeze_validate_exact_101_files(tmp_path,monkeypatch,acceptance,explicit_absolute_identity):
    manifest,locked,submission,files,project,campaign=_produce(tmp_path,monkeypatch,acceptance,explicit_absolute_identity)
    result=validate_final_input_result_bytes(_json(manifest),_json(locked),_json(submission),files,project_directory=project.as_posix(),campaign_absolute_path=campaign.as_posix())
    assert len(result.paths)==101 and result.input_manifest['total_survivors']==20
    assert result.input_manifest.get('acceptance')==manifest.get('acceptance')
    mpath='final_validation_inputs/after_2d_mot/mot_2d_survivors_zeeman_seed3035_mot_seed43035.json'
    rpath='final_validation_inputs/mot_2d_records/replicates/zeeman_seed3035.json'
    mutations=[
        (mpath,lambda row:row.update(unexpected='unreviewed')),
        (mpath,lambda row:row.update(n_input=3)),
        (mpath,lambda row:row.update(n_survivors=2)),
        (mpath,lambda row:row.update(dtype='float32')),
        (mpath,lambda row:row.update(state_layout=['vx','vy','vz','x','y','z'])),
        (mpath,lambda row:row.update(output_sha256='0'*64)),
        (mpath,lambda row:row['design'].update(dt_s=4e-5)),
        (rpath,lambda row:row['replicate'].update(n_input=2.0)),
    ]
    if acceptance:
        mutations.append((mpath,lambda row:row.update(acceptance={})))
        zpath=next(name for name in files if name.endswith('dt40us_seed3035.json'))
        mutations.append((zpath,lambda row:row['controlled_input_origin'].update(initial_state_sha256='0'*64)))
    for path,mutate in mutations:
        changed=dict(files);row=json.loads(changed[path]);mutate(row);changed[path]=_json(row)
        with pytest.raises(FinalInputResultError) as rejected:
            validate_final_input_result_bytes(_json(manifest),_json(locked),_json(submission),changed,project_directory=project.as_posix(),campaign_absolute_path=campaign.as_posix())
        assert rejected.value.code=='input_metadata_mismatch'
