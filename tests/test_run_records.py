from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path

import pytest

import workflow_api.run_records as run_records
from workflow_api.run_records import (
    RunRecordError,
    RunRecordStore,
    decode_record,
    encode_record,
    read_record,
    record_sha256,
    validate_record,
)


NOW = "2026-10-11T10:00:00+00:00"
COMMIT = "a" * 40


def configuration(run_id="run-1", family="zeeman"):
    return {
        "schema_version": "run-configuration-v1",
        "run_id": run_id,
        "family": family,
        "laboratory_spec": {"version": "laboratory-physical-v1", "sha256": "b" * 64},
        "numerical_policy": {"version": "numerical-policy-v1", "sha256": "c" * 64},
        "resolved": {"example_si": 1.25, "enabled": True},
    }


def inputs(run_id="run-1", family="zeeman"):
    return {
        "schema_version": "run-inputs-v1",
        "run_id": run_id,
        "family": family,
        "artifacts": [],
    }


def run_record(run_id="run-1", family="zeeman", retained=False):
    config = configuration(run_id, family)
    source = inputs(run_id, family)
    disposition = (
        {"kind": "particle_states", "path": "results/states.npy", "required": True}
        if retained
        else {
            "kind": "retention_receipt",
            "path": "results/state_retention_receipt.json",
            "required": True,
        }
    )
    return {
        "schema_version": "individual-run-v1",
        "run_id": run_id,
        "family": family,
        "created_utc": NOW,
        "execution_mode": "local",
        "git_revision": COMMIT,
        "configuration_sha256": record_sha256("configuration", config),
        "inputs_sha256": record_sha256("inputs", source),
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


def status(run_id="run-1", state="configured", revision=0, error=None):
    return {
        "schema_version": "run-status-v1",
        "run_id": run_id,
        "revision": revision,
        "state": state,
        "updated_utc": NOW,
        "execution": {"mode": "local", "local_pid": None, "zeus_job_id": None},
        "error": error,
    }


def receipt(run_id="run-1"):
    return {
        "schema_version": "state-retention-receipt-v1",
        "run_id": run_id,
        "created_utc": NOW,
        "reason": "particle_states_not_retained",
    }


def results(run_id="run-1", retained=False, artifact=None):
    artifact = artifact or {
        "kind": "retention_receipt",
        "path": "results/state_retention_receipt.json",
        "sha256": hashlib.sha256(
            encode_record("retention_receipt", receipt(run_id))
        ).hexdigest(),
        "size_bytes": len(encode_record("retention_receipt", receipt(run_id))),
    }
    return {
        "schema_version": "run-results-v1",
        "run_id": run_id,
        "completed_utc": NOW,
        "states_retained": retained,
        "suitability": "individual_only",
        "metrics": {"elapsed_s": 1.0, "captured": 0},
        "artifacts": [artifact],
    }


def create_store(tmp_path, *, retained=False):
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    store = RunRecordStore(root)
    config = configuration()
    source = inputs()
    run = run_record(retained=retained)
    directory = store.create(run, config, source, status())
    return store, directory


@pytest.mark.parametrize(
    "kind,value",
    [
        ("configuration", configuration()),
        ("inputs", inputs()),
        ("run", run_record()),
        ("status", status()),
        ("retention_receipt", receipt()),
        ("results", results()),
    ],
)
def test_every_record_round_trips_canonical_bytes(kind, value):
    encoded = encode_record(kind, value)
    assert encoded.endswith(b"\n")
    assert decode_record(kind, encoded) == value
    assert encode_record(kind, decode_record(kind, encoded)) == encoded


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra=True),
        lambda value: value.update(particle_count=True),
        lambda value: value.update(timestep_s=float("nan")),
        lambda value: value.update(suitability="campaign_input"),
        lambda value: value["outputs"].append(
            {"kind": "particle_states", "path": "../x", "required": True}
        ),
        lambda value: value["outputs"].append(dict(value["outputs"][0])),
    ],
)
def test_run_record_rejects_unknown_bool_nan_claims_and_unsafe_outputs(mutation):
    value = run_record()
    mutation(value)
    with pytest.raises(RunRecordError):
        validate_record("run", value)


