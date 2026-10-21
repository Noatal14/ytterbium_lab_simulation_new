"""Finalization authenticates original bytes, including Windows CRT sentinels."""
from __future__ import annotations

import hashlib
import os

import pytest

from workflow_api import zeus_finalization_remote as receiver


@pytest.mark.parametrize("suffix", [".npy", ".json"])
def test_evidence_digest_preserves_crlf_ctrl_z_and_binary_suffix(tmp_path, monkeypatch, suffix):
    campaign = tmp_path / "data" / "campaign"
    campaign.mkdir(parents=True)
    path = campaign / ("raw" + suffix)
    payload = b"\x93NUMPY\x00\xff\r\nfirst\x1aafter-ctrl-z\r\n\x00last"
    path.write_bytes(payload)
    monkeypatch.setattr(receiver, "raw_evidence_paths", lambda *_: [path])
    expected = hashlib.sha256(
        path.relative_to(tmp_path).as_posix().encode() + b"\x00" + payload + b"\x00"
    ).hexdigest()

    opened, digest = receiver._open_evidence(campaign, {}, tmp_path)
    try:
        assert digest == expected
        os.lseek(opened[0][1], 0, os.SEEK_SET)
        assert os.read(opened[0][1], len(payload) + 1) == payload
        receiver._verify_evidence(opened)
    finally:
        for _, fd, _ in opened:
            os.close(fd)


def test_evidence_open_requests_platform_binary_mode_without_dropping_link_guard(tmp_path, monkeypatch):
    path = tmp_path / "raw.npy"
    path.write_bytes(b"unchanged")
    real_open = os.open
    real_binary = getattr(os, "O_BINARY", 0)
    binary_flag = real_binary or (1 << 29)
    seen = []

    def observed_open(name, flags, *args, **kwargs):
        seen.append(flags)
        return real_open(name, (flags & ~binary_flag) | real_binary, *args, **kwargs)

    monkeypatch.setattr(receiver, "raw_evidence_paths", lambda *_: [path])
    monkeypatch.setattr(receiver.os, "O_BINARY", binary_flag, raising=False)
    monkeypatch.setattr(receiver.os, "open", observed_open)
    opened, _ = receiver._open_evidence(tmp_path, {}, tmp_path)
    try:
        assert seen == [os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | binary_flag]
    finally:
        for _, fd, _ in opened:
            os.close(fd)


def test_binary_evidence_identity_change_still_rejected(tmp_path, monkeypatch):
    path = tmp_path / "raw.npy"
    path.write_bytes(b"original\r\n\x1aoriginal")
    monkeypatch.setattr(receiver, "raw_evidence_paths", lambda *_: [path])
    opened, _ = receiver._open_evidence(tmp_path, {}, tmp_path)
    try:
        path.write_bytes(b"changed-size\r\n\x1achanged-size")
        with pytest.raises(ValueError, match="evidence changed"):
            receiver._verify_evidence(opened)
    finally:
        for _, fd, _ in opened:
            os.close(fd)
