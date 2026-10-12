"""Pinned remote Discovery validation, preliminary-check preparation and retrieval."""

from __future__ import annotations

import base64, fcntl, gzip, hashlib, json, os, re, stat, subprocess, sys, time
from pathlib import Path, PurePosixPath

HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
JOB = re.compile(r"^\d+\[\]\.zeus-master$")
MAX_FILES = 961
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_CHUNK_BYTES = 4 * 1024 * 1024
MAX_CHUNKS = 16
FAMILIES = ("angled_donut", "single_pass")
TARGETS = {"angled_donut": (117, 117, 116), "single_pass": (200, 200, 200)}


def fail(code, status=20):
    print(json.dumps({"error": code}))
    raise SystemExit(status)


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def timestamp(value):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 253402300799
    )


def no_links(root, path):
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if current.exists() and current.is_symlink():
            fail("transition_conflict")


def bounded(path, limit=MAX_FILE_BYTES):
    row = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(row.st_mode)
        or not 0 <= row.st_size <= limit
    ):
        fail("transition_conflict")
    data = path.read_bytes()
    after = path.lstat()
    identity = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if len(data) != row.st_size or identity(after) != identity(row):
        fail("transition_conflict")
    return data


def read_json(path, keys=None, limit=8 * 1024 * 1024):
    try:
        data = bounded(path, limit)
        value = json.loads(data.decode("utf-8", "strict"))
    except SystemExit:
        raise
    except Exception:
        fail("transition_conflict")
    if not isinstance(value, dict) or keys is not None and set(value) != set(keys):
        fail("transition_conflict")
    return value


