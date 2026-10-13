import base64
import hashlib
import json
import os
import threading
from pathlib import Path

import pytest

from workflow_api.mot_3d_preliminary_transition import RemotePreliminaryTransitionState
from workflow_api.mot_3d_refinement_transition import (
    Mot3DRefinementTransitionCoordinator,
)
from workflow_api.mot_3d_closure_transition import Mot3DClosureTransitionCoordinator
from workflow_api.mot_3d_refinement_submission import validate_prior_transition_sync
from workflow_api import mot_3d_preliminary_transition as transition_module
from workflow_api.verified_artifact_bundle import build_artifact_bundle
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.zeus_discovery_submission import canonical_digest
from workflow_api.zeus_snapshot import ZeusProfile


COMMIT = "a" * 40
NOW = 1_800_000_000


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fixture(
    tmp_path: Path,
    monkeypatch,
    *,
    coordinator_type=Mot3DRefinementTransitionCoordinator,
    from_stage="refinement",
    to_stage="closure",
    prepared_status="closure_prepared",
):
    campaign = tmp_path / "data/optimization/mot_3d/campaign"
    campaign.mkdir(parents=True)
    old = json.dumps({"name": "campaign", "stage": from_stage}).encode() + b"\n"
    new = json.dumps({"name": "campaign", "stage": to_stage}).encode() + b"\n"
    (campaign / "campaign.json").write_bytes(old)
    paths = frozenset(
        {"campaign.json", *(f"results/file_{index:03d}.json" for index in range(207))}
    )
    files = {
        name: new if name == "campaign.json" else f"{name}\n".encode() for name in paths
    }
    built = build_artifact_bundle(
        files,
        campaign="campaign",
        commit=COMMIT,
        from_stage=from_stage,
        to_stage=to_stage,
        expected_paths=paths,
    )
    identity = {
        "source_files": {"campaign.json": sha(old)},
        "code_files": {},
        "stage3_local_sync_receipt_sha256": "b" * 64,
        "stage3_remote_receipt_sha256": "c" * 64,
        "stage3_bundle_sha256": "d" * 64,
        "stage4_submission_identity": {},
    }
    transition_key = "e" * 64
    receipt = {
        "version": 1,
        "status": prepared_status,
        "nonce": "f" * 32,
        "transition_key": transition_key,
        "commit": COMMIT,
        "submission_key": "1" * 64,
        "identity_sha256": canonical_digest(identity),
        "old_campaign_sha256": sha(old),
        "new_campaign_sha256": sha(new),
        "evidence_sha256": "2" * 64,
        "files": {name: sha(raw) for name, raw in files.items()},
        "bundle": built.manifest,
        "completed_unix_s": NOW,
    }
    jobs = {
        "angled_donut": {"array": "10[].zeus-master", "merge": "20.zeus-master"},
        "single_pass": {"array": "11[].zeus-master", "merge": "21.zeus-master"},
    }
    state = RemotePreliminaryTransitionState(
        prepared_status,
        "main",
        jobs,
        6,
        2,
        "valid",
        None,
        "2" * 64,
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
        "1" * 64,
        transition_key,
        "data/optimization/mot_3d/campaign",
        paths,
    )

    class Transport:
        def retrieve(self, **payload):
            row = built.manifest["chunks"][payload["chunk_index"]]
            raw = built.chunks[payload["chunk_index"]]
            return RemotePreliminaryTransitionState(
                **{
                    **state.__dict__,
                    "chunk": {
                        "index": row["index"],
                        "sha256": row["sha256"],
                        "content": base64.b64encode(raw).decode(),
                    },
                }
            )

    coordinator = object.__new__(coordinator_type)
    coordinator.clock = lambda: NOW
    monkeypatch.setattr(coordinator, "_expected_paths", lambda _fd: paths)
    return coordinator, plan, Transport(), state, files


def test_refinement_sync_is_manifest_last_and_idempotent(tmp_path, monkeypatch):
    coordinator, plan, transport, state, files = fixture(tmp_path, monkeypatch)
    digest = coordinator._synchronize(plan, transport, state)
    assert coordinator._synchronize(plan, transport, state) == digest
    assert json.loads((plan[2] / "campaign.json").read_text())["stage"] == "closure"
    assert len(files) == 208
    receipt = plan[2] / ".mot_ui/sync/refinement_to_closure.json"
    assert sha(receipt.read_bytes()) == digest
    assert not receipt.with_name("refinement_to_closure.pending.json").exists()


