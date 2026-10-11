from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil

import numpy as np
import pytest

import workflow_api.run_results as run_results_module
from workflow_api.run_discovery import discover_run_snapshot, discover_runs, inspect_run
from workflow_api.run_records import (
    RunRecordError,
    RunRecordStore,
    encode_record,
    record_sha256,
)
from workflow_api.run_results import validate_publication_plan


NOW = "2026-10-11T10:00:00+00:00"


def records(*, retained=False):
    configuration = {
        "schema_version": "run-configuration-v1",
        "run_id": "run-1",
        "family": "zeeman",
        "laboratory_spec": {"version": "laboratory-physical-v1", "sha256": "b" * 64},
        "numerical_policy": {"version": "numerical-policy-v1", "sha256": "c" * 64},
        "resolved": {"example_si": 1.0},
    }
    inputs = {
        "schema_version": "run-inputs-v1",
        "run_id": "run-1",
        "family": "zeeman",
        "artifacts": [],
    }
    disposition = (
        {"kind": "particle_states", "path": "results/states.npy", "required": True}
        if retained
        else {
            "kind": "retention_receipt",
            "path": "results/state_retention_receipt.json",
            "required": True,
        }
    )
    run = {
        "schema_version": "individual-run-v1",
        "run_id": "run-1",
        "family": "zeeman",
        "created_utc": NOW,
        "execution_mode": "local",
        "git_revision": "a" * 40,
        "configuration_sha256": record_sha256("configuration", configuration),
        "inputs_sha256": record_sha256("inputs", inputs),
        "particle_count": 100,
        "seed": 7,
        "solver": "RK4StCustom",
        "timestep_s": 4e-5,
        "retention": {"particle_states": retained},
        "outputs": [
            {"kind": "summary", "path": "results/summary.json", "required": True},
            disposition,
        ],
        "suitability": "individual_only",
    }
    status = {
        "schema_version": "run-status-v1",
        "run_id": "run-1",
        "revision": 3,
        "state": "running",
        "updated_utc": NOW,
        "execution": {"mode": "local", "local_pid": 123, "zeus_job_id": None},
        "error": None,
    }
    initial = dict(status)
    initial.update(revision=0, state="configured")
    initial["execution"] = {"mode": "local", "local_pid": None, "zeus_job_id": None}
    return run, configuration, inputs, initial, status


def make_run(tmp_path: Path, *, retained=False):
    root = tmp_path / "repo"
    root.mkdir()
    store = RunRecordStore(root)
    run, config, inputs, initial, running = records(retained=retained)
    directory = store.create(run, config, inputs, initial)
    # D3 neither owns nor invokes the execution lifecycle.  Install a
    # canonical running fixture directly, as an executor will once D2 exposes
    # its separately reviewed admission boundary.
    (directory / "status.json").write_bytes(encode_record("status", running))
    return root, directory


def receipt():
    return {
        "schema_version": "state-retention-receipt-v1",
        "run_id": "run-1",
        "created_utc": NOW,
        "reason": "particle_states_not_retained",
    }


def result(artifact, *, retained=False, captured=0):
    return {
        "schema_version": "run-results-v1",
        "run_id": "run-1",
        "completed_utc": NOW,
        "states_retained": retained,
        "suitability": "individual_only",
        "metrics": {"captured": captured},
        "artifacts": [artifact],
    }