def publish(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    no_links(path.parents[len(path.parts) - len(path.parts)], path) if False else None
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    fd = os.open(
        tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(tmp, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                fail("transition_conflict")
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    directory = os.open(path.parent, os.O_RDONLY)
    os.fsync(directory)
    os.close(directory)


def atomic_json(path, value):
    publish(path, canonical(value) + b"\n")


def expected_paths():
    paths = []
    for family in FAMILIES:
        for worker, target in enumerate(TARGETS[family]):
            paths += [
                f"discovery/{family}/worker_{worker}/trials/trial_{number:04d}.json"
                for number in range(target)
            ]
        paths += [
            f"discovery/{family}/merged/merged_summary.json",
            f"discovery/{family}/merged/ranked_trials.csv",
            f"selection/discovery/{family}.json",
            f"jobs/preliminary_check/{family}_array.pbs",
            f"jobs/preliminary_check/{family}_merge.pbs",
        ]
    paths.append("campaign.json")
    assert len(paths) == MAX_FILES
    return tuple(sorted(paths))


def discovery_receipts(campaign, payload):
    bootstrap = read_json(campaign / ".mot_ui/transitions/discovery_bootstrap.json")
    submission = read_json(campaign / ".mot_ui/submissions/discovery.json")
    if (
        digest(canonical(bootstrap)) != payload["bootstrap_digest"]
        or bootstrap.get("bootstrap_key") != payload["bootstrap_key"]
        or bootstrap.get("commit") != payload["commit"]
    ):
        fail("transition_conflict")
    if (
        submission.get("status") != "submitted"
        or submission.get("submission_key") != payload["submission_key"]
        or submission.get("commit") != payload["commit"]
    ):
        fail("transition_conflict")
    chain = submission.get("chain")
    lengths = {"angled_donut": 2, "single_pass": 3}
    if (
        not isinstance(chain, dict)
        or set(chain) != set(FAMILIES)
        or any(
            not isinstance(chain[x], list)
            or len(chain[x]) != lengths[x]
            or any(not JOB.fullmatch(str(j)) for j in chain[x])
            for x in FAMILIES
        )
    ):
        fail("transition_conflict")
    for family in FAMILIES:
        for index, job in enumerate(chain[family], 1):
            step = read_json(
                campaign / f".mot_ui/submissions/discovery_{family}_{index}.json"
            )
            job_name = f"jobs/{family}/round_{index:02d}.pbs"
            if (
                set(step)
                != {
                    "status",
                    "nonce",
                    "family",
                    "round",
                    "pbs_sha256",
                    "depends_on",
                    "job_id",
                    "completed_unix_s",
                }
                or step.get("status") != "submitted"
                or step.get("nonce") != submission.get("nonce")
                or step.get("family") != family
                or step.get("round") != index
                or step.get("job_id") != job
                or step.get("pbs_sha256") != bootstrap.get("files", {}).get(job_name)
                or step.get("depends_on")
                != (chain[family][index - 2] if index > 1 else None)
                or not timestamp(step.get("completed_unix_s"))
            ):
                fail("transition_conflict")
    return bootstrap, submission, chain


def scheduler_lifecycle(chain):
    from workflow_api.zeus_discovery_submission_remote import (
        run_captured,
        scheduler_state,
    )

    states = []
    for family in FAMILIES:
        for job in chain[family]:
            try:
                code, out, err = run_captured(
                    ["/usr/local/bin/qstat", "-x", "-t", "-f", job]
                )
            except Exception:
                states.append("status_unknown")
            else:
                states.append(
                    "status_unknown" if code or err else scheduler_state(out, job)
                )
    for value in ("completed_failed", "held", "status_unknown", "running", "queued"):
        if value in states:
            return value
    return "completed_success_unvalidated"


def validate_outputs(campaign, manifest):
    from studies.mot_3d_campaign import validate_discovery_complete

    try:
        for family in FAMILIES:
            validate_discovery_complete(campaign, manifest, family)
    except FileNotFoundError:
        return "completed_success_unvalidated"
    except Exception:
        return "outputs_invalid"
    return "ready_to_advance"


def build_bundle(campaign, commit):
    files = []
    total = 0
    for name in expected_paths():
        path = campaign.joinpath(*PurePosixPath(name).parts)
        no_links(campaign, path)
        data = bounded(path)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            fail("transition_bundle_too_large")
        files.append(
            {
                "path": name,
                "size": len(data),
                "sha256": digest(data),
                "content": base64.b64encode(data).decode("ascii"),
            }
        )
    payload = {
        "version": 1,
        "campaign": campaign.name,
        "commit": commit,
        "from_stage": "discovery",
        "to_stage": "preliminary_check",
        "files": files,
        "uncompressed_bytes": total,
    }
    raw = canonical(payload)
    packed = gzip.compress(raw, compresslevel=9, mtime=0)
    chunks = [
        packed[i : i + MAX_CHUNK_BYTES] for i in range(0, len(packed), MAX_CHUNK_BYTES)
    ]
    if not chunks or len(chunks) > MAX_CHUNKS:
        fail("transition_bundle_too_large")
    manifest = {
        "version": 1,
        "file_count": len(files),
        "uncompressed_bytes": total,
        "bundle_sha256": digest(packed),
        "chunks": [
            {"index": i, "size": len(chunk), "sha256": digest(chunk)}
            for i, chunk in enumerate(chunks)
        ],
    }
    return manifest, packed, chunks


def response(lifecycle, branch, chain, receipt=None, bundle=None, chunk=None):
    print(
        json.dumps(
            {
                "lifecycle": lifecycle,
                "branch": branch,
                "chain": chain,
                "receipt": receipt,
                "bundle": bundle,
                "chunk": chunk,
            },
            separators=(",", ":"),
        )
    )


def transition_paths(campaign, operation):
    transitions = campaign / ".mot_ui/transitions"
    if transitions.exists():
        no_links(campaign, transitions)
        if not transitions.is_dir():
            fail("transition_conflict")
    elif operation == "prepare":
        transitions.mkdir(parents=True, exist_ok=False)
        directory = os.open(transitions.parent, os.O_RDONLY)
        os.fsync(directory)
        os.close(directory)
    return (
        transitions,
        transitions / "preliminary_check.json",
        transitions / "preliminary_check.pending.json",
        transitions / "preliminary_check.bundle.gz",
    )


def main():
    if len(sys.argv) != 5 or sys.argv[1] not in {
        "inspect",
        "status",
        "prepare",
        "retrieve",
    }:
        fail("invalid_request")
    operation, username, requested, encoded = sys.argv[1:]
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded))
        root = Path(requested).resolve(strict=True)
        relative = PurePosixPath(payload["campaign"])
    except Exception:
        fail("invalid_request")
    base = {"campaign", "commit", "bootstrap_digest", "bootstrap_key", "submission_key"}
    expected = base | (
        {"nonce"}
        if operation == "prepare"
        else (
            {"transition_key", "bundle_sha256", "chunk_index"}
            if operation == "retrieve"
            else set()
        )
    )
    if (
        not isinstance(payload, dict)
        or set(payload) != expected
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,31}", username)
        or root != Path(f"/home/{username}/ytterbium_lab_simulation_new")
        or relative.is_absolute()
        or relative.parts[:3] != ("data", "optimization", "mot_3d")
        or len(relative.parts) != 4
        or any(x in {"", ".", ".."} for x in relative.parts)
        or not HEX40.fullmatch(str(payload["commit"]))
        or any(
            not HEX64.fullmatch(str(payload[k]))
            for k in ("bootstrap_digest", "bootstrap_key", "submission_key")
        )
    ):
        fail("invalid_request")
    campaign = root.joinpath(*relative.parts)
    no_links(root, campaign)
    try:
        head = subprocess.run(
            ["/usr/bin/git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["/usr/bin/git", "branch", "--show-current"],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except Exception:
        fail("remote_checkout_mismatch")
    if (
        head != payload["commit"]
        or not branch
        or len(branch) > 256
        or not branch.isprintable()
    ):
        fail("remote_checkout_mismatch")
    manifest = read_json(campaign / "campaign.json")
    _, submission, chain = discovery_receipts(campaign, payload)
    transitions, final, pending, bundle_path = transition_paths(campaign, operation)
    transition_key = digest(
        canonical(
            {
                "campaign": relative.as_posix(),
                "commit": payload["commit"],
                "bootstrap_digest": payload["bootstrap_digest"],
                "submission_key": payload["submission_key"],
                "chain": chain,
            }
        )
    )
    if final.exists():
        receipt = read_json(final)
        if (
            receipt.get("transition_key") != transition_key
            or receipt.get("commit") != payload["commit"]
            or receipt.get("status") != "preliminary_check_prepared"
        ):
            fail("transition_outcome_unknown")
        bundle = receipt.get("bundle")
        if operation == "retrieve":
            if (
                payload["transition_key"] != transition_key
                or payload["bundle_sha256"] != bundle.get("bundle_sha256")
                or not isinstance(payload["chunk_index"], int)
            ):
                fail("invalid_request")
            packed = bounded(bundle_path, MAX_TOTAL_BYTES)
            chunks = [
                packed[i : i + MAX_CHUNK_BYTES]
                for i in range(0, len(packed), MAX_CHUNK_BYTES)
            ]
            index = payload["chunk_index"]
            if not 0 <= index < len(chunks):
                fail("invalid_request")
            chunk = {
                "index": index,
                "sha256": digest(chunks[index]),
                "content": base64.b64encode(chunks[index]).decode("ascii"),
            }
            response(
                "preliminary_check_prepared", branch, chain, receipt, bundle, chunk
            )
            return
        response("preliminary_check_prepared", branch, chain, receipt, bundle)
        return
    if operation == "retrieve":
        fail("transition_not_prepared")
    lifecycle = scheduler_lifecycle(chain)
    recovering = pending.exists() and manifest.get("stage") == "preliminary_check"
    if recovering:
        lifecycle = "ready_to_advance" if operation == "prepare" else "outcome_unknown"
    elif lifecycle == "completed_success_unvalidated":
        lifecycle = validate_outputs(campaign, manifest)
    if operation in {"inspect", "status"} or lifecycle != "ready_to_advance":
        response(lifecycle, branch, chain)
        return
    if not HEX32.fullmatch(str(payload.get("nonce", ""))):
        fail("invalid_request")
    lock_fd = os.open(
        transitions / "preliminary_check.lock",
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        fail("transition_busy")
    try:
        if final.exists():
            fail("transition_outcome_unknown")
        if pending.exists():
            old = read_json(pending)
            if (
                old.get("nonce") != payload["nonce"]
                or old.get("transition_key") != transition_key
            ):
                fail("transition_outcome_unknown")
        else:
            atomic_json(
                pending,
                {
                    "status": "preliminary_check_pending",
                    "nonce": payload["nonce"],
                    "transition_key": transition_key,
                    "created_unix_s": int(time.time()),
                },
            )
        manifest = read_json(campaign / "campaign.json")
        if manifest.get("stage") == "discovery":
            if (
                scheduler_lifecycle(chain) != "completed_success_unvalidated"
                or validate_outputs(campaign, manifest) != "ready_to_advance"
            ):
                fail("transition_conflict")
            from argparse import Namespace
            from studies.mot_3d_campaign import advance_campaign

            advance_campaign(Namespace(campaign=str(campaign)))
        manifest = read_json(campaign / "campaign.json")
        if manifest.get("stage") != "preliminary_check":
            fail("transition_outcome_unknown")
        bundle, packed, _ = build_bundle(campaign, payload["commit"])
        publish(bundle_path, packed)
        receipt = {
            "status": "preliminary_check_prepared",
            "nonce": payload["nonce"],
            "transition_key": transition_key,
            "commit": payload["commit"],
            "bootstrap_digest": payload["bootstrap_digest"],
            "submission_key": payload["submission_key"],
            "chain": chain,
            "bundle": bundle,
            "completed_unix_s": int(time.time()),
        }
        atomic_json(final, receipt)
        pending.unlink()
        directory = os.open(transitions, os.O_RDONLY)
        os.fsync(directory)
        os.close(directory)
    except SystemExit:
        raise
    except Exception:
        fail("transition_outcome_unknown")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    response("preliminary_check_prepared", branch, chain, receipt, bundle)


if __name__ == "__main__":
    main()
