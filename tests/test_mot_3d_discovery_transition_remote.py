import base64
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflow_api import mot_3d_discovery_transition_remote as remote
from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    ReceiverKind,
    ReceiverOperation,
    _RECEIVERS,
)


def test_exact_discovery_transition_allowlist_is_closed():
    paths = remote.expected_paths()
    assert len(paths) == 961 == len(set(paths))
    assert sum("/trials/trial_" in path for path in paths) == 950
    assert sum(path.endswith("/merged_summary.json") for path in paths) == 2
    assert sum(path.endswith("/ranked_trials.csv") for path in paths) == 2
    assert sum(path.startswith("selection/discovery/") for path in paths) == 2
    assert sum(path.startswith("jobs/preliminary_check/") for path in paths) == 4
    assert paths.count("campaign.json") == 1
    assert not any(
        "smoke" in path or path.endswith((".db", ".sqlite")) for path in paths
    )


def _campaign(tmp_path: Path) -> Path:
    campaign = tmp_path / "campaign"
    for index, name in enumerate(remote.expected_paths()):
        path = campaign / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"artifact-{index}\n".encode())
    return campaign


def test_bundle_is_deterministic_bounded_and_self_verifying(tmp_path):
    campaign = _campaign(tmp_path)
    first, packed, chunks = remote.build_bundle(campaign, "a" * 40)
    second, packed_again, chunks_again = remote.build_bundle(campaign, "a" * 40)
    assert first == second and packed == packed_again and chunks == chunks_again
    assert first["file_count"] == 961
    assert first["bundle_sha256"] == hashlib.sha256(packed).hexdigest()
    assert len(chunks) <= remote.MAX_CHUNKS
    assert all(len(chunk) <= remote.MAX_CHUNK_BYTES for chunk in chunks)
    payload = json.loads(gzip.decompress(packed))
    assert [row["path"] for row in payload["files"]] == list(remote.expected_paths())
    for row in payload["files"]:
        content = base64.b64decode(row["content"], validate=True)
        assert row["size"] == len(content)
        assert row["sha256"] == hashlib.sha256(content).hexdigest()


def test_bundle_rejects_oversized_member(tmp_path):
    campaign = _campaign(tmp_path)
    (campaign / remote.expected_paths()[0]).write_bytes(
        b"x" * (remote.MAX_FILE_BYTES + 1)
    )
    with pytest.raises(SystemExit):
        remote.build_bundle(campaign, "a" * 40)


def test_bounded_read_ignores_access_time_changes(tmp_path, monkeypatch):
    path = tmp_path / "evidence.json"
    path.write_bytes(b"{}")
    original = path.lstat()
    calls = 0

    def changed_atime(candidate):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original
        return SimpleNamespace(
            st_dev=original.st_dev,
            st_ino=original.st_ino,
            st_mode=original.st_mode,
            st_nlink=original.st_nlink,
            st_uid=original.st_uid,
            st_gid=original.st_gid,
            st_size=original.st_size,
            st_atime_ns=original.st_atime_ns + 1,
            st_mtime_ns=original.st_mtime_ns,
            st_ctime_ns=original.st_ctime_ns,
        )

    monkeypatch.setattr(Path, "lstat", changed_atime)
    monkeypatch.setattr(Path, "is_symlink", lambda unused: False)
    assert remote.bounded(path) == b"{}"


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_inspect_and_status_transition_paths_are_zero_write(tmp_path):
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    before = set(campaign.rglob("*"))
    for operation in ("inspect", "status", "retrieve"):
        paths = remote.transition_paths(campaign, operation)
        assert not paths[0].exists()
        assert set(campaign.rglob("*")) == before
    paths = remote.transition_paths(campaign, "prepare")
    assert paths[0].is_dir()


def test_pinned_receiver_policy_is_exact(tmp_path):
    receiver = tmp_path / "workflow_api/mot_3d_discovery_transition_remote.py"
    receiver.parent.mkdir(parents=True)
    receiver.write_text(Path(remote.__file__).read_text())
    executable = tmp_path / "ssh"
    executable.write_text("#!/bin/sh\n")
    policy = PinnedSshPolicy.mot_3d_discovery_transition(
        tmp_path, executable, timeout=30
    )
    assert policy.receiver is ReceiverKind.MOT_3D_DISCOVERY_TRANSITION
    assert _RECEIVERS[policy.receiver].operations == frozenset(
        {
            ReceiverOperation.INSPECT,
            ReceiverOperation.PREPARE,
            ReceiverOperation.STATUS,
            ReceiverOperation.RETRIEVE,
        }
    )
