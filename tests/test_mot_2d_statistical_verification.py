"""Actual producer rounding evidence, plus conservative decision attacks."""
import base64
import copy
import hashlib
import json
import math
from pathlib import Path

import pytest

from workflow_api.mot_2d_statistical_verification import verify_sensitivity_summary


def _actual():
    fixture = json.loads((Path(__file__).parent / 'fixtures/production_plan_actual_o16_drift.json').read_text())
    raw = [base64.b64decode(fixture['local_summary']['raw_base64']), base64.b64decode(fixture['rendered']['sensitivity_summary.json']['raw_base64'])]
    return raw, [json.loads(value) for value in raw]


@pytest.mark.parametrize('reverse', [False, True])
def test_captured_actual_27_fields_both_directions_unchanged(reverse):
    raw, values = _actual()
    original = copy.deepcopy(values)
    def differences(left, right):
        if isinstance(left, dict):
            return sum(differences(left[key], right[key]) for key in left)
        if isinstance(left, list):
            return sum(differences(a, b) for a, b in zip(left, right))
        return int(left != right)
    assert differences(*values) == 27
    hashes = [hashlib.sha256(value).hexdigest() for value in raw]
    observed, expected = values[::(-1 if reverse else 1)]
    verify_sensitivity_summary(observed, expected, target_loss_fraction=.0075)
    assert values == original
    assert [hashlib.sha256(value).hexdigest() for value in raw] == hashes


@pytest.mark.parametrize('attack', ['mean', 'difference', 'count', 'confidence', 'flag', 'parameter', 'extra', 'nonfinite', 'bool', 'large', 'internal'])
def test_actual_capture_attacks_rejected(attack):
    _, (observed, expected) = _actual()
    group = next(iter(observed.values()))
    point = group['points'][0]
    comparison = point['comparison_to_reference']
    if attack == 'mean': comparison['mean_difference_fraction'] += .01
    elif attack == 'difference': comparison['differences_fraction'][0] += .01
    elif attack == 'count': comparison['count'] = 5
    elif attack == 'confidence': group['production_selection']['familywise_confidence_per_comparison'] = .95
    elif attack == 'flag': point['within_loss_margin_at_95_percent'] = not point['within_loss_margin_at_95_percent']
    elif attack == 'parameter': point['parameters']['detuning_gamma'] += .01
    elif attack == 'extra': comparison['extra'] = True
    elif attack == 'nonfinite': comparison['95_ci_half_width_fraction'] = float('nan')
    elif attack == 'bool': comparison['95_ci_half_width_fraction'] = True
    elif attack == 'large': comparison['95_ci_half_width_fraction'] += .01
    elif attack == 'internal': comparison['95_ci_fraction'][1] = math.nextafter(comparison['95_ci_fraction'][1], math.inf)
    with pytest.raises(ValueError):
        verify_sensitivity_summary(observed, expected, target_loss_fraction=.0075)


def _summary(low=.2, half=.1):
    mean = low + half
    comparison = {'mean_difference_fraction': mean, 'differences_fraction': [mean]*5,
                  '95_ci_fraction': [mean-half, mean+half], '95_ci_half_width_fraction': half}
    center_comparison = {'mean_difference_fraction': 0., 'differences_fraction': [0.]*5,
                         '95_ci_fraction': [0., 0.], '95_ci_half_width_fraction': 0.}
    center = {'parameters': {'x': 0.}, 'offsets': {'detuning_gamma': 0., 'magnet_radius_m': 0.}, 'mean_efficiency': .1,
              'comparison_to_reference': center_comparison, 'within_loss_margin_at_95_percent': True}
    other = {'parameters': {'x': 1.}, 'offsets': {'detuning_gamma': 1., 'magnet_radius_m': 0.}, 'mean_efficiency': .5,
             'comparison_to_reference': comparison, 'within_loss_margin_at_95_percent': low >= -.0075}
    selected = other if low > 0 else center
    return {'s0': {'points': [center, other], 'production_selection': {
        'parameters': selected['parameters'], 'offsets_from_confirmed_winner': selected['offsets'],
        'mean_efficiency': selected['mean_efficiency'], 'comparison_to_confirmed_winner': selected['comparison_to_reference'],
        'selection_reason': 'sensitivity_neighbor_clearly_better_at_95_percent' if low > 0 else 'no_sensitivity_neighbor_clearly_better_at_95_percent',
        'familywise_method': 'Bonferroni simultaneous paired intervals', 'familywise_confidence_per_comparison': .95}}}


