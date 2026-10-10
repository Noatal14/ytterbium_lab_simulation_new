import json
import os
from pathlib import Path

import pytest

from workflow_api.manifest_codec import (
    MAX_MANIFEST_BYTES,
    ManifestCodecError,
    ManifestFailure,
    decode_manifest,
    read_manifest,
)
from workflow_api.discovery import DiscoveryError, _read_manifest


FIXTURES = Path(__file__).parent / "fixtures" / "campaign_manifests"


@pytest.mark.parametrize(
    ("name", "family", "version"),
    [
        ("mot_2d_v1.json", "mot_2d", "mot-2d-manifest-v1"),
        ("mot_3d_v1.json", "mot_3d", "mot-3d-manifest-v1"),
    ],
)
def test_existing_implicit_v1_fixtures_preserve_exact_bytes_and_model(
    name, family, version
):
    path = FIXTURES / name
    before = path.read_bytes()
    document = read_manifest(path, expected_family=family)

    assert document.family == family
    assert document.version == version
    assert document.raw_bytes == before
    assert document.model == json.loads(before)
    assert path.read_bytes() == before


def test_wrong_expected_family_and_unknown_kind_fail_closed():
    raw = (FIXTURES / "mot_2d_v1.json").read_bytes()
    with pytest.raises(ValueError, match="does not match expected"):
        decode_manifest(raw, expected_family="mot_3d")
    with pytest.raises(ValueError, match="Unsupported campaign kind"):
        decode_manifest(b'{"kind":"future_campaign"}')


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "mot_2d_s0_campaign", "upstream_2d_campaign": {}},
        {"kind": "mot_3d_campaign_v2", "s0_values": [1.3]},
    ],
)
def test_mixed_implicit_schemas_fail_closed(payload):
    with pytest.raises(ValueError, match="mixes incompatible"):
        decode_manifest(json.dumps(payload).encode())


def test_non_object_invalid_utf8_and_oversize_fail_closed():
    for raw in (
        b"[]",
        b"\xff",
        b'{"kind":"mot_2d_s0_campaign","kind":"mot_3d_campaign_v2"}',
        b"{" + b" " * MAX_MANIFEST_BYTES,
    ):
        with pytest.raises(ValueError):
            decode_manifest(raw)


def test_reader_rejects_symlink_and_truncated_read(tmp_path, monkeypatch):
    source = tmp_path / "campaign.json"
    source.write_bytes((FIXTURES / "mot_2d_v1.json").read_bytes())
    link = tmp_path / "linked.json"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="trusted regular"):
        read_manifest(link)

    real_read = os.read
    calls = 0

    def truncated(descriptor, count):
        nonlocal calls
        calls += 1
        return real_read(descriptor, min(count, 8)) if calls == 1 else b""

    monkeypatch.setattr(os, "read", truncated)
    with pytest.raises(ValueError, match="truncated"):
        read_manifest(source)


def test_parsed_model_is_not_a_normalized_or_shared_copy():
    raw = b'{"kind":"mot_2d_s0_campaign", "stage" : "smoke"}\n'
    first = decode_manifest(raw)
    second = decode_manifest(raw)
    first.model["stage"] = "changed-locally"

    assert first.raw_bytes == raw
    assert second.raw_bytes == raw
    assert second.model["stage"] == "smoke"
    mutable = first.model
    mutable["nested"] = {"rows": [1]}
    mutable["nested"]["rows"].append(2)
    assert "nested" not in first.model


def test_final_path_replacement_with_symlink_to_same_inode_is_rejected(
    tmp_path, monkeypatch
):
    source = tmp_path / "campaign.json"
    source.write_bytes((FIXTURES / "mot_2d_v1.json").read_bytes())
    same_inode = tmp_path / "same-inode.json"
    os.link(source, same_inode)
    real_read = os.read
    replaced = False

    def replace_after_read(descriptor, count):
        nonlocal replaced
        chunk = real_read(descriptor, count)
        if chunk and not replaced:
            source.unlink()
            source.symlink_to(same_inode)
            replaced = True
        return chunk

    monkeypatch.setattr(os, "read", replace_after_read)
    with pytest.raises(ManifestCodecError) as caught:
        read_manifest(source)
    assert caught.value.reason is ManifestFailure.CHANGED


@pytest.mark.parametrize(
    ("reason", "code", "message"),
    [
        (
            ManifestFailure.NOT_REGULAR,
            "invalid_manifest",
            "Campaign record is not a trusted regular file.",
        ),
        (
            ManifestFailure.INVALID_JSON,
            "invalid_manifest",
            "Campaign record is not valid JSON.",
        ),
        (
            ManifestFailure.NON_OBJECT,
            "invalid_manifest",
            "Campaign record must contain a JSON object.",
        ),
        (
            ManifestFailure.OVERSIZED,
            "oversized_manifest",
            "Campaign record is too large to inspect safely.",
        ),
        (
            ManifestFailure.UNAVAILABLE,
            "unavailable_manifest",
            "Campaign record is unavailable.",
        ),
        (
            ManifestFailure.UNSUPPORTED_KIND,
            "unsupported_campaign",
            "Campaign record has an unsupported workflow kind.",
        ),
    ],
)
def test_discovery_preserves_every_historical_manifest_error_contract(
    tmp_path, monkeypatch, reason, code, message
):
    def fail(*_args, **_kwargs):
        raise ManifestCodecError(reason, "internal detail must not cross boundary")

    monkeypatch.setattr("workflow_api.discovery.read_manifest", fail)
    with pytest.raises(DiscoveryError) as caught:
        _read_manifest(tmp_path / "campaign.json")
    assert caught.value.code == code
    assert caught.value.message == message
