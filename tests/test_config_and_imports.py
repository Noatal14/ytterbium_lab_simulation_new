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
        "split_simulation",
        "zeeman_simulation",
        "mot_2d_simulation",
        "mot_3d_simulation",
        "optimize_2d_mot",
        "optimize_2d_mot_fixed_s0",
        "thermal_beam",
        "lab_setup.config_builder",
    ]

    for name in modules:
        module = importlib.import_module(name)
        assert module is not None


def test_active_config_names_match_main_workflow():
    split_simulation = importlib.import_module("split_simulation")
    assert split_simulation.DEFAULT_NUM_PARTICLES == config.DEFAULT_NUM_PARTICLES


def test_mot_simulation_forwards_requested_seed(monkeypatch):
    mot_2d_simulation = importlib.import_module("mot_2d_simulation")
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