def _drift(summary):
    value = copy.deepcopy(summary)
    group = value['s0']
    comparison = group['points'][1]['comparison_to_reference']
    half = math.nextafter(comparison['95_ci_half_width_fraction'], math.inf)
    comparison['95_ci_half_width_fraction'] = half
    mean = comparison['mean_difference_fraction']
    comparison['95_ci_fraction'] = [mean-half, mean+half]
    if group['production_selection']['parameters'] == group['points'][1]['parameters']:
        group['production_selection']['comparison_to_confirmed_winner'] = copy.deepcopy(comparison)
    return value


def test_unambiguous_drift_and_exact_zero_center_accepted():
    expected = _summary()
    verify_sensitivity_summary(_drift(expected), expected, target_loss_fraction=.0075)


@pytest.mark.parametrize('low', [0., math.ulp(.1), -.0075])
def test_threshold_contact_or_crossing_rejected(low):
    expected = _summary(low=low)
    with pytest.raises(ValueError, match='ambiguous'):
        verify_sensitivity_summary(_drift(expected), expected, target_loss_fraction=.0075)


def test_ranking_tie_rejected_only_on_portability_path():
    expected = _summary()
    rival = copy.deepcopy(expected['s0']['points'][1])
    rival['parameters'] = {'x': 2.}
    expected['s0']['points'].append(rival)
    verify_sensitivity_summary(expected, copy.deepcopy(expected), target_loss_fraction=.0075)
    with pytest.raises(ValueError, match='ranking'):
        verify_sensitivity_summary(_drift(expected), expected, target_loss_fraction=.0075)


def test_selected_comparison_must_be_identical_to_selected_point():
    expected = _summary()
    observed = _drift(expected)
    observed['s0']['production_selection']['comparison_to_confirmed_winner'] = copy.deepcopy(expected['s0']['points'][1]['comparison_to_reference'])
    with pytest.raises(ValueError, match='selection'):
        verify_sensitivity_summary(observed, expected, target_loss_fraction=.0075)


@pytest.mark.parametrize('acceptance', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_validation_boundary_preserves_original_files_and_observed_values(tmp_path, monkeypatch, acceptance, reverse):
    from workflow_api import mot_2d_validation as validation
    fixture = json.loads((Path(__file__).parent / 'fixtures/production_plan_actual_o16_drift.json').read_text())
    raw, summaries = _actual()
    if reverse:
        raw.reverse()
        summaries.reverse()
    tasks_raw = base64.b64decode(fixture['rendered']['production/tasks.json']['raw_base64'])
    tasks = json.loads(tasks_raw)
    (tmp_path / 'production').mkdir()
    (tmp_path / 'sensitivity_summary.json').write_bytes(raw[0])
    (tmp_path / 'production/tasks.json').write_bytes(tasks_raw)
    manifest = copy.deepcopy(fixture['manifest'])
    original_provenance = copy.deepcopy(manifest["provenance"])
    assert "workflow_api/mot_2d_statistical_verification.py" not in original_provenance["hashed_files"]
    if not acceptance:
        manifest.pop('acceptance', None)
    # This boundary test isolates the new read-comparison; existing genuine
    # evaluation validators retain responsibility for SHA/roles/raw replicates.
    monkeypatch.setattr(validation, 'validated_evaluation_outputs', lambda root, manifest, stage: fixture[stage + '_rows'])
    monkeypatch.setattr(validation, 'derive_production_transition', lambda *args: (summaries[1], tasks))
    observed, observed_tasks = validation.validated_production_transition(tmp_path, manifest)
    assert observed == summaries[0]
    assert observed_tasks == tasks
    # Reader upgrades do not add their new code to archived source16 provenance.
    assert manifest["provenance"] == original_provenance
    assert (tmp_path / 'sensitivity_summary.json').read_bytes() == raw[0]
    assert (tmp_path / 'production/tasks.json').read_bytes() == tasks_raw
    bad_tasks = copy.deepcopy(tasks)
    bad_tasks[0]['zeeman_seed'] = True
    (tmp_path / 'production/tasks.json').write_text(json.dumps(bad_tasks))
    with pytest.raises(ValueError, match='not canonical'):
        validation.validated_production_transition(tmp_path, manifest)


@pytest.mark.parametrize("field", ["half", "low", "high"])
def test_zero_scale_signed_representation_changes_rejected(field):
    expected = _summary()
    observed = copy.deepcopy(expected)
    comparison = observed["s0"]["points"][0]["comparison_to_reference"]
    if field == "half":
        comparison["95_ci_half_width_fraction"] = -0.0
    else:
        comparison["95_ci_fraction"][0 if field == "low" else 1] = -0.0
    with pytest.raises(ValueError, match="Zero-scale"):
        verify_sensitivity_summary(observed, expected, target_loss_fraction=.0075)
