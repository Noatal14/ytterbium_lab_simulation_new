import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflow_api.manifest_codec import (
    MAX_MANIFEST_BYTES,
    ManifestCodecError,
    ManifestFailure,
    decode_manifest,
    normalize_manifest,
    read_manifest,
    read_normalized_manifest,
)
from workflow_api.discovery import DiscoveryError, _read_manifest
from studies import mot_2d_s0_campaign, mot_3d_campaign


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


@pytest.mark.parametrize(
    ("name", "family", "version"),
    [
        ("mot_2d_v1.json", "mot_2d", "mot-2d-manifest-v1"),
        ("mot_3d_v1.json", "mot_3d", "mot-3d-manifest-v1"),
    ],
)
def test_v1_normalization_adds_internal_version_without_rewriting_source(
    name, family, version
):
    path = FIXTURES / name
    before = path.read_bytes()
    normalized = read_normalized_manifest(path, expected_family=family)

    assert normalized.family == family
    assert normalized.schema_version == version
    assert normalized.raw_bytes == before
    assert normalized.manifest == json.loads(before)
    assert "schema_version" not in normalized.manifest
    assert path.read_bytes() == before


def test_normalized_manifest_is_detached_from_document_and_callers():
    document = decode_manifest((FIXTURES / "mot_2d_v1.json").read_bytes())
    normalized = normalize_manifest(document)
    first = normalized.manifest
    first["stage"] = "caller-change"
    assert normalized.manifest["stage"] == "complete"
    assert document.model["stage"] == "complete"


def test_historical_2d_status_output_is_unchanged_through_versioned_codec(
    tmp_path, capsys
):
    root = tmp_path / "campaign"
    root.mkdir()
    raw = (FIXTURES / "mot_2d_v1.json").read_bytes()
    (root / "campaign.json").write_bytes(raw)

    mot_2d_s0_campaign.status(SimpleNamespace(campaign=str(root)))

    assert capsys.readouterr().out == (
        "Campaign: fixture-2d\nCurrent stage: complete\ns0 values: [1.3]\n"
    )
    assert (root / "campaign.json").read_bytes() == raw


def test_historical_3d_status_output_is_unchanged_through_versioned_codec(
    tmp_path, capsys
):
    root = tmp_path / "campaign"
    root.mkdir()
    raw = (FIXTURES / "mot_3d_v1.json").read_bytes()
    (root / "campaign.json").write_bytes(raw)

    mot_3d_campaign.status(SimpleNamespace(campaign=str(root)))

    assert capsys.readouterr().out == (
        "Campaign: fixture-3d\nCurrent stage: dt_validation_required\n"
    )
    assert (root / "campaign.json").read_bytes() == raw


def test_3d_status_cli_resolves_codec_before_dispatch(tmp_path):
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "campaign.json").write_bytes(
        (FIXTURES / "mot_3d_v1.json").read_bytes()
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "studies.mot_3d_campaign",
            "status",
            "--campaign",
            str(root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == (
        "Campaign: fixture-3d\nCurrent stage: dt_validation_required\n"
    )


@pytest.mark.parametrize(
    "raw",
    [
        b'{"kind":"mot_2d_s0_campaign","kind":"mot_2d_s0_campaign"}',
        b"{" + b" " * MAX_MANIFEST_BYTES,
    ],
    ids=["duplicate-key", "oversized"],
)
def test_2d_status_uses_the_same_strict_manifest_failures(tmp_path, raw):
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "campaign.json").write_bytes(raw)
    with pytest.raises(ManifestCodecError):
        mot_2d_s0_campaign.status(SimpleNamespace(campaign=str(root)))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"kind":"mot_3d_campaign_v2","kind":"mot_3d_campaign_v2"}',
        b"{" + b" " * MAX_MANIFEST_BYTES,
    ],
    ids=["duplicate-key", "oversized"],
)
def test_3d_status_uses_the_same_strict_manifest_failures(tmp_path, raw):
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "campaign.json").write_bytes(raw)
    with pytest.raises(ManifestCodecError):
        mot_3d_campaign.status(SimpleNamespace(campaign=str(root)))


@pytest.mark.parametrize(
    "operation",
    [
        lambda root: mot_3d_campaign.status(SimpleNamespace(campaign=str(root))),
        lambda root: mot_3d_campaign.advance_campaign(
            SimpleNamespace(campaign=str(root))
        ),
        mot_3d_campaign.submit_discovery,
        mot_3d_campaign.submit_selection_stage,
        mot_3d_campaign.submit_final_validation_inputs,
        mot_3d_campaign.freeze_final_validation_inputs,
    ],
)
@pytest.mark.parametrize(
    "raw",
    [
        b'{"kind":"mot_3d_campaign_v2","kind":"mot_3d_campaign_v2"}',
        b"{" + b" " * MAX_MANIFEST_BYTES,
        b'{"kind":"mot_2d_s0_campaign","stage":"discovery"}',
    ],
    ids=["duplicate-key", "oversized", "wrong-family"],
)
def test_every_public_3d_campaign_reader_uses_the_strict_codec(
    tmp_path, operation, raw
):
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "campaign.json").write_bytes(raw)

    with pytest.raises(ManifestCodecError):
        operation(root)


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
