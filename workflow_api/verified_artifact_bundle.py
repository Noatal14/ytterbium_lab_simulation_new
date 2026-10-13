"""Deterministic bounded bundles for verified workflow artifacts."""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Mapping


MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_REVIEWED_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_REVIEWED_TOTAL_BYTES = 128 * 1024 * 1024
MAX_CHUNK_BYTES = 4 * 1024 * 1024
MAX_CHUNKS = 16
HEX40 = re.compile(r"^[0-9a-f]{40}$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ArtifactBundleError(ValueError):
    pass


def _total_bound(value: object) -> int:
    if type(value) is not int or value not in {
        MAX_TOTAL_BYTES,
        MAX_REVIEWED_TOTAL_BYTES,
    }:
        raise ArtifactBundleError("invalid artifact bundle bound")
    return value


def _file_bound(value: object) -> int:
    if type(value) is not int or value not in {
        MAX_FILE_BYTES,
        MAX_REVIEWED_FILE_BYTES,
    }:
        raise ArtifactBundleError("invalid artifact file bound")
    return value


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_path(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 512:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and "//" not in value
        and not value.endswith("/")
        and bool(path.parts)
        and all(
            part not in {"", ".", ".."} and NAME.fullmatch(part) for part in path.parts
        )
    )


def _strict_json(raw: bytes) -> object:
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    return json.loads(
        raw.decode("utf-8", "strict"),
        object_pairs_hook=pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
    )


@dataclass(frozen=True)
class BuiltArtifactBundle:
    manifest: Mapping[str, object]
    packed: bytes
    chunks: tuple[bytes, ...]


def build_artifact_bundle(
    files: Mapping[str, bytes],
    *,
    campaign: str,
    commit: str,
    from_stage: str,
    to_stage: str,
    expected_paths: frozenset[str],
    max_total_bytes: int = MAX_TOTAL_BYTES,
    max_file_bytes: int = MAX_FILE_BYTES,
) -> BuiltArtifactBundle:
    max_total_bytes = _total_bound(max_total_bytes)
    max_file_bytes = _file_bound(max_file_bytes)
    if (
        not isinstance(campaign, str)
        or NAME.fullmatch(campaign) is None
        or not isinstance(commit, str)
        or HEX40.fullmatch(commit) is None
        or not isinstance(from_stage, str)
        or NAME.fullmatch(from_stage) is None
        or not isinstance(to_stage, str)
        or NAME.fullmatch(to_stage) is None
        or not expected_paths
        or any(not _safe_path(path) for path in expected_paths)
        or set(files) != expected_paths
    ):
        raise ArtifactBundleError("artifact registry mismatch")
    total = 0
    rows = []
    for path in sorted(expected_paths):
        data = files[path]
        if not isinstance(data, bytes) or not 0 < len(data) <= max_file_bytes:
            raise ArtifactBundleError("artifact exceeds per-file bound")
        total += len(data)
        if total > max_total_bytes:
            raise ArtifactBundleError("artifact bundle exceeds total bound")
        rows.append(
            {
                "path": path,
                "size": len(data),
                "sha256": sha256(data),
                "content": base64.b64encode(data).decode("ascii"),
            }
        )
    payload = {
        "version": 1,
        "campaign": campaign,
        "commit": commit,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "files": rows,
        "uncompressed_bytes": total,
    }
    packed = gzip.compress(canonical_json(payload), compresslevel=9, mtime=0)
    chunks = tuple(
        packed[index : index + MAX_CHUNK_BYTES]
        for index in range(0, len(packed), MAX_CHUNK_BYTES)
    )
    if not chunks or len(chunks) > max_total_bytes // MAX_CHUNK_BYTES:
        raise ArtifactBundleError("artifact bundle exceeds chunk bound")
    manifest = {
        "version": 1,
        "file_count": len(rows),
        "uncompressed_bytes": total,
        "bundle_sha256": sha256(packed),
        "chunks": [
            {"index": index, "size": len(chunk), "sha256": sha256(chunk)}
            for index, chunk in enumerate(chunks)
        ],
    }
    return BuiltArtifactBundle(manifest, packed, chunks)


def unpack_artifact_bundle(
    packed: bytes,
    manifest: Mapping[str, object],
    *,
    campaign: str,
    commit: str,
    from_stage: str,
    to_stage: str,
    expected_paths: frozenset[str],
    max_total_bytes: int = MAX_TOTAL_BYTES,
    max_file_bytes: int = MAX_FILE_BYTES,
) -> dict[str, bytes]:
    max_total_bytes = _total_bound(max_total_bytes)
    max_file_bytes = _file_bound(max_file_bytes)
    if (
        not isinstance(packed, bytes)
        or not packed
        or len(packed) > max_total_bytes
        or not isinstance(campaign, str)
        or NAME.fullmatch(campaign) is None
        or not isinstance(commit, str)
        or HEX40.fullmatch(commit) is None
        or not isinstance(from_stage, str)
        or NAME.fullmatch(from_stage) is None
        or not isinstance(to_stage, str)
        or NAME.fullmatch(to_stage) is None
        or not expected_paths
        or any(not _safe_path(path) for path in expected_paths)
    ):
        raise ArtifactBundleError("invalid bundle arguments")
    if not isinstance(manifest, Mapping):
        raise ArtifactBundleError("invalid bundle manifest")
    uncompressed_bytes = manifest.get("uncompressed_bytes")
    chunk_rows = manifest.get("chunks")
    if (
        set(manifest)
        != {"version", "file_count", "uncompressed_bytes", "bundle_sha256", "chunks"}
        or type(manifest.get("version")) is not int
        or manifest.get("version") != 1
        or manifest.get("file_count") != len(expected_paths)
        or isinstance(manifest.get("file_count"), bool)
        or not isinstance(uncompressed_bytes, int)
        or isinstance(uncompressed_bytes, bool)
        or not len(expected_paths) <= uncompressed_bytes <= max_total_bytes
        or manifest.get("bundle_sha256") != sha256(packed)
        or not isinstance(chunk_rows, list)
        or not 1 <= len(chunk_rows) <= max_total_bytes // MAX_CHUNK_BYTES
    ):
        raise ArtifactBundleError("invalid bundle manifest")
    chunks = tuple(
        packed[index : index + MAX_CHUNK_BYTES]
        for index in range(0, len(packed), MAX_CHUNK_BYTES)
    )
    expected_chunks = [
        {"index": index, "size": len(chunk), "sha256": sha256(chunk)}
        for index, chunk in enumerate(chunks)
    ]
    if manifest["chunks"] != expected_chunks:
        raise ArtifactBundleError("invalid bundle chunks")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(packed), mode="rb") as stream:
            raw = stream.read(2 * max_total_bytes + 1)
        if len(raw) > 2 * max_total_bytes:
            raise ArtifactBundleError("expanded bundle exceeds bound")
        payload = _strict_json(raw)
    except ArtifactBundleError:
        raise
    except Exception as exc:
        raise ArtifactBundleError("invalid compressed bundle") from exc
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "version",
            "campaign",
            "commit",
            "from_stage",
            "to_stage",
            "files",
            "uncompressed_bytes",
        }
        or payload.get("version") != 1
        or payload.get("campaign") != campaign
        or payload.get("commit") != commit
        or payload.get("from_stage") != from_stage
        or payload.get("to_stage") != to_stage
        or payload.get("uncompressed_bytes") != manifest.get("uncompressed_bytes")
        or not isinstance(payload.get("files"), list)
        or len(payload["files"]) != len(expected_paths)
    ):
        raise ArtifactBundleError("invalid bundle payload")
    result = {}
    total = 0
    for row in payload["files"]:
        if not isinstance(row, dict) or set(row) != {
            "path",
            "size",
            "sha256",
            "content",
        }:
            raise ArtifactBundleError("invalid bundle entry")
        path = row["path"]
        if path in result or path not in expected_paths or not _safe_path(path):
            raise ArtifactBundleError("invalid bundle path")
        size = row["size"]
        digest = row["sha256"]
        content = row["content"]
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or not 0 < size <= max_file_bytes
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(content, str)
            or len(content) > 4 * ((max_file_bytes + 2) // 3)
        ):
            raise ArtifactBundleError("invalid bundle entry")
        try:
            data = base64.b64decode(content, validate=True)
        except Exception as exc:
            raise ArtifactBundleError("invalid bundle content") from exc
        if len(data) != size or sha256(data) != digest:
            raise ArtifactBundleError("invalid bundle entry digest")
        result[path] = data
        total += len(data)
    if set(result) != expected_paths or total != manifest.get("uncompressed_bytes"):
        raise ArtifactBundleError("incomplete bundle")
    return result
