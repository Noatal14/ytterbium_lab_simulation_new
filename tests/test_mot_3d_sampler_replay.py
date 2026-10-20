"""The real multivariate 3D sampler survives actual SQLite reconnects exactly."""
import optuna
import pytest

from studies.mot_3d.discovery.optimize import (
    _resolved_trial_parameters, _seed_parameters, build_trial_profile,
    restore_discovery_sampler,
)


def _open(path, family, seed=117):
    study = optuna.create_study(storage='sqlite:///' + str(path), study_name=family,
        direction='maximize', sampler=optuna.samplers.TPESampler(
            seed=seed, multivariate=True, n_startup_trials=24), load_if_exists=True)
    study.enqueue_trial(_seed_parameters(family, 0),
                        user_attrs={'source': 'physics_seed'}, skip_if_exists=True)
    return study


def _objective(family, trial):
    profile, parameters, derived = build_trial_profile(family, trial)
    count = int(abs(sum(parameters.values())) * 1000) % 8
    attributes = {'resolved_parameters': _resolved_trial_parameters(profile, parameters, derived),
        'usable_at_end_count': count, 'usable_ever_count': 8,
        'entered_capture_region_count': 8, 'slow_inside_count': count,
        'runtime_seconds': 0.25}
    for key, value in attributes.items():
        trial.set_user_attr(key, value)
    return count / 8


def _restore(study, family, seed=117):
    restore_discovery_sampler(study, family=family, worker_index=0,
                             sampler_seed=seed, startup_trials=24, particle_count=8)


@pytest.mark.parametrize('family', ['angled_donut', 'single_pass'])
@pytest.mark.parametrize('checkpoints', [(1, 4, 8, 16, 24, 32, 40), (32, 40)],
                         ids=['startup-and-adaptive-restarts', 'adaptive-native-prefix'])
def test_sqlite_checkpoint_sequence_equals_uninterrupted(tmp_path, family, checkpoints):
    baseline = _open(tmp_path / 'baseline.db', family)
    baseline.optimize(lambda trial: _objective(family, trial), n_trials=40)
    expected = [(trial.params, trial.values, trial.user_attrs) for trial in baseline.trials]
    for target in checkpoints:
        resumed = _open(tmp_path / 'resumed.db', family)
        _restore(resumed, family)
        resumed.optimize(lambda trial: _objective(family, trial), n_trials=target-len(resumed.trials))
    assert [(trial.params, trial.values, trial.user_attrs) for trial in resumed.trials] == expected
    assert len({tuple(sorted(trial.params.items())) for trial in resumed.trials}) == 40


@pytest.mark.parametrize('attack', ['wrong_seed', 'unknown_attribute', 'partial_failure', 'invented_tpe_key'])
def test_unverifiable_history_fails_closed(tmp_path, attack):
    family = 'single_pass'
    study = _open(tmp_path / 'history.db', family)
    if attack == 'partial_failure':
        trial = study.ask()
        trial.suggest_float('green_s0', 1, 100)
        study.tell(trial, state=optuna.trial.TrialState.FAIL)
    else:
        study.optimize(lambda trial: _objective(family, trial), n_trials=2)
        if attack == 'unknown_attribute':
            # Public storage API preserves an intentionally unsupported history.
            trial = study.ask()
            trial.set_user_attr('unreviewed', True)
            _objective(family, trial)
            study.tell(trial, 0.0)
        elif attack == 'invented_tpe_key':
            tampered = optuna.create_study(direction='maximize')
            for index, saved in enumerate(study.trials):
                attributes = dict(saved.system_attrs)
                if index == 0:
                    attributes['tpe:relative_params:invented'] = None
                tampered.add_trial(optuna.trial.create_trial(
                    params=saved.params, distributions=saved.distributions,
                    values=saved.values, state=saved.state,
                    user_attrs=saved.user_attrs, system_attrs=attributes,
                ))
            study = tampered
    with pytest.raises(RuntimeError, match='history|sampler'):
        _restore(study, family, seed=118 if attack == 'wrong_seed' else 117)


@pytest.mark.parametrize('family', ['angled_donut', 'single_pass'])
def test_full_suggestion_failure_consumes_same_stream_after_restart(tmp_path, family):
    def prefix(path):
        study = _open(path, family)
        study.optimize(lambda trial: _objective(family, trial), n_trials=1)
        failed = study.ask()
        build_trial_profile(family, failed)
        study.tell(failed, state=optuna.trial.TrialState.FAIL)
        return study
    baseline = prefix(tmp_path / 'baseline-fail.db')
    baseline.optimize(lambda trial: _objective(family, trial), n_trials=30)
    prefix(tmp_path / 'resumed-fail.db')
    resumed = _open(tmp_path / 'resumed-fail.db', family)
    _restore(resumed, family)
    resumed.optimize(lambda trial: _objective(family, trial), n_trials=30)
    assert [(trial.params, trial.values, trial.state) for trial in resumed.trials] == [
        (trial.params, trial.values, trial.state) for trial in baseline.trials]


def test_initial_waiting_queue_is_verified_without_replacing_fresh_sampler(tmp_path):
    family = 'single_pass'
    study = _open(tmp_path / 'waiting.db', family)
    sampler = study.sampler
    _restore(study, family)
    assert study.sampler is sampler
    assert len(study.trials) == 1
    invalid = optuna.create_study(direction='maximize')
    invalid.enqueue_trial(_seed_parameters(family, 0), user_attrs={'source':'unreviewed'})
    with pytest.raises(RuntimeError, match='queued'):
        _restore(invalid, family)