def test_refinement_status_contract_uses_closure_vocabulary(tmp_path, monkeypatch):
    coordinator, plan, _, state, _ = fixture(tmp_path, monkeypatch)
    coordinator._plan = lambda _request: plan
    coordinator._inspect = lambda _request, operation="inspect": (plan, None, state)
    coordinator._verify_local_snapshot = lambda *_args: None
    payload = coordinator.status({})
    assert payload["campaign"]["stage"] == "refinement"
    assert payload["refinement"]["status"] == "closure_prepared"
    assert payload["validation"]["expected_result_artifacts"] == 200
    assert payload["next_action"] == "synchronize_results"
    assert payload["transition"] == {"status": "closure_prepared"}


def test_preview_and_confirm_are_session_bound_and_idempotent(tmp_path, monkeypatch):
    coordinator, plan, _, prepared, _ = fixture(tmp_path, monkeypatch)
    ready = RemotePreliminaryTransitionState(
        **{
            **prepared.__dict__,
            "lifecycle": "ready_to_advance",
            "receipt": None,
            "bundle": None,
        }
    )

    class Transport:
        def prepare(self, **_payload):
            return prepared

    transport = Transport()
    coordinator._previews = PreviewRegistry(
        clock=lambda: NOW, token_factory=lambda: "token"
    )
    coordinator._confirm_lock = threading.Lock()
    coordinator._inspect = lambda _request, operation="inspect": (
        plan,
        transport,
        ready if operation == "inspect" else prepared,
    )
    coordinator._synchronize = lambda *_args: "9" * 64
    monkeypatch.setattr(transition_module.secrets, "token_hex", lambda _size: "f" * 32)

    preview = coordinator.preview({}, session_id="session-a")
    assert preview["from_stage"] == "refinement"
    assert preview["to_stage"] == "closure"
    assert preview["refinement"]["result_artifacts"] == 200
    assert preview["artifacts"]["transfer_files"] == 208
    assert preview["effects"]["submit_closure"] is False

    result = coordinator.confirm({"preview_token": "token"}, session_id="session-a")
    assert result["status"] == "closure_prepared"
    assert result["artifacts"]["synchronized"] == 201
    assert (
        coordinator.confirm({"preview_token": "token"}, session_id="session-a")
        == result
    )


def _prior_sync_fixture(tmp_path: Path):
    campaign = tmp_path / "campaign"
    sync_dir = campaign / ".mot_ui/sync"
    sync_dir.mkdir(parents=True)
    files = {"campaign.json": b"campaign\n", "selection/refinement/a.json": b"a\n"}
    for name, raw in files.items():
        target = campaign / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    receipt = {
        "status": "synchronized",
        "transition_key": "1" * 64,
        "remote_receipt_sha256": "2" * 64,
        "bundle_sha256": "3" * 64,
        "files": {name: sha(raw) for name, raw in files.items()},
        "completed_unix_s": NOW,
    }
    path = sync_dir / "preliminary_to_refinement.json"
    path.write_text(json.dumps(receipt))
    return campaign, path, receipt, frozenset(files)


def test_prior_sync_authority_rehashes_exact_closed_registry(tmp_path):
    campaign, path, receipt, expected = _prior_sync_fixture(tmp_path)
    fd = os.open(campaign, os.O_RDONLY | os.O_DIRECTORY)
    try:
        parsed, raw = validate_prior_transition_sync(fd, expected)
        assert parsed == receipt
        assert sha(raw) == sha(path.read_bytes())
        (campaign / "selection/refinement/a.json").write_bytes(b"changed\n")
        with pytest.raises(ValueError):
            validate_prior_transition_sync(fd, expected)
    finally:
        os.close(fd)


def test_prior_sync_authority_rejects_missing_extra_and_symlink(tmp_path):
    campaign, path, receipt, expected = _prior_sync_fixture(tmp_path)
    fd = os.open(campaign, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for changed in (
            expected - {"campaign.json"},
            expected | {"extra.json"},
        ):
            with pytest.raises(ValueError):
                validate_prior_transition_sync(fd, frozenset(changed))
        path.unlink()
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps(receipt))
        path.symlink_to(outside)
        with pytest.raises(OSError):
            validate_prior_transition_sync(fd, expected)
    finally:
        os.close(fd)
