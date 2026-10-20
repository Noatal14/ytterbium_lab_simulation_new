"""Historical receipt reads cannot authorize new jobs or relax frozen bytes."""
from copy import deepcopy
import hashlib
import json

import pytest

from workflow_api.mot_2d_spec import project_historical_manifest
from test_acceptance_profile import two_d_manifest


def sha(value):
    return hashlib.sha256((json.dumps(value, indent=2, sort_keys=True) + '\n').encode()).hexdigest()


@pytest.mark.parametrize('acceptance', [False, True])
def test_projection_exact_hash_preserves_unknown_fields_and_never_mutates(acceptance):
    original = two_d_manifest() if acceptance else {'kind': 'mot_2d_s0_campaign', 'stage': 'smoke', 'stages': {}, 'name': 'test'}
    original['stage'] = 'screen'
    original['stages'] = {'screen': {'tasks': 3}}
    current = deepcopy(original)
    current['stage'] = 'complete'
    current['stages'].update(refine={'tasks': 3}, confirmation={'tasks': 5}, sensitivity={'tasks': 17}, production={'tasks': 20}, final_report='final_report.json')
    before = deepcopy(current)
    assert project_historical_manifest(current, 'screen', sha(original)) == original
    assert current == before
    for field in ('unknown', 'final_report'):
        changed = deepcopy(current); changed[field] = 'unreviewed'
        with pytest.raises(ValueError, match='exact frozen hash'):
            project_historical_manifest(changed, 'screen', sha(original))
    changed = deepcopy(current); changed['stages']['unreviewed_stage'] = {}
    with pytest.raises(ValueError, match='exact frozen hash'):
        project_historical_manifest(changed, 'screen', sha(original))
    with pytest.raises(ValueError): project_historical_manifest(current, 'arbitrary', sha(original))
    with pytest.raises(ValueError): project_historical_manifest(original, 'complete', sha(current))
    with pytest.raises(ValueError): project_historical_manifest(current, 'screen', '0' * 64)
    changed = deepcopy(current); changed.pop('kind')
    with pytest.raises(ValueError): project_historical_manifest(changed, 'screen', sha(original))
    if acceptance:
        for attack in ('missing', 'wrong'):
            changed = deepcopy(current)
            if attack == 'missing': changed.pop('acceptance')
            else: changed['acceptance']['profile_sha256'] = '0' * 64
            with pytest.raises(ValueError): project_historical_manifest(changed, 'screen', sha(original))


@pytest.mark.parametrize('acceptance', [False, True])
def test_sensitivity_count_reads_exact_frozen_deduplicated_registry(acceptance):
    from workflow_api.mot_2d_spec import sensitivity_task_count
    value = two_d_manifest() if acceptance else {'kind': 'mot_2d_s0_campaign', 's0_values': [1.3]}
    value['stages'] = {'sensitivity': {'tasks': 16}}
    assert sensitivity_task_count(value) == 16
    value['stages']['sensitivity']['tasks'] = 17
    assert sensitivity_task_count(value) == 17
    for invalid in (None, True, '16', 0, 18):
        value['stages']['sensitivity']['tasks'] = invalid
        with pytest.raises(ValueError): sensitivity_task_count(value)
