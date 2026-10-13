import base64
import hashlib
import json
import os
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from workflow_api.mot_3d_preliminary_transition import (
    Mot3DPreliminaryTransitionCoordinator,
    Mot3DPreliminaryTransitionError,
    RemotePreliminaryTransitionState,
)
from workflow_api import mot_3d_preliminary_transition as transition_module
from workflow_api.verified_artifact_bundle import build_artifact_bundle
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.zeus_discovery_submission import canonical_digest
from workflow_api.zeus_snapshot import ZeusProfile


COMMIT = "a" * 40
NOW = 1_800_000_000


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fixture(tmp_path, monkeypatch):
    campaign = tmp_path / "data/optimization/mot_3d/campaign"
    campaign.mkdir(parents=True)
    old = b'{"name":"campaign","stage":"preliminary_check"}\n'
    new = b'{"name":"campaign","stage":"refinement"}\n'
    (campaign / "campaign.json").write_bytes(old)
    paths = frozenset(
        {"campaign.json", *(f"results/file_{i:03d}.json" for i in range(159))}
    )
    files = {
        name: (new if name == "campaign.json" else f"{name}\n".encode())
        for name in paths
    }
    built = build_artifact_bundle(
        files,
        campaign="campaign",
        commit=COMMIT,
        from_stage="preliminary_check",
        to_stage="refinement",
        expected_paths=paths,
    )
    identity = {
        "source_files": {"campaign.json": sha(old)},
        "code_files": {},
        "stage1_receipt_sha256": "b" * 64,
        "stage1_bundle_sha256": "c" * 64,
    }
    transition_key = "d" * 64
    receipt = {
        "version": 1,
        "status": "refinement_prepared",
        "nonce": "e" * 32,
        "transition_key": transition_key,
        "commit": COMMIT,
        "submission_key": "f" * 64,
        "identity_sha256": canonical_digest(identity),
        "old_campaign_sha256": sha(old),
        "new_campaign_sha256": sha(new),
        "evidence_sha256": "1" * 64,
        "files": {name: sha(raw) for name, raw in files.items()},
        "bundle": built.manifest,
        "completed_unix_s": NOW,
    }
    jobs = {
        family: {
            "array": f"{10+i}[] .zeus-master".replace("[] ", "[]"),
            "merge": f"{20+i}.zeus-master",
        }
        for i, family in enumerate(("angled_donut", "single_pass"))
    }
    state = RemotePreliminaryTransitionState(
        "refinement_prepared",
        "main",
        jobs,
        6,
        2,
        "valid",
        None,
        "1" * 64,
        receipt,
        built.manifest,
        None,
    )
    plan = (
        "mot_3d-campaign",
        ZeusProfile.parse(
            {
                "username": "tal.noa",
                "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
            }
        ),
        campaign,
        {"name": "campaign"},
        COMMIT,
        identity,
        "f" * 64,
        transition_key,
        "data/optimization/mot_3d/campaign",
        paths,
    )

    class Transport:
        def retrieve(self, **payload):
            row = built.manifest["chunks"][payload["chunk_index"]]
            raw = built.chunks[payload["chunk_index"]]
            return RemotePreliminaryTransitionState(
                "refinement_prepared",
                "main",
                jobs,
                6,
                2,
                "valid",
                None,
                "1" * 64,
                receipt,
                built.manifest,
                {
                    "index": row["index"],
                    "sha256": row["sha256"],
                    "content": base64.b64encode(raw).decode(),
                },
            )

    coordinator = object.__new__(Mot3DPreliminaryTransitionCoordinator)
    coordinator.clock = lambda: NOW
    monkeypatch.setattr(coordinator, "_expected_paths", lambda _fd: paths)
    return coordinator, plan, Transport(), state, files, paths


def test_synchronizes_exact_bundle_manifest_last_and_recovers(tmp_path, monkeypatch):
    coordinator, plan, transport, state, files, _ = fixture(tmp_path, monkeypatch)
    digest = coordinator._synchronize(plan, transport, state)
    assert len(digest) == 64
    for name, raw in files.items():
        assert (plan[2] / name).read_bytes() == raw
    assert coordinator._synchronize(plan, transport, state) == digest
    receipt = plan[2] / ".mot_ui/sync/preliminary_to_refinement.json"
    assert sha(receipt.read_bytes()) == digest
    assert not (
        plan[2] / ".mot_ui/sync/preliminary_to_refinement.pending.json"
    ).exists()


def test_existing_different_artifact_is_never_overwritten(tmp_path, monkeypatch):
    coordinator, plan, transport, state, _, _ = fixture(tmp_path, monkeypatch)
    target = plan[2] / "results/file_003.json"
    target.parent.mkdir()
    target.write_bytes(b"user data")
    with pytest.raises(Mot3DPreliminaryTransitionError) as error:
        coordinator._synchronize(plan, transport, state)
    assert error.value.code == "local_sync_conflict"
    assert target.read_bytes() == b"user data"
    assert (
        json.loads((plan[2] / "campaign.json").read_text())["stage"]
        == "preliminary_check"
    )


