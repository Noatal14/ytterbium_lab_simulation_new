"""Pinned receiver for verified Preliminary Check -> Refinement transition.

Read operations never create state. PREPARE publishes generated artifacts with
no-replace semantics, commits campaign.json last with compare-and-swap, and
records success only after re-verifying the exact 160-file transfer registry.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import time
from pathlib import Path, PurePosixPath

from workflow_api.mot_3d_preliminary_results import (
    FAMILIES,
    expected_paths,
    expected_preliminary_particle_selection,
    validate_preliminary_result_bytes,
)
from workflow_api.mot_3d_preliminary_submission_remote import (
    ARRAY,
    DIR_FLAGS,
    SCALAR,
    bounded_at,
    canonical,
    digest,
    json_bytes,
    open_dir_at,
    read_relative_at,
    regular_exists_at,
    run,
    scheduler,
    stamp,
    strict_json_at,
    unlink_at,
)
from workflow_api.verified_artifact_bundle import (
    MAX_CHUNK_BYTES,
    MAX_TOTAL_BYTES,
    build_artifact_bundle,
)

HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_FILE = 2 * 1024 * 1024


def render_refinement_transition(*args, **kwargs):
    """Load the study renderer only inside the pinned receiver process."""

    from studies.mot_3d_campaign import render_refinement_transition as render

    return render(*args, **kwargs)


GENERATED_PATHS = frozenset(
    {
        "campaign.json",
        *(f"selection/refinement/{family}.json" for family in FAMILIES),
        *(
            f"jobs/refinement/{family}_{kind}.pbs"
            for family in FAMILIES
            for kind in ("array", "merge")
        ),
    }
)
SOURCE_IDENTITY_PATHS = frozenset(
    {
        "campaign.json",
        *(f"selection/discovery/{family}.json" for family in FAMILIES),
        *(
            f"jobs/preliminary_check/{family}_{kind}.pbs"
            for family in FAMILIES
            for kind in ("array", "merge")
        ),
    }
)
CODE_PATHS = frozenset(
    {
        "config.py",
        "studies/mot_3d_campaign.py",
        "studies/mot_3d/integrity.py",
        "studies/mot_3d/preliminary/merge.py",
        "studies/mot_3d/refinement/select.py",
        "workflow_api/mot_3d_preliminary_results.py",
        "workflow_api/mot_3d_stage_topology.py",
        "workflow_api/verified_artifact_bundle.py",
        "workflow_api/mot_3d_preliminary_transition_remote.py",
        "lab_setup/specifications/mot_3d_timestep_policy_v1.json",
    }
)
FINAL_KEYS = {
    "version",
    "status",
    "nonce",
    "transition_key",
    "commit",
    "submission_key",
    "identity_sha256",
    "old_campaign_sha256",
    "new_campaign_sha256",
    "evidence_sha256",
    "files",
    "bundle",
    "completed_unix_s",
}
PENDING_KEYS = (FINAL_KEYS - {"completed_unix_s"}) | {"created_unix_s"}


def fail(code: str, status: int = 20) -> None:
    print(json.dumps({"error": code}))
    raise SystemExit(status)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _exact_bundle(value: object, *, file_count: int) -> bool:
    if (
        not isinstance(value, dict)
        or set(value)
        != {"version", "file_count", "uncompressed_bytes", "bundle_sha256", "chunks"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or type(value["file_count"]) is not int
        or value["file_count"] != file_count
        or type(value["uncompressed_bytes"]) is not int
        or not file_count <= value["uncompressed_bytes"] <= MAX_TOTAL_BYTES
        or not isinstance(value["bundle_sha256"], str)
        or HEX64.fullmatch(value["bundle_sha256"]) is None
        or not isinstance(value["chunks"], list)
        or not 1 <= len(value["chunks"]) <= 16
    ):
        return False
    return all(
        isinstance(row, dict)
        and set(row) == {"index", "size", "sha256"}
        and type(row["index"]) is int
        and row["index"] == index
        and type(row["size"]) is int
        and 0 < row["size"] <= MAX_CHUNK_BYTES
        and isinstance(row["sha256"], str)
        and HEX64.fullmatch(row["sha256"]) is not None
        for index, row in enumerate(value["chunks"])
    )


def _safe_relative(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 512:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and bool(path.parts)
        and "//" not in value
        and not value.endswith("/")
        and all(
            part not in {"", ".", ".."} and SAFE_NAME.fullmatch(part)
            for part in path.parts
        )
    )


def _publish_bytes(parent: int, name: str, raw: bytes, *, identical_ok: bool) -> None:
    if not SAFE_NAME.fullmatch(name) or not isinstance(raw, bytes) or not raw:
        fail("preliminary_transition_outcome_unknown")
    if regular_exists_at(parent, name):
        if (
            identical_ok
            and bounded_at(parent, name, max(MAX_TOTAL_BYTES, len(raw))) == raw
        ):
            return
        fail("preliminary_transition_conflict")
    temporary = f".{name}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
    fd = -1
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent,
        )
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(
            temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False
        )
        os.fsync(parent)
    except FileExistsError:
        fail("preliminary_transition_conflict")
    except OSError:
        fail("preliminary_transition_outcome_unknown")
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass


def _publish_relative(campaign_fd: int, relative: str, raw: bytes) -> None:
    parts = PurePosixPath(relative).parts
    descriptor = campaign_fd
    opened = []
    try:
        for part in parts[:-1]:
            descriptor = open_dir_at(descriptor, part, create=True)
            opened.append(descriptor)
        _publish_bytes(descriptor, parts[-1], raw, identical_ok=True)
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _replace_campaign(campaign_fd: int, old: bytes, new: bytes) -> None:
    current = bounded_at(campaign_fd, "campaign.json", MAX_FILE)
    if current == new:
        return
    if current != old:
        fail("preliminary_transition_conflict")
    before = os.stat("campaign.json", dir_fd=campaign_fd, follow_symlinks=False)
    temporary = f".campaign.json.{os.getpid()}.{os.urandom(4).hex()}.tmp"
    fd = -1
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=campaign_fd,
        )
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write(new)
            stream.flush()
            os.fsync(stream.fileno())
        if bounded_at(campaign_fd, "campaign.json", MAX_FILE) != old:
            fail("preliminary_transition_conflict")
        now = os.stat("campaign.json", dir_fd=campaign_fd, follow_symlinks=False)
        if (now.st_dev, now.st_ino, now.st_ctime_ns) != (
            before.st_dev,
            before.st_ino,
            before.st_ctime_ns,
        ):
            fail("preliminary_transition_conflict")
        os.replace(
            temporary, "campaign.json", src_dir_fd=campaign_fd, dst_dir_fd=campaign_fd
        )
        os.fsync(campaign_fd)
    except OSError:
        fail("preliminary_transition_outcome_unknown")
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=campaign_fd)
        except FileNotFoundError:
            pass


def _open_submissions(campaign_fd: int):
    mot_ui = open_dir_at(campaign_fd, ".mot_ui")
    try:
        submissions = open_dir_at(mot_ui, "submissions")
    finally:
        os.close(mot_ui)
    return submissions


def _exact_stage2(campaign_fd: int, submission_key: str, commit: str):
    submissions_fd = _open_submissions(campaign_fd)
    try:
        final = strict_json_at(
            submissions_fd,
            "preliminary_check.json",
            keys={
                "version",
                "status",
                "submission_key",
                "nonce",
                "commit",
                "jobs",
                "created_unix_s",
                "submitted_unix_s",
            },
        )
        if (
            type(final["version"]) is not int
            or final["version"] != 1
            or final["status"] != "submitted"
            or final["submission_key"] != submission_key
            or final["commit"] != commit
            or not isinstance(final["nonce"], str)
            or HEX32.fullmatch(final["nonce"]) is None
            or not stamp(final["created_unix_s"])
            or not stamp(final["submitted_unix_s"])
            or final["submitted_unix_s"] < final["created_unix_s"]
            or not isinstance(final["jobs"], dict)
            or set(final["jobs"]) != set(FAMILIES)
        ):
            fail("preliminary_transition_conflict")
        jobs = final["jobs"]
        seen = set()
        previous_completed = final["created_unix_s"]
        for family in FAMILIES:
            row = jobs.get(family)
            if (
                not isinstance(row, dict)
                or set(row) != {"array", "merge"}
                or not isinstance(row["array"], str)
                or not isinstance(row["merge"], str)
                or ARRAY.fullmatch(row["array"]) is None
                or SCALAR.fullmatch(row["merge"]) is None
            ):
                fail("preliminary_transition_conflict")
            numeric = {row["array"].split("[", 1)[0], row["merge"].split(".", 1)[0]}
            if seen & numeric:
                fail("preliminary_transition_conflict")
            seen |= numeric
            for kind in ("array", "merge"):
                step = strict_json_at(
                    submissions_fd,
                    f"preliminary_check_{family}_{kind}.json",
                    keys={
                        "status",
                        "submission_key",
                        "nonce",
                        "commit",
                        "family",
                        "kind",
                        "pbs_sha256",
                        "depends_on",
                        "job_id",
                        "created_unix_s",
                        "completed_unix_s",
                    },
                )
                dependency = row["array"] if kind == "merge" else None
                pbs = read_relative_at(
                    campaign_fd, f"jobs/preliminary_check/{family}_{kind}.pbs", MAX_FILE
                )
                if (
                    step["status"] != "submitted"
                    or step["submission_key"] != submission_key
                    or step["nonce"] != final["nonce"]
                    or step["commit"] != commit
                    or step["family"] != family
                    or step["kind"] != kind
                    or step["depends_on"] != dependency
                    or step["job_id"] != row[kind]
                    or step["pbs_sha256"] != _sha(pbs)
                    or not stamp(step["created_unix_s"])
                    or not stamp(step["completed_unix_s"])
                    or not final["created_unix_s"]
                    <= step["created_unix_s"]
                    <= step["completed_unix_s"]
                    <= final["submitted_unix_s"]
                    or step["created_unix_s"] < previous_completed
                ):
                    fail("preliminary_transition_conflict")
                previous_completed = step["completed_unix_s"]
        compatibility = json_bytes(
            read_relative_at(
                campaign_fd, "preliminary_check_submission.json", MAX_FILE
            ),
            keys={
                "kind",
                "stage",
                "status",
                "dependency",
                "submission_key",
                "nonce",
                "commit",
                "created_unix_s",
                "submitted_unix_s",
                "families",
            },
            error="preliminary_transition_conflict",
        )
        if compatibility != {
            "kind": "mot_3d_selection_stage_submission",
            "stage": "preliminary_check",
            "status": "submitted",
            "dependency": "afterok",
            "submission_key": submission_key,
            "nonce": final["nonce"],
            "commit": commit,
            "created_unix_s": final["created_unix_s"],
            "submitted_unix_s": final["submitted_unix_s"],
            "families": {
                family: {
                    "array_job_id": jobs[family]["array"],
                    "merge_job_id": jobs[family]["merge"],
                }
                for family in FAMILIES
            },
        }:
            fail("preliminary_transition_conflict")
        return final, jobs
    finally:
        os.close(submissions_fd)


def _scheduler(jobs):
    states = []
    arrays = merges = 0
    for family in FAMILIES:
        state, count = scheduler(jobs[family]["array"], "array")
        states.append(state)
        arrays += count
        state, count = scheduler(jobs[family]["merge"], "merge")
        states.append(state)
        merges += count
    lifecycle = "completed_success_unvalidated"
    for candidate in (
        "completed_failed",
        "held",
        "status_unknown",
        "running",
        "queued",
    ):
        if candidate in states:
            lifecycle = candidate
            break
    return lifecycle, arrays, merges


def _response(
    lifecycle,
    branch,
    jobs,
    arrays,
    merges,
    *,
    validation="not_started",
    reason=None,
    evidence=None,
    receipt=None,
    bundle=None,
    chunk=None,
):
    print(
        json.dumps(
            {
                "lifecycle": lifecycle,
                "branch": branch,
                "jobs": jobs,
                "completed_array_tasks": arrays,
                "completed_merge_jobs": merges,
                "validation": validation,
                "reason_code": reason,
                "evidence_sha256": evidence,
                "receipt": receipt,
                "bundle": bundle,
                "chunk": chunk,
            },
            separators=(",", ":"),
        )
    )


def _identity(
    payload,
    campaign_fd: int,
    root_fd: int,
    *,
    advanced_campaign_sha256: str | None = None,
):
    identity = payload.get("identity")
    if (
        not isinstance(identity, dict)
        or set(identity)
        != {
            "source_files",
            "code_files",
            "stage1_receipt_sha256",
            "stage1_bundle_sha256",
        }
        or not isinstance(identity["source_files"], dict)
        or set(identity["source_files"]) != SOURCE_IDENTITY_PATHS
        or not isinstance(identity["code_files"], dict)
        or set(identity["code_files"]) != CODE_PATHS
        or any(
            HEX64.fullmatch(str(value)) is None
            for value in identity["source_files"].values()
        )
        or any(
            HEX64.fullmatch(str(value)) is None
            for value in identity["code_files"].values()
        )
        or HEX64.fullmatch(str(identity["stage1_receipt_sha256"])) is None
        or HEX64.fullmatch(str(identity["stage1_bundle_sha256"])) is None
    ):
        fail("invalid_request")
    frozen = {}
    for name, expected in identity["source_files"].items():
        raw = read_relative_at(campaign_fd, name, MAX_FILE)
        accepted = {expected}
        if name == "campaign.json" and advanced_campaign_sha256 is not None:
            accepted.add(advanced_campaign_sha256)
        if _sha(raw) not in accepted:
            fail("preliminary_transition_conflict")
        frozen[name] = raw
    for name, expected in identity["code_files"].items():
        if _sha(read_relative_at(root_fd, name, MAX_FILE)) != expected:
            fail("preliminary_transition_conflict")
    transition = read_relative_at(
        campaign_fd, ".mot_ui/transitions/preliminary_check.json", MAX_FILE
    )
    transition_row = json_bytes(
        transition,
        keys={
            "status",
            "nonce",
            "transition_key",
            "commit",
            "bootstrap_digest",
            "submission_key",
            "chain",
            "bundle",
            "completed_unix_s",
        },
        error="preliminary_transition_conflict",
    )
    stage1_bundle = read_relative_at(
        campaign_fd,
        ".mot_ui/transitions/preliminary_check.bundle.gz",
        MAX_TOTAL_BYTES,
    )
    bundle = transition_row["bundle"]
    chunks = [
        stage1_bundle[index : index + MAX_CHUNK_BYTES]
        for index in range(0, len(stage1_bundle), MAX_CHUNK_BYTES)
    ]
    expected_chunks = [
        {"index": index, "size": len(chunk), "sha256": _sha(chunk)}
        for index, chunk in enumerate(chunks)
    ]
    if (
        _sha(transition) != identity["stage1_receipt_sha256"]
        or transition_row["status"] != "preliminary_check_prepared"
        or transition_row["commit"] != payload["commit"]
        or transition_row["submission_key"] != payload["submission_key"]
        or HEX32.fullmatch(str(transition_row["nonce"])) is None
        or HEX64.fullmatch(str(transition_row["transition_key"])) is None
        or HEX64.fullmatch(str(transition_row["bootstrap_digest"])) is None
        or not stamp(transition_row["completed_unix_s"])
        or not isinstance(transition_row["chain"], dict)
        or set(transition_row["chain"]) != set(FAMILIES)
        or any(
            not isinstance(transition_row["chain"][family], list)
            or len(transition_row["chain"][family])
            != (2 if family == "angled_donut" else 3)
            or any(
                ARRAY.fullmatch(str(job)) is None
                for job in transition_row["chain"][family]
            )
            for family in FAMILIES
        )
        or not _exact_bundle(bundle, file_count=961)
        or bundle["bundle_sha256"] != identity["stage1_bundle_sha256"]
        or _sha(stage1_bundle) != identity["stage1_bundle_sha256"]
        or bundle["chunks"] != expected_chunks
    ):
        fail("preliminary_transition_conflict")
    expected_key = digest(
        {
            "campaign": payload["campaign"],
            "commit": payload["commit"],
            "submission_key": payload["submission_key"],
            "identity": identity,
        }
    )
    if expected_key != payload["transition_key"]:
        fail("preliminary_transition_conflict")
    return identity, frozen


def _capture(
    campaign_fd: int,
    project_directory: Path,
    campaign_absolute_path: Path,
    manifest_raw: bytes,
):
    manifest = json_bytes(manifest_raw, error="preliminary_transition_conflict")
    selections = {
        family: read_relative_at(
            campaign_fd, f"selection/discovery/{family}.json", MAX_FILE
        )
        for family in FAMILIES
    }
    parsed = {
        family: json_bytes(raw, error="preliminary_transition_conflict")
        for family, raw in selections.items()
    }
    results = {
        name: read_relative_at(campaign_fd, name, MAX_FILE)
        for name in expected_paths(parsed)
    }
    particle = expected_preliminary_particle_selection(
        manifest, project_directory=str(project_directory)
    )
    validated = validate_preliminary_result_bytes(
        manifest_bytes=manifest_raw,
        selection_bytes=selections,
        result_files=results,
        expected_particle_selection=particle,
        campaign_absolute_path=str(campaign_absolute_path),
        project_directory=str(project_directory),
    )
    return manifest, results, validated


def _verify_success(campaign_fd: int, transitions_fd: int, payload, receipt):
    if (
        set(receipt) != FINAL_KEYS
        or type(receipt["version"]) is not int
        or receipt["version"] != 1
        or receipt["status"] != "refinement_prepared"
        or receipt["transition_key"] != payload["transition_key"]
        or receipt["commit"] != payload["commit"]
        or receipt["submission_key"] != payload["submission_key"]
        or receipt["identity_sha256"] != digest(payload["identity"])
        or any(
            HEX64.fullmatch(str(receipt[key])) is None
            for key in (
                "identity_sha256",
                "old_campaign_sha256",
                "new_campaign_sha256",
                "evidence_sha256",
            )
        )
        or HEX32.fullmatch(str(receipt["nonce"])) is None
        or not stamp(receipt["completed_unix_s"])
        or not isinstance(receipt["files"], dict)
        or len(receipt["files"]) != 160
        or any(
            not _safe_relative(name) or HEX64.fullmatch(str(value)) is None
            for name, value in receipt["files"].items()
        )
        or not _exact_bundle(receipt["bundle"], file_count=160)
    ):
        fail("preliminary_transition_outcome_unknown")
    selections = {
        family: json_bytes(
            read_relative_at(
                campaign_fd, f"selection/discovery/{family}.json", MAX_FILE
            ),
            error="preliminary_transition_outcome_unknown",
        )
        for family in FAMILIES
    }
    exact_paths = (
        frozenset(expected_paths(selections))
        | {"preliminary_check_submission.json"}
        | GENERATED_PATHS
    )
    if set(receipt["files"]) != exact_paths:
        fail("preliminary_transition_outcome_unknown")
    for name, expected in receipt["files"].items():
        if _sha(read_relative_at(campaign_fd, name, MAX_FILE)) != expected:
            fail("preliminary_transition_outcome_unknown")
    packed = bounded_at(transitions_fd, "refinement.bundle.gz", MAX_TOTAL_BYTES)
    chunks = [
        packed[index : index + MAX_CHUNK_BYTES]
        for index in range(0, len(packed), MAX_CHUNK_BYTES)
    ]
    expected_chunks = [
        {"index": index, "size": len(chunk), "sha256": _sha(chunk)}
        for index, chunk in enumerate(chunks)
    ]
    bundle = receipt["bundle"]
    if (
        _sha(packed) != bundle.get("bundle_sha256")
        or not _exact_bundle(bundle, file_count=160)
        or bundle.get("chunks") != expected_chunks
        or receipt["new_campaign_sha256"] != receipt["files"].get("campaign.json")
    ):
        fail("preliminary_transition_outcome_unknown")
    return packed, chunks


def _transition_names(transitions_fd: int) -> set[str]:
    try:
        names = set(os.listdir(transitions_fd))
    except OSError:
        fail("preliminary_transition_outcome_unknown")
    relevant = {
        name
        for name in names
        if name.startswith("refinement") or name.startswith(".refinement")
    }
    allowed = {
        "refinement.lock",
        "refinement.pending.json",
        "refinement.json",
        "refinement.bundle.gz",
    }
    if not relevant <= allowed:
        fail("preliminary_transition_outcome_unknown")
    return relevant


def main(*, trusted_root_override=None):
    if len(sys.argv) != 5 or sys.argv[1] not in {
        "inspect",
        "status",
        "prepare",
        "retrieve",
    }:
        fail("invalid_request")
    operation, username, requested, encoded = sys.argv[1:]
    if (
        re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,31}", username) is None
        or requested != f"/home/{username}/ytterbium_lab_simulation_new"
    ):
        fail("invalid_request")
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(encoded),
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        requested_root = Path(requested)
        root = (
            Path(trusted_root_override).resolve(strict=True)
            if trusted_root_override is not None
            else requested_root.resolve(strict=True)
        )
        relative = PurePosixPath(payload["campaign"])
    except Exception:
        fail("invalid_request")
    required = {"campaign", "commit", "submission_key", "transition_key", "identity"}
    if operation == "prepare":
        required.add("nonce")
    if operation == "retrieve":
        required |= {"bundle_sha256", "chunk_index"}
    if (
        not isinstance(payload, dict)
        or set(payload) != required
        or (trusted_root_override is None and root != requested_root)
        or relative.is_absolute()
        or len(relative.parts) != 4
        or relative.parts[:3] != ("data", "optimization", "mot_3d")
        or any(part in {"", ".", ".."} for part in relative.parts)
        or HEX40.fullmatch(str(payload.get("commit"))) is None
        or HEX64.fullmatch(str(payload.get("submission_key"))) is None
        or HEX64.fullmatch(str(payload.get("transition_key"))) is None
    ):
        fail("invalid_request")
    root_fd = os.open(root, DIR_FLAGS)
    opened = []
    campaign_fd = root_fd
    try:
        for part in relative.parts:
            campaign_fd = open_dir_at(campaign_fd, part)
            opened.append(campaign_fd)
        code, out, err = run(
            ["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"], limit=4096
        )
        code2, out2, err2 = run(
            ["/usr/bin/git", "-C", str(root), "branch", "--show-current"], limit=4096
        )
        code3, out3, err3 = run(
            [
                "/usr/bin/git",
                "-C",
                str(root),
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            limit=1024 * 1024,
        )
        head = out.decode("ascii", "strict").strip() if not code and not err else ""
        branch = (
            out2.decode("utf-8", "strict").strip() if not code2 and not err2 else ""
        )
        if (
            head != payload["commit"]
            or not branch
            or len(branch) > 256
            or not branch.isprintable()
            or code3
            or err3
            or out3
        ):
            fail("remote_checkout_mismatch")
        mot_ui_fd = open_dir_at(campaign_fd, ".mot_ui")
        opened.append(mot_ui_fd)
        if operation == "prepare":
            transitions_fd = open_dir_at(mot_ui_fd, "transitions", create=True)
            opened.append(transitions_fd)
        else:
            try:
                transitions_fd = os.open("transitions", DIR_FLAGS, dir_fd=mot_ui_fd)
                row = os.fstat(transitions_fd)
                if not stat.S_ISDIR(row.st_mode):
                    raise OSError
                opened.append(transitions_fd)
            except FileNotFoundError:
                transitions_fd = -1
            except OSError:
                fail("preliminary_transition_outcome_unknown")
        receipt = None
        pending_receipt = None
        transition_names = (
            _transition_names(transitions_fd) if transitions_fd >= 0 else set()
        )
        if (
            "refinement.json" in transition_names
            and "refinement.bundle.gz" not in transition_names
        ) or (
            "refinement.bundle.gz" in transition_names
            and not {
                "refinement.pending.json",
                "refinement.json",
            }
            & transition_names
        ):
            fail("preliminary_transition_outcome_unknown")
        if transitions_fd >= 0 and regular_exists_at(transitions_fd, "refinement.json"):
            receipt = strict_json_at(
                transitions_fd, "refinement.json", keys=FINAL_KEYS, limit=MAX_FILE
            )
            if (
                receipt["transition_key"] != payload["transition_key"]
                or receipt["commit"] != payload["commit"]
                or receipt["submission_key"] != payload["submission_key"]
                or receipt["identity_sha256"] != digest(payload["identity"])
                or HEX64.fullmatch(str(receipt["new_campaign_sha256"])) is None
            ):
                fail("preliminary_transition_outcome_unknown")
        if transitions_fd >= 0 and regular_exists_at(
            transitions_fd, "refinement.pending.json"
        ):
            pending_receipt = strict_json_at(
                transitions_fd,
                "refinement.pending.json",
                keys=PENDING_KEYS,
                limit=MAX_FILE,
            )
            if (
                type(pending_receipt["version"]) is not int
                or pending_receipt["version"] != 1
                or pending_receipt["status"] != "refinement_pending"
                or pending_receipt["transition_key"] != payload["transition_key"]
                or pending_receipt["commit"] != payload["commit"]
                or pending_receipt["submission_key"] != payload["submission_key"]
                or pending_receipt["identity_sha256"] != digest(payload["identity"])
                or HEX32.fullmatch(str(pending_receipt["nonce"])) is None
                or not stamp(pending_receipt["created_unix_s"])
                or any(
                    HEX64.fullmatch(str(pending_receipt[key])) is None
                    for key in (
                        "identity_sha256",
                        "old_campaign_sha256",
                        "new_campaign_sha256",
                        "evidence_sha256",
                    )
                )
                or not isinstance(pending_receipt["files"], dict)
                or len(pending_receipt["files"]) != 160
                or any(
                    not _safe_relative(name) or HEX64.fullmatch(str(value)) is None
                    for name, value in pending_receipt["files"].items()
                )
                or not isinstance(pending_receipt["bundle"], dict)
            ):
                fail("preliminary_transition_outcome_unknown")
        if receipt is not None and pending_receipt is not None:
            comparable = {
                key: value
                for key, value in pending_receipt.items()
                if key not in {"status", "created_unix_s"}
            }
            final_comparable = {
                key: value
                for key, value in receipt.items()
                if key not in {"status", "completed_unix_s"}
            }
            if comparable != final_comparable:
                fail("preliminary_transition_outcome_unknown")
        identity, frozen = _identity(
            payload,
            campaign_fd,
            root_fd,
            advanced_campaign_sha256=(
                receipt["new_campaign_sha256"]
                if receipt is not None
                else (
                    pending_receipt["new_campaign_sha256"]
                    if pending_receipt is not None
                    else None
                )
            ),
        )
        _, jobs = _exact_stage2(
            campaign_fd, payload["submission_key"], payload["commit"]
        )
        lifecycle, arrays, merges = _scheduler(jobs)
        if receipt is not None:
            _, chunks = _verify_success(campaign_fd, transitions_fd, payload, receipt)
            if pending_receipt is not None and operation == "prepare":
                if payload.get("nonce") != receipt["nonce"]:
                    fail("preliminary_transition_outcome_unknown")
                cleanup_lock = os.open(
                    "refinement.lock",
                    os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=transitions_fd,
                )
                try:
                    fcntl.flock(cleanup_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    unlink_at(transitions_fd, "refinement.pending.json")
                except BlockingIOError:
                    fail("preliminary_transition_busy")
                finally:
                    os.close(cleanup_lock)
            if operation == "retrieve":
                index = payload["chunk_index"]
                if (
                    type(index) is not int
                    or not 0 <= index < len(chunks)
                    or payload["bundle_sha256"] != receipt["bundle"]["bundle_sha256"]
                ):
                    fail("invalid_request")
                chunk = {
                    "index": index,
                    "sha256": _sha(chunks[index]),
                    "content": base64.b64encode(chunks[index]).decode("ascii"),
                }
                _response(
                    "refinement_prepared",
                    branch,
                    jobs,
                    6,
                    2,
                    validation="valid",
                    evidence=receipt["evidence_sha256"],
                    receipt=receipt,
                    bundle=receipt["bundle"],
                    chunk=chunk,
                )
                return
            _response(
                "refinement_prepared",
                branch,
                jobs,
                6,
                2,
                validation="valid",
                evidence=receipt["evidence_sha256"],
                receipt=receipt,
                bundle=receipt["bundle"],
            )
            return
        if operation == "retrieve":
            fail("preliminary_transition_not_prepared")
        current_campaign_sha = _sha(
            read_relative_at(campaign_fd, "campaign.json", MAX_FILE)
        )
        if (
            pending_receipt is not None
            and current_campaign_sha == pending_receipt["new_campaign_sha256"]
        ):
            if operation != "prepare":
                _response(
                    "outcome_unknown",
                    branch,
                    jobs,
                    arrays,
                    merges,
                    validation="valid",
                    evidence=pending_receipt["evidence_sha256"],
                )
                return
            if payload.get("nonce") != pending_receipt["nonce"]:
                fail("preliminary_transition_outcome_unknown")
            lock_fd = os.open(
                "refinement.lock",
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=transitions_fd,
            )
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                receipt = {
                    key: value
                    for key, value in pending_receipt.items()
                    if key not in {"status", "created_unix_s"}
                }
                receipt.update(
                    {
                        "status": "refinement_prepared",
                        "completed_unix_s": int(time.time()),
                    }
                )
                _verify_success(campaign_fd, transitions_fd, payload, receipt)
                _publish_bytes(
                    transitions_fd,
                    "refinement.json",
                    canonical(receipt) + b"\n",
                    identical_ok=True,
                )
                receipt = strict_json_at(
                    transitions_fd, "refinement.json", keys=FINAL_KEYS, limit=MAX_FILE
                )
                _verify_success(campaign_fd, transitions_fd, payload, receipt)
                unlink_at(transitions_fd, "refinement.pending.json")
            except BlockingIOError:
                fail("preliminary_transition_busy")
            finally:
                os.close(lock_fd)
            _response(
                "refinement_prepared",
                branch,
                jobs,
                6,
                2,
                validation="valid",
                evidence=receipt["evidence_sha256"],
                receipt=receipt,
                bundle=receipt["bundle"],
            )
            return
        if lifecycle != "completed_success_unvalidated":
            _response(lifecycle, branch, jobs, arrays, merges)
            return
        manifest_raw = frozen["campaign.json"]
        try:
            manifest, results, validated = _capture(
                campaign_fd,
                requested_root,
                requested_root.joinpath(*relative.parts),
                manifest_raw,
            )
        except SystemExit:
            raise
        except Exception as exc:
            _response(
                "completed_success_unvalidated",
                branch,
                jobs,
                6,
                2,
                validation="scientifically_invalid",
                reason=getattr(exc, "code", "result_registry_invalid"),
            )
            return
        if operation in {"inspect", "status"}:
            _response(
                "ready_to_advance",
                branch,
                jobs,
                6,
                2,
                validation="valid",
                evidence=validated.evidence_sha256,
            )
            return
        if HEX32.fullmatch(str(payload.get("nonce"))) is None:
            fail("invalid_request")
        lock_fd = os.open(
            "refinement.lock",
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=transitions_fd,
        )
        try:
            row = os.fstat(lock_fd)
            if not stat.S_ISREG(row.st_mode) or row.st_nlink != 1:
                fail("preliminary_transition_outcome_unknown")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for name, raw in frozen.items():
                if read_relative_at(campaign_fd, name, MAX_FILE) != raw:
                    fail("preliminary_transition_conflict")
            _identity(payload, campaign_fd, root_fd)
            _exact_stage2(campaign_fd, payload["submission_key"], payload["commit"])
            if _scheduler(jobs) != ("completed_success_unvalidated", 6, 2):
                fail("preliminary_transition_conflict")
            generated, _ = render_refinement_transition(
                relative, manifest, validated.summaries
            )
            if set(generated) != GENERATED_PATHS:
                fail("preliminary_transition_conflict")
            files = dict(results)
            files["preliminary_check_submission.json"] = read_relative_at(
                campaign_fd, "preliminary_check_submission.json", MAX_FILE
            )
            files.update(generated)
            parsed = {
                family: json_bytes(
                    read_relative_at(
                        campaign_fd, f"selection/discovery/{family}.json", MAX_FILE
                    ),
                    error="preliminary_transition_conflict",
                )
                for family in FAMILIES
            }
            expected_transfer = (
                frozenset(expected_paths(parsed))
                | {"preliminary_check_submission.json"}
                | GENERATED_PATHS
            )
            if set(files) != expected_transfer or len(files) != 160:
                fail("preliminary_transition_conflict")
            built = build_artifact_bundle(
                files,
                campaign=relative.name,
                commit=payload["commit"],
                from_stage="preliminary_check",
                to_stage="refinement",
                expected_paths=expected_transfer,
            )
            hashes = {name: _sha(raw) for name, raw in files.items()}
            pending = {
                "version": 1,
                "status": "refinement_pending",
                "nonce": payload["nonce"],
                "transition_key": payload["transition_key"],
                "commit": payload["commit"],
                "submission_key": payload["submission_key"],
                "identity_sha256": digest(identity),
                "old_campaign_sha256": _sha(manifest_raw),
                "new_campaign_sha256": hashes["campaign.json"],
                "evidence_sha256": validated.evidence_sha256,
                "files": hashes,
                "bundle": built.manifest,
                "created_unix_s": int(time.time()),
            }
            if regular_exists_at(transitions_fd, "refinement.pending.json"):
                current = strict_json_at(
                    transitions_fd,
                    "refinement.pending.json",
                    keys=set(pending),
                    limit=MAX_FILE,
                )
                if {k: v for k, v in current.items() if k != "created_unix_s"} != {
                    k: v for k, v in pending.items() if k != "created_unix_s"
                }:
                    fail("preliminary_transition_outcome_unknown")
                pending = current
            else:
                _publish_bytes(
                    transitions_fd,
                    "refinement.pending.json",
                    canonical(pending) + b"\n",
                    identical_ok=False,
                )
            for name in sorted(GENERATED_PATHS - {"campaign.json"}):
                _publish_relative(campaign_fd, name, generated[name])
            _publish_bytes(
                transitions_fd, "refinement.bundle.gz", built.packed, identical_ok=True
            )
            _replace_campaign(campaign_fd, manifest_raw, generated["campaign.json"])
            receipt = {
                k: v
                for k, v in pending.items()
                if k not in {"status", "created_unix_s", "bundle"}
            }
            receipt.update(
                {
                    "status": "refinement_prepared",
                    "bundle": built.manifest,
                    "completed_unix_s": int(time.time()),
                }
            )
            _verify_success(campaign_fd, transitions_fd, payload, receipt)
            _publish_bytes(
                transitions_fd,
                "refinement.json",
                canonical(receipt) + b"\n",
                identical_ok=True,
            )
            receipt = strict_json_at(
                transitions_fd, "refinement.json", keys=FINAL_KEYS, limit=MAX_FILE
            )
            _verify_success(campaign_fd, transitions_fd, payload, receipt)
            unlink_at(transitions_fd, "refinement.pending.json")
        except BlockingIOError:
            fail("preliminary_transition_busy")
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        _response(
            "refinement_prepared",
            branch,
            jobs,
            6,
            2,
            validation="valid",
            evidence=receipt["evidence_sha256"],
            receipt=receipt,
            bundle=receipt["bundle"],
        )
    finally:
        for fd in reversed(opened):
            try:
                os.close(fd)
            except OSError:
                pass
        os.close(root_fd)


if __name__ == "__main__":
    main()
