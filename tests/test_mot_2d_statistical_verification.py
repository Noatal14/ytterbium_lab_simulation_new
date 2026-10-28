"""Actual producer rounding evidence, plus conservative decision attacks."""
import base64
import copy
import hashlib
import json
import math
from pathlib import Path

import pytest

from workflow_api.mot_2d_statistical_verification import verify_sensitivity_summary


def _actual_production_statistics():
    return json.loads((Path(__file__).parent / 'fixtures/production_student_ci_native_e918.json').read_text())


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('attack', [
    None, 'mean', 'count', 'bool', 'extra', 'missing', 'nonfinite',
    'negative', 'internal', 'large', 'shared_extra',
])
def test_actual_production_student_statistics(reverse, attack):
    from workflow_api.mot_2d_statistical_verification import verify_replicate_statistics
    fixture = _actual_production_statistics()
    observed, expected = fixture['recorded'], fixture['native_recomputed']
    if reverse:
        observed, expected = expected, observed
    original = copy.deepcopy((observed, expected))
    half = 'conditional_95_ci_half_width'
    if attack == 'mean': observed['mean_conditional_efficiency'] += .01
    elif attack == 'count': observed['n_replicates'] = True
    elif attack == 'bool': observed[half] = True
    elif attack == 'extra': observed['extra'] = 1
    elif attack == 'shared_extra': observed['extra'] = expected['extra'] = 1
    elif attack == 'missing': observed.pop(half)
    elif attack == 'nonfinite': observed[half] = float('nan')
    elif attack == 'negative': observed[half] = -observed[half]
    elif attack == 'internal': observed['conditional_95_ci'][0] += .01
    elif attack == 'large': observed[half] += .01
    if attack is None:
        verify_replicate_statistics(observed, expected)
        assert (observed, expected) == original
    else:
        with pytest.raises(ValueError):
            verify_replicate_statistics(observed, expected)


@pytest.mark.parametrize('steps', [4, 8])
def test_production_student_interval_scale_bound(steps):
    from workflow_api.mot_2d_statistical_verification import verify_replicate_statistics
    expected = _actual_production_statistics()['recorded']
    observed = copy.deepcopy(expected)
    mean = expected['mean_conditional_efficiency']
    half = expected['conditional_95_ci_half_width'] + steps * math.ulp(mean)
    observed['conditional_95_ci_half_width'] = half
    observed['conditional_95_ci'] = [mean - half, mean + half]
    if steps == 4:
        verify_replicate_statistics(observed, expected)
    else:
        with pytest.raises(ValueError, match='portability bound'):
            verify_replicate_statistics(observed, expected)


@pytest.mark.parametrize('attack', [None, 'signed_zero', 'bool', 'nonfinite'])
def test_production_zero_scale_is_exact(attack):
    from workflow_api.mot_2d_statistical_verification import verify_replicate_statistics
    expected = _actual_production_statistics()['recorded']
    for name in expected:
        if name != 'n_replicates':
            expected[name] = [0., 0.] if name.endswith('_ci') else 0.
    observed = copy.deepcopy(expected)
    if attack == 'signed_zero': observed['conditional_95_ci_half_width'] = -0.
    elif attack == 'bool': observed['conditional_95_ci_half_width'] = False
    elif attack == 'nonfinite': observed['conditional_95_ci_half_width'] = float('nan')
    if attack is None:
        verify_replicate_statistics(observed, expected)
    else:
        with pytest.raises(ValueError):
            verify_replicate_statistics(observed, expected)


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('attack', [None, 'prediction', 'decision', 'state_hash'])
def test_sealed_validator_production_student_read_boundary(tmp_path, monkeypatch, reverse, attack):
    """Actual recorded/native statistics at the sealed-validator boundary.

    The existing portable sealed fixture validates the surrounding file contract.
    Only its statistics recomputation is isolated with the captured native value;
    this is not a claim that the fixture is the physical e918 campaign.
    """
    from test_mot_2d_campaign_integrity import (
        _write_portable_sealed_campaign, _patch_portable_production_transition,
    )
    from workflow_api import mot_2d_validation as validation
    from workflow_api.models import StageProgress
    _patch_portable_production_transition(monkeypatch)
    campaign, manifest = _write_portable_sealed_campaign(tmp_path)
    fixture = _actual_production_statistics()
    observed, expected = fixture['recorded'], fixture['native_recomputed']
    if reverse:
        observed, expected = expected, observed
    monkeypatch.setattr(validation, 'summarize_replicates', lambda rows: copy.deepcopy(expected))
    path = campaign / 'production/s0_1p300000/summary.json'
    summary = json.loads(path.read_bytes())
    summary['replicate_statistics'] = observed
    if attack == 'prediction':
        summary['prediction_for_10m_zeeman_survivors']['critical_value'] += .01
    elif attack == 'decision':
        summary['stopping_rule_passes'] = not summary['stopping_rule_passes']
    elif attack == 'state_hash':
        state = next((tmp_path / 'data/particle_states/after_2d_mot').rglob('*.npy'))
        state.write_bytes(state.read_bytes() + b'tamper')
    raw = json.dumps(summary).encode()
    path.write_bytes(raw)
    progress = (
        StageProgress('sensitivity', 17, 17, 'complete'),
        StageProgress('production', 20, 20, 'complete'),
    )
    assert validation.sealed_final_is_valid(campaign, manifest, progress, tmp_path) is (attack is None)
    assert path.read_bytes() == raw