def test_omitted_states_plan_requires_exact_receipt_and_no_states(tmp_path):
    _root, directory = make_run(tmp_path)
    raw = encode_record("retention_receipt", receipt())
    artifact = {
        "kind": "retention_receipt",
        "path": "results/state_retention_receipt.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    plan = validate_publication_plan(directory, result(artifact), receipt())
    assert plan.receipt_bytes == raw
    assert plan.state_array is None
    assert plan.expected_status_revision == 3
    (directory / "results/states.npy").write_bytes(b"stale")
    with pytest.raises(RunRecordError, match="remain"):
        validate_publication_plan(directory, result(artifact), receipt())


def test_retained_states_are_float64_n_by_six_finite_and_counted(tmp_path):
    _root, directory = make_run(tmp_path, retained=True)
    path = directory / "results/states.npy"
    np.save(path, np.arange(18, dtype=np.float64).reshape(3, 6))
    raw = path.read_bytes()
    artifact = {
        "kind": "particle_states",
        "path": "results/states.npy",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    plan = validate_publication_plan(
        directory, result(artifact, retained=True, captured=3)
    )
    assert plan.state_array.shape == (3, 6)
    assert plan.state_array.survivor_count == 3
    values = np.load(path)
    values[0, 0] = np.nan
    np.save(path, values)
    changed = path.read_bytes()
    artifact.update(sha256=hashlib.sha256(changed).hexdigest(), size_bytes=len(changed))
    with pytest.raises(RunRecordError, match="non-finite"):
        validate_publication_plan(
            directory, result(artifact, retained=True, captured=3)
        )


def test_state_symlink_and_wrong_digest_are_rejected(tmp_path):
    _root, directory = make_run(tmp_path, retained=True)
    outside = tmp_path / "outside.npy"
    np.save(outside, np.zeros((1, 6), dtype=np.float64))
    path = directory / "results/states.npy"
    path.symlink_to(outside)
    raw = outside.read_bytes()
    artifact = {
        "kind": "particle_states",
        "path": "results/states.npy",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    with pytest.raises(RunRecordError, match="trusted regular"):
        validate_publication_plan(
            directory, result(artifact, retained=True, captured=1)
        )
    path.unlink()
    path.write_bytes(raw)
    artifact["sha256"] = "f" * 64
    with pytest.raises(RunRecordError, match="digest"):
        validate_publication_plan(
            directory, result(artifact, retained=True, captured=1)
        )


@pytest.mark.parametrize(
    "array", [np.zeros((2, 5)), np.zeros((2, 6), dtype=np.float32), np.zeros((101, 6))]
)
def test_state_shape_dtype_and_particle_bound_are_closed(tmp_path, array):
    _root, directory = make_run(tmp_path, retained=True)
    path = directory / "results/states.npy"
    np.save(path, array)
    raw = path.read_bytes()
    artifact = {
        "kind": "particle_states",
        "path": "results/states.npy",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    with pytest.raises(RunRecordError):
        validate_publication_plan(
            directory, result(artifact, retained=True, captured=len(array))
        )


def test_realized_outputs_must_exactly_match_planned_set(tmp_path):
    _root, directory = make_run(tmp_path)
    raw = encode_record("retention_receipt", receipt())
    artifact = {
        "kind": "retention_receipt",
        "path": "results/state_retention_receipt.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    value = result(artifact)
    value["artifacts"].append(
        {
            "kind": "run_log",
            "path": "logs/extra.log",
            "sha256": "d" * 64,
            "size_bytes": 0,
        }
    )
    with pytest.raises(RunRecordError, match="reviewed plan"):
        validate_publication_plan(directory, value, receipt())


def test_optional_declared_output_may_be_absent_or_realized_with_exact_kind(tmp_path):
    _root, directory = make_run(tmp_path)
    run = records()[0]
    run["outputs"].append(
        {"kind": "run_log", "path": "logs/run.log", "required": False}
    )
    (directory / "run.json").write_bytes(encode_record("run", run))
    raw = encode_record("retention_receipt", receipt())
    receipt_row = {
        "kind": "retention_receipt",
        "path": "results/state_retention_receipt.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    validate_publication_plan(directory, result(receipt_row), receipt())
    log = directory / "logs/run.log"
    log.write_bytes(b"done\n")
    log_row = {
        "kind": "run_log",
        "path": "logs/run.log",
        "sha256": hashlib.sha256(b"done\n").hexdigest(),
        "size_bytes": 5,
    }
    realized = result(receipt_row)
    realized["artifacts"].append(log_row)
    validate_publication_plan(directory, realized, receipt())
    log_row["kind"] = "scheduler_receipt"
    with pytest.raises(RunRecordError, match="kinds"):
        validate_publication_plan(directory, realized, receipt())


def test_artifact_parent_replacement_is_detected_through_descriptor_chain(
    tmp_path, monkeypatch
):
    _root, directory = make_run(tmp_path, retained=True)
    states = directory / "results/states.npy"
    np.save(states, np.zeros((1, 6), dtype=np.float64))
    raw = states.read_bytes()
    artifact = {
        "kind": "particle_states",
        "path": "results/states.npy",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    original = run_results_module._finish_stable_read
    swapped = False

    def replace_parent(parent, name, descriptor, opened, links):
        nonlocal swapped
        if links and not swapped:
            swapped = True
            (directory / "results").rename(directory / "results-detached")
            (directory / "results").mkdir()
        return original(parent, name, descriptor, opened, links)

    monkeypatch.setattr(run_results_module, "_finish_stable_read", replace_parent)
    with pytest.raises(RunRecordError, match="path changed"):
        validate_publication_plan(
            directory, result(artifact, retained=True, captured=1)
        )


def test_run_directory_replacement_is_detected_even_with_open_descriptor(
    tmp_path, monkeypatch
):
    _root, directory = make_run(tmp_path)
    raw = encode_record("retention_receipt", receipt())
    artifact = {
        "kind": "retention_receipt",
        "path": "results/state_retention_receipt.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    original = run_results_module._read_record_at
    swapped = False

    def replace_run(descriptor, relative, kind):
        nonlocal swapped
        value = original(descriptor, relative, kind)
        if not swapped:
            swapped = True
            directory.rename(directory.with_name("run-1-detached"))
            directory.mkdir()
        return value

    monkeypatch.setattr(run_results_module, "_read_record_at", replace_run)
    with pytest.raises(RunRecordError, match="changed"):
        validate_publication_plan(directory, result(artifact), receipt())


@pytest.mark.parametrize("level", ("data", "runs", "family"))
def test_canonical_ancestor_replacement_is_detected(tmp_path, monkeypatch, level):
    root, directory = make_run(tmp_path)
    raw = encode_record("retention_receipt", receipt())
    artifact = {
        "kind": "retention_receipt",
        "path": "results/state_retention_receipt.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    targets = {
        "data": root / "data",
        "runs": root / "data/runs",
        "family": root / "data/runs/zeeman",
    }
    target = targets[level]
    original = run_results_module._read_record_at
    swapped = False

    def replace_ancestor(descriptor, relative, kind):
        nonlocal swapped
        value = original(descriptor, relative, kind)
        if not swapped:
            swapped = True
            target.rename(target.with_name(f"{target.name}-detached"))
            target.mkdir()
        return value

    monkeypatch.setattr(run_results_module, "_read_record_at", replace_ancestor)
    with pytest.raises(RunRecordError, match="changed"):
        validate_publication_plan(directory, result(artifact), receipt())


def test_inspection_uses_held_run_descriptor_across_aba_swap(tmp_path, monkeypatch):
    root, directory = make_run(tmp_path)
    detached = directory.with_name("run-1-detached")
    replacement = directory.with_name("run-1-replacement")
    original = run_results_module._read_record_at
    calls = 0

    def aba_swap(descriptor, relative, kind):
        nonlocal calls
        value = original(descriptor, relative, kind)
        calls += 1
        if calls == 1:
            directory.rename(detached)
            directory.mkdir()
        elif calls == 4:
            directory.rename(replacement)
            detached.rename(directory)
        return value

    monkeypatch.setattr(run_results_module, "_read_record_at", aba_swap)
    inspected = inspect_run(root, "zeeman", "run-1")
    assert calls >= 4
    assert inspected.run["run_id"] == "run-1"
    assert inspected.status["state"] == "running"


def test_status_mode_and_timestamp_must_match_run(tmp_path):
    _root, directory = make_run(tmp_path)
    raw = encode_record("retention_receipt", receipt())
    artifact = {
        "kind": "retention_receipt",
        "path": "results/state_retention_receipt.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    status = records()[4]
    status["execution"] = {"mode": "zeus", "local_pid": None, "zeus_job_id": "1.server"}
    (directory / "status.json").write_bytes(encode_record("status", status))
    with pytest.raises(RunRecordError, match="execution mode"):
        validate_publication_plan(directory, result(artifact), receipt())

    run = records()[0]
    run["created_utc"] = "2026-10-11T10:00:01Z"
    (directory / "run.json").write_bytes(encode_record("run", run))
    status = records()[4]
    (directory / "status.json").write_bytes(encode_record("status", status))
    with pytest.raises(RunRecordError, match="timestamps"):
        validate_publication_plan(directory, result(artifact), receipt())


def test_receipt_is_bound_to_run_and_registry_bytes(tmp_path):
    _root, directory = make_run(tmp_path)
    raw = encode_record("retention_receipt", receipt())
    artifact = {
        "kind": "retention_receipt",
        "path": "results/state_retention_receipt.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    other = dict(receipt())
    other["run_id"] = "other"
    with pytest.raises(RunRecordError, match="another run"):
        validate_publication_plan(directory, result(artifact), other)
    artifact["sha256"] = "e" * 64
    with pytest.raises(RunRecordError, match="does not match"):
        validate_publication_plan(directory, result(artifact), receipt())


def test_discovery_distinguishes_durable_registry_running_from_verified_success(
    tmp_path,
):
    root, directory = make_run(tmp_path)
    raw = encode_record("retention_receipt", receipt())
    (directory / "results/state_retention_receipt.json").write_bytes(raw)
    artifact = {
        "kind": "retention_receipt",
        "path": "results/state_retention_receipt.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    registry = result(artifact)
    (directory / "results/summary.json").write_bytes(encode_record("results", registry))
    found = discover_runs(root)
    assert found[0].integrity == "incomplete_publication"
    assert found[0].state == "running"
    inspected = inspect_run(root, "zeeman", "run-1")
    assert inspected.integrity == "incomplete_publication"
    assert (
        inspected.publication.results_sha256
        == hashlib.sha256(encode_record("results", registry)).hexdigest()
    )
    with pytest.raises(TypeError):
        inspected.run["seed"] = 8


def test_running_registry_rejects_swap_to_different_valid_run(tmp_path, monkeypatch):
    root, directory = make_run(tmp_path)
    raw = encode_record("retention_receipt", receipt())
    (directory / "results/state_retention_receipt.json").write_bytes(raw)
    artifact = {
        "kind": "retention_receipt",
        "path": "results/state_retention_receipt.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    registry = result(artifact)
    (directory / "results/summary.json").write_bytes(encode_record("results", registry))

    replacement = directory.with_name("run-1-valid-replacement")
    detached = directory.with_name("run-1-detached")
    shutil.copytree(directory, replacement)
    replacement_status = records()[4]
    replacement_status["revision"] = 99
    (replacement / "status.json").write_bytes(
        encode_record("status", replacement_status)
    )
    original = run_results_module._validate_publication_plan_at
    swapped = False

    def swap_before_validation(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            directory.rename(detached)
            replacement.rename(directory)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        run_results_module, "_validate_publication_plan_at", swap_before_validation
    )
    with pytest.raises(RunRecordError, match="changed"):
        inspect_run(root, "zeeman", "run-1")


def test_succeeded_timestamp_follows_durable_registry(tmp_path):
    root, directory = make_run(tmp_path)
    completed = "2026-10-11T10:01:00+00:00"
    succeeded_at = "2026-10-11T10:02:00+00:00"
    value = receipt()
    value["created_utc"] = completed
    raw = encode_record("retention_receipt", value)
    (directory / "results/state_retention_receipt.json").write_bytes(raw)
    artifact = {
        "kind": "retention_receipt",
        "path": "results/state_retention_receipt.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    registry = result(artifact)
    registry["completed_utc"] = completed
    (directory / "results/summary.json").write_bytes(encode_record("results", registry))
    succeeded = {
        "schema_version": "run-status-v1",
        "run_id": "run-1",
        "revision": 4,
        "state": "succeeded",
        "updated_utc": succeeded_at,
        "execution": {"mode": "local", "local_pid": None, "zeus_job_id": None},
        "error": None,
    }
    (directory / "status.json").write_bytes(encode_record("status", succeeded))
    inspected = inspect_run(root, "zeeman", "run-1")
    assert inspected.integrity == "complete_verified"
    registry["completed_utc"] = "2026-10-11T10:03:00+00:00"
    (directory / "results/summary.json").write_bytes(encode_record("results", registry))
    assert discover_runs(root)[0].integrity == "invalid"


def test_discovery_never_calls_succeeded_without_a_registry_complete(tmp_path):
    root, directory = make_run(tmp_path)
    status = {
        "schema_version": "run-status-v1",
        "run_id": "run-1",
        "revision": 4,
        "state": "succeeded",
        "updated_utc": NOW,
        "execution": {"mode": "local", "local_pid": None, "zeus_job_id": None},
        "error": None,
    }
    (directory / "status.json").write_bytes(encode_record("status", status))
    found = discover_runs(root)
    assert found[0].integrity == "invalid"
    assert found[0].state == "unknown"


def test_discovery_ignores_hidden_staging_and_reports_symlink_path(tmp_path):
    root = tmp_path / "repo"
    family = root / "data/runs/zeeman"
    family.mkdir(parents=True)
    (family / ".run.creating-deadbeef").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (family / "evil").symlink_to(outside, target_is_directory=True)
    found = discover_runs(root)
    assert len(found) == 1
    assert found[0].run_id == "evil"
    assert found[0].integrity == "invalid"
    assert found[0].diagnostic == "untrusted_run_path"


def test_discovery_overflow_is_bounded_without_total_failure(tmp_path):
    root, _directory = make_run(tmp_path)
    family = root / "data/runs/zeeman"
    (family / "run-2").mkdir()
    snapshot = discover_run_snapshot(root, maximum_runs=1)
    assert len(snapshot.records) == 1
    assert snapshot.truncated is True


def test_hidden_entries_consume_discovery_budget_before_sorting(tmp_path):
    root, _directory = make_run(tmp_path)
    family = root / "data/runs/zeeman"
    for index in range(4):
        (family / f".hidden-{index}").mkdir()
    snapshot = discover_run_snapshot(root, maximum_runs=2)
    assert snapshot.truncated is True
    assert len(snapshot.records) <= 2


def test_typed_inspection_rejects_noncanonical_identity(tmp_path):
    root, _directory = make_run(tmp_path)
    for run_id in ("../run-1", "run-1/child", ".hidden", "UPPER"):
        with pytest.raises(RunRecordError, match="Run id"):
            inspect_run(root, "zeeman", run_id)
