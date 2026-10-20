"""Captured bytes permit only known renderer identities of the exact registry entry."""
import pytest
from workflow_api.mot_3d_preliminary_results import _outcome_reference_matches


@pytest.mark.parametrize('acceptance', [False, True])
def test_exact_absolute_and_repository_relative_forms(acceptance):
    project = '/home/tal.noa/' + ('ytterbium_lab_simulation_ui_acceptance' if acceptance else 'ytterbium_lab_simulation_new')
    campaign = 'data/optimization/mot_3d/' + ('ui_acceptance/' if acceptance else '') + 'campaign'
    artifact = 'refinement/single_pass/worker_0/candidate_seed_42001.npz'
    for reference in (campaign + '/' + artifact, project + '/' + campaign + '/' + artifact):
        assert _outcome_reference_matches(reference, campaign_absolute_path=project + '/' + campaign,
                                         project_directory=project, artifact=artifact)


@pytest.mark.parametrize('reference', [
    'candidate_seed_42001.npz', '../refinement/candidate_seed_42001.npz',
    'data/optimization/mot_3d/other/refinement/candidate_seed_42001.npz',
    'data/optimization/mot_3d/campaign/refinement/../refinement/candidate_seed_42001.npz',
    '/home/other/ytterbium_lab_simulation_new/data/optimization/mot_3d/campaign/refinement/candidate_seed_42001.npz',
    'data\\optimization\\mot_3d\\campaign\\refinement\\candidate_seed_42001.npz',
])
def test_suffix_lookalikes_and_escapes_are_rejected(reference):
    project = '/home/tal.noa/ytterbium_lab_simulation_new'
    assert not _outcome_reference_matches(reference,
        campaign_absolute_path=project + '/data/optimization/mot_3d/campaign',
        project_directory=project, artifact='refinement/candidate_seed_42001.npz')
