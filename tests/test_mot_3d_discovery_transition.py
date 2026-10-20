import base64
import gzip
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from workflow_api.mot_3d_discovery_transition import (
    EXPECTED_BUNDLE_PATHS,
    Mot3DDiscoveryTransitionCoordinator,
    Mot3DDiscoveryTransitionError,
    RemoteDiscoveryTransitionState,
)
import workflow_api.mot_3d_discovery_transition as transition_module
from workflow_api.zeus_snapshot import ZeusProfile


CHAIN = {
    "angled_donut": ("101[].zeus-master", "102[].zeus-master"),
    "single_pass": (
        "103[].zeus-master",
        "104[].zeus-master",
        "105[].zeus-master",
    ),
}


class FakeTransport:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def inspect(self, **payload):
        self.calls.append(("inspect", payload))
        return self.state

    def status(self, **payload):
        self.calls.append(("status", payload))
        return self.state


# Pinned host executables; remote receiver fixtures remain isolated below.
SSH_EXECUTABLE = Path(shutil.which("ssh")).resolve()
GIT_EXECUTABLE = Path(shutil.which("git")).resolve()


def coordinator(tmp_path, state):
    root = tmp_path / "repo"
    campaign = root / "data/optimization/mot_3d/campaign"
    campaign.mkdir(parents=True)
    (campaign / "campaign.json").write_text("{}")
    profile = ZeusProfile.parse(
        {
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        }
    )
    transport = FakeTransport(state)
    service = Mot3DDiscoveryTransitionCoordinator(
        root,
        SSH_EXECUTABLE,
        GIT_EXECUTABLE,
        clock=lambda: 100.0,
        token_factory=lambda: "token",
        transport_factory=lambda _profile: transport,
    )
    service._base = lambda _request: (
        "campaign-id",
        profile,
        campaign,
        {"name": "campaign"},
        "a" * 40,
        {"campaign.json": "b" * 64},
        "c" * 32,
        "d" * 64,
        "e" * 64,
        "f" * 64,
    )
    return service, transport


def state(lifecycle="ready_to_advance"):
    return RemoteDiscoveryTransitionState(lifecycle, "main", CHAIN, None, None, None)


def test_closed_bundle_allowlist_is_exact_and_has_950_trials():
    trials = [name for name in EXPECTED_BUNDLE_PATHS if "/trials/" in name]
    assert len(EXPECTED_BUNDLE_PATHS) == 961
    assert len(trials) == 950
    assert "campaign.json" in EXPECTED_BUNDLE_PATHS
    assert not any(
        "smoke" in name or name.endswith(".db") for name in EXPECTED_BUNDLE_PATHS
    )


def test_preview_is_session_bound_review_without_prepare(tmp_path):
    service, transport = coordinator(tmp_path, state())
    result = service.preview(
        {
            "campaign_id": "campaign-id",
            "username": "tal.noa",
            "project_directory": "/home/tal.noa/ytterbium_lab_simulation_new",
        },
        session_id="session-a",
    )
    assert result["preview_token"] == "token"
    assert result["discovery"]["completed_trials"] == 950
    assert result["effects"] == {
        "synchronize_discovery": True,
        "prepare_preliminary_check": True,
        "submit_preliminary_check": False,
        "start_simulation": False,
        "overwrite_existing": False,
    }
    assert [name for name, _ in transport.calls] == ["inspect"]
    with pytest.raises(Mot3DDiscoveryTransitionError, match="confirmation_invalid"):
        service.confirm({"preview_token": "token"}, session_id="session-b")


@pytest.mark.parametrize(
    "bad_chain",
    [
        {"angled_donut": CHAIN["angled_donut"], "single_pass": ()},
        {**CHAIN, "extra": ()},
        {**CHAIN, "angled_donut": ("not-a-job", "102[].zeus-master")},
    ],
)
def test_remote_chain_is_exact(bad_chain):
    with pytest.raises(Mot3DDiscoveryTransitionError, match="remote_response_invalid"):
        Mot3DDiscoveryTransitionCoordinator._validate_state(
            RemoteDiscoveryTransitionState(
                "ready_to_advance", "main", bad_chain, None, None, None
            )
        )


