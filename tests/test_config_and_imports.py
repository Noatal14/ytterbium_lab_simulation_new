import importlib

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
        "full_simulation",
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
