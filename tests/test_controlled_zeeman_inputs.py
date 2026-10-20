from types import SimpleNamespace

import numpy as np
import pytest

from simulations import zeeman


@pytest.fixture
def solver_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(zeeman, 'build_base_config', lambda **kwargs: (SimpleNamespace(mass=1.0), 'same physical config'))
    monkeypatch.setattr(zeeman, 'get_zeeman_only_zone', lambda **kwargs: 'same zones')
    monkeypatch.setattr(zeeman, 'generate_timepoints', lambda t, dt: (np.array([0.0, t]), 2))
    def solver(**kwargs):
        calls.append(kwargs)
        return [], None
    monkeypatch.setattr(zeeman, 'run_multiple_atoms_simulation', solver)
    monkeypatch.setattr(zeeman, 'zeeman_extract_survivors', lambda results, cutoff: (np.zeros((0, 6)), []))
    return calls


def test_thermal_default_and_explicit_none_produce_identical_solver_inputs(monkeypatch, solver_calls):
    thermal = []
    def source(**kwargs):
        thermal.append(kwargs)
        return np.arange(6).reshape(2, 3), np.arange(6, 12).reshape(2, 3), None
    monkeypatch.setattr(zeeman, 'generate_thermal_beam_state', source)
    zeeman.zeeman_simulation(N_particles=2, npools=1, seed=3000)
    zeeman.zeeman_simulation(N_particles=2, npools=1, seed=3000, initial_states=None)
    assert thermal[0] == thermal[1]
    for first, second in zip(solver_calls[0]['u0'], solver_calls[1]['u0']):
        assert np.array_equal(first, second)
    assert np.array_equal(solver_calls[0]['time_points'], solver_calls[1]['time_points'])
    assert {key: value for key, value in solver_calls[0].items() if key not in ('u0', 'time_points')} == {key: value for key, value in solver_calls[1].items() if key not in ('u0', 'time_points')}


def test_explicit_inputs_still_use_normal_solver_and_do_not_alias_caller(monkeypatch, solver_calls):
    def forbidden(**kwargs): raise AssertionError('Explicit inputs unexpectedly used the thermal sampler')
    monkeypatch.setattr(zeeman, 'generate_thermal_beam_state', forbidden)
    initial = np.arange(12, dtype=float).reshape(2, 6)
    zeeman.zeeman_simulation(N_particles=2, npools=1, seed=3035, initial_states=initial)
    assert solver_calls[0]['config'] == 'same physical config'
    assert solver_calls[0]['sim_function'] is zeeman.RK4StCustom
    assert solver_calls[0]['seed_idx'] == 3035
    assert np.array_equal(np.asarray(solver_calls[0]['u0']), initial)
    solver_calls[0]['u0'][0][0] = -100
    assert initial[0, 0] == 0.0


@pytest.mark.parametrize('states', [np.zeros((1, 6)), np.zeros((2, 5)), np.full((2, 6), np.nan), np.full((2, 6), np.inf)])
def test_invalid_explicit_inputs_never_reach_solver(states, solver_calls):
    with pytest.raises(ValueError, match='initial states'):
        zeeman.zeeman_simulation(N_particles=2, npools=1, initial_states=states)
    assert solver_calls == []


def test_controlled_mixture_has_independent_seed_jitter_and_exact_origin():
    import hashlib
    from config import ZEEMAN_BEAM_DIRECTION, ZEEMAN_SIM_CONFIG, Geometry
    from workflow_api.acceptance_inputs import controlled_initial_states
    recipe = {'recipe_version': 'near_cutoff_two_admitted_v1', 'admitted_particles': 2,
              'upstream_offset_m': 0.0005, 'longitudinal_jitter_m': 0.00005,
              'radial_jitter_m': 0.00005, 'speed_m_s': 10.0, 'speed_jitter_m_s': 0.5,
              'transverse_speed_jitter_m_s': 0.05, 'off_aperture_radius_m': 0.02}
    profile = SimpleNamespace(policy={'generation': {'zeeman_initial_particles': 32, 'controlled_input_recipe': recipe}})
    first, origin = controlled_initial_states(3000, profile)
    repeated, repeat_origin = controlled_initial_states(3000, profile)
    fresh, fresh_origin = controlled_initial_states(3035, profile)
    assert first.shape == (32, 6) and np.all(np.isfinite(first))
    assert np.array_equal(first, repeated) and origin == repeat_origin
    assert not np.array_equal(first, fresh) and origin['initial_state_sha256'] != fresh_origin['initial_state_sha256']
    axis = np.asarray(ZEEMAN_BEAM_DIRECTION)
    assert np.all(first[:, :3] @ axis > ZEEMAN_SIM_CONFIG['cutoff_distance_m'])
    radius = np.linalg.norm(first[:, :3] - (first[:, :3] @ axis)[:, None] * axis, axis=1)
    assert np.all(radius[:2] < Geometry.ZEEMAN_ARM_1_RADIUS_M)
    assert np.all(radius[2:] > Geometry.ZEEMAN_ARM_1_RADIUS_M)
    assert origin['suitability'] == 'acceptance_only'
    assert origin['initial_state_sha256'] == hashlib.sha256(first.astype('<f8').tobytes()).hexdigest()


def test_explicit_input_metadata_records_actual_initial_state_digest(tmp_path):
    import hashlib
    import json
    from studies.zeeman.generate_ensembles import corrected_field
    initial = np.arange(12, dtype=np.float64).reshape(2, 6)
    survivors = np.zeros((1, 6))
    path = tmp_path / 'controlled.npy'
    np.save(path, survivors)
    metadata = zeeman.write_zeeman_metadata(path, survivors, {
        'N_particles': 2, 'initial_states': initial, 'seed': 3000,
        'zeeman_field_config': corrected_field(),
    }, 1.0)
    value = json.loads(metadata.read_text())
    assert value['suitability'] == 'acceptance_only'
    assert value['input_origin'] == {'kind': 'explicit_initial_states', 'particle_count': 2,
                                    'suitability': 'acceptance_only', 'thermal_sampler_used': False,
                                    'initial_state_sha256': hashlib.sha256(initial.astype('<f8').tobytes()).hexdigest()}


def test_frozen_positive_recipe_uses_all32_near_axis_actual_inputs():
    from workflow_api.acceptance_profile import load_acceptance_profile
    from workflow_api.acceptance_inputs import controlled_initial_states
    from config import ZEEMAN_BEAM_DIRECTION, Geometry
    profile = load_acceptance_profile()
    states, origin = controlled_initial_states(3000, profile)
    axis = np.asarray(ZEEMAN_BEAM_DIRECTION)
    radius = np.linalg.norm(states[:, :3] - (states[:, :3] @ axis)[:, None] * axis, axis=1)
    assert states.shape == (32, 6)
    assert np.all(radius < Geometry.ZEEMAN_ARM_1_RADIUS_M)
    assert origin['recipe']['admitted_particles'] == 32
    assert origin['recipe']['speed_m_s'] == 42.0
    assert origin['recipe']['distribution'] == 'controlled_near_cutoff_not_thermal'
