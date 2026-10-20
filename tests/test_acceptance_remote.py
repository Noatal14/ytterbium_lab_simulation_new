import pytest
from workflow_api.acceptance_profile import load_acceptance_profile
from workflow_api.acceptance_remote import assert_campaign_target, campaign_path_parts
from workflow_api.zeus_snapshot import ZeusProfile


def model():
    return {'kind': 'mot_2d_ui_acceptance_v1', 'acceptance': load_acceptance_profile().provenance()}


def test_exact_acceptance_target_is_separate_from_individual_and_scientific_targets():
    path = '/home/tal.noa/ytterbium_lab_simulation_ui_acceptance'
    assert ZeusProfile.parse({'username':'tal.noa', 'project_directory':path}).project_directory == path
    assert_campaign_target(model(), 'tal.noa', path, 'data/optimization/mot_2d/ui_acceptance/canary')
    for other in ('ytterbium_lab_simulation_new', 'ytterbium_lab_simulation_ui_test'):
        with pytest.raises(ValueError):
            assert_campaign_target(model(), 'tal.noa', f'/home/tal.noa/{other}')
    with pytest.raises(ValueError):
        assert_campaign_target({'kind':'mot_2d_s0_campaign'}, 'tal.noa', path)


@pytest.mark.parametrize('path', ['data/optimization/mot_2d/canonical', 'data/optimization/mot_2d/ui_acceptance', 'data/optimization/mot_2d/ui_acceptance/../canonical'])
def test_test_manifest_never_authorizes_scientific_or_ambiguous_path(path):
    with pytest.raises(ValueError):
        assert_campaign_target(model(), 'tal.noa', '/home/tal.noa/ytterbium_lab_simulation_ui_acceptance', path)


def test_path_syntax_does_not_authorize_mutation_without_profile_authentication():
    path = 'data/optimization/mot_2d/ui_acceptance/canary'
    assert len(campaign_path_parts(path, 'mot_2d')) == 5
    with pytest.raises(ValueError):
        assert_campaign_target({'kind':'mot_2d_s0_campaign'}, 'tal.noa', '/home/tal.noa/ytterbium_lab_simulation_new', path)
    for invalid in (path+'/extra', 'data/optimization/mot_2d/ui_acceptance', '../'+path):
        with pytest.raises(ValueError): campaign_path_parts(invalid, 'mot_2d')
