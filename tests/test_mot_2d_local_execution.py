import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

from lab_setup.physical_specification import (
    CANONICAL_ZEEMAN_PROFILE_NAME,
    CANONICAL_ZEEMAN_PROFILE_SHA256,
    LABORATORY_PHYSICAL_SPECIFICATION,
    LABORATORY_SPEC_SHA256,
    LABORATORY_SPEC_VERSION,
)
import workflow_api.mot_2d_individual_sources as source_catalog
from workflow_api.mot_2d_individual_sources import list_individual_mot_2d_sources
from workflow_api.mot_2d_sources import SourceScanLimits
import workflow_api.mot_2d_local_execution as local_execution
import config
from workflow_api.mot_2d_local_execution import Mot2DLocalWorker
from workflow_api.mot_2d_run_plan import build_mot_2d_run_plan
from workflow_api.run_execution import (
    IndividualRunExecutionCoordinator,
    WorkerProductError,
    WorkerRequest,
    issue_execution_authority,
)
from workflow_api.run_records import RunRecordStore


NOW = "2026-10-11T10:00:00+00:00"


def _source(root: Path, rows: int = 4) -> str:
    directory = root / "data/particle_states/after_zeeman/source"
    directory.mkdir(parents=True)
    profile = LABORATORY_PHYSICAL_SPECIFICATION["canonical_zeeman_profile"]
    field = {key: list(profile[key]) for key in ("radii_m", "positions_m", "tilt_angles_deg")}
    for seed in range(3000, 3035):
        state = directory / f"production_zeeman_n50000_dt40us_seed{seed}.npy"
        np.save(state, np.arange(rows * 6, dtype=np.float64).reshape(rows, 6) + seed)
        state.with_suffix(".json").write_text(json.dumps({
            "shape": [rows, 6], "dtype": "float64", "n_survivors": rows,
            "output_sha256": hashlib.sha256(state.read_bytes()).hexdigest(),
            "laboratory_spec_version": LABORATORY_SPEC_VERSION,
            "laboratory_spec_sha256": LABORATORY_SPEC_SHA256,
            "zeeman_profile_sha256": CANONICAL_ZEEMAN_PROFILE_SHA256,
            "parameters": {"seed": seed, "resolved_zeeman_magnet_profile": CANONICAL_ZEEMAN_PROFILE_NAME, "n_initial_atoms": 50000, "dt_s": 4e-5, "zeeman_field_config": field},
            "software": {"git_commit": "a" * 40},
        }))
    return list_individual_mot_2d_sources(root)["sources"][0]["id"]


def _request(source_id: str, *, retained: bool = True) -> dict:
    return {"source_id": source_id, "particle_count": 20, "selection_seed": 123, "mot_seed": 456, "s0": 1.3, "detuning_gamma": -0.9196610026631429, "magnet_radius_m": 0.04676406447474441, "npools": 8, "retain_particle_states": retained, "execution_mode": "local"}


def _plan(root: Path, *, retained: bool = True):
    return build_mot_2d_run_plan(_request(_source(root), retained=retained), repository_root=root, run_id="mot2d-local-1", git_revision="b" * 40, created_utc=NOW)


class Engine:
    def __init__(self, survivors=3): self.calls = []; self.survivors = survivors
    def __call__(self, states, **kwargs):
        self.calls.append((states.copy(), kwargs))
        return [], self.survivors, np.ascontiguousarray(states[:self.survivors])


def _worker_request(plan):
    return WorkerRequest(plan.run, plan.configuration, plan.inputs)


def test_worker_materializes_frozen_selection_and_calls_exact_engine_once(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root); engine = Engine()
    product = Mot2DLocalWorker(root, engine=engine, monotonic=iter((1.0, 2.5)).__next__, clock=lambda: NOW).run(_worker_request(plan))
    assert len(engine.calls) == 1
    states, kwargs = engine.calls[0]
    identities = plan.configuration["resolved"]["sampling"]["selected_identities"]
    records = plan.configuration["resolved"]["input_source"]["records"]
    expected = np.stack([np.load(root / records[index]["path"])[row] for index, row in identities])
    np.testing.assert_array_equal(states, expected)
    assert kwargs["_2d_mot_config"] == {"s0": 1.3, "detuning_gamma": -0.9196610026631429, "swap_polarization": False}
    assert kwargs["magnet_radius"] == 0.04676406447474441
    assert kwargs["dt"] == 0.625e-6
    assert kwargs["t_max_s"] == 0.025
    assert kwargs["gravity_enabled"] is kwargs["stochastic"] is True
    assert kwargs["npools"] == 8 and kwargs["seed"] == 456
    frozen_laser = plan.configuration["resolved"]["upstream_zeeman_boundary"]["laser"]
    assert kwargs["zeeman_config"] == {
        "s0": frozen_laser["s0"],
        "detuning_gamma": frozen_laser["detuning_gamma"],
        "polarization": frozen_laser["polarization"],
    }
    assert kwargs["zeeman_field_config"] == local_execution._plain(
        plan.configuration["resolved"]["upstream_zeeman_boundary"]["field"]
    )
    assert kwargs["stochastic_sim_function"] is local_execution.RK4StHybridCustom
    metrics = product.results["metrics"]
    assert metrics["n_input"] == 20 and metrics["n_survivors"] == 3
    assert metrics["conditional_efficiency"] == 3 / 20
    assert metrics["elapsed_s"] == 1.5
    assert metrics["selection_sha256"] == plan.configuration["resolved"]["sampling"]["selected_identities_sha256"]
    assert metrics["provenance"]["configuration_sha256"] == plan.run["configuration_sha256"]
    assert product.results["suitability"] == "individual_only"