def test_symlink_parent_is_rejected_without_manifest_advance(tmp_path, monkeypatch):
    coordinator, plan, transport, state, _, _ = fixture(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, plan[2] / "results")
    with pytest.raises(Mot3DPreliminaryTransitionError) as error:
        coordinator._synchronize(plan, transport, state)
    assert error.value.code == "local_sync_conflict"
    assert not list(outside.iterdir())
    assert b"preliminary_check" in (plan[2] / "campaign.json").read_bytes()


def test_tampered_chunk_causes_zero_artifact_publication(tmp_path, monkeypatch):
    coordinator, plan, transport, state, _, _ = fixture(tmp_path, monkeypatch)
    original = transport.retrieve

    def corrupt(**payload):
        remote = original(**payload)
        row = dict(remote.chunk)
        row["content"] = base64.b64encode(b"bad").decode()
        return replace(remote, chunk=row)

    transport.retrieve = corrupt
    with pytest.raises(Mot3DPreliminaryTransitionError) as error:
        coordinator._synchronize(plan, transport, state)
    assert error.value.code == "remote_response_invalid"
    assert not (plan[2] / "results").exists()
    assert b"preliminary_check" in (plan[2] / "campaign.json").read_bytes()


def test_status_matches_frozen_dto_and_uses_descriptor_receipt_digest(
    tmp_path, monkeypatch
):
    coordinator, plan, transport, state, _, _ = fixture(tmp_path, monkeypatch)
    coordinator._inspect = lambda _request, operation="inspect": (
        plan,
        transport,
        state,
    )
    coordinator._verify_local_snapshot = lambda _campaign, _state: "9" * 64
    value = coordinator.status({})
    assert set(value) == {
        "source",
        "queried_at",
        "campaign",
        "preliminary",
        "scheduler",
        "validation",
        "transition",
        "next_action",
        "local_sync",
    }
    assert set(value["preliminary"]) == {"status", "chain"}
    assert value["campaign"]["stage"] == "refinement"
    assert value["next_action"] == "open_refinement"
    assert value["local_sync"] == {"status": "synchronized", "receipt_sha256": "9" * 64}


def test_preview_is_session_bound_and_confirmation_replays_result(
    tmp_path, monkeypatch
):
    coordinator, plan, transport, prepared, _, _ = fixture(tmp_path, monkeypatch)
    ready = RemotePreliminaryTransitionState(
        "ready_to_advance",
        "main",
        prepared.jobs,
        6,
        2,
        "valid",
        None,
        "1" * 64,
        None,
        None,
        None,
    )
    coordinator._previews = PreviewRegistry(
        clock=lambda: NOW, token_factory=lambda: "token"
    )
    coordinator._confirm_lock = threading.Lock()
    coordinator.clock = lambda: NOW
    coordinator._inspect = lambda _request, operation="inspect": (
        plan,
        transport,
        ready,
    )
    preview = coordinator.preview({}, session_id="owner")
    assert set(preview["artifacts"]) == {
        "synchronize",
        "create",
        "update",
        "transfer_files",
    }
    with pytest.raises(Mot3DPreliminaryTransitionError) as error:
        coordinator.confirm({"preview_token": "token"}, session_id="other")
    assert error.value.code == "confirmation_invalid"
    nonce = coordinator._previews.get("token").value.nonce
    prepared = replace(prepared, receipt={**prepared.receipt, "nonce": nonce})
    transport.prepare = lambda **_payload: prepared
    coordinator._synchronize = lambda *_args: "8" * 64
    result = coordinator.confirm({"preview_token": "token"}, session_id="owner")
    assert result["local_sync"]["receipt_sha256"] == "8" * 64
    assert coordinator.confirm({"preview_token": "token"}, session_id="owner") == result


def test_expired_preview_never_prepares(tmp_path, monkeypatch):
    coordinator, plan, transport, prepared, _, _ = fixture(tmp_path, monkeypatch)
    ready = RemotePreliminaryTransitionState(
        "ready_to_advance",
        "main",
        prepared.jobs,
        6,
        2,
        "valid",
        None,
        "1" * 64,
        None,
        None,
        None,
    )
    now = [NOW]
    coordinator.clock = lambda: now[0]
    coordinator._previews = PreviewRegistry(
        clock=lambda: now[0], token_factory=lambda: "token"
    )
    coordinator._confirm_lock = threading.Lock()
    coordinator._inspect = lambda _request, operation="inspect": (
        plan,
        transport,
        ready,
    )
    coordinator.preview({}, session_id="owner")
    now[0] += 301
    with pytest.raises(Mot3DPreliminaryTransitionError) as error:
        coordinator.confirm({"preview_token": "token"}, session_id="owner")
    assert error.value.code == "confirmation_expired"


