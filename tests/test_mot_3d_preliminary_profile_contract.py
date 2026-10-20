"""Discovery synchronization retains an exact policy-derived artifact registry."""
from workflow_api.mot_3d_discovery_transition import EXPECTED_BUNDLE_PATHS, _expected_bundle_paths
from studies.mot_3d_campaign import build_campaign_manifest


def test_canonical_preliminary_source_registry_stays_exact_961():
    manifest = build_campaign_manifest(name='canonical', input_directory='data/source', upstream={}, roles={},
                                       revision='a'*40, physical_model_sha256='b'*64)
    assert _expected_bundle_paths(manifest) == EXPECTED_BUNDLE_PATHS
    assert len(_expected_bundle_paths(manifest)) == 961


def test_acceptance_preliminary_source_registry_is_exact_35():
    manifest = build_campaign_manifest(name='TESTONLY', input_directory='data/acceptance/source', upstream={}, roles={},
                                       revision='a'*40, physical_model_sha256='b'*64,
                                       acceptance_profile_id='ui_acceptance_v1')
    paths = _expected_bundle_paths(manifest)
    assert len(paths) == 35
    assert sum('/trials/' in path for path in paths) == 24
    assert {path for path in paths if '/trials/' not in path} == {
        'campaign.json',
        *(f'discovery/{family}/merged/{name}' for family in ('angled_donut', 'single_pass')
          for name in ('merged_summary.json', 'ranked_trials.csv')),
        *(f'selection/discovery/{family}.json' for family in ('angled_donut', 'single_pass')),
        *(f'jobs/preliminary_check/{family}_{kind}.pbs' for family in ('angled_donut', 'single_pass')
          for kind in ('array', 'merge')),
    }