def _actual():
    fixture = json.loads((Path(__file__).parent / 'fixtures/production_plan_actual_o16_drift.json').read_text())
    raw = [base64.b64decode(fixture['local_summary']['raw_base64']), base64.b64decode(fixture['rendered']['sensitivity_summary.json']['raw_base64'])]
    return raw, [json.loads(value) for value in raw]


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('attack', [
    None, 'mean', 'bool', 'extra', 'missing', 'decision', 'large', 'pbs', 'tasks',
])
def test_collection_rendered_history_uses_existing_ci_contract(tmp_path, monkeypatch, reverse, attack):
    """Exercise the duplicate check that rejected real cross-platform collection.

    Isolate rendering, not the comparison under test. Full-chain collection tests
    separately exercise original-byte hashes and the complete scientific closure.
    """
    from workflow_api import mot_2d_collection as collection
    from workflow_api import mot_2d_plan as plan
    from workflow_api import mot_2d_screen as screen
    from workflow_api import mot_2d_validation as validation

    raw, _ = _actual()
    if reverse:
        raw.reverse()
    observed = json.loads(raw[0])
    point = next(iter(observed.values()))['points'][0]
    if attack == 'mean':
        point['comparison_to_reference']['mean_difference_fraction'] += .01
    elif attack == 'bool':
        point['comparison_to_reference']['95_ci_half_width_fraction'] = True
    elif attack == 'extra':
        point['comparison_to_reference']['extra'] = 1
    elif attack == 'missing':
        point['comparison_to_reference'].pop('95_ci_half_width_fraction')
    elif attack == 'decision':
        point['within_loss_margin_at_95_percent'] = not point['within_loss_margin_at_95_percent']
    elif attack == 'large':
        point['comparison_to_reference']['95_ci_half_width_fraction'] += .01
    original = raw[0] if attack in (None, 'pbs', 'tasks') else json.dumps(observed).encode()
    campaign = tmp_path / 'campaign'
    campaign.mkdir()
    (campaign / 'sensitivity_summary.json').write_bytes(original)
    (campaign / 'job.pbs').write_bytes(raw[0] if attack == 'pbs' else raw[1])
    (campaign / 'tasks.json').write_bytes(raw[0] if attack == 'tasks' else raw[1])
    for name in ('validate_screen_outputs', 'validate_refine_outputs'):
        monkeypatch.setattr(screen, name, lambda *args: [])
    monkeypatch.setattr(validation, 'validated_evaluation_outputs', lambda *args: [])
    renderers = (
        'render_campaign_files', 'render_screen_transition', 'render_refine_transition',
        'render_confirmation_transition', 'render_sensitivity_transition',
    )
    for name in renderers:
        monkeypatch.setattr(plan, name, lambda *args: {})
    monkeypatch.setattr(plan, 'render_production_transition', lambda *args: {
        'sensitivity_summary.json': raw[1], 'job.pbs': raw[1], 'tasks.json': raw[1],
    })
    manifest = {'stage': 'complete', 'stages': {}, 'fixed_design': {
        'target_95_half_width_fraction': .0075,
    }}
    if attack is None:
        collection.validate_rendered_history(tmp_path, campaign, manifest)
    else:
        with pytest.raises(ValueError):
            collection.validate_rendered_history(tmp_path, campaign, manifest)
    assert (campaign / 'sensitivity_summary.json').read_bytes() == original


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