def test_crash_after_manifest_last_recovers_without_overwrite(tmp_path, monkeypatch):
    coordinator, plan, transport, state, files, _ = fixture(tmp_path, monkeypatch)
    real = transition_module._atomic_json_at
    crashed = [False]

    def boundary(parent, name, value, replace):
        if name == "preliminary_to_refinement.json" and not crashed[0]:
            crashed[0] = True
            raise OSError("simulated crash")
        return real(parent, name, value, replace=replace)

    monkeypatch.setattr(transition_module, "_atomic_json_at", boundary)
    with pytest.raises(Mot3DPreliminaryTransitionError):
        coordinator._synchronize(plan, transport, state)
    assert (plan[2] / "campaign.json").read_bytes() == files["campaign.json"]
    digest = coordinator._synchronize(plan, transport, state)
    assert len(digest) == 64
    for name, raw in files.items():
        assert (plan[2] / name).read_bytes() == raw


def test_crash_after_final_receipt_recovers_and_removes_matching_intent(
    tmp_path, monkeypatch
):
    coordinator, plan, transport, state, _, _ = fixture(tmp_path, monkeypatch)
    real_unlink = transition_module.os.unlink
    crashed = [False]

    def crash_before_pending_unlink(path, *args, **kwargs):
        if path == "preliminary_to_refinement.pending.json" and not crashed[0]:
            crashed[0] = True
            raise OSError("simulated crash")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(transition_module.os, "unlink", crash_before_pending_unlink)
    with pytest.raises(Mot3DPreliminaryTransitionError):
        coordinator._synchronize(plan, transport, state)
    sync = plan[2] / ".mot_ui/sync"
    assert (sync / "preliminary_to_refinement.json").is_file()
    assert (sync / "preliminary_to_refinement.pending.json").is_file()

    monkeypatch.setattr(transition_module.os, "unlink", real_unlink)
    digest = coordinator._synchronize(plan, transport, state)
    assert len(digest) == 64
    assert not (sync / "preliminary_to_refinement.pending.json").exists()


def test_final_receipt_with_mismatched_pending_intent_fails_closed(
    tmp_path, monkeypatch
):
    coordinator, plan, transport, state, _, _ = fixture(tmp_path, monkeypatch)
    coordinator._synchronize(plan, transport, state)
    sync = plan[2] / ".mot_ui/sync"
    (sync / "preliminary_to_refinement.pending.json").write_text(
        json.dumps({"status": "synchronizing", "created_unix_s": NOW})
    )

    with pytest.raises(Mot3DPreliminaryTransitionError) as error:
        coordinator._synchronize(plan, transport, state)
    assert error.value.code == "local_sync_conflict"
    assert (sync / "preliminary_to_refinement.pending.json").is_file()


def test_symlinked_local_receipt_is_never_trusted(tmp_path, monkeypatch):
    coordinator, plan, transport, state, _, _ = fixture(tmp_path, monkeypatch)
    coordinator._synchronize(plan, transport, state)
    receipt = plan[2] / ".mot_ui/sync/preliminary_to_refinement.json"
    outside = tmp_path / "receipt.json"
    outside.write_bytes(receipt.read_bytes())
    receipt.unlink()
    os.symlink(outside, receipt)
    assert coordinator._verify_local_snapshot(plan[2], state) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"validation": "valid", "evidence_sha256": None},
        {"validation": "valid", "reason_code": "summary_mismatch"},
        {"validation": "scientifically_invalid", "reason_code": "invented"},
        {"validation": "scientifically_invalid", "lifecycle": "running"},
        {
            "lifecycle": "ready_to_advance",
            "validation": "not_started",
            "evidence_sha256": None,
        },
        {"lifecycle": "ready_to_advance", "completed_array_tasks": 5},
        {"lifecycle": "running", "validation": "valid"},
        {"chunk": {"index": 0, "sha256": "a" * 64, "content": "AA=="}},
    ],
)
def test_remote_state_cross_product_rejects_incoherent_evidence(
    tmp_path, monkeypatch, changes
):
    coordinator, _, _, state, _, _ = fixture(tmp_path, monkeypatch)
    candidate = replace(state, **changes)
    with pytest.raises(Mot3DPreliminaryTransitionError) as error:
        coordinator._validate_state(candidate)
    assert error.value.code == "remote_response_invalid"


def test_outcome_unknown_with_valid_evidence_requires_manual_inspection(
    tmp_path, monkeypatch
):
    coordinator, plan, transport, prepared, _, _ = fixture(tmp_path, monkeypatch)
    ambiguous = replace(
        prepared, lifecycle="outcome_unknown", receipt=None, bundle=None, chunk=None
    )
    coordinator._validate_state(ambiguous)
    coordinator._inspect = lambda _request, operation="inspect": (
        plan,
        transport,
        ambiguous,
    )
    value = coordinator.status({})
    assert value["validation"]["status"] == "valid"
    assert value["next_action"] == "inspect_zeus"
    assert value["local_sync"]["status"] == "not_synchronized"
