"""Checkpoint sampling must equal one uninterrupted public Optuna run."""
import optuna
import pytest

from studies.mot_2d.optimization import restore_sampler, suggest_parameters


@pytest.mark.parametrize('fixed', [1.3, None])
@pytest.mark.parametrize('queued', [False, True])
def test_checkpoint_replay_matches_uninterrupted(fixed, queued, tmp_path):
    points = [{'detuning_gamma': -1.2, 'magnet_radius': .048}] if queued else []
    def suggest(trial):
        return suggest_parameters(trial, fixed, (1.1, 1.5), (-1.55, -.85), (.045, .051))
    def create(storage=None):
        study = optuna.create_study(study_name='replay', storage=storage, load_if_exists=True, directions=['maximize'] if fixed else ['maximize', 'minimize'],
                                   sampler=optuna.samplers.TPESampler(seed=701))
        for point in points:
            study.enqueue_trial(point)
        return study
    def objective(trial):
        params = suggest(trial)
        value = -(params['detuning_gamma'] + 1.1) ** 2 + params['magnet_radius']
        return value if fixed else (value, params['s0'])
    storage = f"sqlite:///{tmp_path / 'study.db'}"
    full, resumed = create(), create(storage)
    full.optimize(objective, n_trials=20)
    for target in [1, 2, 3, 4, 8, 12, 16, 20]:
        resumed = optuna.load_study(study_name="replay", storage=storage, sampler=optuna.samplers.TPESampler(seed=701))
        restore_sampler(resumed, seed=701, suggest=suggest, enqueue_points=points)
        resumed.optimize(objective, n_trials=target - len(resumed.trials))
    assert [(t.params, t.values) for t in resumed.trials] == [(t.params, t.values) for t in full.trials]
    assert len({tuple(t.params.items()) for t in resumed.trials[:4]}) == 4


def test_replay_rejects_wrong_seed_and_partial_failure():
    def suggest(t):
        return suggest_parameters(t, 1.3, (1, 2), (-2, -1), (.04, .05))
    study = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=701))
    study.optimize(lambda t: suggest(t)['magnet_radius'], n_trials=1)
    with pytest.raises(RuntimeError, match='frozen seed'):
        restore_sampler(study, seed=702, suggest=suggest, enqueue_points=[])
    failed = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=701))
    t = failed.ask()
    t.suggest_float('detuning_gamma', -2, -1)
    failed.tell(t, state=optuna.trial.TrialState.FAIL)
    with pytest.raises(RuntimeError, match='frozen seed'):
        restore_sampler(failed, seed=701, suggest=suggest, enqueue_points=[])


def test_replay_full_failure_and_waiting_queue():
    points = [{'detuning_gamma': -1.2, 'magnet_radius': .048},
              {'detuning_gamma': -1.3, 'magnet_radius': .049}]
    def suggest(t):
        return suggest_parameters(t, None, (1, 2), (-2, -1), (.04, .05))
    study = optuna.create_study(directions=['maximize', 'minimize'],
                               sampler=optuna.samplers.TPESampler(seed=701))
    for point in points:
        study.enqueue_trial(point)
    trial = study.ask()
    suggest(trial)
    study.tell(trial, state=optuna.trial.TrialState.FAIL)
    before = study.get_trials(deepcopy=True)
    restore_sampler(study, seed=701, suggest=suggest, enqueue_points=points)
    assert study.get_trials(deepcopy=True) == before
    trial = study.ask()
    parameters = suggest(trial)
    assert parameters['detuning_gamma'] == points[1]['detuning_gamma']
    study.tell(trial, [1, parameters['s0']])
    restore_sampler(study, seed=701, suggest=suggest, enqueue_points=points)


def test_replay_rejects_invented_null_tpe_attribute():
    study = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=701))
    def suggest(t):
        return suggest_parameters(t, 1.3, (1, 2), (-2, -1), (.04, .05))
    study.optimize(lambda t: suggest(t)['magnet_radius'], n_trials=1)
    saved = study.trials[0]
    tampered = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=701))
    tampered.add_trial(optuna.trial.create_trial(
        params=saved.params, distributions=saved.distributions, values=saved.values,
        system_attrs={'tpe:relative_params:invented': None},
    ))
    with pytest.raises(RuntimeError, match='frozen seed'):
        restore_sampler(tampered, seed=701, suggest=suggest, enqueue_points=[])
