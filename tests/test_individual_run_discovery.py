import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

import workflow_api.individual_run_discovery as discovery_api
from workflow_api.individual_run_discovery import (
    CanonicalIndividualRunRegistry,
    IndividualRunDiscoveryError,
)
from workflow_api.run_records import RunRecordStore, encode_record, record_sha256
from workflow_api.run_discovery import DiscoverySnapshot


NOW = "2026-10-11T10:00:00+00:00"


def _records(run_id="run-1", family="zeeman", *, retained=False):
    configuration = {
        "schema_version": "run-configuration-v1",
        "run_id": run_id,
        "family": family,
        "laboratory_spec": {"version": "laboratory-physical-v1", "sha256": "b" * 64},
        "numerical_policy": {"version": "numerical-policy-v1", "sha256": "c" * 64},
        "resolved": {"particle_count": 100, "detuning_gamma": -1.0, "simulation": {"particle_count": 100}},
    }
    inputs = {
        "schema_version": "run-inputs-v1",
        "run_id": run_id,
        "family": family,
        "artifacts": [],
    }
    run = {
        "schema_version": "individual-run-v1",
        "run_id": run_id,
        "family": family,
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
            (
                {"kind": "particle_states", "path": "results/states.npy", "required": True}
                if retained
                else {
                    "kind": "retention_receipt",
                    "path": "results/state_retention_receipt.json",
                    "required": True,
                }
            ),
        ],
        "suitability": "individual_only",
    }
    status = {
        "schema_version": "run-status-v1",
        "run_id": run_id,
        "revision": 0,
        "state": "configured",
        "updated_utc": NOW,
        "execution": {"mode": "local", "local_pid": None, "zeus_job_id": None},
        "error": None,
    }
    return run, configuration, inputs, status


def _registry(tmp_path: Path, *identities: tuple[str, str]):
    root = tmp_path / "repo"
    root.mkdir()
    store = RunRecordStore(root)
    for run_id, family in identities or (("run-1", "zeeman"),):
        store.create(*_records(run_id, family))
    return root, CanonicalIndividualRunRegistry(
        root, clock=lambda: "2026-10-11T12:00:00+00:00"
    )


def _running_registry(tmp_path: Path, *, retained=False):
    root = tmp_path / "repo"
    root.mkdir()
    store = RunRecordStore(root)
    run, configuration, inputs, initial = _records(retained=retained)
    directory = store.create(run, configuration, inputs, initial)
    running = copy.deepcopy(initial)
    running.update(revision=3, state="running")
    running["execution"] = {"mode": "local", "local_pid": 123, "zeus_job_id": None}
    (directory / "status.json").write_bytes(encode_record("status", running))
    return root, directory, CanonicalIndividualRunRegistry(
        root, clock=lambda: "2026-10-11T12:00:00+00:00"
    )


def _receipt(run_id="run-1"):
    return {
        "schema_version": "state-retention-receipt-v1",
        "run_id": run_id,
        "created_utc": NOW,
        "reason": "particle_states_not_retained",
    }


def _result(artifact, *, retained=False, captured=0):
    return {
        "schema_version": "run-results-v1",
        "run_id": "run-1",
        "completed_utc": NOW,
        "states_retained": retained,
        "suitability": "individual_only",
        "metrics": {"n_initial": 100, "n_survivors": captured, "captured": captured,
                    "survival_fraction": captured / 100, "elapsed_s": 0.0},
        "artifacts": [artifact],
    }


def test_lists_only_verified_canonical_packages_and_detail_is_read_only(tmp_path):
    root, registry = _registry(tmp_path, ("zeta", "zeeman"), ("alpha", "mot_2d"))
    before = {
        path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*.json")
    }

    listing = registry.list_runs()
    assert listing["invalid_count"] == 0
    assert listing["total"] == 2
    assert {row["display_name"] for row in listing["runs"]} == {"zeta", "alpha"}
    assert registry.list_runs()["runs"] == listing["runs"]
    assert all(row["record_kind"] == "individual_simulation_run" for row in listing["runs"])
    assert all(row["scientific_role"] == "individual-only" for row in listing["runs"])
    assert all(row["trust"] == "verified-package" for row in listing["runs"])

    zeta = next(row for row in listing["runs"] if row["display_name"] == "zeta")
    detail = registry.get_run(zeta["id"])
    assert detail["display_name"] == "zeta"
    assert detail["configuration"] == {
        "status": "complete",
        "resolved": {"particle_count": 100, "detuning_gamma": -1.0, "simulation": {"particle_count": 100}},
    }
    assert detail["retention"] == {
        "particle_states_requested": False,
        "status": "pending",
    }
    assert detail["results"] == {"availability": "not_ready", "completed_at": None}
    assert detail["artifacts"] == []
    assert detail["metrics"] is None
    assert detail["error"] is None
    json.dumps(detail)
    after = {
        path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*.json")
    }
    assert after == before