@pytest.mark.parametrize("retained", [True, False])
def test_coordinator_publishes_d3_states_or_receipt(tmp_path, retained):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root, retained=retained)
    records = plan.storage_records(); store = RunRecordStore(root)
    try: store.create(records["run"], records["configuration"], records["inputs"], records["status"])
    finally: store.close()
    engine = Engine(2)
    worker = Mot2DLocalWorker(root, engine=engine, monotonic=iter((1.0, 1.5)).__next__, clock=lambda: NOW)
    coordinator = IndividualRunExecutionCoordinator(
        root, worker, issue_execution_authority(), clock=lambda: NOW
    )
    result = coordinator.execute("mot_2d", "mot2d-local-1")
    assert result == {"state": "succeeded", "recovered": False, "worker_started": True}
    assert coordinator.execute("mot_2d", "mot2d-local-1") == {
        "state": "succeeded", "recovered": True, "worker_started": False,
    }
    assert len(engine.calls) == 1
    run_dir = root / "data/runs/mot_2d/mot2d-local-1"
    summary = json.loads((run_dir / "results/summary.json").read_text())
    assert summary["states_retained"] is retained
    if retained:
        states = np.load(run_dir / "results/states.npy", allow_pickle=False)
        assert states.dtype == np.float64 and states.shape == (2, 6)
        assert not (run_dir / "results/state_retention_receipt.json").exists()
    else:
        assert (run_dir / "results/state_retention_receipt.json").is_file()
        assert not (run_dir / "results/states.npy").exists()


@pytest.mark.parametrize("replacement", ["symlink", "fifo", "digest"])
def test_input_artifact_mutation_is_rejected_before_engine(tmp_path, replacement):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root); engine = Engine()
    record = plan.configuration["resolved"]["input_source"]["records"][0]
    target = root / record["path"]
    if replacement == "symlink":
        backup = target.with_name("backup.npy"); target.rename(backup); target.symlink_to(backup.name)
    elif replacement == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("POSIX FIFO fixture is unavailable on Windows")
        target.unlink(); os.mkfifo(target)
    else:
        target.write_bytes(b"x" * record["size_bytes"])
    with pytest.raises(WorkerProductError):
        Mot2DLocalWorker(root, engine=engine).run(_worker_request(plan))
    assert engine.calls == []


def test_selection_digest_and_engine_count_mismatch_are_rejected(tmp_path):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root)
    records = plan.storage_records(); records["configuration"]["resolved"]["sampling"]["selected_identities_sha256"] = "0" * 64
    request = WorkerRequest(records["run"], records["configuration"], records["inputs"])
    engine = Engine()
    with pytest.raises(WorkerProductError, match="selection digest"):
        Mot2DLocalWorker(root, engine=engine).run(request)
    assert engine.calls == []
    with pytest.raises(WorkerProductError, match="count"):
        Mot2DLocalWorker(root, engine=lambda states, **kwargs: ([], 4, states[:3])).run(_worker_request(plan))


def test_global_runtime_drift_after_confirmation_does_not_change_frozen_run(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root); engine = Engine()
    monkeypatch.setitem(config.MOT_2D_SIM_CONFIG, "dt_s", 1.25e-6)
    monkeypatch.setitem(config.MOT_2D_SIM_CONFIG, "t_max_s", 0.123)
    monkeypatch.setitem(config.MOT_2D_SIM_CONFIG, "start_distance_m", 0.321)
    Mot2DLocalWorker(root, engine=engine).run(_worker_request(plan))
    assert len(engine.calls) == 1
    assert engine.calls[0][1]["dt"] == 0.625e-6
    assert engine.calls[0][1]["t_max_s"] == 0.025


