"""Portable local transaction tests: execute on Windows NT as well as POSIX.

Payloads are captured from the existing genuine on-disk producer/receiver test,
with its documented fake scheduler/trajectory seam. Validators are never patched.
"""

from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import zipfile

import pytest

from workflow_api import mot_2d_collection as collection

CONTRACTS = Path(__file__).parent / "contracts/v1"


@pytest.fixture(params=["v1", "TEAM"])
def transaction(request, tmp_path):
    fixture = CONTRACTS / f"finalization_collection_{request.param}.zip"
    with zipfile.ZipFile(fixture) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names)) and len(names) < 200
        metadata = collection._strict_json(archive.read("fixture.json"))
        assert (
            metadata["scope"]
            == "hermetic-existing-on-disk-protocol-fake-scheduler-and-trajectories-not-physical-evidence"
        )
        assert set(names) == {"fixture.json", "bundle.gz"} | {
            "bootstrap/" + n for n in metadata["bootstrap_sha256"]
        }
        root = tmp_path / "project"
        root.mkdir()
        for name, digest in metadata["bootstrap_sha256"].items():
            path = PurePosixPath(name)
            assert not path.is_absolute() and ".." not in path.parts and path.parts[0] == "data"
            data = archive.read("bootstrap/" + name)
            assert collection.sha256(data) == digest
            target = root.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        packed = archive.read("bundle.gz")
    descriptor = metadata["descriptor"]
    campaign = root / descriptor["campaign"]
    original = (campaign / "campaign.json").read_bytes()
    collection.validate_descriptor(
        {"descriptor": descriptor, "chunk": None},
        root,
        campaign,
        descriptor["commit"],
        collection._strict_json(original),
    )
    paths = frozenset(r["path"] for r in descriptor["files"])
    files = collection.unpack_artifact_bundle(
        packed,
        descriptor["bundle"],
        campaign=campaign.name,
        commit=descriptor["commit"],
        from_stage="complete",
        to_stage="collected",
        expected_paths=paths,
        max_file_bytes=collection.FILE_LIMIT,
        max_total_bytes=collection.TOTAL_LIMIT,
    )
    api = collection.CollectionCoordinator(SimpleNamespace(root=root, clock=lambda: 1234567890))
    return api, campaign, original, descriptor, files, metadata


def commit(transaction):
    api, campaign, original, descriptor, files, _ = transaction
    counts = api.synchronize(campaign, original, descriptor, files, api.observations(descriptor))
    return counts, api.local_sync(campaign, descriptor)


def catalogue(transaction):
    api, _, _, _, _, metadata = transaction
    from workflow_api.mot_3d_bootstrap import Mot3DDiscoveryBootstrapService

    return Mot3DDiscoveryBootstrapService(
        api.owner.root, acceptance_profile_id="ui_acceptance_v1" if metadata["acceptance"] else None
    )._sources()


def test_native_positive_canonical_commit_and_audit(transaction):
    api, campaign, original, descriptor, files, _ = transaction
    assert not catalogue(transaction)
    counts, sync = commit(transaction)
    assert counts["updated"] == 1 and counts["created"] + counts["identical"] == len(files) - 1
    assert sync["status"] == "synchronized"
    assert (
        campaign / ".mot_ui/sync" / f"{collection.SYNC}.original-manifest.json"
    ).read_bytes() == original
    collection.validate_complete(api.owner.root, campaign, descriptor["manifest"])
    assert len(catalogue(transaction)) == len(descriptor["manifest"]["s0_values"])
    assert api.status(campaign, descriptor["receipt"]) == sync


def test_native_foreign_target_preserved(transaction):
    api, campaign, original, descriptor, files, _ = transaction
    target = campaign / "final_report.json"
    target.write_bytes(b"foreign")
    before = api.observations(descriptor)
    with pytest.raises(ValueError, match="Conflicting collection artifact"):
        api.synchronize(campaign, original, descriptor, files, before)
    assert target.read_bytes() == b"foreign"
    assert (campaign / "campaign.json").read_bytes() == original
    assert not catalogue(transaction)


