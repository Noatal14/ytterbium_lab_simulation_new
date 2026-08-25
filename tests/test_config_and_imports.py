import importlib

import numpy as np

import config


def test_authoritative_force_scale_and_defaults_are_exposed():
    assert hasattr(config, "FORCE_SCALE_N")
    assert isinstance(config.FORCE_SCALE_N, float)
    assert config.FORCE_SCALE_N > 0
    assert hasattr(config, "DEFAULT_NUM_PARTICLES")
    assert config.DEFAULT_NUM_PARTICLES > 0


def test_main_active_modules_import_cleanly():
    modules = [
        "simulations.pipeline",
        "simulations.zeeman",
        "simulations.mot_2d",
        "simulations.mot_3d",
        "simulations.thermal_beam",
        "studies.optimize_2d_mot",
        "studies.optimize_2d_mot_joint",
        "studies.mot_2d_timestep_convergence",
        "studies.optimize_2d_mot_fixed_s0",
        "studies.mot_seed_scan",
        "lab_setup.atom_species",
        "lab_setup.config_builder",
    ]

    for name in modules:
        module = importlib.import_module(name)
        assert module is not None


def test_active_config_names_match_main_workflow():
    pipeline = importlib.import_module("simulations.pipeline")
    assert pipeline.DEFAULT_NUM_PARTICLES == config.DEFAULT_NUM_PARTICLES


def test_mot_simulation_forwards_requested_seed(monkeypatch):
    mot_2d_simulation = importlib.import_module("simulations.mot_2d")
    captured = {}

    monkeypatch.setattr(
        mot_2d_simulation,
        "build_base_config",
        lambda **kwargs: (None, object()),
    )

    def fake_run_multiple_atoms_simulation(**kwargs):
        captured["seed_idx"] = kwargs["seed_idx"]
        return [], None

    monkeypatch.setattr(
        mot_2d_simulation,
        "run_multiple_atoms_simulation",
        fake_run_multiple_atoms_simulation,
    )
    monkeypatch.setattr(
        mot_2d_simulation,
        "mot_extract_survivors",
        lambda results: (np.empty((0, 6)), 0, []),
    )

    mot_2d_simulation.mot_simulation(
        survivor_states=np.zeros((1, 6)),
        seed=137,
    )

    assert captured["seed_idx"] == 137


def test_paired_mot_batch_preserves_per_ensemble_rng_streams(monkeypatch):
    mot_2d_simulation = importlib.import_module("simulations.mot_2d")
    captured = {}

    monkeypatch.setattr(
        mot_2d_simulation,
        "build_base_config",
        lambda **kwargs: (None, object()),
    )

    def fake_run_multiple_atoms_simulation(**kwargs):
        captured.update(kwargs)
        return list(range(len(kwargs["u0"]))), None

    monkeypatch.setattr(
        mot_2d_simulation,
        "run_multiple_atoms_simulation",
        fake_run_multiple_atoms_simulation,
    )
    monkeypatch.setattr(
        mot_2d_simulation,
        "mot_extract_survivors",
        lambda results: (np.empty((len(results), 6)), len(results), []),
    )

    grouped = mot_2d_simulation.mot_simulation_paired_ensembles(
        survivor_state_ensembles=[np.zeros((2, 6)), np.ones((3, 6))],
        seeds=[4000, 4001],
        npools=7,
    )

    assert [count for _, count, _ in grouped] == [2, 3]
    assert len(captured["u0"]) == 5
    assert captured["npools"] == 7

    actual = captured["trajectory_seed_sequences"]
    expected = [
        *np.random.SeedSequence(4000).spawn(2),
        *np.random.SeedSequence(4001).spawn(3),
    ]
    assert all(
        np.array_equal(a.generate_state(8), b.generate_state(8))
        for a, b in zip(actual, expected)
    )
