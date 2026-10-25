"""Retired TEST ONLY policy stays evidence; executable selection is canonical."""
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
    assert_scientific_source,
)

FIXTURES = Path(__file__).parent / 'fixtures'


def model(profile='ui_acceptance_v1'):
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


def test_v1_specification_bytes_are_unchanged():
    path=Path(__file__).parents[1]/'workflow_api/specifications/ui_acceptance_v1.json'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == '001cc9d89ddc291522bc0ded876b58ebb9b6dae86c24f28963fe2ca0bc09952f'


def test_historical_v2_policy_is_preserved_but_not_executable():
    value=json.loads((FIXTURES/'historical_acceptance_v2/ui_acceptance_v2.json').read_bytes())
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    assert hashlib.sha256(raw).hexdigest()=='b7f40de6cbf9311e42408ecbc0ff3ecfa66195e2ebdab2287c317ee43c1517b7'
    with pytest.raises(ValueError):load_acceptance_profile('ui_acceptance_v2')


@pytest.mark.parametrize('family',['angled_donut','single_pass'])
def test_selection_uses_canonical_order_without_mutating_captured_summary(family):
    summary=source_summary(family);before=deepcopy(summary)
    expected=select_candidates(summary,family,count=12)
    assert workload.discovery_selection(model(None),summary,family)==expected
    assert workload.discovery_selection(model(),summary,family)==expected
    assert summary==before


@pytest.mark.parametrize('profile',['ui_acceptance_v2','ui_acceptance_unreviewed'])
def test_retired_and_unknown_markers_cannot_be_promoted_or_frozen(tmp_path,profile):
    from studies.mot_3d_campaign import freeze_inputs
    with pytest.raises(ValueError):assert_scientific_source({'nested':[{'profile_id':profile}]})
    with pytest.raises(ValueError):policy_for_marker({'profile_id':profile})
    with pytest.raises(ValueError):freeze_inputs(tmp_path/'absent',acceptance_profile_id=profile)


def test_unknown_profile_is_rejected_before_candidate_selection(monkeypatch):
    import studies.mot_3d.discovery.select as selector
    value=model();value['acceptance']['profile_id']='ui_acceptance_v2'
    def forbidden(*args,**kwargs):raise AssertionError('selection must not run')
    monkeypatch.setattr(selector,'select_candidates',forbidden)
    with pytest.raises(ValueError):workload.discovery_selection(value,{},'single_pass')