def test_native_candidate_invalid_does_not_replace_manifest(transaction):
    api, campaign, original, descriptor, files, _ = transaction
    changed = dict(files)
    name = next(n for n in files if n.endswith("/trial_0000.json"))
    changed[name] = b"{}"
    with pytest.raises(ValueError):
        api.synchronize(campaign, original, descriptor, changed, api.observations(descriptor))
    assert (campaign / "campaign.json").read_bytes() == original
    assert not catalogue(transaction)


def test_native_cas_crash_before_receipt_is_scientifically_visible_not_synced(
    transaction, monkeypatch
):
    api, campaign, original, descriptor, files, _ = transaction
    real_publish = collection.publish
    before_cas = []
    replace = collection._atomic_replace_at

    def observe_replace(parent, name, data):
        before_cas.append(catalogue(transaction))
        return replace(parent, name, data)

    def fail_receipt(parent, name, data):
        if name == collection.SYNC + ".json":
            assert len(catalogue(transaction)) == len(descriptor["manifest"]["s0_values"])
            raise OSError("receipt publication fault")
        return real_publish(parent, name, data)

    with monkeypatch.context() as patch:
        patch.setattr(collection, "_atomic_replace_at", observe_replace)
        patch.setattr(collection, "publish", fail_receipt)
        with pytest.raises(OSError, match="receipt publication fault"):
            commit(transaction)
    assert before_cas == [[]]
    assert json.loads((campaign / "campaign.json").read_bytes())["stage"] == "complete"
    assert api.local_sync(campaign, descriptor) == {"status": "not_synchronized"}
    assert (
        campaign / ".mot_ui/sync" / f"{collection.SYNC}.original-manifest.json"
    ).read_bytes() == original
    # Explicit same-identity reconciliation, not an automatic workflow retry.
    counts = api.synchronize(
        campaign,
        (campaign / "campaign.json").read_bytes(),
        descriptor,
        files,
        api.observations(descriptor),
    )
    assert (
        counts["created"] == 0 and api.local_sync(campaign, descriptor)["status"] == "synchronized"
    )


def test_native_published_receipt_then_error_remains_unsynchronized_until_reconciled(
    transaction, monkeypatch
):
    api, campaign, original, descriptor, files, _ = transaction
    publish = collection.publish

    def acts_then_raises(parent, name, data):
        result = publish(parent, name, data)
        if name == collection.SYNC + ".json":
            raise OSError("after receipt publication")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(collection, "publish", acts_then_raises)
        with pytest.raises(OSError, match="after receipt publication"):
            commit(transaction)
    receipt_path = campaign / ".mot_ui/sync" / f"{collection.SYNC}.json"
    first = receipt_path.read_bytes()
    assert api.local_sync(campaign, descriptor) == {"status": "not_synchronized"}
    api.synchronize(
        campaign,
        (campaign / "campaign.json").read_bytes(),
        descriptor,
        files,
        api.observations(descriptor),
    )
    assert receipt_path.read_bytes() == first
    assert api.local_sync(campaign, descriptor)["status"] == "synchronized"


def test_native_lock_fences_status_while_writer_active(transaction):
    api, campaign, _, descriptor, _, _ = transaction
    commit(transaction)
    parent = collection.os.open(campaign / ".mot_ui/sync", collection._DIRECTORY_FLAGS)
    lock = collection.os.open(f"{collection.SYNC}.lock", collection.os.O_RDWR, dir_fd=parent)
    try:
        collection.locking.flock(lock, collection.locking.LOCK_EX | collection.locking.LOCK_NB)
        with pytest.raises(BlockingIOError):
            api.local_sync(campaign, descriptor)
    finally:
        collection.locking.flock(lock, collection.locking.LOCK_UN)
        collection.os.close(lock)
        collection.os.close(parent)


