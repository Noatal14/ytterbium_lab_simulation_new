"""Same-revision collection through real receiver/worker/validator contracts.

The shared fixture substitutes only scheduling and physical trajectories, as
in the existing complete on-disk protocol qualification. No external SSH runs.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil

import pytest

from workflow_api import mot_2d_collection as collection
from workflow_api.zeus_finalization import (
    ZeusFinalizationCoordinator,
    ZeusFinalizationError,
)


@pytest.fixture(scope="module", params=[True, False], ids=["v1", "TEAM-multi-s0"])
def completed(request, tmp_path_factory):
    if os.name == "nt":
        pytest.skip("Genuine POSIX receiver/scheduler fixture; portable IO tests are separate")
    from test_mot_2d_receiver_protocol_chain import (
        _run_full_on_disk_receiver_protocol_chain,
    )

    root = tmp_path_factory.mktemp("collection-chain")
    patch = pytest.MonkeyPatch()
    acceptance = request.param
    try:
        chain = _run_full_on_disk_receiver_protocol_chain(
            root,
            patch,
            acceptance,
            s0_values=[1.3] if acceptance else [1.1, 1.3],
            checkout=None if acceptance else "ytterbium_lab_simulation_ui",
        )
        saved = root / "original-local-data"
        shutil.copytree(chain.local / "data", saved)
        chain.acceptance = acceptance
        chain.original_data = saved
        chain.local_canonical = chain.local / chain.relative
        chain.remote_map = {
            p.relative_to(chain.remote).as_posix(): collection.sha256(p.read_bytes())
            for p in (chain.remote / "data").rglob("*")
            if p.is_file()
        }
        export = os.environ.get("COLLECTION_FIXTURE_EXPORT")
        if export:
            export_completed_fixture(chain, Path(export))
        yield chain
    finally:
        patch.undo()


def export_completed_fixture(chain, destination):
    """Optional producer capture for portable transaction tests, never physics proof."""
    import zipfile

    api = ZeusFinalizationCoordinator(chain.local, chain.ssh, chain.git)
    _, _, _, descriptor = api.collection.plan(chain.request)
    files = collection.files_snapshot(
        chain.remote, frozenset(r["path"] for r in descriptor["files"])
    )
    bundle = collection.build_artifact_bundle(
        files,
        campaign=chain.campaign.name,
        commit=chain.commit,
        from_stage="complete",
        to_stage="collected",
        expected_paths=frozenset(files),
        max_file_bytes=collection.FILE_LIMIT,
        max_total_bytes=collection.TOTAL_LIMIT,
    )
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / (
        "finalization_collection_" + ("v1" if chain.acceptance else "TEAM") + ".zip"
    )
    metadata = {
        "scope": "hermetic-existing-on-disk-protocol-fake-scheduler-and-trajectories-not-physical-evidence",
        "producer_commit": chain.commit,
        "acceptance": chain.acceptance,
        "capture_command": "pytest tests/test_mot_2d_collection.py with COLLECTION_FIXTURE_EXPORT",
        "descriptor": descriptor,
        "bootstrap_sha256": {},
    }
    members = {"bundle.gz": bundle.packed}
    for file in sorted((chain.local / "data").rglob("*")):
        if file.is_file():
            name = file.relative_to(chain.local).as_posix()
            data = file.read_bytes()
            members["bootstrap/" + name] = data
            metadata["bootstrap_sha256"][name] = collection.sha256(data)
    members["fixture.json"] = collection.canonical_json(metadata)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, data)


@pytest.fixture
def local(completed):
    chain = completed
    shutil.rmtree(chain.local / "data")
    shutil.copytree(chain.original_data, chain.local / "data")
    api = ZeusFinalizationCoordinator(chain.local, chain.ssh, chain.git)
    api.collection.previews._token_factory = lambda: "collection-contract-test-token"
    return chain, api


def collect(chain, api):
    preview = api.collection_preview(chain.request, session_id="collection")
    result = api.collection_confirm(
        {"preview_token": preview["preview_token"]}, session_id="collection"
    )
    return preview, result


def catalogue(chain):
    from workflow_api.mot_3d_bootstrap import Mot3DDiscoveryBootstrapService

    return Mot3DDiscoveryBootstrapService(
        chain.local,
        acceptance_profile_id="ui_acceptance_v1" if chain.acceptance else None,
    )._sources()


def test_full_chain_collection(local):
    chain, api = local
    old = (chain.local_canonical / "campaign.json").read_bytes()
    assert not catalogue(chain)
    preview = api.collection_preview(chain.request, session_id="collection")
    assert preview["effects"] == {
        "collect_verified_outputs": True,
        "submit_job": False,
        "start_simulation": False,
    }
    assert preview["local_sync"] == {"status": "not_synchronized"}
    assert (chain.local_canonical / "campaign.json").read_bytes() == old
    result = api.collection_confirm(
        {"preview_token": preview["preview_token"]}, session_id="collection"
    )
    assert result["status"] == "collected" and result["local_sync"]["status"] == "synchronized"
    assert result["submitted_to_zeus"] is result["simulation_started"] is False
    manifest = json.loads((chain.local_canonical / "campaign.json").read_bytes())
    collection.validate_complete(chain.local, chain.local_canonical, manifest)
    assert {r["path"] for r in preview["artifacts"]["files"]} == collection.registry_paths(
        chain.local, chain.local_canonical, manifest
    )
    bs, br = (1, 4) if chain.acceptance else (17, 10)
    q = len(json.loads((chain.local_canonical / "sensitivity/tasks.json").read_bytes()))
    assert (
        len(preview["artifacts"]["files"])
        == 21 + len(manifest["s0_values"]) * (80 + 3 * bs + 3 * br) + q
    )
    assert len(catalogue(chain)) == len(manifest["s0_values"])
    assert len(chain.qsub_calls) == 9
    assert chain.remote_map == {
        p.relative_to(chain.remote).as_posix(): collection.sha256(p.read_bytes())
        for p in (chain.remote / "data").rglob("*")
        if p.is_file()
    }
    assert (
        api.collection_confirm({"preview_token": preview["preview_token"]}, session_id="collection")
        == result
    )
    status = api.status(chain.request)
    assert status["local_sync"] == result["local_sync"]
    output = Path(
        "/private/tmp/team-collection-public-dtos-"
        + ("v1" if chain.acceptance else "TEAM")
        + ".json"
    )
    output.write_text(
        json.dumps({"preview": preview, "confirm": result, "status": status}, indent=2) + "\n"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_path",
        "path_escape",
        "missing_path",
        "size_bool",
        "receipt_nonce",
        "receipt_commit",
        "receipt_files",
        "bundle_count",
        "bundle_hash",
        "manifest_source",
    ],
)
def test_descriptor_tamper_is_rejected_before_local_writes(local, monkeypatch, mutation):
    chain, api = local
    base, old, transport, descriptor = api.collection.plan(chain.request)
    d = deepcopy(descriptor)
    if mutation == "extra_path":
        d["files"].append(
            {"path": chain.relative + "/unexpected.json", "size": 1, "sha256": "a" * 64}
        )
        d["files"].sort(key=lambda r: r["path"])
        d["registry_sha256"] = collection.sha256(collection.canonical_json(d["files"]))
    elif mutation == "path_escape":
        d["files"][0]["path"] = "../escape"
    elif mutation == "missing_path":
        d["files"].pop()
    elif mutation == "size_bool":
        d["files"][0]["size"] = True
    elif mutation == "receipt_nonce":
        d["receipt"]["nonce"] = "not-a-nonce"
    elif mutation == "receipt_commit":
        d["receipt"]["commit"] = "0" * 40
    elif mutation == "receipt_files":
        d["receipt"]["files"]["final_report.json"] = "0" * 64
    elif mutation == "bundle_count":
        d["bundle"]["file_count"] += 1
    elif mutation == "bundle_hash":
        d["bundle"]["bundle_sha256"] = "invalid"
    elif mutation == "manifest_source":
        d["manifest"]["ensemble_source"]["directory"] = "data/particle_states/after_zeeman/other"
    with pytest.raises(ZeusFinalizationError):
        collection.validate_descriptor(
            {"descriptor": d, "chunk": None}, chain.local, base[2], base[4], base[3]
        )
    assert (chain.local_canonical / "campaign.json").read_bytes() == old
    assert not (chain.local_canonical / ".mot_ui/sync").exists()


def test_profile_session_expiry_and_source_revision_are_closed(local, monkeypatch):
    chain, api = local
    for request in (
        {"campaign_id": chain.campaign_id},
        chain.request | {"extra": "ignored"},
    ):
        with pytest.raises(ZeusFinalizationError):
            api.collection_preview(request, session_id="collection")
    preview = api.collection_preview(chain.request, session_id="collection")
    with pytest.raises(ZeusFinalizationError, match="confirmation_invalid"):
        api.collection_confirm({"preview_token": preview["preview_token"]}, session_id="other")
    now = api.clock()
    monkeypatch.setattr(api, "clock", lambda: now + 301)
    with pytest.raises(ZeusFinalizationError, match="confirmation_expired"):
        api.collection_confirm({"preview_token": preview["preview_token"]}, session_id="collection")
    from workflow_api.repository_snapshot import (
        RepositorySnapshotProvider,
        RepositorySnapshot,
    )

    monkeypatch.setattr(
        RepositorySnapshotProvider, "capture", lambda self: RepositorySnapshot("0" * 40)
    )
    with pytest.raises(ZeusFinalizationError, match="local_checkout_mismatch"):
        api.collection_preview(chain.request, session_id="collection")


@pytest.mark.parametrize("kind", ["foreign", "symlink", "hardlink"])
def test_existing_target_no_overwrite(local, kind):
    chain, api = local
    preview = api.collection_preview(chain.request, session_id="collection")
    row = next(r for r in preview["artifacts"]["files"] if r["path"].endswith("/final_report.json"))
    target = chain.local / row["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (chain.local_canonical / "campaign.json").read_bytes()
    if kind == "foreign":
        target.write_bytes(b"foreign retained")
    else:
        foreign = chain.local / "data/foreign.json"
        foreign.write_bytes(b"foreign retained")
        if kind == "symlink":
            target.symlink_to(foreign)
        else:
            os.link(foreign, target)
    with pytest.raises(ZeusFinalizationError):
        api.collection_confirm({"preview_token": preview["preview_token"]}, session_id="collection")
    assert target.read_bytes() == b"foreign retained"
    assert (chain.local_canonical / "campaign.json").read_bytes() == original
    assert not catalogue(chain)


def test_size_cap_before_publication(local, monkeypatch):
    chain, api = local
    paths = collection.registry_paths(
        chain.remote,
        chain.campaign,
        json.loads((chain.campaign / "campaign.json").read_bytes()),
    )
    before = (chain.local_canonical / "campaign.json").read_bytes()
    monkeypatch.setattr(collection, "TOTAL_LIMIT", 1)
    with pytest.raises(ZeusFinalizationError, match="collection_too_large"):
        collection.files_snapshot(chain.remote, paths)
    assert (chain.local_canonical / "campaign.json").read_bytes() == before
    assert not (chain.local_canonical / ".mot_ui/sync").exists()


def test_manifest_is_scientific_commit_before_audit_receipt(local, monkeypatch):
    chain, api = local
    preview = api.collection_preview(chain.request, session_id="collection")
    original = collection.publish
    observed = []

    def crash_before_receipt(parent, name, data):
        if name == collection.SYNC + ".json":
            observed.append(catalogue(chain))
            raise OSError("fault before audit receipt")
        return original(parent, name, data)

    monkeypatch.setattr(collection, "publish", crash_before_receipt)
    with pytest.raises(ZeusFinalizationError, match="collection_outcome_unknown"):
        api.collection_confirm({"preview_token": preview["preview_token"]}, session_id="collection")
    assert observed and len(observed[0]) == len(
        json.loads((chain.campaign / "campaign.json").read_bytes())["s0_values"]
    )
    assert json.loads((chain.local_canonical / "campaign.json").read_bytes())["stage"] == "complete"
    assert (chain.local_canonical / ".mot_ui/sync" / f"{collection.SYNC}.pending.json").is_file()
    assert not (chain.local_canonical / ".mot_ui/sync" / f"{collection.SYNC}.json").exists()
    assert api.status(chain.request)["local_sync"] == {"status": "not_synchronized"}


def test_bad_published_closure_does_not_commit_manifest(local, monkeypatch):
    chain, api = local
    preview = api.collection_preview(chain.request, session_id="collection")
    original = (chain.local_canonical / "campaign.json").read_bytes()
    publish = collection.publish

    def change_trial(parent, name, data):
        return publish(parent, name, b"{}" if name == "trial_0000.json" else data)

    monkeypatch.setattr(collection, "publish", change_trial)
    with pytest.raises(ZeusFinalizationError, match="collection_outcome_unknown"):
        api.collection_confirm({"preview_token": preview["preview_token"]}, session_id="collection")
    assert (chain.local_canonical / "campaign.json").read_bytes() == original
    assert not catalogue(chain)


def test_manifest_cas_race_preserves_foreign_manifest(local, monkeypatch):
    chain, api = local
    preview = api.collection_preview(chain.request, session_id="collection")
    real = collection.validate_complete
    raced = []

    def race(root, campaign, manifest):
        real(root, campaign, manifest)
        if root == chain.local and not raced:
            raced.append(True)
            (campaign / "campaign.json").write_bytes(b'{"foreign":true}\n')

    monkeypatch.setattr(collection, "validate_complete", race)
    with pytest.raises(ZeusFinalizationError, match="collection_outcome_unknown"):
        api.collection_confirm({"preview_token": preview["preview_token"]}, session_id="collection")
    assert (chain.local_canonical / "campaign.json").read_bytes() == b'{"foreign":true}\n'
    assert not catalogue(chain)


def test_same_bytes_replaced_inode_after_preview_is_not_accepted(local):
    chain, api = local
    preview = api.collection_preview(chain.request, session_id="collection")
    target = chain.local_canonical / "jobs/01_smoke.pbs"
    data = target.read_bytes()
    replacement = target.with_name("replacement.pbs")
    replacement.write_bytes(data)
    os.replace(replacement, target)
    with pytest.raises(ZeusFinalizationError, match="remote_files_changed"):
        api.collection_confirm({"preview_token": preview["preview_token"]}, session_id="collection")
    assert json.loads((chain.local_canonical / "campaign.json").read_bytes())["stage"] == "smoke"


def test_backup_and_explicit_recovery_after_scientific_commit(local, monkeypatch):
    chain, api = local
    original = (chain.local_canonical / "campaign.json").read_bytes()
    preview = api.collection_preview(chain.request, session_id="collection")
    publish = collection.publish

    def crash(parent, name, data):
        if name == collection.SYNC + ".json":
            raise OSError("before audit")
        return publish(parent, name, data)

    with monkeypatch.context() as patch:
        patch.setattr(collection, "publish", crash)
        with pytest.raises(ZeusFinalizationError, match="collection_outcome_unknown"):
            api.collection_confirm(
                {"preview_token": preview["preview_token"]}, session_id="collection"
            )
    sync = chain.local_canonical / ".mot_ui/sync"
    assert (sync / f"{collection.SYNC}.original-manifest.json").read_bytes() == original
    pending = json.loads((sync / f"{collection.SYNC}.pending.json").read_bytes())
    assert pending["old_manifest_sha256"] == collection.sha256(original)
    # New explicit review, never automatic old-confirm replay or invented receipt.
    reopened = ZeusFinalizationCoordinator(chain.local, chain.ssh, chain.git)
    fresh = reopened.collection_preview(chain.request, session_id="new-session")
    result = reopened.collection_confirm(
        {"preview_token": fresh["preview_token"]}, session_id="new-session"
    )
    assert result["local_sync"]["status"] == "synchronized"
    assert (sync / f"{collection.SYNC}.original-manifest.json").read_bytes() == original
    assert len(chain.qsub_calls) == 9


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX producer receiver fixture; captured local transaction runs natively too",
)
def test_zero_survivor_producer_collects_but_never_becomes_3d_source(tmp_path, monkeypatch):
    from test_mot_2d_receiver_protocol_chain import (
        _Protocol,
        _run_full_on_disk_receiver_protocol_chain,
    )
    from studies.mot_2d import optimization
    import numpy as np

    work = _Protocol.work

    def actual_zero_work(chain, stage):
        if stage != "production":
            return work(chain, stage)
        with monkeypatch.context() as patch:
            patch.setattr(
                optimization,
                "mot_simulation_paired_ensembles",
                lambda **kwargs: [
                    ([], 0, np.empty((0, 6))) for _ in kwargs["survivor_state_ensembles"]
                ],
            )
            return work(chain, stage)

    monkeypatch.setattr(_Protocol, "work", actual_zero_work)
    chain = _run_full_on_disk_receiver_protocol_chain(tmp_path, monkeypatch, True)
    chain.acceptance = True
    chain.local_canonical = chain.local / chain.relative
    api = ZeusFinalizationCoordinator(chain.local, chain.ssh, chain.git)
    preview, result = collect(chain, api)
    assert result["local_sync"]["status"] == "synchronized"
    collection.validate_complete(
        chain.local,
        chain.local_canonical,
        json.loads((chain.local_canonical / "campaign.json").read_bytes()),
    )
    assert all(row["total_survivors"] == 0 for row in api.status(chain.request)["results"])
    metadata = [
        json.loads((chain.local / r["path"]).read_bytes())
        for r in preview["artifacts"]["files"]
        if "survivor_states/" in r["path"] and r["path"].endswith(".json")
    ]
    assert len(metadata) == 20 and all(row["n_survivors"] == 0 for row in metadata)
    assert not catalogue(chain)


def test_unknown_consumes_token_and_requires_new_explicit_review(local, monkeypatch):
    chain, api = local
    preview = api.collection_preview(chain.request, session_id="collection")
    attempted = []

    def unknown(*args, **kwargs):
        attempted.append(True)
        raise OSError("transaction begin unknown")

    monkeypatch.setattr(api.collection, "synchronize", unknown)
    for _ in range(2):
        with pytest.raises(ZeusFinalizationError, match="collection_outcome_unknown"):
            api.collection_confirm(
                {"preview_token": preview["preview_token"]}, session_id="collection"
            )
    assert attempted == [True]


def test_expiry_during_readonly_retrieval_never_publishes(local, monkeypatch):
    from workflow_api.zeus_finalization import PinnedSshFinalizationTransport

    chain, api = local
    preview = api.collection_preview(chain.request, session_id="collection")
    before = (chain.local_canonical / "campaign.json").read_bytes()
    now = api.clock()
    retrieve = PinnedSshFinalizationTransport.retrieve

    def delayed(transport, **payload):
        response = retrieve(transport, **payload)
        if "chunk_index" in payload:
            monkeypatch.setattr(api, "clock", lambda: now + 301)
        return response

    monkeypatch.setattr(PinnedSshFinalizationTransport, "retrieve", delayed)
    with pytest.raises(ZeusFinalizationError, match="confirmation_expired"):
        api.collection_confirm({"preview_token": preview["preview_token"]}, session_id="collection")
    assert (chain.local_canonical / "campaign.json").read_bytes() == before
    assert not (chain.local_canonical / ".mot_ui/sync").exists()


def test_actual_receiver_multichunk_collection_is_bounded_readonly(local):
    """Exercise real RETRIEVE receiver/chunks, not a canned retrieve transport."""
    import base64
    import random
    import sqlite3
    import time

    chain, api = local
    target = chain.campaign / "screen/s0_1p300000/worker0/joint_screening.db"
    if not target.exists():
        target = chain.campaign / "screen/s0_1p100000/worker0/joint_screening.db"
    old = target.read_bytes()
    try:
        # SQLite normally retains free pages after deletion. A private test
        # table, dropped before validation, leaves incompressible free-page
        # bytes while every schema, study attribute, trial and result is intact.
        # This is transport-size qualification only, not physical evidence.
        payload = random.Random(197).randbytes(5 * 1024 * 1024)
        with sqlite3.connect(target) as connection:
            connection.execute("PRAGMA secure_delete=OFF")
            connection.execute("CREATE TABLE collection_size_probe (padding BLOB)")
            connection.execute("INSERT INTO collection_size_probe VALUES(?)", (payload,))
            connection.commit()
            connection.execute("DROP TABLE collection_size_probe")
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert target.stat().st_size <= collection.FILE_LIMIT
        start = time.monotonic()
        boundary = len(chain.boundary_calls)
        preview, result = collect(chain, api)
        elapsed = time.monotonic() - start
        count = api.collection.previews.get(preview["preview_token"]).value.descriptor["bundle"][
            "chunks"
        ]
        assert len(count) > 1
        actual = chain.boundary_calls[boundary:]
        assert all(
            kind == "finalization" and operation == "retrieve" for kind, operation, _ in actual
        )
        assert len([p for _, _, p in actual if "chunk_index" in p]) == len(count)
        assert result["local_sync"]["status"] == "synchronized" and len(chain.qsub_calls) == 9
        Path(
            "/private/tmp/team-collection-multichunk-"
            + ("v1" if chain.acceptance else "TEAM")
            + ".json"
        ).write_text(
            json.dumps(
                {
                    "scope": "hermetic actual receiver; fake SSH/scheduler/trajectory only",
                    "chunk_count": len(count),
                    "file_count": preview["artifacts"]["file_count"],
                    "uncompressed_bytes": preview["artifacts"]["total_bytes"],
                    "maximum_file_bytes": preview["artifacts"]["maximum_file_bytes"],
                    "preview_confirm_seconds": elapsed,
                    "remote_operations": len(actual),
                    "qsub_total_unchanged": 9,
                    "repeated_snapshot_validation_compression": True,
                },
                indent=2,
            )
            + "\n"
        )
    finally:
        target.write_bytes(old)


@pytest.mark.parametrize(
    "path", ["workflow_api/mot_2d_collection.py", "workflow_api/verified_artifact_bundle.py"]
)
def test_operational_collection_dependencies_are_pinned(local, path):
    chain, api = local
    target = chain.local / path
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n# unreviewed change\n")
        with pytest.raises(ZeusFinalizationError, match="local_checkout_mismatch"):
            api.collection_preview(chain.request, session_id="collection")
        assert not (chain.local_canonical / ".mot_ui/sync").exists()
    finally:
        target.write_bytes(original)