def test_decoder_rejects_duplicate_keys_invalid_utf8_and_oversize():
    for raw in (
        b'{"schema_version":"x","schema_version":"y"}',
        b"\xff",
        b"x" * (8 * 1024 * 1024 + 1),
    ):
        with pytest.raises(RunRecordError):
            decode_record("run", raw)


def test_store_creates_manifest_last_identity_bound_records_and_never_overwrites(
    tmp_path,
):
    store, directory = create_store(tmp_path)
    assert store.read("zeeman", "run-1", "run") == run_record()
    assert store.read("zeeman", "run-1", "configuration") == configuration()
    assert sorted(path.name for path in directory.iterdir()) == [
        "configuration.json",
        "inputs.json",
        "logs",
        "results",
        "run.json",
        "status.json",
    ]
    before = {path.name: path.read_bytes() for path in directory.glob("*.json")}
    with pytest.raises(RunRecordError, match="already exists"):
        store.create(run_record(), configuration(), inputs(), status())
    assert {path.name: path.read_bytes() for path in directory.glob("*.json")} == before


def test_failed_creation_remains_hidden_and_never_publishes_run(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    store = RunRecordStore(root)
    real_publish = run_records._publish_no_replace_at
    calls = 0

    def fail_second(parent, name, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated crash")
        return real_publish(parent, name, data)

    monkeypatch.setattr(run_records, "_publish_no_replace_at", fail_second)
    with pytest.raises(OSError, match="simulated crash"):
        store.create(run_record(), configuration(), inputs(), status())
    family = root / "data/runs/zeeman"
    assert not (family / "run-1").exists()
    hidden = [path for path in family.iterdir() if path.name.startswith(".")]
    assert len(hidden) == 1 and hidden[0].name.endswith(".staging")


def test_d2_store_has_no_result_publication_or_progress_admission_api(tmp_path):
    store, _ = create_store(tmp_path)
    assert not hasattr(store, "publish_results")
    assert not hasattr(store, "admit")


def test_create_rejects_cross_identity_digest_and_non_initial_status_without_writes(
    tmp_path,
):
    root = tmp_path / "repo"
    root.mkdir()
    store = RunRecordStore(root)
    bad = run_record()
    bad["configuration_sha256"] = "0" * 64
    for args in (
        (bad, configuration(), inputs(), status()),
        (run_record(), configuration("other"), inputs(), status()),
        (
            run_record(),
            configuration(),
            inputs(),
            status(state="validated", revision=1),
        ),
    ):
        with pytest.raises(RunRecordError):
            store.create(*args)
    assert not (root / "data/runs/zeeman/run-1").exists()


def test_generic_status_update_allows_only_pre_admission_cancellation(tmp_path):
    store, directory = create_store(tmp_path)
    for forbidden in ("validated", "reviewed", "queued", "running", "succeeded"):
        with pytest.raises(RunRecordError):
            store.update_status("zeeman", "run-1", status(state=forbidden, revision=1))
    cancelled = status(state="cancelled", revision=1)
    store.update_status("zeeman", "run-1", cancelled)
    assert read_record(directory / "status.json", "status") == cancelled
    with pytest.raises(RunRecordError):
        store.update_status("zeeman", "run-1", status(state="succeeded", revision=2))


def test_concurrent_status_writers_allow_only_one_revision(tmp_path):
    store, _ = create_store(tmp_path)
    proposals = [status(state="cancelled", revision=1) for _ in range(8)]

    def update(value):
        try:
            store.update_status("zeeman", "run-1", value)
            return "ok"
        except RunRecordError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(update, proposals))
    assert outcomes.count("ok") == 1
    assert store.read("zeeman", "run-1", "status")["revision"] == 1


def test_read_rejects_symlinked_record(tmp_path):
    store, directory = create_store(tmp_path)
    original = directory / "configuration.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(outside)
    with pytest.raises(RunRecordError, match="trusted regular"):
        store.read("zeeman", "run-1", "configuration")


def test_canonical_output_paths_require_exact_kinds_and_required_flag():
    for mutation in (
        lambda value: value["outputs"][0].update(kind="run_log"),
        lambda value: value["outputs"][0].update(required=False),
        lambda value: value["outputs"][1].update(kind="run_log"),
    ):
        value = run_record()
        mutation(value)
        with pytest.raises(RunRecordError, match="correctly typed"):
            validate_record("run", value)


def test_store_rejects_symlinked_root_component_and_lock(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "data").symlink_to(outside, target_is_directory=True)
    store = RunRecordStore(root)
    with pytest.raises(RunRecordError, match="untrusted component"):
        store.create(run_record(), configuration(), inputs(), status())

    (root / "data").unlink()
    store, directory = create_store(tmp_path / "second")
    outside_lock = tmp_path / "lock"
    outside_lock.write_text("outside")
    (directory / ".records.lock").symlink_to(outside_lock)
    with pytest.raises(RunRecordError, match="lock"):
        store.update_status("zeeman", "run-1", status(state="cancelled", revision=1))
    assert outside_lock.read_text() == "outside"


def test_create_remains_bound_to_open_family_when_path_is_swapped(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    root.mkdir()
    store = RunRecordStore(root)
    real_stat = run_records.os.stat
    family = root / "data/runs/zeeman"
    displaced = root / "data/runs/zeeman-original"
    swapped = False

    def swap_before_staging(name, *args, **kwargs):
        nonlocal swapped
        if not swapped and name == "run-1" and kwargs.get("dir_fd") is not None:
            swapped = True
            family.rename(displaced)
            family.mkdir()
        return real_stat(name, *args, **kwargs)

    monkeypatch.setattr(run_records.os, "stat", swap_before_staging)
    with pytest.raises(RunRecordError, match="changed during creation"):
        store.create(run_record(), configuration(), inputs(), status())
    assert (displaced / "run-1/run.json").is_file()
    assert list(family.iterdir()) == []


def test_read_remains_bound_to_open_run_when_path_is_swapped(tmp_path, monkeypatch):
    store, directory = create_store(tmp_path)
    displaced = directory.with_name("run-1-original")
    real_read = run_records._read_regular_at
    swapped = False

    def swap_before_read(parent, name):
        nonlocal swapped
        if not swapped:
            swapped = True
            directory.rename(displaced)
            directory.mkdir()
            (directory / "configuration.json").write_bytes(b"not trusted")
        return real_read(parent, name)

    monkeypatch.setattr(run_records, "_read_regular_at", swap_before_read)
    assert store.read("zeeman", "run-1", "configuration") == configuration()


def test_update_remains_bound_after_lock_when_run_path_is_swapped(
    tmp_path, monkeypatch
):
    store, directory = create_store(tmp_path)
    displaced = directory.with_name("run-1-original")
    replacement_status = encode_record("status", status())
    real_read = run_records._read_record_at
    swapped = False

    def swap_after_lock(parent, name, kind):
        nonlocal swapped
        if not swapped:
            swapped = True
            directory.rename(displaced)
            directory.mkdir()
            (directory / "status.json").write_bytes(replacement_status)
        return real_read(parent, name, kind)

    monkeypatch.setattr(run_records, "_read_record_at", swap_after_lock)
    cancelled = status(state="cancelled", revision=1)
    store.update_status("zeeman", "run-1", cancelled)
    assert read_record(displaced / "status.json", "status") == cancelled
    assert (directory / "status.json").read_bytes() == replacement_status
