"""Team deployment uses ordinary scientific code and explicit personal targets."""
from copy import deepcopy
from pathlib import Path

import pytest

from workflow_api.campaign_deployment import (
    TEAM_CHECKOUT, SCIENTIFIC_CHECKOUT, normal_checkout, environment_for_checkout,
    render_normal_deployment,
)
from workflow_api.acceptance_remote import assert_campaign_target
from workflow_api.zeus_snapshot import ZeusProfile
from workflow_api.zeeman_zeus_execution import _target_pbs
from studies import mot_3d_campaign as campaign


@pytest.mark.parametrize("username", ["tal.noa", "new.member"])
@pytest.mark.parametrize("kind", ["mot_2d_s0_campaign", "mot_3d_campaign_v2"])
def test_personal_team_target_cannot_fall_back_to_scientific_or_test(username, kind):
    manifest = {"kind": kind, "execution_checkout": TEAM_CHECKOUT}
    project = f"/home/{username}/{TEAM_CHECKOUT}"
    assert ZeusProfile.parse({"username": username, "project_directory": project}).project_directory == project
    assert_campaign_target(manifest, username, project)
    for other in (SCIENTIFIC_CHECKOUT, "ytterbium_lab_simulation_ui_test", "arbitrary"):
        with pytest.raises(ValueError):
            assert_campaign_target(manifest, username, f"/home/{username}/{other}")
    assert environment_for_checkout(TEAM_CHECKOUT) == "atomsmltr-ui"


def team_manifest():
    return campaign.build_campaign_manifest(
        name="team-deployment", input_directory="data/particle_states/after_2d_mot/source",
        upstream={"execution_checkout": TEAM_CHECKOUT}, roles={}, revision="a" * 40,
        physical_model_sha256="b" * 64,
    )


def assert_team_job(text):
    assert f"cd ~/{TEAM_CHECKOUT}" in text
    assert "source ~/venvs/atomsmltr-ui/bin/activate" in text
    assert "ytterbium_lab_simulation_new" not in text
    assert "ui_test" not in text and "ui_acceptance" not in text and "vnode=gd002" not in text


def test_3d_inherits_binding_without_changing_scientific_design():
    value = team_manifest()
    legacy = campaign.build_campaign_manifest(name=value['name'], input_directory=value['input_directory'],
        upstream={}, roles={}, revision='a'*40, physical_model_sha256='b'*64)
    assert normal_checkout(value) == TEAM_CHECKOUT
    assert value['design'] == legacy['design']
    assert 'execution_checkout' not in legacy
    with pytest.raises(ValueError, match="Acceptance"):
        campaign.build_campaign_manifest(name='mixed', input_directory='input', upstream={'execution_checkout':TEAM_CHECKOUT},
            roles={}, revision='a'*40, physical_model_sha256='b'*64, acceptance_profile_id='ui_acceptance_v1')


def test_all_3d_discovery_jobs_use_team_paths_and_preserve_resources_and_physics():
    value = team_manifest()
    before = deepcopy(value)
    files, *_ = campaign.render_discovery_jobs(Path('data/optimization/mot_3d/team-deployment'), 'a'*40,
        Path('data/particle_states/after_2d_mot/source'), manifest=value)
    legacy = deepcopy(value); del legacy['execution_checkout']
    old, *_ = campaign.render_discovery_jobs(Path('data/optimization/mot_3d/team-deployment'), 'a'*40,
        Path('data/particle_states/after_2d_mot/source'), manifest=legacy)
    assert files.keys() == old.keys()
    for name,text in files.items():
        if name.endswith('.pbs'):
            assert_team_job(text)
            assert text.replace(TEAM_CHECKOUT, SCIENTIFIC_CHECKOUT).replace('venvs/atomsmltr-ui/', 'venvs/atomsmltr/') == old[name]
    assert value == before


@pytest.mark.parametrize('stage', ['preliminary_check','refinement','closure','finalist_selection','final_validation'])
def test_3d_later_stage_adapter_requires_exact_template_and_preserves_payload(stage):
    from workflow_api.mot_3d_workload import rendered_job
    value = team_manifest()
    original = campaign._header('reviewed', 'a'*40) + 'python -m simulations.mot_3d --dt 5e-06 --t-max 0.05\n'
    actual = rendered_job(original, value, stage)
    assert_team_job(actual)
    assert actual.replace(TEAM_CHECKOUT, SCIENTIFIC_CHECKOUT).replace('venvs/atomsmltr-ui/', 'venvs/atomsmltr/') == original
    with pytest.raises(ValueError, match='template'):
        rendered_job(original*2, value, stage)


@pytest.mark.parametrize('family', ['zeeman','mot_2d','mot_3d'])
def test_individual_pbs_uses_ignored_runtime_without_test_placement(family):
    module = __import__('workflow_api.'+family+'_zeus_execution', fromlist=['_render_pbs'])
    original = module._render_pbs({'run_id':'example','git_revision':'a'*40}, 'b'*64).decode()
    actual = module._render_pbs({'run_id':'example','git_revision':'a'*40}, 'b'*64,
        f'/home/new.member/{TEAM_CHECKOUT}').decode()
    assert TEAM_CHECKOUT in actual and SCIENTIFIC_CHECKOUT not in actual
    runtime_family={'zeeman':'zeeman','mot_2d':'mot-2d','mot_3d':'mot-3d'}[family]
    assert f'"data/runs/.zeus-state/individual-{runtime_family}/' in actual
    assert 'venvs/atomsmltr-ui/bin/activate' in actual
    assert 'vnode=gd002' not in actual
    assert [line for line in actual.splitlines() if line.startswith('#PBS')] == [line for line in original.splitlines() if line.startswith('#PBS')]


def test_actual_final_input_generation_and_validation_renderers_use_team_target(monkeypatch):
    from tests.test_mot_3d_posix_rendering import _inputs
    value, summaries = _inputs(monkeypatch)
    value.pop('acceptance')
    value['kind'] = 'mot_3d_campaign_v2'
    value['execution_checkout'] = TEAM_CHECKOUT
    root = f'data/optimization/mot_3d/{value["name"]}'
    files, updated = campaign.render_final_validation_input_transition(root, value, summaries,
        {family:'a'*64 for family in campaign.FAMILIES}, 'b'*64)
    emitted = [raw.decode() for name,raw in files.items() if name.endswith('.pbs')]
    assert len(emitted) == 3
    for text in emitted:
        assert_team_job(text)
        assert '--acceptance-profile' not in text
    final_files, _ = campaign.render_final_validation_transition(root, updated)
    for name,raw in final_files.items():
        if name.endswith('.pbs'):
            assert_team_job(raw.decode())