def test_bundle_caps_and_exact_chunk_sequence_are_strict():
    valid = {
        "version": 1,
        "file_count": 961,
        "uncompressed_bytes": 1,
        "bundle_sha256": "a" * 64,
        "chunks": [{"index": 0, "size": 1, "sha256": "b" * 64}],
    }
    Mot3DDiscoveryTransitionCoordinator._validate_bundle(valid)
    for mutation in (
        {**valid, "file_count": 960},
        {**valid, "uncompressed_bytes": 64 * 1024 * 1024 + 1},
        {**valid, "chunks": [{"index": 1, "size": 1, "sha256": "b" * 64}]},
        {
            **valid,
            "chunks": [{"index": 0, "size": 4 * 1024 * 1024 + 1, "sha256": "b" * 64}],
        },
    ):
        with pytest.raises(
            Mot3DDiscoveryTransitionError, match="remote_response_invalid"
        ):
            Mot3DDiscoveryTransitionCoordinator._validate_bundle(mutation)


def test_local_sync_rejects_symlinked_sync_directory_without_external_write(tmp_path):
    service, _ = coordinator(tmp_path, state())
    plan = service._base({})
    outside = tmp_path / "outside"
    outside.mkdir()
    (plan[2] / ".mot_ui").mkdir()
    (plan[2] / ".mot_ui/sync").symlink_to(outside, target_is_directory=True)
    prepared = RemoteDiscoveryTransitionState(
        "preliminary_check_prepared",
        "main",
        CHAIN,
        {
            "transition_key": "a" * 64,
            "nonce": "b" * 32,
        },
        {"bundle_sha256": "c" * 64, "chunks": []},
        None,
    )
    with pytest.raises(Mot3DDiscoveryTransitionError, match="local_sync_conflict"):
        service._synchronize(plan, object(), prepared)
    assert list(outside.iterdir()) == []


def test_local_receipt_symlink_is_never_followed(tmp_path):
    service, _ = coordinator(tmp_path, state())
    plan = service._base({})
    sync = plan[2] / ".mot_ui/sync"
    sync.mkdir(parents=True)
    secret = tmp_path / "secret"
    secret.write_text("private")
    receipt = sync / "discovery_to_preliminary.json"
    receipt.symlink_to(secret)
    prepared = RemoteDiscoveryTransitionState(
        "preliminary_check_prepared", "main", CHAIN, {}, {}, None
    )
    assert not service._verify_local_receipt(
        plan[2], prepared, receipt, raise_on_error=False
    )


def test_campaign_mutation_during_publication_is_preserved_and_fails_closed(
    tmp_path, monkeypatch
):
    service, _ = coordinator(tmp_path, state())
    plan = list(service._base({}))
    campaign = plan[2]
    old = (campaign / "campaign.json").read_bytes()
    plan[5] = {"campaign.json": hashlib.sha256(old).hexdigest()}
    new_manifest = b'{"stage":"preliminary_check"}'
    rows = []
    for name in sorted(EXPECTED_BUNDLE_PATHS):
        content = new_manifest if name == "campaign.json" else b""
        rows.append(
            {
                "path": name,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "content": base64.b64encode(content).decode("ascii"),
            }
        )
    payload = {
        "version": 1,
        "campaign": campaign.name,
        "commit": plan[4],
        "from_stage": "discovery",
        "to_stage": "preliminary_check",
        "files": rows,
        "uncompressed_bytes": len(new_manifest),
    }
    packed = gzip.compress(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode(),
        mtime=0,
    )
    bundle = {
        "version": 1,
        "file_count": 961,
        "uncompressed_bytes": len(new_manifest),
        "bundle_sha256": hashlib.sha256(packed).hexdigest(),
        "chunks": [
            {
                "index": 0,
                "size": len(packed),
                "sha256": hashlib.sha256(packed).hexdigest(),
            }
        ],
    }
    receipt = {"transition_key": "a" * 64, "nonce": "b" * 32}
    prepared = RemoteDiscoveryTransitionState(
        "preliminary_check_prepared", "main", CHAIN, receipt, bundle, None
    )

    class Retrieve:
        def retrieve(self, **_payload):
            return RemoteDiscoveryTransitionState(
                "preliminary_check_prepared",
                "main",
                CHAIN,
                receipt,
                bundle,
                {
                    "index": 0,
                    "sha256": bundle["chunks"][0]["sha256"],
                    "content": base64.b64encode(packed).decode("ascii"),
                },
            )

    original_publish = transition_module._publish_no_replace_at
    changed = False

    def mutate_then_publish(parent_fd, name, data):
        nonlocal changed
        original_publish(parent_fd, name, data)
        if not changed and name == "trial_0000.json":
            changed = True
            (campaign / "campaign.json").write_bytes(b"concurrent mutation")

    monkeypatch.setattr(
        transition_module, "_publish_no_replace_at", mutate_then_publish
    )
    with pytest.raises(Mot3DDiscoveryTransitionError, match="local_sync_conflict"):
        service._synchronize(tuple(plan), Retrieve(), prepared)
    assert (campaign / "campaign.json").read_bytes() == b"concurrent mutation"
