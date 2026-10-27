"""Pinned receiver for validating and explicitly finalizing 2D Production."""

from __future__ import annotations

try:
    import fcntl
except ImportError:  # Only imported on Windows; remote execution remains POSIX.
    from workflow_api.platform_io import locking as fcntl
import hashlib
import json
import os
import re
import stat
import sys
import time
from pathlib import Path, PurePosixPath

from workflow_api.zeus_sensitivity_remote import (
    atomic_json,
    bounded,
    canonical_digest,
    fail,
    no_links,
    publish,
    run_captured,
    safe_status,
    scheduler_snapshot,
    timestamp,
)


def response(
    lifecycle,
    scheduler,
    evidence_digest,
    files,
    results,
    production_identity,
    branch,
    receipt,
):
    print(
        json.dumps(
            {
                "lifecycle": lifecycle,
                "scheduler": scheduler,
                "evidence_digest": evidence_digest,
                "files": files,
                "results": results,
                "production_identity": production_identity,
                "branch": branch,
                "receipt": receipt,
            }
        )
    )


def read_json(path: Path, limit: int = 8 * 1024 * 1024):
    try:
        return json.loads(bounded(path, limit))
    except SystemExit:
        raise
    except Exception:
        fail("finalization_conflict")


def validate_static(payload: dict, root: Path):
    exact = {"campaign", "commit"}
    optional = {
        "evidence_digest",
        "final_files",
        "results_digest",
        "finalization_key",
        "nonce",
    }
    if not exact.issubset(payload) or set(payload) - exact - optional:
        fail("invalid_request")
    relative = PurePosixPath(str(payload.get("campaign", "")))
    if (
        relative.is_absolute()
        or (len(relative.parts) != 4 and not (len(relative.parts) == 5 and relative.parts[3] == "ui_acceptance"))
        or relative.parts[:3] != ("data", "optimization", "mot_2d")
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        fail("invalid_request")
    commit = payload.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        fail("invalid_request")
    campaign = root.joinpath(*relative.parts)
    _authorize_acceptance_campaign(campaign, root)
    no_links(root, campaign)
    if not campaign.is_dir():
        fail("campaign_not_found")
    try:
        head = run_captured(
            ["/usr/bin/git", "rev-parse", "HEAD"], cwd=root, limit=4096, timeout=10
        )
        branch_row = run_captured(
            ["/usr/bin/git", "branch", "--show-current"],
            cwd=root,
            limit=4096,
            timeout=10,
        )
        worktree = run_captured(
            ["/usr/bin/git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root,
            limit=4 * 1024 * 1024,
            timeout=20,
        )
    except Exception:
        fail("local_checkout_mismatch")
    try:
        revision = head[1].decode("ascii", "strict").strip()
        branch = branch_row[1].decode("utf-8", "strict").strip()
    except UnicodeDecodeError:
        fail("local_checkout_mismatch")
    if (
        head[0]
        or head[2]
        or revision != commit
        or branch_row[0]
        or branch_row[2]
        or not branch
        or len(branch) > 256
        or not branch.isprintable()
        or worktree[0]
        or worktree[2]
        or not safe_status(worktree[1], root)
    ):
        fail("local_checkout_mismatch")

    transition = read_json(campaign / ".mot_ui/transitions/production.json")
    transition_exact = {
        "status",
        "nonce",
        "transition_key",
        "commit",
        "sensitivity_submission_key",
        "sensitivity_submission_nonce",
        "sensitivity_job_id",
        "rows_digest",
        "rows",
        "files",
        "scheduler",
        "completed_unix_s",
    }
    if (
        not isinstance(transition, dict)
        or set(transition) != transition_exact
        or transition.get("status") != "production_prepared"
        or transition.get("commit") != commit
        or not timestamp(transition.get("completed_unix_s"))
        or not re.fullmatch(r"[0-9a-f]{32}", str(transition.get("nonce")))
    ):
        fail("production_preparation_invalid")
    rows = transition.get("rows")
    rows_digest = transition.get("rows_digest")
    if (
        not isinstance(rows, list)
        or not re.fullmatch(r"[0-9a-f]{64}", str(rows_digest))
        or canonical_digest(rows) != rows_digest
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(transition.get("sensitivity_submission_key", ""))
        )
        or not re.fullmatch(
            r"[0-9a-f]{32}", str(transition.get("sensitivity_submission_nonce", ""))
        )
        or not re.fullmatch(
            r"\d+\[\]\.zeus-master", str(transition.get("sensitivity_job_id", ""))
        )
    ):
        fail("production_preparation_invalid")
    production_files = transition.get("files")
    expected = {
        "sensitivity_summary.json",
        "production/tasks.json",
        "jobs/06_production.pbs",
        "campaign.json",
    }
    if (
        not isinstance(production_files, dict)
        or set(production_files) != expected
        or any(
            not re.fullmatch(r"[0-9a-f]{64}", str(value))
            for value in production_files.values()
        )
    ):
        fail("production_preparation_invalid")
    expected_transition_key = canonical_digest(
        {
            "campaign": relative.as_posix(),
            "commit": commit,
            "sensitivity_submission_key": transition["sensitivity_submission_key"],
            "sensitivity_submission_nonce": transition["sensitivity_submission_nonce"],
            "sensitivity_job_id": transition["sensitivity_job_id"],
            "rows_digest": rows_digest,
            "files": production_files,
        }
    )
    if transition.get("transition_key") != expected_transition_key:
        fail("production_preparation_invalid")
    transition_digest = canonical_digest(transition)
    manifest = read_json(campaign / "campaign.json")
    if (
        not isinstance(manifest, dict)
        or manifest.get("stage") not in {"production", "complete"}
        or manifest.get("provenance", {}).get("git_commit") != commit
    ):
        fail("production_preparation_invalid")
    # Do not trust a self-consistent rewrite of the transition and submission
    # ledgers.  Re-derive the sensitivity rows from their sealed task/result
    # evidence and require the historical receipt to contain those exact rows.
    try:
        prior_sensitivity = json.loads(json.dumps(manifest))
        prior_sensitivity["stage"] = "sensitivity"
        prior_sensitivity.get("stages", {}).pop("production", None)
        prior_sensitivity.get("stages", {}).pop("final_report", None)
        from workflow_api.mot_2d_validation import validated_evaluation_outputs

        authoritative_rows = validated_evaluation_outputs(
            campaign, prior_sensitivity, "sensitivity"
        )
    except Exception:
        fail("production_preparation_invalid")
    if transition["rows"] != authoritative_rows:
        fail("production_preparation_invalid")
    for name, digest in production_files.items():
        if manifest.get("stage") == "complete" and name == "campaign.json":
            prior = json.loads(json.dumps(manifest))
            prior["stage"] = "production"
            prior.get("stages", {}).pop("final_report", None)
            data = (json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()
        else:
            data = bounded(campaign / name)
        if hashlib.sha256(data).hexdigest() != digest:
            fail("production_preparation_invalid")
    submission = read_json(campaign / ".mot_ui/submissions/production.json")
    submission_exact = {
        "version",
        "status",
        "submission_key",
        "transition_nonce",
        "transition_digest",
        "pbs_sha256",
        "nonce",
        "job_file",
        "commit",
        "created_unix_s",
        "job_id",
        "completed_unix_s",
    }
    if (
        not isinstance(submission, dict)
        or set(submission) != submission_exact
        or submission.get("version") != 1
        or submission.get("status") != "submitted"
        or submission.get("transition_nonce") != transition["nonce"]
        or submission.get("transition_digest") != transition_digest
        or submission.get("pbs_sha256") != production_files["jobs/06_production.pbs"]
        or submission.get("job_file") != f"{relative.as_posix()}/jobs/06_production.pbs"
        or submission.get("commit") != commit
        or not re.fullmatch(r"\d+\[\]\.zeus-master", str(submission.get("job_id")))
        or not re.fullmatch(r"[0-9a-f]{32}", str(submission.get("nonce")))
        or not timestamp(submission.get("created_unix_s"))
        or not timestamp(submission.get("completed_unix_s"))
        or submission["completed_unix_s"] < submission["created_unix_s"]
    ):
        fail("production_submission_invalid")
    expected_submission_key = canonical_digest(
        {
            "campaign": relative.as_posix(),
            "commit": commit,
            "transition_nonce": transition["nonce"],
            "transition_digest": transition_digest,
            "files": production_files,
            "job_file": "jobs/06_production.pbs",
        }
    )
    if submission.get("submission_key") != expected_submission_key:
        fail("production_submission_invalid")
    identity = {
        "production_files": production_files,
        "transition_nonce": transition["nonce"],
        "transition_digest": transition_digest,
        "submission_key": submission["submission_key"],
        "submission_nonce": submission["nonce"],
        "job_id": submission["job_id"],
    }
    return campaign, manifest, branch, submission, relative, identity


def scheduler(root: Path, manifest: dict, submission: dict):
    count = 20 * len(manifest["s0_values"])
    try:
        code, stdout, stderr = run_captured(
            ["/opt/pbs/bin/qstat", "-x", "-t", "-f", submission["job_id"]],
            cwd=root,
            limit=4 * 1024 * 1024,
            timeout=20,
        )
        if code or stderr:
            raise ValueError()
        row = scheduler_snapshot(stdout, submission["job_id"], count)
    except Exception:
        row = {
            "state": "unknown",
            "task_count": count,
            "counts": {
                "queued": 0,
                "running": 0,
                "held": 0,
                "succeeded": 0,
                "failed": 0,
            },
            "job_id": submission["job_id"],
        }
    row["submission_nonce"] = submission["nonce"]
    return row


def raw_evidence_paths(campaign: Path, manifest: dict, root: Path):
    paths = [
        campaign / "campaign.json",
        campaign / "sensitivity_summary.json",
        campaign / "production/tasks.json",
    ]
    for frozen in manifest["input_ensembles"]["sealed_validation"]:
        paths.extend((root / frozen["path"], root / frozen["metadata_path"]))
    for value in manifest["s0_values"]:
        key = f"s0_{float(value):.6f}".replace(".", "p")
        label = f"{float(value):.6f}".rstrip("0").rstrip(".")
        replicate = campaign / "production" / key / "replicates"
        from workflow_api.mot_2d_spec import survivor_states_directory
        states = survivor_states_directory(manifest, campaign, float(value))
        if not states.is_absolute():
            states = root / states
        for seed, mot_seed in zip(
            manifest["seed_roles"]["sealed_validation"],
            manifest["mot_seeds"]["sealed_validation"],
        ):
            paths.append(replicate / f"zeeman_seed{seed}.json")
            state = (
                states / f"mot_2d_survivors_zeeman_seed{seed}_mot_seed{mot_seed}.npy"
            )
            paths.extend((state, state.with_suffix(".json")))
    return paths


def _open_evidence(campaign: Path, manifest: dict, root: Path):
    """Open and retain every evidence inode across validation and rendering."""
    opened = []
    digest = hashlib.sha256()
    try:
        for path in raw_evidence_paths(campaign, manifest, root):
            no_links(root, path)
            fd = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
            )
            info = os.fstat(fd)
            limit = 8 * 1024**3 if path.suffix == ".npy" else 64 * 1024**2
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                os.close(fd)
                raise ValueError("invalid evidence file")
            identity = (
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )
            opened.append((path, fd, identity))
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(b"\0")
            if path == campaign / "campaign.json":
                digest.update(
                    (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
                )
            else:
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            digest.update(b"\0")
        return opened, digest.hexdigest()
    except Exception:
        for _, fd, _ in opened:
            os.close(fd)
        raise


def _verify_evidence(opened, *, ignore_paths=()) -> None:
    ignored = set(ignore_paths)
    for path, fd, identity in opened:
        if path in ignored:
            continue
        current = os.fstat(fd)
        path_info = path.lstat()
        observed = (
            current.st_dev,
            current.st_ino,
            current.st_size,
            current.st_mtime_ns,
            current.st_ctime_ns,
        )
        if (
            observed != identity
            or stat.S_ISLNK(path_info.st_mode)
            or (path_info.st_dev, path_info.st_ino) != identity[:2]
        ):
            raise ValueError("evidence changed during finalization")


def derive(campaign: Path, manifest: dict, root: Path, *, retain_evidence=False):
    prior = json.loads(json.dumps(manifest))
    if prior.get("stage") == "complete":
        prior["stage"] = "production"
        prior.get("stages", {}).pop("final_report", None)
    from workflow_api.mot_2d_plan import render_finalization

    opened, evidence = _open_evidence(campaign, prior, root)
    try:
        files, results = render_finalization(prior, campaign, root)
        _verify_evidence(opened)
        if retain_evidence:
            return prior, files, results, evidence, opened
    finally:
        if not retain_evidence:
            for _, fd, _ in opened:
                os.close(fd)
    return prior, files, results, evidence


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"inspect", "prepare"}:
        fail("invalid_request")
    operation = sys.argv[1]
    try:
        raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError()
        payload = json.loads(raw)
    except Exception:
        fail("invalid_request")
    if not isinstance(payload, dict):
        fail("invalid_request")
    root = Path.cwd().resolve(strict=True)
    campaign, manifest, branch, submission, relative, identity = validate_static(
        payload, root
    )
    current_scheduler = scheduler(root, manifest, submission)
    state = campaign / ".mot_ui"
    transitions = state / "transitions"
    receipt_path = transitions / "finalization.json"
    pending_path = transitions / "finalization.pending.json"
    lock_path = transitions / "finalization.lock"
    for path in (state, transitions, receipt_path, pending_path, lock_path):
        no_links(campaign, path)

    receipt = read_json(receipt_path) if receipt_path.exists() else None
    if receipt is not None or manifest.get("stage") == "complete":
        try:
            _, files, results, evidence = derive(campaign, manifest, root)
            hashes = {
                name: hashlib.sha256(data).hexdigest() for name, data in files.items()
            }
            results_digest = canonical_digest(results)
            key = canonical_digest(
                {
                    "campaign": relative.as_posix(),
                    "commit": payload["commit"],
                    "production_submission_key": identity["submission_key"],
                    "production_submission_nonce": submission["nonce"],
                    "production_job_id": submission["job_id"],
                    "evidence_digest": evidence,
                    "files": hashes,
                    "results_digest": results_digest,
                }
            )
            # Inspection is strictly read-only, including crash recovery.  Expose
            # the already-published, fully revalidated plan so a new explicit
            # prepare request can complete the durable pending transaction.
            if receipt is None and pending_path.exists() and operation == "inspect":
                response(
                    "ready_to_finalize",
                    current_scheduler,
                    evidence,
                    hashes,
                    results,
                    identity,
                    branch,
                    None,
                )
                return
            if receipt is None and pending_path.exists():
                if (
                    payload.get("evidence_digest") != evidence
                    or payload.get("final_files") != hashes
                    or payload.get("results_digest") != results_digest
                    or payload.get("finalization_key") != key
                    or not re.fullmatch(r"[0-9a-f]{32}", str(payload.get("nonce", "")))
                ):
                    fail("finalization_conflict")
                pending = read_json(pending_path)
                pending_exact = {
                    "status",
                    "nonce",
                    "finalization_key",
                    "production_submission_key",
                    "production_submission_nonce",
                    "production_job_id",
                    "evidence_digest",
                    "files",
                    "results_digest",
                    "scheduler",
                    "created_unix_s",
                }
                if (
                    not isinstance(pending, dict)
                    or set(pending) != pending_exact
                    or pending.get("status") != "finalization_pending"
                    or pending.get("finalization_key") != key
                    or pending.get("production_submission_key")
                    != identity["submission_key"]
                    or pending.get("production_submission_nonce") != submission["nonce"]
                    or pending.get("production_job_id") != submission["job_id"]
                    or pending.get("evidence_digest") != evidence
                    or pending.get("files") != hashes
                    or pending.get("results_digest") != results_digest
                    or not timestamp(pending.get("created_unix_s"))
                    or any(
                        hashlib.sha256(bounded(campaign / name)).hexdigest() != digest
                        for name, digest in hashes.items()
                    )
                ):
                    raise ValueError()
                receipt = {
                    "status": "campaign_complete",
                    "nonce": pending["nonce"],
                    "finalization_key": key,
                    "commit": payload["commit"],
                    "production_submission_key": identity["submission_key"],
                    "production_submission_nonce": submission["nonce"],
                    "production_job_id": submission["job_id"],
                    "evidence_digest": evidence,
                    "files": hashes,
                    "results_digest": results_digest,
                    "results": results,
                    "scheduler": pending["scheduler"],
                    "completed_unix_s": int(time.time()),
                }
                atomic_json(receipt_path, receipt)
                pending_path.unlink()
            exact = {
                "status",
                "nonce",
                "finalization_key",
                "commit",
                "production_submission_key",
                "production_submission_nonce",
                "production_job_id",
                "evidence_digest",
                "files",
                "results_digest",
                "results",
                "scheduler",
                "completed_unix_s",
            }
            if (
                not isinstance(receipt, dict)
                or set(receipt) != exact
                or receipt.get("status") != "campaign_complete"
                or receipt.get("finalization_key") != key
                or receipt.get("commit") != payload["commit"]
                or receipt.get("production_submission_key")
                != identity["submission_key"]
                or receipt.get("production_submission_nonce") != submission["nonce"]
                or receipt.get("production_job_id") != submission["job_id"]
                or receipt.get("evidence_digest") != evidence
                or receipt.get("files") != hashes
                or receipt.get("results_digest") != results_digest
                or receipt.get("results") != results
                or not timestamp(receipt.get("completed_unix_s"))
            ):
                raise ValueError()
            response(
                "campaign_complete",
                receipt["scheduler"],
                evidence,
                hashes,
                results,
                identity,
                branch,
                receipt,
            )
            return
        except Exception:
            fail("finalization_outcome_unknown")

    lifecycle = {
        "queued": "queued",
        "running": "running",
        "held": "held",
        "completed_failed": "failed",
        "unknown": "status_unknown",
        "completed_success": "complete",
    }.get(current_scheduler["state"], "status_unknown")
    files = {}
    results = []
    evidence = ""
    if lifecycle == "complete":
        try:
            _, rendered, results, evidence = derive(campaign, manifest, root)
            files = {
                name: hashlib.sha256(data).hexdigest()
                for name, data in rendered.items()
            }
        except FileNotFoundError:
            lifecycle = "awaiting_outputs"
        except Exception:
            lifecycle = "outputs_invalid"
        else:
            lifecycle = "ready_to_finalize"
    if operation == "inspect" or lifecycle != "ready_to_finalize":
        response(
            lifecycle,
            current_scheduler,
            evidence,
            files,
            results,
            identity,
            branch,
            None,
        )
        return

    results_digest = canonical_digest(results)
    finalization_key = canonical_digest(
        {
            "campaign": relative.as_posix(),
            "commit": payload["commit"],
            "production_submission_key": identity["submission_key"],
            "production_submission_nonce": submission["nonce"],
            "production_job_id": submission["job_id"],
            "evidence_digest": evidence,
            "files": files,
            "results_digest": results_digest,
        }
    )
    if (
        payload.get("evidence_digest") != evidence
        or payload.get("final_files") != files
        or payload.get("results_digest") != results_digest
        or payload.get("finalization_key") != finalization_key
        or not re.fullmatch(r"[0-9a-f]{32}", str(payload.get("nonce", "")))
    ):
        fail("finalization_conflict")
    transitions.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(
        lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        fail("finalization_busy")
    try:
        locked_scheduler = scheduler(root, manifest, submission)
        if (
            locked_scheduler != current_scheduler
            or locked_scheduler["state"] != "completed_success"
        ):
            fail("production_status_unknown")
        (
            locked_manifest,
            locked_rendered,
            locked_results,
            locked_evidence,
            evidence_fds,
        ) = derive(campaign, manifest, root, retain_evidence=True)
        locked_hashes = {
            name: hashlib.sha256(data).hexdigest()
            for name, data in locked_rendered.items()
        }
        if (
            locked_evidence != evidence
            or locked_hashes != files
            or locked_results != results
        ):
            fail("finalization_conflict")
        if receipt_path.exists() or pending_path.exists():
            fail("finalization_outcome_unknown")
        pending = {
            "status": "finalization_pending",
            "nonce": payload["nonce"],
            "finalization_key": finalization_key,
            "production_submission_key": identity["submission_key"],
            "production_submission_nonce": submission["nonce"],
            "production_job_id": submission["job_id"],
            "evidence_digest": evidence,
            "files": files,
            "results_digest": results_digest,
            "scheduler": current_scheduler,
            "created_unix_s": int(time.time()),
        }
        atomic_json(pending_path, pending)
        for name, data in locked_rendered.items():
            target = campaign / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if name == "campaign.json":
                temporary = campaign / f".campaign.{payload['nonce']}.tmp"
                with temporary.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            else:
                publish(target, data, 0o644)
        _verify_evidence(evidence_fds, ignore_paths=(campaign / "campaign.json",))
        receipt = {
            "status": "campaign_complete",
            "nonce": payload["nonce"],
            "finalization_key": finalization_key,
            "commit": payload["commit"],
            "production_submission_key": identity["submission_key"],
            "production_submission_nonce": submission["nonce"],
            "production_job_id": submission["job_id"],
            "evidence_digest": evidence,
            "files": files,
            "results_digest": results_digest,
            "results": results,
            "scheduler": current_scheduler,
            "completed_unix_s": int(time.time()),
        }
        atomic_json(receipt_path, receipt)
        pending_path.unlink()
        descriptor = os.open(transitions, os.O_RDONLY)
        os.fsync(descriptor)
        os.close(descriptor)
        for _, evidence_fd, _ in evidence_fds:
            os.close(evidence_fd)
        evidence_fds = []
    finally:
        for _, evidence_fd, _ in locals().get("evidence_fds", []):
            os.close(evidence_fd)
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    response(
        "campaign_complete",
        current_scheduler,
        evidence,
        files,
        results,
        identity,
        branch,
        receipt,
    )



def _authorize_acceptance_campaign(campaign, root):
    """Authenticate acceptance before locks, publication, or scheduler mutation."""
    try:
        from workflow_api.acceptance_profile import assert_scientific_source, is_acceptance_manifest
        current = root
        for part in campaign.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError('Unsafe campaign path.')
        manifest_path = campaign / 'campaign.json'
        if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Unsafe campaign manifest.')
        value = json.loads(manifest_path.read_text(encoding='utf-8'))
        if is_acceptance_manifest(value) or 'acceptance' in value or 'execution_checkout' in value or root.name in ('ytterbium_lab_simulation_ui_acceptance', 'ytterbium_lab_simulation_ui_test') or 'ui_acceptance' in campaign.parts:
            from workflow_api.acceptance_remote import assert_campaign_target
            from workflow_api.mot_2d_spec import validate_campaign_policy
            validate_campaign_policy(value)
            assert_campaign_target(value, root.parent.name, root, campaign)
        else:
            assert_scientific_source(value)
    except (OSError, ValueError, TypeError, KeyError):
        fail('remote_preparation_invalid')

if __name__ == "__main__":
    main()