def test_d3_truncation_is_explicit_in_the_list_contract(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(
        discovery_api,
        "discover_run_snapshot",
        lambda _root, *, maximum_runs: DiscoverySnapshot((), True),
    )
    registry = CanonicalIndividualRunRegistry(root)
    assert registry.list_runs() == {
        "runs": [],
        "invalid_count": 0,
        "total": 0,
        "truncated": True,
    }


def test_invalid_package_is_counted_but_never_returned(tmp_path):
    root, registry = _registry(tmp_path)
    configuration_path = root / "data/runs/zeeman/run-1/configuration.json"
    value = _records()[1]
    value["resolved"]["particle_count"] = 101
    configuration_path.write_bytes(encode_record("configuration", value))

    assert registry.list_runs() == {
        "runs": [],
        "invalid_count": 1,
        "total": 0,
        "truncated": False,
    }


def test_verified_results_expose_retention_and_metrics_without_campaign_claims(tmp_path):
    root, registry = _registry(tmp_path)
    directory = root / "data/runs/zeeman/run-1"
    receipt = {
        "schema_version": "state-retention-receipt-v1",
        "run_id": "run-1",
        "created_utc": NOW,
        "reason": "particle_states_not_retained",
    }
    receipt_bytes = encode_record("retention_receipt", receipt)
    receipt_path = directory / "results/state_retention_receipt.json"
    receipt_path.write_bytes(receipt_bytes)
    result = {
        "schema_version": "run-results-v1",
        "run_id": "run-1",
        "completed_utc": NOW,
        "states_retained": False,
        "suitability": "individual_only",
        "metrics": {"n_initial": 100, "n_survivors": 0, "captured": 0,
                    "survival_fraction": 0.0, "elapsed_s": 1.25},
        "artifacts": [
            {
                "kind": "retention_receipt",
                "path": "results/state_retention_receipt.json",
                "sha256": hashlib.sha256(receipt_bytes).hexdigest(),
                "size_bytes": len(receipt_bytes),
            }
        ],
    }
    (directory / "results/summary.json").write_bytes(encode_record("results", result))
    succeeded = copy.deepcopy(_records()[3])
    succeeded.update(revision=4, state="succeeded")
    (directory / "status.json").write_bytes(encode_record("status", succeeded))

    row = registry.list_runs()["runs"][0]
    assert row["lifecycle"] == "results_ready"
    assert row["next_action"] == "view_results"
    assert row["retention"] == {
        "particle_states_requested": False,
        "status": "not_retained",
    }
    detail = registry.get_run(row["id"])
    assert detail["results"] == {"availability": "verified", "completed_at": NOW}
    assert detail["metrics"] == {"n_initial": 100, "n_survivors": 0, "captured": 0,
                                  "survival_fraction": 0.0, "elapsed_s": 1.25}
    assert detail["scientific_role"] == "individual-only"


def test_running_durable_registry_is_visible_but_never_called_verified(tmp_path):
    _root, directory, registry = _running_registry(tmp_path)
    receipt = _receipt()
    raw = encode_record("retention_receipt", receipt)
    (directory / "results/state_retention_receipt.json").write_bytes(raw)
    artifact = {
        "kind": "retention_receipt",
        "path": "results/state_retention_receipt.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    (directory / "results/summary.json").write_bytes(
        encode_record("results", _result(artifact))
    )

    listing = registry.list_runs()
    assert listing["invalid_count"] == 0
    row = listing["runs"][0]
    assert row["record_state"] == "running"
    assert row["integrity"] == "incomplete_publication"
    assert row["lifecycle"] == "incomplete_publication"
    assert row["results"]["availability"] == "incomplete_publication"
    assert row["retention"]["status"] == "publication_pending"
    assert row["warnings"] == ["Result publication is not yet terminal."]
    detail = registry.get_run(row["id"])
    assert detail["metrics"] == {"n_initial": 100, "n_survivors": 0, "captured": 0,
                                  "survival_fraction": 0.0, "elapsed_s": 0.0}
    assert detail["trust"] == "verified-package"


@pytest.mark.parametrize(
    "corruption",
    ["malformed_npy", "stale_states", "extra_artifact", "receipt_mismatch"],
)
def test_d3_result_corruption_is_never_admitted_by_the_api(tmp_path, corruption):
    retained = corruption == "malformed_npy"
    _root, directory, registry = _running_registry(tmp_path, retained=retained)
    if retained:
        raw = b"not-an-npy"
        (directory / "results/states.npy").write_bytes(raw)
        artifact = {
            "kind": "particle_states",
            "path": "results/states.npy",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }
        result = _result(artifact, retained=True)
    else:
        receipt = _receipt("other" if corruption == "receipt_mismatch" else "run-1")
        raw = encode_record("retention_receipt", receipt)
        (directory / "results/state_retention_receipt.json").write_bytes(raw)
        artifact = {
            "kind": "retention_receipt",
            "path": "results/state_retention_receipt.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }
        result = _result(artifact)
        if corruption == "stale_states":
            np.save(directory / "results/states.npy", np.zeros((1, 6), dtype=np.float64))
        elif corruption == "extra_artifact":
            log = directory / "logs/extra.log"
            log.write_bytes(b"extra")
            result["artifacts"].append(
                {
                    "kind": "run_log",
                    "path": "logs/extra.log",
                    "sha256": hashlib.sha256(b"extra").hexdigest(),
                    "size_bytes": 5,
                }
            )
    (directory / "results/summary.json").write_bytes(encode_record("results", result))

    assert registry.list_runs() == {
        "runs": [],
        "invalid_count": 1,
        "total": 0,
        "truncated": False,
    }


@pytest.mark.parametrize("identifier", ["", "individual-run-xyz", "../run-1", 3])
def test_detail_rejects_invalid_public_identifiers(tmp_path, identifier):
    _root, registry = _registry(tmp_path)
    with pytest.raises(IndividualRunDiscoveryError) as caught:
        registry.get_run(identifier)
    assert (caught.value.code, caught.value.message) == (
        "invalid_run_id",
        "Individual-run identifier is invalid.",
    )


def test_detail_uses_opaque_id_and_safe_not_found_error(tmp_path):
    _root, registry = _registry(tmp_path)
    identifier = registry.list_runs()["runs"][0]["id"]
    assert identifier.startswith("individual-run-")
    assert "run-1" not in identifier
    missing = "individual-run-" + ("f" * 24)
    if missing == identifier:
        missing = "individual-run-" + ("e" * 24)
    with pytest.raises(IndividualRunDiscoveryError) as caught:
        registry.get_run(missing)
    assert (caught.value.code, caught.value.message) == (
        "run_not_found",
        "Individual run was not found.",
    )


def test_detail_never_exposes_stored_executor_error_text(tmp_path):
    root, registry = _registry(tmp_path)
    path = root / "data/runs/zeeman/run-1/status.json"
    value = copy.deepcopy(_records()[3])
    value.update(revision=1, state="failed")
    value["error"] = {"code": "internal_secret", "message": "secret /absolute/path"}
    path.write_bytes(encode_record("status", value))
    identifier = registry.list_runs()["runs"][0]["id"]
    detail = registry.get_run(identifier)
    assert detail["error"] == {
        "code": "run_failed",
        "message": "The individual run failed.",
    }
    assert "secret" not in repr(detail)
    assert "/absolute/path" not in repr(detail)


def test_failed_local_future_is_visible_without_mutating_saved_execution(tmp_path):
    from workflow_api.run_progress import IndividualRunProgressRegistry

    root, directory, _ = _running_registry(tmp_path)
    progress = IndividualRunProgressRegistry()
    progress.start("zeeman", "run-1", 100)
    progress.update("zeeman", "run-1", 100, 100)
    progress.fail("zeeman", "run-1", "RunRecordError")
    registry = CanonicalIndividualRunRegistry(root, progress_registry=progress)
    before = (directory / "status.json").read_bytes()
    row = registry.list_runs()["runs"][0]
    assert row["record_state"] == "running"
    assert row["execution"]["progress"] is None
    assert row["results"]["availability"] == "not_ready"
    assert row["warnings"] == [
        "Local execution stopped before its outcome was verified. Do not resubmit; inspect the original run."
    ]
    detail = registry.get_run(row["id"])
    assert detail["execution"]["progress"] is None
    assert "RunRecordError" not in json.dumps(detail)
    assert (directory / "status.json").read_bytes() == before


@pytest.mark.parametrize('mode,state', [('zeus','configured'),('local','cancelled')])
def test_queue_observer_never_claims_zeus_or_terminal_execution(tmp_path, mode, state):
    from workflow_api.run_progress import IndividualRunProgressRegistry
    root=tmp_path/'repo';root.mkdir()
    run, configuration, inputs, status=_records()
    run['execution_mode']=mode
    status['execution']['mode']=mode
    store=RunRecordStore(root)
    try: directory=store.create(run,configuration,inputs,status)
    finally:store.close()
    if state != 'configured':
        status['state']=state;status['revision'] += 1
        (directory/'status.json').write_bytes(encode_record('status',status))
    progress=IndividualRunProgressRegistry();progress.schedule('zeeman','run-1')
    before=(directory/'status.json').read_bytes()
    registry=CanonicalIndividualRunRegistry(root,progress_registry=progress)
    row=registry.list_runs()['runs'][0]
    assert row['execution']['locally_scheduled'] is False
    assert row['next_action']=='none'
    assert registry.get_run(row['id'])['execution']['locally_scheduled'] is False
    assert (directory/'status.json').read_bytes()==before


def test_queue_snapshot_precedes_canonical_read_when_future_finishes_during_get(tmp_path, monkeypatch):
    import workflow_api.individual_run_discovery as discovery
    from workflow_api.run_progress import IndividualRunProgressRegistry
    root=tmp_path/'repo';root.mkdir()
    records=_records();store=RunRecordStore(root)
    try:directory=store.create(*records)
    finally:store.close()
    progress=IndividualRunProgressRegistry();progress.schedule('zeeman','run-1')
    before={path.name:path.read_bytes() for path in directory.glob('*.json')}
    original=discovery.inspect_run
    def read_then_finish(*args, **kwargs):
        inspected=original(*args, **kwargs)
        progress.finish('zeeman','run-1')
        return inspected
    monkeypatch.setattr(discovery,'inspect_run',read_then_finish)
    registry=CanonicalIndividualRunRegistry(root,progress_registry=progress)
    row=registry.list_runs()['runs'][0]
    assert row['record_state']=='configured'
    assert row['execution']['locally_scheduled'] is True and row['next_action']=='wait'
    assert not progress.is_scheduled('zeeman','run-1')
    assert {path.name:path.read_bytes() for path in directory.glob('*.json')}==before
    progress.schedule('zeeman','run-1')
    detail=registry.get_run(row['id'])
    assert detail['execution']['locally_scheduled'] is True and detail['next_action']=='wait'
    assert {path.name:path.read_bytes() for path in directory.glob('*.json')}==before


def test_terminal_completion_between_queue_observation_and_canonical_read_suppresses_mark(tmp_path, monkeypatch):
    import workflow_api.individual_run_discovery as discovery
    from workflow_api.run_progress import IndividualRunProgressRegistry
    root=tmp_path/'repo';root.mkdir();records=_records();store=RunRecordStore(root)
    try:directory=store.create(*records)
    finally:store.close()
    progress=IndividualRunProgressRegistry();progress.schedule('zeeman','run-1')
    original=discovery.inspect_run;completed=False
    def concurrent_completion_then_read(*args, **kwargs):
        nonlocal completed
        if not completed:
            # Simulate the executor's terminal commit and subsequent done callback
            # between the observer snapshot and the registry's canonical read.
            status=copy.deepcopy(records[3]);status.update(state='cancelled',revision=1)
            (directory/'status.json').write_bytes(encode_record('status',status))
            progress.finish('zeeman','run-1');completed=True
        return original(*args, **kwargs)
    monkeypatch.setattr(discovery,'inspect_run',concurrent_completion_then_read)
    registry=CanonicalIndividualRunRegistry(root,progress_registry=progress)
    row=registry.list_runs()['runs'][0]
    assert completed and row['record_state']=='cancelled'
    assert row['execution']['locally_scheduled'] is False and row['next_action']=='none'
    assert registry.get_run(row['id'])['execution']['locally_scheduled'] is False
