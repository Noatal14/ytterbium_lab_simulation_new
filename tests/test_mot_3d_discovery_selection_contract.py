"""The real discovery selection writer feeds the preliminary closed registry."""
from copy import deepcopy

import optuna
import pytest
from studies.mot_3d.discovery.optimize import _seed_parameters, build_trial_profile
from studies.mot_3d.discovery.select import select_candidates
from workflow_api.mot_3d_preliminary_results import _candidate_ids, PreliminaryResultError


def _written_selection(family):
    rows = []
    for index in range(12):
        profile, parameters, derived = build_trial_profile(
            family, optuna.trial.FixedTrial(_seed_parameters(family, index % 3)))
        rows.append({'worker_index': index % 3, 'trial_number': index // 3,
                     'usable_at_end_fraction': .8 - index / 1000, 'usable_at_end_count': 8,
                     'runtime_seconds': .1, 'parameters': parameters,
                     'derived_parameters': derived, 'resolved_profile': profile})
    return select_candidates({'ranked_trials': rows}, family, count=12)


@pytest.mark.parametrize('family', ['angled_donut', 'single_pass'])
def test_actual_selection_writer_is_accepted(family):
    selection = _written_selection(family)
    assert _candidate_ids(selection, family) == tuple(f'{family}_{index:02d}' for index in range(12))


@pytest.mark.parametrize('attack', ['missing', 'extra', 'requested', 'selected', 'boolean', 'duplicate'])
def test_changed_selection_schema_or_count_is_rejected(attack):
    selection = deepcopy(_written_selection('angled_donut'))
    if attack == 'missing': selection.pop('selected_candidate_count')
    elif attack == 'extra': selection['candidate_count'] = 12
    elif attack == 'requested': selection['requested_candidate_count'] = 11
    elif attack == 'selected': selection['selected_candidate_count'] = 11
    elif attack == 'boolean': selection['selected_candidate_count'] = True
    else: selection['candidates'][1]['candidate_id'] = selection['candidates'][0]['candidate_id']
    with pytest.raises(PreliminaryResultError, match='selection_mismatch'):
        _candidate_ids(selection, 'angled_donut')