def test_native_backup_tamper_never_gives_synchronized(transaction):
    api, campaign, _, descriptor, _, _ = transaction
    commit(transaction)
    backup = campaign / ".mot_ui/sync" / f"{collection.SYNC}.original-manifest.json"
    value = json.loads(backup.read_bytes())
    value["name"] = "foreign campaign"
    backup.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        api.local_sync(campaign, descriptor)


def test_native_named_read_uses_platform_adapter_not_path_stat(tmp_path, monkeypatch):
    file = tmp_path / "plain.json"
    file.write_bytes(b"{}")
    parent = collection.os.open(tmp_path, collection._DIRECTORY_FLAGS)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                Path,
                "stat",
                lambda *a, **kw: (_ for _ in ()).throw(AssertionError("native path stat bypass")),
            )
            assert collection.read_at(parent, "plain.json") == b"{}"
    finally:
        collection.os.close(parent)


def test_oversized_sparse_file_is_refused_without_loading(tmp_path):
    file = tmp_path / "large.db"
    with file.open("wb") as stream:
        stream.truncate(collection.FILE_LIMIT + 1)
    with pytest.raises(Exception, match="collection_too_large"):
        collection.files_snapshot(tmp_path, frozenset({"large.db"}))


@pytest.mark.parametrize("boundary", ["open", "write", "file_fsync", "directory_fsync"])
def test_exclusive_publication_faults_retain_target(tmp_path, monkeypatch, boundary):
    import stat

    parent = collection.os.open(tmp_path, collection._DIRECTORY_FLAGS)
    real_open = collection.os.open
    real_fsync = collection.os.fsync
    real_fdopen = collection.os.fdopen
    try:
        with monkeypatch.context() as patch:
            if boundary == "open":

                def open_after(*args, **kwargs):
                    fd = real_open(*args, **kwargs)
                    if args[0] == "owned.json" and args[1] & collection.os.O_EXCL:
                        collection.os.close(fd)
                        raise OSError("acts then raises open")
                    return fd

                patch.setattr(collection.os, "open", open_after)
            elif boundary == "write":

                class FailingStream:
                    def __init__(self, fd, mode):
                        self.stream = real_fdopen(fd, mode)

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        return self.stream.__exit__(*args)

                    def write(self, data):
                        self.stream.write(data)
                        self.stream.flush()
                        raise OSError("acts then raises write")

                patch.setattr(collection.os, "fdopen", FailingStream)
            else:

                def fsync_fault(fd):
                    is_directory = stat.S_ISDIR(collection.os.fstat(fd).st_mode)
                    if is_directory == (boundary == "directory_fsync"):
                        real_fsync(fd)
                        raise OSError("acts then raises fsync")
                    real_fsync(fd)

                patch.setattr(collection.os, "fsync", fsync_fault)
            with pytest.raises(OSError):
                collection.publish(parent, "owned.json", b"payload")
        assert (tmp_path / "owned.json").exists()
        assert (tmp_path / "owned.json").read_bytes() in (b"", b"payload")
        assert len(list(tmp_path.iterdir())) == 1
    finally:
        collection.os.close(parent)


def test_native_no_getuid_platform_runs_positive_transaction(transaction, monkeypatch):
    """Model NT stat owner0 and missing stdlib getuid, exercising actual writes."""
    original = collection.os

    def native_row(row):
        names = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        return SimpleNamespace(
            **{name: (0 if name == "st_uid" else getattr(row, name)) for name in names}
        )

    class NativeOwnerOS:
        def __getattr__(self, name):
            if name == "getuid":
                raise AttributeError(name)
            return getattr(original, name)

        def fstat(self, fd):
            return native_row(original.fstat(fd))

        def stat(self, *args, **kwargs):
            return native_row(original.stat(*args, **kwargs))

    with monkeypatch.context() as patch:
        patch.setattr(collection, "os", NativeOwnerOS())
        _, sync = commit(transaction)
        assert sync["status"] == "synchronized"
