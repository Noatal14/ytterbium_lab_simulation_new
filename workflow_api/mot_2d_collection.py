"""Bounded same-revision collection of a completed 2D campaign.

The complete manifest is the scientific commit point. The later sync receipt
records collection custody; it is deliberately not an input admission gate.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import threading

from workflow_api.platform_io import os, locking
from workflow_api.mot_2d_spec import (
    refinement_targets,
    survivor_states_directory,
    validate_campaign_policy,
    authorize_review_target,
)
from workflow_api.verified_artifact_bundle import (
    build_artifact_bundle,
    unpack_artifact_bundle,
    canonical_json,
    sha256,
    MAX_REVIEWED_FILE_BYTES as FILE_LIMIT,
    MAX_REVIEWED_TOTAL_BYTES as TOTAL_LIMIT,
    MAX_CHUNK_BYTES,
    _strict_json,
)
from workflow_api.mot_3d_discovery_transition import (
    _DIRECTORY_FLAGS,
    _open_parent_at,
    _open_directory_at,
    _atomic_replace_at,
)
from workflow_api.preview_registry import PreviewRegistry

SYNC = "finalization_collection"
SHA = re.compile(r"^[0-9a-f]{64}$")


def error(code):
    from workflow_api.zeus_finalization import ZeusFinalizationError

    return ZeusFinalizationError(code)


def identity(row):
    return (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_nlink,
        row.st_uid,
        row.st_gid,
        row.st_size,
        row.st_mtime_ns,
        row.st_ctime_ns,
    )


def read_at(parent, name, limit=FILE_LIMIT):
    """Stable FD and named identity, with no aliases or shared file inodes."""
    fd = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        dir_fd=parent,
    )
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != getattr(os, "getuid", lambda: 0)()
            or not 0 < before.st_size <= limit
        ):
            raise ValueError("Unsafe collection artifact")
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, min(1024 * 1024, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if (
            len(data) != before.st_size
            or identity(before) != identity(os.fstat(fd))
            or identity(before) != identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
        ):
            raise ValueError("Collection artifact changed")
        return bytes(data)
    finally:
        os.close(fd)


def read(root_fd, name, limit=FILE_LIMIT):
    path = PurePosixPath(name)
    if (
        not isinstance(name, str)
        or path.is_absolute()
        or path.as_posix() != name
        or any(p in {"", ".", ".."} for p in path.parts)
    ):
        raise ValueError("Unsafe collection path")
    parent = _open_parent_at(root_fd, path.parts[:-1], create=False)
    try:
        return read_at(parent, path.name, limit)
    finally:
        os.close(parent)


def publish(parent, name, data):
    """Exclusive target reservation: no hardlink publication/NFS link count window.

    Failed partial reservations remain for explicit inspection, never overwrite.
    """
    try:
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent,
        )
    except FileExistsError:
        if read_at(parent, name, max(len(data), 1)) != data:
            raise ValueError("Conflicting collection artifact")
        flush_existing(parent, name)
        return False
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)
        if read_at(parent, name, len(data)) != data:
            raise ValueError("Published collection artifact changed")
        return True
    except BaseException:
        # Target may be partially durable: retain it and pending intent.
        raise


def flush_existing(parent, name):
    """Explicit reconciliation flushes an identical inode without replacing it."""
    fd = os.open(name, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
    try:
        before = identity(os.fstat(fd))
        if before[3] != 1 or not stat.S_ISREG(before[2]):
            raise ValueError("Unsafe existing collection inode")
        os.fsync(fd)
        if before != identity(os.stat(name, dir_fd=parent, follow_symlinks=False)):
            raise ValueError("Collection inode changed during flush")
    finally:
        os.close(fd)
    os.fsync(parent)


def registry_paths(root, campaign, manifest, *, sensitivity_counts=None):
    """Explicit complete validator closure; no recursive wildcard collection."""
    if manifest.get("stage") != "complete":
        raise ValueError("Campaign is not complete")
    profile = validate_campaign_policy(manifest)
    from workflow_api.campaign_deployment import normal_checkout, TEAM_CHECKOUT

    if not profile and normal_checkout(manifest) != TEAM_CHECKOUT:
        raise ValueError("Collection requires campaign-owned TEAM survivor outputs")
    relative = campaign.relative_to(root).as_posix()
    fixed = {
        "campaign.json",
        "final_report.json",
        "screen/tasks.json",
        "refine/tasks.json",
        "confirmation/tasks.json",
        "sensitivity/tasks.json",
        "production/tasks.json",
        "screening_candidates.json",
        "refined_candidates.json",
        "winners.json",
        "sensitivity_summary.json",
        "jobs/01_smoke.pbs",
        "jobs/02_screen.pbs",
        "jobs/03_submit_refinement_chain.sh",
        "jobs/04_confirmation.pbs",
        "jobs/05_sensitivity.pbs",
        "jobs/06_production.pbs",
    }
    rounds = refinement_targets(manifest)
    fixed.update(f"jobs/03_refine_round_{r:02d}.pbs" for r in range(1, len(rounds) + 1))
    paths = {f"{relative}/{name}" for name in fixed}
    bs = manifest["fixed_design"]["trial_budgets"]["screen_per_worker"]
    br = manifest["fixed_design"]["trial_budgets"]["refine_per_worker"]
    tasks = None
    if sensitivity_counts is None:
        from workflow_api.mot_2d_validation import (
            validated_evaluation_outputs,
            expected_sensitivity_tasks,
        )

        prior = deepcopy(manifest)
        prior["stage"] = "confirmation"
        for later in ("sensitivity", "production", "final_report"):
            prior["stages"].pop(later, None)
        tasks = expected_sensitivity_tasks(
            manifest, validated_evaluation_outputs(campaign, prior, "confirmation")
        )
    count = 17 + len(rounds)
    for raw in manifest["s0_values"]:
        value = float(raw)
        key = f"s0_{value:.6f}".replace(".", "p")
        names = {f"smoke/{key}/summary.json", f"smoke/{key}/trials/trial_0000.json"}
        for stage, budget in (("screen", bs), ("refine", br)):
            for worker in range(3):
                prefix = f"{stage}/{key}/worker{worker}"
                names.update((f"{prefix}/summary.json", f"{prefix}/joint_screening.db"))
                names.update(f"{prefix}/trials/trial_{t:04d}.json" for t in range(budget))
        names.update(f"confirmation/{key}/point_{i:02d}.json" for i in range(5))
        indices = (
            [t["point_index"] for t in tasks if float(t["s0"]) == value]
            if tasks is not None
            else list(range(sensitivity_counts[value]))
        )
        if indices != list(range(len(indices))) or not 1 <= len(indices) <= 17:
            raise ValueError("Invalid canonical sensitivity registry")
        names.update(f"sensitivity/{key}/point_{i:02d}.json" for i in indices)
        names.add(f"production/{key}/summary.json")
        states = survivor_states_directory(manifest, campaign, value)
        if not states.is_absolute():
            states = root / states
        states_relative = states.relative_to(root).as_posix()
        expected = (
            f"{relative}/survivor_states/"
            if profile
            else f"data/particle_states/after_2d_mot/campaigns/{campaign.name}/"
        )
        if not states_relative.startswith(expected):
            raise ValueError("Survivor ownership mismatch")
        for z, m in zip(
            manifest["seed_roles"]["sealed_validation"],
            manifest["mot_seeds"]["sealed_validation"],
        ):
            names.add(f"production/{key}/replicates/zeeman_seed{z}.json")
            stem = f"{states_relative}/mot_2d_survivors_zeeman_seed{z}_mot_seed{m}"
            paths.update((f"{stem}.npy", f"{stem}.json"))
        paths.update(f"{relative}/{name}" for name in names)
        count += 80 + 3 * bs + 3 * br + len(indices)
    if len(paths) != count:
        raise ValueError("Collection registry count mismatch")
    return frozenset(paths)


def validate_complete(root, campaign, manifest):
    from workflow_api.mot_2d_validation import (
        modern_contract,
        validated_progress,
        sealed_final_is_valid,
    )

    if manifest.get("stage") != "complete" or not modern_contract(manifest, root)[0]:
        raise ValueError("Invalid complete campaign contract")
    progress = validated_progress(campaign, manifest)
    if (
        {p.stage for p in progress}
        != {"smoke", "screen", "refine", "confirmation", "sensitivity", "production"}
        or any(p.status != "complete" for p in progress)
        or not sealed_final_is_valid(campaign, manifest, progress, root)
    ):
        raise ValueError("Complete campaign evidence is invalid")
    validate_rendered_history(root, campaign, manifest)


def validate_rendered_history(root, campaign, manifest):
    from workflow_api import mot_2d_plan as plan
    from workflow_api.mot_2d_screen import (
        validate_screen_outputs,
        validate_refine_outputs,
    )
    from workflow_api.mot_2d_validation import validated_evaluation_outputs

    order = (
        "smoke",
        "screen",
        "refine",
        "confirmation",
        "sensitivity",
        "production",
        "complete",
    )

    def prior(stage):
        result = deepcopy(manifest)
        result["stage"] = stage
        for later in order[order.index(stage) + 1 :] + ("final_report",):
            result.get("stages", {}).pop(later, None)
        return result

    screen = validate_screen_outputs(campaign, prior("screen"))
    refine = validate_refine_outputs(campaign, prior("refine"))
    confirmation = validated_evaluation_outputs(campaign, prior("confirmation"), "confirmation")
    sensitivity = validated_evaluation_outputs(campaign, prior("sensitivity"), "sensitivity")
    rendered = [
        plan.render_campaign_files(prior("smoke"), campaign, root),
        plan.render_screen_transition(prior("smoke"), campaign, root),
        plan.render_refine_transition(prior("screen"), campaign, root, screen),
        plan.render_confirmation_transition(prior("refine"), campaign, root, refine),
        plan.render_sensitivity_transition(prior("confirmation"), campaign, root, confirmation),
        plan.render_production_transition(
            prior("sensitivity"), campaign, root, confirmation, sensitivity
        ),
    ]
    fd = os.open(root, _DIRECTORY_FLAGS)
    try:
        relative = campaign.relative_to(root).as_posix()
        for files in rendered:
            for name, data in files.items():
                if name != "campaign.json" and read(fd, f"{relative}/{name}") != data:
                    raise ValueError("Canonical prepared artifact differs")
    finally:
        os.close(fd)


def files_snapshot(root, paths):
    fd = os.open(root, _DIRECTORY_FLAGS)
    try:
        # Reject over-size registries before reading their contents.
        total = 0
        for name in sorted(paths):
            path = PurePosixPath(name)
            parent = _open_parent_at(fd, path.parts[:-1], create=False)
            try:
                row = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                if not 0 < row.st_size <= FILE_LIMIT:
                    raise error("collection_too_large")
                total += row.st_size
                if total > TOTAL_LIMIT:
                    raise error("collection_too_large")
            finally:
                os.close(parent)
        return {name: read(fd, name) for name in sorted(paths)}
    finally:
        os.close(fd)


def remote_collection(root, payload, *, authenticated=None):
    """Read-only existing FINALIZATION RETRIEVE. No scheduler or publication."""
    from workflow_api.zeus_finalization_remote import (
        validate_static,
        derive,
        read_json,
        completed_receipt_valid,
    )

    if set(payload) not in (
        {"campaign", "commit"},
        {"campaign", "commit", "bundle_sha256", "chunk_index"},
    ):
        raise ValueError("Invalid collection request")
    campaign, manifest, _branch, submission, relative, production = (
        authenticated
        if authenticated is not None
        else validate_static({k: payload[k] for k in ("campaign", "commit")}, root)
    )
    if manifest.get("stage") != "complete":
        raise ValueError("Campaign is not complete")
    _, rendered, results, evidence = derive(campaign, manifest, root)
    hashes = {n: sha256(b) for n, b in rendered.items()}
    receipt_path = campaign / ".mot_ui/transitions/finalization.json"
    fd = os.open(root, _DIRECTORY_FLAGS)
    try:
        receipt_raw = read(fd, receipt_path.relative_to(root).as_posix())
    finally:
        os.close(fd)
    receipt = _strict_json(receipt_raw)
    key = sha256(
        canonical_json(
            {
                "campaign": relative.as_posix(),
                "commit": payload["commit"],
                "production_submission_key": production["submission_key"],
                "production_submission_nonce": submission["nonce"],
                "production_job_id": submission["job_id"],
                "evidence_digest": evidence,
                "files": hashes,
                "results_digest": sha256(canonical_json(results)),
            }
        )
    )
    if not completed_receipt_valid(
        receipt,
        key,
        payload["commit"],
        production,
        submission,
        evidence,
        hashes,
        results,
    ):
        raise ValueError("Invalid completed finalization receipt")
    paths = registry_paths(root, campaign, manifest)
    files = files_snapshot(root, paths)
    validate_complete(root, campaign, manifest)
    if any(files[f"{relative}/{name}"] != data for name, data in rendered.items()):
        raise ValueError("Finalization artifacts changed")
    if files_snapshot(root, paths) != files:
        raise ValueError("Collection artifacts changed")
    fd = os.open(root, _DIRECTORY_FLAGS)
    try:
        if read(fd, receipt_path.relative_to(root).as_posix()) != receipt_raw:
            raise ValueError("Finalization receipt changed")
    finally:
        os.close(fd)
    bundle = build_artifact_bundle(
        files,
        campaign=campaign.name,
        commit=payload["commit"],
        from_stage="complete",
        to_stage="collected",
        expected_paths=paths,
        max_total_bytes=TOTAL_LIMIT,
        max_file_bytes=FILE_LIMIT,
    )
    rows = [{"path": n, "size": len(b), "sha256": sha256(b)} for n, b in sorted(files.items())]
    descriptor = {
        "campaign": relative.as_posix(),
        "commit": payload["commit"],
        "manifest": manifest,
        "receipt": receipt,
        "receipt_sha256": sha256(receipt_raw),
        "production_identity": production,
        "branch": _branch,
        "files": rows,
        "registry_sha256": sha256(canonical_json(rows)),
        "bundle": dict(bundle.manifest),
    }
    chunk = None
    if "chunk_index" in payload:
        index = payload["chunk_index"]
        if (
            type(index) is not int
            or not 0 <= index < len(bundle.chunks)
            or payload["bundle_sha256"] != bundle.manifest["bundle_sha256"]
        ):
            raise ValueError("Invalid collection chunk")
        chunk = {
            "index": index,
            "content": base64.b64encode(bundle.chunks[index]).decode("ascii"),
        }
    return {"descriptor": descriptor, "chunk": chunk}


@dataclass(frozen=True)
class Pending:
    session: str
    request: dict
    campaign: Path
    old_raw: bytes
    descriptor: dict
    expires: float
    existing: dict
    result: dict | None = None
    consumed: bool = False


class CollectionCoordinator:
    def __init__(self, owner):
        self.owner = owner
        self.previews = PreviewRegistry(clock=owner.clock)
        self.mutex = threading.Lock()

    def assert_revision(self, commit):
        from workflow_api.repository_snapshot import RepositorySnapshotProvider

        from workflow_api.repository_snapshot import RepositoryFilesChangedError

        try:
            snapshot = RepositorySnapshotProvider(
                self.owner.root,
                self.owner.git,
                audited_paths=(
                    "workflow_api",
                    "studies",
                    "simulations",
                    "utils",
                    "lab_setup",
                    "atomsmltr/src",
                    "config.py",
                ),
            ).capture()
        except RepositoryFilesChangedError as exc:
            raise error("local_checkout_mismatch") from exc
        if snapshot.commit != commit:
            raise error("local_checkout_mismatch")

    def plan(self, request):
        owner = self.owner
        if not isinstance(request, dict) or set(request) != {
            "campaign_id",
            "username",
            "project_directory",
        }:
            raise error("request_invalid")
        from workflow_api.zeus_snapshot import ZeusProfile

        try:
            ZeusProfile.parse(
                {
                    "username": request["username"],
                    "project_directory": request["project_directory"],
                }
            )
        except ValueError as exc:
            raise error("profile_invalid") from exc
        base = owner._base_plan(request)
        self.assert_revision(base[4])
        authorize_review_target(
            base[3], base[1], base[2], owner.root, type(error("profile_invalid"))
        )
        root_fd = os.open(owner.root, _DIRECTORY_FLAGS)
        try:
            old = read(root_fd, (base[2].relative_to(owner.root) / "campaign.json").as_posix())
        finally:
            os.close(root_fd)
        if _strict_json(old) != base[3]:
            raise error("collection_conflict")
        from workflow_api.mot_2d_validation import modern_contract

        if not modern_contract(base[3], owner.root)[0]:
            raise error("collection_invalid")
        transport = owner.transport_factory(base[1])
        response = transport.retrieve(
            campaign=base[2].relative_to(owner.root).as_posix(), commit=base[4]
        )
        descriptor = validate_descriptor(response, owner.root, base[2], base[4], base[3])
        return base, old, transport, descriptor

    def preview(self, request, *, session_id):
        base, old, _, descriptor = self.plan(request)
        creates, identical = self.local_plan(descriptor)
        expires = self.owner.clock() + 300
        token = self.previews.add(
            Pending(
                session_id,
                dict(request),
                base[2],
                old,
                descriptor,
                expires,
                self.observations(descriptor),
            ),
            expires_at=expires,
            capacity=32,
        )
        rows = descriptor["files"]
        return {
            "preview_token": token,
            "expires_in_seconds": 300,
            "campaign": {
                "id": base[0],
                "name": base[3]["name"],
                "git_commit": base[4],
                "stage": "complete",
            },
            "source": {
                "finalization_receipt_sha256": descriptor["receipt_sha256"],
                "complete_manifest_sha256": next(
                    r["sha256"]
                    for r in rows
                    if r["path"] == f"{descriptor['campaign']}/campaign.json"
                ),
                "registry_sha256": descriptor["registry_sha256"],
                "bundle_sha256": descriptor["bundle"]["bundle_sha256"],
            },
            "artifacts": {
                "files": rows,
                "file_count": len(rows),
                "total_bytes": sum(r["size"] for r in rows),
                "maximum_file_bytes": max(r["size"] for r in rows),
                "create": creates,
                "identical": identical,
                "update": [f"{descriptor['campaign']}/campaign.json"],
            },
            "effects": {
                "collect_verified_outputs": True,
                "submit_job": False,
                "start_simulation": False,
            },
            "local_sync": self.local_sync(base[2], descriptor),
        }

    def observations(self, descriptor):
        fd = os.open(self.owner.root, _DIRECTORY_FLAGS)
        observed = {}
        try:
            for row in descriptor["files"]:
                name = row["path"]
                path = PurePosixPath(name)
                parent = -1
                try:
                    parent = _open_parent_at(fd, path.parts[:-1], create=False)
                    # A bounded read authenticates both the inode and its name.
                    read_at(parent, path.name)
                    observed[name] = identity(
                        os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                    )
                except FileNotFoundError:
                    observed[name] = None
                finally:
                    if parent >= 0:
                        os.close(parent)
            return observed
        finally:
            os.close(fd)

    def local_plan(self, descriptor):
        creates = []
        identical = []
        fd = os.open(self.owner.root, _DIRECTORY_FLAGS)
        try:
            for row in descriptor["files"]:
                if row["path"] == f"{descriptor['campaign']}/campaign.json":
                    continue
                try:
                    data = read(fd, row["path"])
                except FileNotFoundError:
                    creates.append(row["path"])
                else:
                    if len(data) != row["size"] or sha256(data) != row["sha256"]:
                        raise error("collection_conflict")
                    identical.append(row["path"])
        finally:
            os.close(fd)
        return creates, identical

    def status(self, campaign, remote_receipt):
        """Verify an already durable collection audit without any remote write."""
        fd = os.open(self.owner.root, _DIRECTORY_FLAGS)
        try:
            name = (
                campaign.relative_to(self.owner.root) / ".mot_ui/sync" / f"{SYNC}.json"
            ).as_posix()
            try:
                receipt = _strict_json(read(fd, name))
            except FileNotFoundError:
                return {"status": "not_synchronized"}
            manifest = _strict_json(
                read(
                    fd,
                    (campaign.relative_to(self.owner.root) / "campaign.json").as_posix(),
                )
            )
            if not isinstance(receipt, dict) or receipt.get("remote_receipt_digest") != sha256(
                canonical_json(remote_receipt)
            ):
                raise error("collection_conflict")
            descriptor = {
                "commit": manifest["provenance"]["git_commit"],
                "receipt_sha256": receipt.get("remote_receipt_sha256"),
                "receipt": remote_receipt,
                "manifest": manifest,
                "registry_sha256": receipt.get("registry_sha256"),
                "bundle": {"bundle_sha256": receipt.get("bundle_sha256")},
                "files": receipt.get("files"),
            }
            if not isinstance(descriptor["files"], list):
                raise error("collection_conflict")
            if {r["path"] for r in descriptor["files"]} != registry_paths(
                self.owner.root, campaign, manifest
            ):
                raise error("collection_conflict")
            if descriptor["registry_sha256"] != sha256(canonical_json(descriptor["files"])):
                raise error("collection_conflict")
            return self.local_sync(campaign, descriptor)
        finally:
            os.close(fd)

    def local_sync(self, campaign, descriptor):
        root_fd = os.open(self.owner.root, _DIRECTORY_FLAGS)
        parent = lock = -1
        try:
            relative = campaign.relative_to(self.owner.root) / ".mot_ui/sync"
            try:
                parent = _open_parent_at(root_fd, relative.parts, create=False)
                lock = os.open(
                    f"{SYNC}.lock",
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent,
                )
            except FileNotFoundError:
                return {"status": "not_synchronized"}
            row = os.fstat(lock)
            if (
                not stat.S_ISREG(row.st_mode)
                or row.st_nlink != 1
                or row.st_uid != getattr(os, "getuid", lambda: 0)()
            ):
                raise error("collection_conflict")
            locking.flock(lock, locking.LOCK_EX | locking.LOCK_NB)
            return self._local_sync_locked(campaign, descriptor)
        finally:
            if lock >= 0:
                try:
                    locking.flock(lock, locking.LOCK_UN)
                finally:
                    os.close(lock)
            if parent >= 0:
                os.close(parent)
            os.close(root_fd)

    def _local_sync_locked(self, campaign, descriptor):
        fd = os.open(self.owner.root, _DIRECTORY_FLAGS)
        try:
            name = (
                campaign.relative_to(self.owner.root) / ".mot_ui/sync" / f"{SYNC}.json"
            ).as_posix()
            try:
                receipt = _strict_json(read(fd, name))
            except FileNotFoundError:
                return {"status": "not_synchronized"}
            expected = sync_identity(descriptor)
            backup = read(
                fd,
                (
                    campaign.relative_to(self.owner.root)
                    / ".mot_ui/sync"
                    / f"{SYNC}.original-manifest.json"
                ).as_posix(),
            )
            validate_original(backup, descriptor["manifest"])
            if (
                not isinstance(receipt, dict)
                or set(receipt) != set(expected) | {"completed_unix_s", "original_manifest_sha256"}
                or receipt.get("original_manifest_sha256") != sha256(backup)
                or any(receipt[k] != v for k, v in expected.items())
                or type(receipt["completed_unix_s"]) is not int
                or not 0 <= receipt["completed_unix_s"] <= 253402300799
            ):
                raise error("collection_conflict")
            for row in descriptor["files"]:
                if sha256(read(fd, row["path"])) != row["sha256"]:
                    raise error("collection_conflict")
            validate_complete(self.owner.root, campaign, descriptor["manifest"])
            pending_name = (
                campaign.relative_to(self.owner.root) / ".mot_ui/sync" / f"{SYNC}.pending.json"
            ).as_posix()
            try:
                pending = _strict_json(read(fd, pending_name))
            except FileNotFoundError:
                pass
            else:
                expected_pending = {
                    **sync_identity(descriptor),
                    "status": "collecting",
                    "old_manifest_sha256": sha256(backup),
                }
                if pending != expected_pending:
                    raise error("collection_conflict")
                # A full receipt may have become visible before its publisher's
                # final fsync returned. Only explicit reconciliation clears intent.
                return {"status": "not_synchronized"}
            return {"status": "synchronized", "receipt_sha256": sha256(read(fd, name))}
        finally:
            os.close(fd)

    def confirm(self, request, *, session_id):
        if (
            not isinstance(request, dict)
            or set(request) != {"preview_token"}
            or not isinstance(request["preview_token"], str)
        ):
            raise error("request_invalid")
        with self.mutex:
            record = self.previews.get(request["preview_token"])
            pending = None if record is None else record.value
            if pending is None or not secrets.compare_digest(pending.session, session_id):
                raise error("confirmation_invalid")
            if pending.result is not None:
                self.assert_revision(pending.descriptor["commit"])
                if (
                    self.local_sync(pending.campaign, pending.descriptor)
                    != pending.result["local_sync"]
                ):
                    raise error("collection_outcome_unknown")
                return dict(pending.result)
            if pending.consumed:
                raise error("collection_outcome_unknown")
            if self.owner.clock() > pending.expires:
                raise error("confirmation_expired")
            base, old, transport, descriptor = self.plan(pending.request)
            if (
                descriptor != pending.descriptor
                or old != pending.old_raw
                or self.observations(descriptor) != pending.existing
            ):
                raise error("remote_files_changed")
            chunks = []
            for row in descriptor["bundle"]["chunks"]:
                response = transport.retrieve(
                    campaign=descriptor["campaign"],
                    commit=descriptor["commit"],
                    bundle_sha256=descriptor["bundle"]["bundle_sha256"],
                    chunk_index=row["index"],
                )
                if (
                    not isinstance(response, dict)
                    or set(response) != {"descriptor", "chunk"}
                    or response["descriptor"] != descriptor
                    or not isinstance(response["chunk"], dict)
                    or set(response["chunk"]) != {"index", "content"}
                    or type(response["chunk"]["index"]) is not int
                    or response["chunk"]["index"] != row["index"]
                ):
                    raise error("remote_response_invalid")
                data = base64.b64decode(response["chunk"]["content"], validate=True)
                if len(data) != row["size"] or sha256(data) != row["sha256"]:
                    raise error("remote_response_invalid")
                chunks.append(data)
            paths = frozenset(row["path"] for row in descriptor["files"])
            files = unpack_artifact_bundle(
                b"".join(chunks),
                descriptor["bundle"],
                campaign=base[2].name,
                commit=base[4],
                from_stage="complete",
                to_stage="collected",
                expected_paths=paths,
                max_file_bytes=FILE_LIMIT,
                max_total_bytes=TOTAL_LIMIT,
            )
            if [
                {"path": n, "size": len(b), "sha256": sha256(b)} for n, b in sorted(files.items())
            ] != descriptor["files"]:
                raise error("remote_response_invalid")
            # Read-only validation/retrieval does not renew confirmation consent.
            if self.owner.clock() > pending.expires:
                raise error("confirmation_expired")
            self.assert_revision(descriptor["commit"])
            if self.owner.clock() > pending.expires:
                raise error("confirmation_expired")
            from dataclasses import replace

            self.previews.replace(request["preview_token"], replace(pending, consumed=True))
            try:
                counts = self.synchronize(base[2], old, descriptor, files, pending.existing)
                sync = self.local_sync(base[2], descriptor)
            except Exception as exc:
                raise error("collection_outcome_unknown") from exc
            result = {
                "status": "collected",
                "campaign_id": base[0],
                "stage": "complete",
                "submitted_to_zeus": False,
                "simulation_started": False,
                "local_sync": sync,
                "artifacts": counts,
            }
            from dataclasses import replace

            self.previews.replace(
                request["preview_token"], replace(pending, result=result, consumed=True)
            )
            return result

    def synchronize(self, campaign, old, descriptor, files, existing):
        root = self.owner.root
        root_fd = os.open(root, _DIRECTORY_FLAGS)
        campaign_fd = mot_fd = sync_fd = lock_fd = -1
        try:
            relative = campaign.relative_to(root).as_posix()
            campaign_fd = _open_parent_at(root_fd, PurePosixPath(relative).parts, create=False)
            mot_fd = _open_directory_at(campaign_fd, ".mot_ui", create=True)
            sync_fd = _open_directory_at(mot_fd, "sync", create=True)
            lock_fd = os.open(
                f"{SYNC}.lock",
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=sync_fd,
            )
            row = os.fstat(lock_fd)
            if (
                not stat.S_ISREG(row.st_mode)
                or row.st_nlink != 1
                or row.st_uid != getattr(os, "getuid", lambda: 0)()
            ):
                raise ValueError("Unsafe collection lock")
            locking.flock(lock_fd, locking.LOCK_EX | locking.LOCK_NB)
            lock_identity = identity(os.fstat(lock_fd))
            if lock_identity != identity(
                os.stat(f"{SYNC}.lock", dir_fd=sync_fd, follow_symlinks=False)
            ):
                raise ValueError("Collection lock identity changed")
            if self.observations(descriptor) != existing:
                raise ValueError("Local collection identities changed")
            backup_name = f"{SYNC}.original-manifest.json"
            new = files[f"{relative}/campaign.json"]
            try:
                backup = read_at(sync_fd, backup_name)
            except FileNotFoundError:
                # An old complete canonical file is not an alternate producer.
                if _strict_json(old).get("stage") == "complete" and old != new:
                    raise ValueError("Foreign complete original manifest")
                validate_original(old, descriptor["manifest"])
                publish(sync_fd, backup_name, old)
                backup = old
            else:
                validate_original(backup, descriptor["manifest"])
                if old not in (backup, new):
                    raise ValueError("Original collection manifest changed")
            intent = {
                "status": "collecting",
                **sync_identity(descriptor),
                "old_manifest_sha256": sha256(backup),
            }
            intent["status"] = "collecting"
            intent_raw = canonical_json(intent) + b"\n"
            try:
                existing = read_at(sync_fd, f"{SYNC}.pending.json")
            except FileNotFoundError:
                publish(sync_fd, f"{SYNC}.pending.json", intent_raw)
            else:
                previous = _strict_json(existing)
                if (
                    not isinstance(previous, dict)
                    or set(previous) != set(intent)
                    or any(
                        previous[k] != v for k, v in intent.items() if k != "old_manifest_sha256"
                    )
                    or not isinstance(previous.get("old_manifest_sha256"), str)
                    or not SHA.fullmatch(previous["old_manifest_sha256"])
                ):
                    raise ValueError("Conflicting collection intent")
                # An explicit newly reviewed recovery may observe the complete
                # manifest already committed, before its audit receipt existed.
                if previous["old_manifest_sha256"] != sha256(backup):
                    raise ValueError("Conflicting original manifest intent")
            new = files[f"{relative}/campaign.json"]
            current = read_at(campaign_fd, "campaign.json")
            if current not in (old, new):
                raise ValueError("Manifest compare failed")
            counts = {"created": 0, "identical": 0, "updated": 1}
            published_identities = {}
            for name, data in sorted(files.items()):
                if name == f"{relative}/campaign.json":
                    continue
                path = PurePosixPath(name)
                parent = _open_parent_at(root_fd, path.parts[:-1], create=True)
                try:
                    created = publish(parent, path.name, data)
                    counts["created" if created else "identical"] += 1
                    published_identities[name] = identity(
                        os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                    )
                finally:
                    os.close(parent)
            # Validate actual canonical artifacts, using the candidate manifest
            # object while the canonical old manifest remains non-complete.
            validate_complete(root, campaign, descriptor["manifest"])
            if registry_paths(root, campaign, descriptor["manifest"]) != frozenset(files):
                raise ValueError("Published collection registry mismatch")
            for name, data in files.items():
                if name != f"{relative}/campaign.json" and read(root_fd, name) != data:
                    raise ValueError("Collection changed before commit")
            observed = self.observations(descriptor)
            if any(observed[name] != stamp for name, stamp in published_identities.items()):
                raise ValueError("Published collection identity changed")
            bound = _open_parent_at(root_fd, PurePosixPath(relative).parts, create=False)
            try:
                if (os.fstat(bound).st_dev, os.fstat(bound).st_ino) != (
                    os.fstat(campaign_fd).st_dev,
                    os.fstat(campaign_fd).st_ino,
                ):
                    raise ValueError("Campaign directory identity changed")
            finally:
                os.close(bound)
            if read_at(campaign_fd, "campaign.json") != current:
                raise ValueError("Manifest CAS conflict")
            if lock_identity != identity(
                os.stat(f"{SYNC}.lock", dir_fd=sync_fd, follow_symlinks=False)
            ):
                raise ValueError("Collection lock was replaced")
            if current != new:
                _atomic_replace_at(campaign_fd, "campaign.json", new)
            validate_complete(root, campaign, descriptor["manifest"])
            receipt = {
                **sync_identity(descriptor),
                "completed_unix_s": int(self.owner.clock()),
                "original_manifest_sha256": sha256(backup),
            }
            receipt_name = f"{SYNC}.json"
            try:
                existing_receipt = read_at(sync_fd, receipt_name)
            except FileNotFoundError:
                publish(sync_fd, receipt_name, canonical_json(receipt) + b"\n")
            else:
                previous = _strict_json(existing_receipt)
                if (
                    not isinstance(previous, dict)
                    or set(previous) != set(receipt)
                    or any(previous[k] != v for k, v in receipt.items() if k != "completed_unix_s")
                    or type(previous["completed_unix_s"]) is not int
                    or not 0 <= previous["completed_unix_s"] <= 253402300799
                ):
                    raise ValueError("Conflicting collection receipt")
                # Explicit recovery flushes the exact already-published receipt,
                # without replacing it or inventing a new completion timestamp.
                flush_existing(sync_fd, receipt_name)
            # Receipt is durable before pending deletion; failure retains audit.
            os.unlink(f"{SYNC}.pending.json", dir_fd=sync_fd)
            os.fsync(sync_fd)
            return counts
        finally:
            if lock_fd >= 0:
                try:
                    locking.flock(lock_fd, locking.LOCK_UN)
                finally:
                    os.close(lock_fd)
            for fd in (sync_fd, mot_fd, campaign_fd, root_fd):
                if fd >= 0:
                    os.close(fd)


def validate_original(raw, complete):
    """Authenticate an exact preserved historical manifest, never rewrite it."""
    original = _strict_json(raw)
    if not isinstance(original, dict):
        raise ValueError("Invalid original campaign manifest")
    order = (
        "smoke",
        "screen",
        "refine",
        "confirmation",
        "sensitivity",
        "production",
        "complete",
    )
    if original.get("stage") not in order:
        raise ValueError("Invalid original campaign stage")
    a = deepcopy(original)
    b = deepcopy(complete)
    for value in (a, b):
        value.pop("stage", None)
        value.pop("stages", None)
    if a != b:
        raise ValueError("Original campaign identity differs")
    stages = original.get("stages", {})
    if not isinstance(stages, dict):
        raise ValueError("Invalid original stage registry")
    allowed = set(order[: order.index(original["stage"]) + 1])
    if original["stage"] == "complete":
        allowed.add("final_report")
    if any(k not in allowed or complete.get("stages", {}).get(k) != v for k, v in stages.items()):
        raise ValueError("Original campaign stages differ")
    if original["stage"] == "complete" and original != complete:
        raise ValueError("Original completed campaign differs")


def sync_identity(descriptor):
    return {
        "status": "synchronized",
        "commit": descriptor["commit"],
        "remote_receipt_sha256": descriptor["receipt_sha256"],
        "remote_receipt_digest": sha256(canonical_json(descriptor["receipt"])),
        "registry_sha256": descriptor["registry_sha256"],
        "bundle_sha256": descriptor["bundle"]["bundle_sha256"],
        "files": descriptor["files"],
    }


def validate_descriptor(response, root, campaign, commit, original):
    if (
        not isinstance(response, dict)
        or set(response) != {"descriptor", "chunk"}
        or response["chunk"] is not None
    ):
        raise error("remote_response_invalid")
    d = response["descriptor"]
    exact = {
        "campaign",
        "commit",
        "manifest",
        "receipt",
        "receipt_sha256",
        "files",
        "registry_sha256",
        "bundle",
        "production_identity",
        "branch",
    }
    if (
        not isinstance(d, dict)
        or set(d) != exact
        or d["campaign"] != campaign.relative_to(root).as_posix()
        or d["commit"] != commit
    ):
        raise error("remote_response_invalid")
    manifest = d["manifest"]
    if not isinstance(manifest, dict) or manifest.get("provenance", {}).get("git_commit") != commit:
        raise error("remote_response_invalid")
    # Only canonical stage evolution may differ from the frozen local bootstrap.
    a = deepcopy(manifest)
    b = deepcopy(original)
    for value in (a, b):
        value.pop("stage", None)
        value.pop("stages", None)
    if a != b or manifest.get("stage") != "complete":
        raise error("remote_response_invalid")
    rows = d["files"]
    if (
        not isinstance(rows, list)
        or not rows
        or len(rows) > 20000
        or any(
            not isinstance(r, dict)
            or set(r) != {"path", "size", "sha256"}
            or not isinstance(r["path"], str)
            or type(r["size"]) is not int
            or not 0 < r["size"] <= FILE_LIMIT
            or not isinstance(r["sha256"], str)
            or SHA.fullmatch(r["sha256"]) is None
            for r in rows
        )
        or [r["path"] for r in rows] != sorted({r["path"] for r in rows})
        or sum(r["size"] for r in rows) > TOTAL_LIMIT
        or d["registry_sha256"] != sha256(canonical_json(rows))
    ):
        raise error("remote_response_invalid")
    # Pure path ownership here; exact canonical sensitivity count is checked
    # against actual canonical artifacts before the manifest commit point.
    prefix = f"{d['campaign']}/"
    allowed_states = []
    for value in manifest["s0_values"]:
        path = survivor_states_directory(manifest, campaign, float(value))
        if not path.is_absolute():
            path = root / path
        allowed_states.append(path.relative_to(root).as_posix() + "/")
    for row in rows:
        path = PurePosixPath(row["path"])
        if (
            path.is_absolute()
            or path.as_posix() != row["path"]
            or any(p in {"", ".", ".."} for p in path.parts)
            or not (
                row["path"].startswith(prefix)
                or any(row["path"].startswith(s) for s in allowed_states)
            )
        ):
            raise error("remote_response_invalid")
    sensitivity_counts = {}
    for raw in manifest["s0_values"]:
        value = float(raw)
        key = f"s0_{value:.6f}".replace(".", "p")
        sensitivity_counts[value] = sum(
            r["path"].startswith(f"{d['campaign']}/sensitivity/{key}/") for r in rows
        )
    try:
        expected_paths = registry_paths(
            root, campaign, manifest, sensitivity_counts=sensitivity_counts
        )
    except (ValueError, TypeError, KeyError):
        raise error("remote_response_invalid") from None
    if {r["path"] for r in rows} != expected_paths:
        raise error("remote_response_invalid")
    bundle = d["bundle"]
    if (
        not isinstance(bundle, dict)
        or set(bundle) != {"version", "file_count", "uncompressed_bytes", "bundle_sha256", "chunks"}
        or type(bundle["version"]) is not int
        or bundle["version"] != 1
        or bundle["file_count"] != len(rows)
        or type(bundle["file_count"]) is not int
        or bundle["uncompressed_bytes"] != sum(r["size"] for r in rows)
        or not isinstance(bundle["bundle_sha256"], str)
        or not SHA.fullmatch(bundle["bundle_sha256"])
        or not isinstance(bundle["chunks"], list)
        or not 1 <= len(bundle["chunks"]) <= 32
    ):
        raise error("remote_response_invalid")
    for i, row in enumerate(bundle["chunks"]):
        if (
            not isinstance(row, dict)
            or set(row) != {"index", "size", "sha256"}
            or type(row["index"]) is not int
            or row["index"] != i
            or type(row["size"]) is not int
            or not 0 < row["size"] <= MAX_CHUNK_BYTES
            or not isinstance(row["sha256"], str)
            or not SHA.fullmatch(row["sha256"])
        ):
            raise error("remote_response_invalid")
    receipt = d["receipt"]
    if (
        not isinstance(receipt, dict)
        or receipt.get("status") != "campaign_complete"
        or receipt.get("commit") != commit
        or not isinstance(d["receipt_sha256"], str)
        or not SHA.fullmatch(d["receipt_sha256"])
        or not isinstance(receipt.get("nonce"), str)
        or re.fullmatch(r"[0-9a-f]{32}", receipt["nonce"]) is None
    ):
        raise error("remote_response_invalid")
    from workflow_api.zeus_finalization import (
        ZeusFinalizationCoordinator,
        RemoteProductionState,
    )
    from workflow_api.zeus_finalization_remote import completed_receipt_valid

    try:
        state = RemoteProductionState(
            "campaign_complete",
            receipt["scheduler"],
            receipt["evidence_digest"],
            receipt["files"],
            tuple(receipt["results"]),
            d["production_identity"],
            d["branch"],
            receipt,
        )
        ZeusFinalizationCoordinator._validate_state(state, manifest)
        key = sha256(
            canonical_json(
                {
                    "campaign": d["campaign"],
                    "commit": commit,
                    "production_submission_key": d["production_identity"]["submission_key"],
                    "production_submission_nonce": d["production_identity"]["submission_nonce"],
                    "production_job_id": d["production_identity"]["job_id"],
                    "evidence_digest": receipt["evidence_digest"],
                    "files": receipt["files"],
                    "results_digest": sha256(canonical_json(receipt["results"])),
                }
            )
        )
        submission = {
            "nonce": d["production_identity"]["submission_nonce"],
            "job_id": d["production_identity"]["job_id"],
        }
        if not completed_receipt_valid(
            receipt,
            key,
            commit,
            d["production_identity"],
            submission,
            receipt["evidence_digest"],
            receipt["files"],
            receipt["results"],
        ):
            raise ValueError("Invalid finalization receipt")
        registered = {r["path"]: r["sha256"] for r in rows}
        for name, digest in receipt["files"].items():
            if registered.get(f"{d['campaign']}/{name}") != digest:
                raise ValueError("Finalization file is not registered")
    except (ValueError, KeyError, TypeError):
        raise error("remote_response_invalid") from None
    return d
