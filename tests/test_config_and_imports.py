import importlib

import numpy as np

import config


def test_yb171_reference_atomic_constants():
    assert np.isclose(config.YB171_MASS_AMU, 170.936331515, rtol=0.0, atol=1e-12)

    assert np.isclose(config.BLUE_TRANSITION.wavelength_m, 398.9108443e-9)
    assert np.isclose(
        config.BLUE_TRANSITION.gamma_rad_s,
        2 * np.pi * 29.13e6,
    )
    assert np.isclose(
        config.BLUE_TRANSITION.lande_g * config.MU_B_OVER_H_KHZ_PER_G,
        965.0,
    )

    assert np.isclose(config.GREEN_TRANSITION.wavelength_m, 555.80068663e-9)
    assert np.isclose(
        config.GREEN_TRANSITION.gamma_rad_s,
        2 * np.pi * 182.4e3,
    )
    assert np.isclose(
        config.GREEN_TRANSITION.lande_g * config.MU_B_OVER_H_KHZ_PER_G,
        1392.674,
    )
    assert np.isclose(config.GREEN_SATURATION_INTENSITY_W_M2, 1.3885, rtol=5e-4)


def test_yb171_j0j1_model_uses_stretched_state_zeeman_shift():
    from lab_setup.atom_species import create_yb171

    atom = create_yb171()
    assert np.isclose(
        atom.trans["399"].lande_factor,
        1.5 * config.BLUE_TRANSITION.lande_g,
    )
    assert np.isclose(
        atom.trans["556"].lande_factor,
        1.5 * config.GREEN_TRANSITION.lande_g,
    )
    assert np.isclose(
        atom.trans["399"].lande_factor,
        config.BLUE_TRANSITION_LANDE_G_J,
        rtol=1e-2,
    )
    assert np.isclose(
        atom.trans["556"].lande_factor,
        config.GREEN_TRANSITION_LANDE_G_J,
        rtol=1e-3,
    )
    assert config.BLUE_TRANSITION_LANDE_G_F == config.BLUE_TRANSITION_ZEEMAN_COEFFICIENT_KHZ_PER_G / config.MU_B_OVER_H_KHZ_PER_G
    assert config.GREEN_TRANSITION_LANDE_G_F == config.GREEN_TRANSITION_ZEEMAN_COEFFICIENT_KHZ_PER_G / config.MU_B_OVER_H_KHZ_PER_G
    assert config.BLUE_TRANSITION_MODEL_EFFECTIVE_LANDE_G == 1.5 * config.BLUE_TRANSITION_LANDE_G_F
    assert config.GREEN_TRANSITION_MODEL_EFFECTIVE_LANDE_G == 1.5 * config.GREEN_TRANSITION_LANDE_G_F


def test_v2_facade_preserves_exact_resolved_hardware_values():
    assert config.Geometry.Z_AXIS == (0.0, 0.0, 1.0)
    assert config.Geometry.ZEEMAN_ARM_1_LENGTH_M == 0.378
    assert config.Geometry.SCIENCE_ARM_TOTAL_LENGTH_M == 0.510
    assert config.Geometry.DPS_LENGTH_M == 0.070
    assert config.Geometry.ZEEMAN_LASER_WAIST_M == 0.007
    from lab_setup.mag_field_Zeeman import resolved_zeeman_field_construction
    from lab_setup.zeeman_laser_setup import resolved_zeeman_laser_parameters
    field = resolved_zeeman_field_construction(radii_m=[.01], positions_m=[.02], tilt_angles_deg=[30.], angle_deg=25., start_distance_m=.314)
    assert field["magnet_dimensions_m"] == [.005, .005, .005]
    assert field["magnet_polarization_T"] == -1.24
    assert field["azimuthal_angles_deg"] == [0., 45., 90., 135., 180., 225., 270., 315.]
    laser = resolved_zeeman_laser_parameters()
    assert (laser["waist_m"], laser["waist_position_m"], laser["direction_type"], laser["tag"]) == (.007, [0., 0., 0.], "vector", "Zeeman_Laser")


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
        "studies.mot_2d.optimization",
        "studies.mot_2d.production",
        "studies.beam_source.full_thermal_flux",
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


def test_paired_mot_batch_forwards_stochastic_simulator(monkeypatch):
    mot_2d_simulation = importlib.import_module("simulations.mot_2d")
    captured = {}
    diagnostic_simulator = object()

    monkeypatch.setattr(
        mot_2d_simulation,
        "build_base_config",
        lambda **kwargs: (None, object()),
    )

    def fake_run_multiple_atoms_simulation(**kwargs):
        captured.update(kwargs)
        return [object()], None

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

    mot_2d_simulation.mot_simulation_paired_ensembles(
        survivor_state_ensembles=[np.zeros((1, 6))],
        seeds=[4000],
        npools=0,
        stochastic_sim_function=diagnostic_simulator,
    )

    assert captured["sim_function"] is diagnostic_simulator
