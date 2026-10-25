"""Sequential Optuna replay adapter shared by optimizers, without physics imports."""

import optuna


class SequentialReplaySampler(optuna.samplers.BaseSampler):
    """Keep the advanced sampler attached to its public shadow study."""

    def __init__(self, shadow, suggest):
        self.shadow = shadow
        self.suggest = suggest
        self.active = None

    def before_trial(self, study, trial):
        if self.active is not None:
            raise RuntimeError("Concurrent sampler replay is unsupported.")
        self.active = self.shadow.ask()
        if self.active.number != trial.number:
            raise RuntimeError("Sampler replay trial numbering mismatch.")
        self.suggest(self.active)

    def infer_relative_search_space(self, study, trial):
        return {}

    def sample_relative(self, study, trial, search_space):
        return {}

    def sample_independent(self, study, trial, param_name, param_distribution):
        if self.active is None or self.active.distributions.get(param_name) != param_distribution:
            raise RuntimeError("Sampler replay distribution mismatch.")
        return self.active.params[param_name]

    def after_trial(self, study, trial, state, values):
        if (self.active is None or trial.params != self.active.params
                or trial.distributions != self.active.distributions):
            raise RuntimeError("Sampler replay trial mismatch.")
        self.shadow.tell(self.active, values=values, state=state)
        self.active = None

    def reseed_rng(self):
        raise RuntimeError("Parallel/reseeded sampler replay is unsupported.")