@pytest.mark.parametrize(
    ("field", "mutator"),
    [
        ("identity string", lambda sampling: sampling.__setitem__("selected_identities", [[0, "1"]] + sampling["selected_identities"][1:])),
        ("identity float", lambda sampling: sampling.__setitem__("selected_identities", [[0, 1.0]] + sampling["selected_identities"][1:])),
        ("identity bool", lambda sampling: sampling.__setitem__("selected_identities", [[False, 1]] + sampling["selected_identities"][1:])),
        ("duplicate", lambda sampling: sampling["selected_identities"].__setitem__(1, sampling["selected_identities"][0])),
        ("unsorted", lambda sampling: sampling["selected_identities"].__setitem__(slice(0, 2), list(reversed(sampling["selected_identities"][:2])))),
        ("algorithm", lambda sampling: sampling.__setitem__("algorithm", "numpy-choice")),
        ("version", lambda sampling: sampling.__setitem__("version", 999)),
        ("order", lambda sampling: sampling.__setitem__("canonical_order", "random")),
        ("bounds", lambda sampling: sampling["selected_identities"].__setitem__(0, [999, 0])),
    ],
)
def test_frozen_selection_is_strictly_validated_before_engine(tmp_path, field, mutator):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root); engine = Engine()
    records = plan.storage_records()
    sampling = records["configuration"]["resolved"]["sampling"]
    mutator(sampling)
    with pytest.raises(WorkerProductError, match="selection"):
        Mot2DLocalWorker(root, engine=engine).run(
            WorkerRequest(records["run"], records["configuration"], records["inputs"])
        )
    assert engine.calls == [], field


def test_worker_never_reselects_or_uses_rng(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root); engine = Engine()
    def forbidden(*_args, **_kwargs):
        raise AssertionError("execution must use the frozen identities without reselection")
    monkeypatch.setattr(np.random, "PCG64", forbidden)
    monkeypatch.setattr(np.random, "default_rng", forbidden)
    Mot2DLocalWorker(root, engine=engine).run(_worker_request(plan))
    assert len(engine.calls) == 1


def test_worker_does_not_load_full_source_arrays(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root); engine = Engine()
    monkeypatch.setattr(np, "load", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full array load")))
    Mot2DLocalWorker(root, engine=engine).run(_worker_request(plan))
    assert len(engine.calls) == 1


def test_catalog_plan_and_worker_share_exact_total_source_byte_boundary(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir()
    source_id = _source(root)
    source_directory = root / "data/particle_states/after_zeeman/source"
    total_state_bytes = sum(path.stat().st_size for path in source_directory.glob("*.npy"))
    base = source_catalog.individual_mot_2d_source_scan_limits()

    def limits(total):
        return SourceScanLimits(
            maximum_file_bytes=base.maximum_file_bytes,
            maximum_total_bytes=total,
            maximum_rows_per_file=base.maximum_rows_per_file,
            maximum_total_rows=base.maximum_total_rows,
            maximum_npy_header_bytes=base.maximum_npy_header_bytes,
        )

    monkeypatch.setattr(source_catalog, "_INTERACTIVE_LIMITS", limits(total_state_bytes))
    assert [row["id"] for row in list_individual_mot_2d_sources(root)["sources"]] == [source_id]
    plan = build_mot_2d_run_plan(
        _request(source_id), repository_root=root, run_id="mot2d-byte-boundary",
        git_revision="b" * 40, created_utc=NOW,
    )
    engine = Engine()
    Mot2DLocalWorker(root, engine=engine).run(_worker_request(plan))
    assert len(engine.calls) == 1

    monkeypatch.setattr(source_catalog, "_INTERACTIVE_LIMITS", limits(total_state_bytes - 1))
    assert list_individual_mot_2d_sources(root)["sources"] == []
    rejecting_engine = Engine()
    with pytest.raises(WorkerProductError, match="byte limit"):
        Mot2DLocalWorker(root, engine=rejecting_engine).run(_worker_request(plan))
    assert rejecting_engine.calls == []


def test_trusted_engine_boundary_calls_fixed_simulation_once(monkeypatch):
    calls = []
    expected = ([], 0, np.empty((0, 6), dtype=np.float64))
    monkeypatch.setattr(
        "simulations.mot_2d.mot_simulation",
        lambda states, **kwargs: calls.append((states, kwargs)) or expected,
    )
    states = np.ones((2, 6), dtype=np.float64)
    assert local_execution._trusted_engine(states, seed=7) is expected
    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0][0], states)
    assert calls[0][1] == {"seed": 7}


def test_parent_aba_during_attested_read_is_rejected_before_engine(tmp_path, monkeypatch):
    root = tmp_path / "repo"; root.mkdir(); plan = _plan(root); engine = Engine()
    source = root / "data/particle_states/after_zeeman/source"
    moved = source.with_name("source-old")
    original_read = local_execution.os.read
    swapped = False

    def swapping_read(descriptor, count):
        nonlocal swapped
        result = original_read(descriptor, count)
        if not swapped:
            swapped = True
            source.rename(moved)
            source.mkdir()
        return result

    monkeypatch.setattr(local_execution.os, "read", swapping_read)
    with pytest.raises(WorkerProductError):
        Mot2DLocalWorker(root, engine=engine).run(_worker_request(plan))
    assert swapped is True
    assert engine.calls == []
