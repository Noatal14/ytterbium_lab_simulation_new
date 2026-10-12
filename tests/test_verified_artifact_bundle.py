import gzip
import json

import pytest

from workflow_api.verified_artifact_bundle import (
    ArtifactBundleError,
    build_artifact_bundle,
    unpack_artifact_bundle,
)


def test_bundle_is_deterministic_exact_and_self_verifying():
    files = {"a.json": b"{}\n", "nested/b.bin": b"abc"}
    paths = frozenset(files)
    arguments = dict(
        campaign="campaign",
        commit="a" * 40,
        from_stage="preliminary_check",
        to_stage="refinement",
        expected_paths=paths,
    )
    first = build_artifact_bundle(files, **arguments)
    second = build_artifact_bundle(files, **arguments)
    assert first == second
    assert unpack_artifact_bundle(first.packed, first.manifest, **arguments) == files


def test_bundle_rejects_registry_and_content_mutations():
    files = {"a.json": b"{}\n"}
    arguments = dict(
        campaign="campaign",
        commit="a" * 40,
        from_stage="preliminary_check",
        to_stage="refinement",
        expected_paths=frozenset(files),
    )
    bundle = build_artifact_bundle(files, **arguments)
    with pytest.raises(ArtifactBundleError):
        build_artifact_bundle({**files, "extra": b"x"}, **arguments)
    damaged = bytearray(bundle.packed)
    damaged[-1] ^= 1
    with pytest.raises(ArtifactBundleError):
        unpack_artifact_bundle(bytes(damaged), bundle.manifest, **arguments)


@pytest.mark.parametrize(
    "paths",
    [frozenset(), frozenset({"../escape"}), frozenset({"/absolute"}), frozenset({"a//b"})],
)
def test_bundle_rejects_unsafe_closed_registries(paths):
    with pytest.raises(ArtifactBundleError):
        build_artifact_bundle(
            {path: b"x" for path in paths},
            campaign="campaign",
            commit="a" * 40,
            from_stage="preliminary_check",
            to_stage="refinement",
            expected_paths=paths,
        )


def test_unpack_rejects_manifest_schema_boolean_and_reordered_chunks():
    files = {"a": b"x" * (5 * 1024 * 1024)}
    arguments = dict(
        campaign="campaign",
        commit="a" * 40,
        from_stage="preliminary_check",
        to_stage="refinement",
        expected_paths=frozenset(files),
    )
    with pytest.raises(ArtifactBundleError):
        build_artifact_bundle(files, **arguments)
    bundle = build_artifact_bundle({"a": b"x"}, **{**arguments, "expected_paths": frozenset({"a"})})
    bad = dict(bundle.manifest, version=True)
    with pytest.raises(ArtifactBundleError):
        unpack_artifact_bundle(bundle.packed, bad, **{**arguments, "expected_paths": frozenset({"a"})})
    for invalid in (None, [], "manifest"):
        with pytest.raises(ArtifactBundleError):
            unpack_artifact_bundle(
                bundle.packed,
                invalid,
                **{**arguments, "expected_paths": frozenset({"a"})},
            )
    wrong_chunk = dict(bundle.manifest)
    wrong_chunk["chunks"] = [
        {"index": 1, "size": len(bundle.packed), "sha256": bundle.manifest["bundle_sha256"]}
    ]
    with pytest.raises(ArtifactBundleError):
        unpack_artifact_bundle(
            bundle.packed,
            wrong_chunk,
            **{**arguments, "expected_paths": frozenset({"a"})},
        )


@pytest.mark.parametrize("field,value", [("commit", None), ("from_stage", 1), ("to_stage", False)])
def test_build_rejects_wrong_scalar_types(field, value):
    arguments = {
        "campaign": "campaign",
        "commit": "a" * 40,
        "from_stage": "preliminary_check",
        "to_stage": "refinement",
        "expected_paths": frozenset({"a"}),
    }
    arguments[field] = value
    with pytest.raises(ArtifactBundleError):
        build_artifact_bundle({"a": b"x"}, **arguments)


def test_unpack_rejects_duplicate_json_keys_and_nonfinite_values():
    arguments = dict(
        campaign="campaign",
        commit="a" * 40,
        from_stage="preliminary_check",
        to_stage="refinement",
        expected_paths=frozenset({"a"}),
    )
    for raw in (
        b'{"version":1,"version":1}',
        json.dumps({"version": float("nan")}).encode(),
    ):
        packed = gzip.compress(raw, mtime=0)
        manifest = {
            "version": 1,
            "file_count": 1,
            "uncompressed_bytes": 1,
            "bundle_sha256": __import__("hashlib").sha256(packed).hexdigest(),
            "chunks": [
                {
                    "index": 0,
                    "size": len(packed),
                    "sha256": __import__("hashlib").sha256(packed).hexdigest(),
                }
            ],
        }
        with pytest.raises(ArtifactBundleError):
            unpack_artifact_bundle(packed, manifest, **arguments)
