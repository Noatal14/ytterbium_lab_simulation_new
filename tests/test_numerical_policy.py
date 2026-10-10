"""Integrity and compatibility tests for the numerical-policy contract."""

from __future__ import annotations

from copy import deepcopy
import inspect
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

import config
import lab_setup.numerical_policy as policy_module
from lab_setup.numerical_policy import (
    NUMERICAL_POLICY,
    NUMERICAL_POLICY_SHA256,
    NUMERICAL_POLICY_VERSION,
    SPECIFICATION_PATH,
    _validate,
)
from simulations import mot_2d, mot_3d, pipeline, zeeman


def _mutable():
    return json.loads(SPECIFICATION_PATH.read_text(encoding="utf-8"))


def test_policy_is_immutable_and_config_facade_is_exact():
    assert isinstance(NUMERICAL_POLICY, MappingProxyType)
    assert NUMERICAL_POLICY_VERSION == "numerical-policy-v1"
    assert len(NUMERICAL_POLICY_SHA256) == 64
    assert config.ZEEMAN_SIM_CONFIG == {
        "t_max_s": 0.02, "dt_s": 4e-5,
        "start_distance_m": 0.450, "cutoff_distance_m": 0.100,
    }
    assert config.MOT_2D_SIM_CONFIG == {
        "t_max_s": 0.025, "dt_s": 0.625e-6, "start_distance_m": 0.100,
    }
    assert config.MOT_3D_SIM_CONFIG == {
        "t_max_s": 0.025, "dt_s": 1.25e-6,
        "screening_dt_s": 1.25e-6, "production_dt_s": 0.625e-6,
        "dt_validation_candidates_s": (10e-6, 5e-6, 2.5e-6, 1.25e-6, 0.625e-6),
        "dt_validation_reference_s": 0.3125e-6,
        "solver": "RK4StHybridCustom",
    }
    assert isinstance(config.ZEEMAN_SIM_CONFIG, dict)
    assert isinstance(config.MOT_2D_SIM_CONFIG, dict)
    assert isinstance(config.MOT_3D_SIM_CONFIG["dt_validation_candidates_s"], tuple)


def test_import_time_function_defaults_remain_bound_to_facade_values():
    assert inspect.signature(zeeman.zeeman_simulation).parameters["dt"].default == config.ZEEMAN_SIM_CONFIG["dt_s"]
    assert inspect.signature(mot_2d.mot_simulation).parameters["dt"].default == config.MOT_2D_SIM_CONFIG["dt_s"]
    assert inspect.signature(mot_3d.mot_3d_simulation).parameters["dt"].default == config.MOT_3D_SIM_CONFIG["dt_s"]
    assert inspect.signature(pipeline.run_both).parameters["zeeman_dt"].default == config.ZEEMAN_SIM_CONFIG["dt_s"]
    assert inspect.signature(pipeline.run_both).parameters["mot_dt"].default == config.MOT_2D_SIM_CONFIG["dt_s"]


def test_closed_solver_resolver_controls_2d_default_without_identity_change():
    from utils.RK4StCustom import RK4StCustom
    from utils.RK4StHybridCustom import RK4StHybridCustom

    assert config.MOT_2D_STOCHASTIC_SOLVER_NAME == "RK4StHybridCustom"
    assert config.MOT_2D_STOCHASTIC_SOLVER is RK4StHybridCustom
    assert config.resolve_stochastic_solver("RK4StHybridCustom") is RK4StHybridCustom
    assert config.resolve_stochastic_solver("RK4StCustom") is RK4StCustom
    assert config.MOT_3D_STOCHASTIC_SOLVER_NAME == "RK4StHybridCustom"
    assert config.MOT_3D_STOCHASTIC_SOLVER is RK4StHybridCustom
    assert mot_3d._configured_3d_solver() is RK4StHybridCustom
    assert inspect.signature(mot_2d.mot_simulation).parameters[
        "stochastic_sim_function"
    ].default is RK4StHybridCustom
    with pytest.raises(ValueError, match="Unsupported stochastic solver"):
        config.resolve_stochastic_solver("arbitrary.import.Path")


def test_3d_runtime_solver_selection_observes_the_config_facade(monkeypatch):
    from utils.RK4StCustom import RK4StCustom

    monkeypatch.setitem(config.MOT_3D_SIM_CONFIG, "solver", "RK4StCustom")
    assert mot_3d._configured_3d_solver() is RK4StCustom

    monkeypatch.setitem(config.MOT_3D_SIM_CONFIG, "solver", "unknown")
    with pytest.raises(ValueError, match="Unsupported stochastic solver"):
        mot_3d._configured_3d_solver()


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(extra=True),
    lambda value: value["zeeman"].update(dt_s=True),
    lambda value: value["mot_2d"].update(solver="RK4StCustom"),
    lambda value: value["mot_3d"].update(dt_s=float("nan")),
    lambda value: value["mot_3d"].update(dt_validation_candidates_s=[]),
    lambda value: value["mot_3d"].update(dt_validation_candidates_s=[1e-6, 2e-6]),
    lambda value: value["mot_3d"].update(dt_validation_reference_s=0.625e-6),
    lambda value: value["mot_3d"].update(production_dt_s=2e-6),
    lambda value: value["mot_3d"].update(screening_dt_s=1.1e-6, dt_s=1.1e-6),
    lambda value: value["mot_3d"].update(production_dt_s=0.7e-6),
])
def test_invalid_policy_is_rejected(mutation):
    value = deepcopy(_mutable())
    mutation(value)
    with pytest.raises(ValueError):
        _validate(value)


@pytest.mark.parametrize("kind", ["symlink", "oversize", "truncated"])
def test_loader_rejects_unsafe_or_malformed_files(tmp_path, monkeypatch, kind):
    path = tmp_path / "policy.json"
    if kind == "symlink":
        target = tmp_path / "target.json"
        target.write_text(SPECIFICATION_PATH.read_text())
        path.symlink_to(target)
    elif kind == "oversize":
        path.write_bytes(b" " * (policy_module.MAX_SPECIFICATION_BYTES + 1))
    else:
        path.write_text('{"spec_version":')
    monkeypatch.setattr(policy_module, "SPECIFICATION_PATH", path)
    with pytest.raises(RuntimeError, match="numerical policy is invalid"):
        policy_module._read_validated()


def test_loader_detects_descriptor_change_during_read(tmp_path, monkeypatch):
    path = tmp_path / "policy.json"
    path.write_text(SPECIFICATION_PATH.read_text())
    monkeypatch.setattr(policy_module, "SPECIFICATION_PATH", path)
    real_fstat = os.fstat
    calls = 0

    def changing_fstat(descriptor):
        nonlocal calls
        calls += 1
        observed = real_fstat(descriptor)
        if calls < 2:
            return observed
        values = list(observed)
        values[8] = observed.st_mtime + 1
        return os.stat_result(values)

    monkeypatch.setattr(policy_module.os, "fstat", changing_fstat)
    with pytest.raises(RuntimeError, match="numerical policy is invalid"):
        policy_module._read_validated()
