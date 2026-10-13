"""Pinned receiver for verified Preliminary Check -> Refinement transition.

Read operations never create state. PREPARE publishes generated artifacts with
no-replace semantics, commits campaign.json last with compare-and-swap, and
records success only after re-verifying the exact 160-file transfer registry.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
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
    MAX_REVIEWED_FILE_BYTES,
    MAX_TOTAL_BYTES,
    MAX_REVIEWED_TOTAL_BYTES,
    build_artifact_bundle,
)

HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_FILE = 2 * 1024 * 1024


@dataclass(frozen=True)
class TransitionDescriptor:
    """Immutable stage policy for the hardened selection-stage transition engine."""

    from_stage: str
    to_stage: str
    sync_name: str
    source_result_count: int
    transfer_file_count: int
    source_submission_receipt: str
    prior_local_sync_receipt: str
    generated_paths: frozenset[str]
    source_identity_paths: frozenset[str]
    code_paths: frozenset[str]
    prepared_status: str
    pending_status: str
    error_prefix: str
    selection_stage: str
    prior_transition_name: str
    prior_transition_status: str
    prior_transition_file_count: int
    bundle_max_total_bytes: int = MAX_TOTAL_BYTES
    submission_evidence: str = "family_chain"
    artifact_max_file_bytes: int = MAX_FILE
    workflow_kind: str = "selection_transition"
    terminal_statuses: frozenset[str] = frozenset()
    generated_file_count: int | None = None

    def __post_init__(self):
        safe = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
        if any(
            type(value) is not str or safe.fullmatch(value) is None
            for value in (
                self.from_stage,
                self.to_stage,
                self.sync_name,
                self.prepared_status,
                self.pending_status,
                self.error_prefix,
                self.selection_stage,
                self.prior_transition_name,
                self.prior_transition_status,
            )
        ):
            raise ValueError("invalid transition descriptor")
        if (
            type(self.source_result_count) is not int
            or self.source_result_count <= 0
            or type(self.transfer_file_count) is not int
            or self.transfer_file_count
            != self.source_result_count
            + 1
            + (
                len(self.generated_paths)
                if self.generated_file_count is None
                else self.generated_file_count
            )
            or not _safe_relative(self.source_submission_receipt)
            or type(self.prior_local_sync_receipt) is not str
            or not self.prior_local_sync_receipt.startswith(".mot_ui/sync/")
            or not self.prior_local_sync_receipt.endswith(".json")
            or type(self.generated_paths) is not frozenset
            or type(self.source_identity_paths) is not frozenset
            or type(self.code_paths) is not frozenset
            or not 2 <= len(self.generated_paths) <= 16
            or type(self.prior_transition_file_count) is not int
            or self.prior_transition_file_count <= 0
            or self.bundle_max_total_bytes
            not in {MAX_TOTAL_BYTES, MAX_REVIEWED_TOTAL_BYTES}
            or self.submission_evidence not in {"family_chain", "linear_chain"}
            or self.artifact_max_file_bytes not in {MAX_FILE, MAX_REVIEWED_FILE_BYTES}
            or self.workflow_kind
            not in {"selection_transition", "final_validation_completion"}
            or type(self.terminal_statuses) is not frozenset
            or (
                self.workflow_kind == "final_validation_completion"
                and (
                    self.generated_file_count != 2
                    or self.terminal_statuses
                    != frozenset({"complete", "final_validation_extension_required"})
                )
            )
        ):
            raise ValueError("invalid transition descriptor")

    @property
    def pending_name(self) -> str:
        return f"{self.sync_name}.pending.json"

    @property
    def final_name(self) -> str:
        return f"{self.sync_name}.json"

    @property
    def bundle_name(self) -> str:
        return f"{self.sync_name}.bundle.gz"

    @property
    def lock_name(self) -> str:
        return f"{self.sync_name}.lock"

    def error(self, suffix: str) -> str:
        return f"{self.error_prefix}_{suffix}"


_DESCRIPTOR: ContextVar[TransitionDescriptor] = ContextVar(
    "mot3d_transition_descriptor"
)


def _descriptor() -> TransitionDescriptor:
    try:
        return _DESCRIPTOR.get()
    except LookupError:
        return preliminary_transition_descriptor()


@contextmanager
def descriptor_scope(descriptor: TransitionDescriptor):
    token = _DESCRIPTOR.set(descriptor)
    try:
        yield descriptor
    finally:
        _DESCRIPTOR.reset(token)


def render_refinement_transition(*args, **kwargs):
    """Load the study renderer only inside the pinned receiver process."""

    from studies.mot_3d_campaign import render_refinement_transition as render

    return render(*args, **kwargs)


def _selection_path(family: str) -> str:
    return f"selection/{_descriptor().selection_stage}/{family}.json"


def _receipt_status_valid(status: object) -> bool:
    descriptor = _descriptor()
    return (
        status == descriptor.prepared_status or status in descriptor.terminal_statuses
    )


def _generated_paths_valid(paths: object) -> bool:
    descriptor = _descriptor()
    if type(paths) is not set:
        paths = set(paths)
    if descriptor.workflow_kind != "final_validation_completion":
        return paths == descriptor.generated_paths
    return paths in (
        {"campaign.json", "final_report.json"},
        {"campaign.json", "final_validation_status.json"},
    )


def _terminal_status(files: Mapping[str, object]) -> str:
    descriptor = _descriptor()
    if descriptor.workflow_kind != "final_validation_completion":
        return descriptor.prepared_status
    if "final_report.json" in files:
        return "complete"
    if "final_validation_status.json" in files:
        return "final_validation_extension_required"
    fail(descriptor.error("outcome_unknown"))


def _completion_terminals(campaign_fd: int) -> dict[str, bytes]:
    if _descriptor().workflow_kind != "final_validation_completion":
        return {}
    found = {}
    for name in ("final_report.json", "final_validation_status.json"):
        if not regular_exists_at(campaign_fd, name):
            continue
        try:
            found[name] = read_relative_at(campaign_fd, name, MAX_FILE)
        except Exception:
            fail(_descriptor().error("outcome_unknown"))
    return found


def _result_paths(selections):
    if _descriptor().workflow_kind == "final_validation_completion":
        from workflow_api.mot_3d_final_validation_results import (
            expected_paths as final_validation_paths,
        )

        return final_validation_paths()
    if _descriptor().submission_evidence == "linear_chain":
        from workflow_api.mot_3d_final_input_results import (
            expected_paths as input_paths,
        )

        return input_paths()
    if _descriptor().from_stage == "preliminary_check":
        return expected_paths(selections)
    if _descriptor().from_stage == "closure":
        from workflow_api.mot_3d_closure_results import expected_paths as closure_paths

        return closure_paths(selections)
    if _descriptor().from_stage == "finalist_selection":
        from workflow_api.mot_3d_finalist_results import (
            expected_paths as finalist_paths,
        )

        return finalist_paths(selections)
    from workflow_api.mot_3d_refinement_results import (
        expected_paths as refinement_paths,
    )

    return refinement_paths(selections)


def _validate_results(
    manifest_raw, selections, results, project_directory, campaign_path
):
    manifest = json_bytes(manifest_raw, error=_descriptor().error("conflict"))
    if _descriptor().workflow_kind == "final_validation_completion":
        from workflow_api.mot_3d_final_validation_results import (
            validate_final_validation_result_bytes,
        )

        validated = validate_final_validation_result_bytes(
            manifest_bytes=manifest_raw,
            locked_nominals_bytes=selections["locked_nominals"],
            input_manifest_bytes=selections["input_manifest"],
            generation_submission_bytes=selections["generation_submission"],
            submission_bytes=selections["submission"],
            job_files=selections["job_files"],
            input_files=selections["input_files"],
            result_files=results,
            logical_campaign_root=f"data/optimization/mot_3d/{manifest.get('name')}",
            project_directory=str(project_directory),
            campaign_absolute_path=str(campaign_path),
        )
    elif _descriptor().submission_evidence == "linear_chain":
        from workflow_api.mot_3d_final_input_results import (
            validate_final_input_result_bytes,
        )

        validated = validate_final_input_result_bytes(
            manifest_bytes=manifest_raw,
            locked_nominals_bytes=selections["locked_nominals"],
            submission_bytes=selections["submission"],
            result_files=results,
            campaign_absolute_path=str(campaign_path),
            project_directory=str(project_directory),
        )
    elif _descriptor().from_stage == "preliminary_check":
        particle = expected_preliminary_particle_selection(
            manifest, project_directory=str(project_directory)
        )
        validated = validate_preliminary_result_bytes(
            manifest_bytes=manifest_raw,
            selection_bytes=selections,
            result_files=results,
            expected_particle_selection=particle,
            campaign_absolute_path=str(campaign_path),
            project_directory=str(project_directory),
        )
    elif _descriptor().from_stage == "refinement":
        from workflow_api.mot_3d_refinement_results import (
            validate_refinement_result_bytes,
        )

        validated = validate_refinement_result_bytes(
            manifest_bytes=manifest_raw,
            selection_bytes=selections,
            result_files=results,
            campaign_absolute_path=str(campaign_path),
            project_directory=str(project_directory),
        )
    elif _descriptor().from_stage == "closure":
        from workflow_api.mot_3d_closure_results import validate_closure_result_bytes

        validated = validate_closure_result_bytes(
            manifest_bytes=manifest_raw,
            selection_bytes=selections,
            result_files=results,
            campaign_absolute_path=str(campaign_path),
            project_directory=str(project_directory),
        )
    else:
        from workflow_api.mot_3d_finalist_results import validate_finalist_result_bytes

        validated = validate_finalist_result_bytes(
            manifest_bytes=manifest_raw,
            selection_bytes=selections,
            result_files=results,
            campaign_absolute_path=str(campaign_path),
            project_directory=str(project_directory),
        )
    return manifest, validated


def _render_transition(relative, manifest, validated, manifest_raw):
    if _descriptor().workflow_kind == "final_validation_completion":
        return {
            "campaign.json": validated.campaign_bytes,
            validated.terminal_name: validated.terminal_bytes,
        }, validated.outcome
    if _descriptor().submission_evidence == "linear_chain":
        from studies.mot_3d_campaign import render_final_validation_transition

        return render_final_validation_transition(relative, manifest)
    summaries = validated.summaries
    if _descriptor().to_stage == "refinement":
        return render_refinement_transition(relative, manifest, summaries)
    if _descriptor().to_stage == "closure":
        from studies.mot_3d_campaign import render_closure_transition

        return render_closure_transition(relative, manifest, summaries)
    if _descriptor().to_stage == "final_validation_input_generation":
        from studies.mot_3d_campaign import render_final_validation_input_transition

        summary_hashes = {
            family: validated.hashes[
                f"finalist_selection/{family}/merged/finalist_summary.json"
            ]
            for family in FAMILIES
        }
        return render_final_validation_input_transition(
            relative,
            manifest,
            summaries,
            summary_hashes,
            hashlib.sha256(manifest_raw).hexdigest(),
        )
    from studies.mot_3d_campaign import render_finalist_selection_transition

    return render_finalist_selection_transition(relative, manifest, summaries)


PRELIMINARY_GENERATED_PATHS = frozenset(
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
PRELIMINARY_SOURCE_IDENTITY_PATHS = frozenset(
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
PRELIMINARY_CODE_PATHS = frozenset(
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
# Backward-compatible public constants used by the Stage-3 characterization
# harness. Runtime policy is always read from the bound immutable descriptor.
GENERATED_PATHS = PRELIMINARY_GENERATED_PATHS
SOURCE_IDENTITY_PATHS = PRELIMINARY_SOURCE_IDENTITY_PATHS
CODE_PATHS = PRELIMINARY_CODE_PATHS
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


def preliminary_transition_descriptor() -> TransitionDescriptor:
    return TransitionDescriptor(
        from_stage="preliminary_check",
        to_stage="refinement",
        sync_name="refinement",
        source_result_count=152,
        transfer_file_count=160,
        source_submission_receipt="preliminary_check_submission.json",
        prior_local_sync_receipt=".mot_ui/sync/discovery_to_preliminary.json",
        generated_paths=PRELIMINARY_GENERATED_PATHS,
        source_identity_paths=PRELIMINARY_SOURCE_IDENTITY_PATHS,
        code_paths=PRELIMINARY_CODE_PATHS,
        prepared_status="refinement_prepared",
        pending_status="refinement_pending",
        error_prefix="preliminary_transition",
        selection_stage="discovery",
        prior_transition_name="preliminary_check",
        prior_transition_status="preliminary_check_prepared",
        prior_transition_file_count=961,
    )


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
        or not file_count
        <= value["uncompressed_bytes"]
        <= _descriptor().bundle_max_total_bytes
        or not isinstance(value["bundle_sha256"], str)
        or HEX64.fullmatch(value["bundle_sha256"]) is None
        or not isinstance(value["chunks"], list)
        or not 1
        <= len(value["chunks"])
        <= _descriptor().bundle_max_total_bytes // MAX_CHUNK_BYTES
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
        fail(_descriptor().error("outcome_unknown"))
    if regular_exists_at(parent, name):
        if (
            identical_ok
            and bounded_at(parent, name, max(MAX_TOTAL_BYTES, len(raw))) == raw
        ):
            return
        fail(_descriptor().error("conflict"))
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
        fail(_descriptor().error("conflict"))
    except OSError:
        fail(_descriptor().error("outcome_unknown"))
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
        fail(_descriptor().error("conflict"))
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
            fail(_descriptor().error("conflict"))
        now = os.stat("campaign.json", dir_fd=campaign_fd, follow_symlinks=False)
        if (now.st_dev, now.st_ino, now.st_ctime_ns) != (
            before.st_dev,
            before.st_ino,
            before.st_ctime_ns,
        ):
            fail(_descriptor().error("conflict"))
        os.replace(
            temporary, "campaign.json", src_dir_fd=campaign_fd, dst_dir_fd=campaign_fd
        )
        os.fsync(campaign_fd)
    except OSError:
        fail(_descriptor().error("outcome_unknown"))
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
    if _descriptor().submission_evidence == "linear_chain":
        return _exact_linear_submission(campaign_fd, submission_key, commit)
    submissions_fd = _open_submissions(campaign_fd)
    try:
        final = strict_json_at(
            submissions_fd,
            f"{_descriptor().from_stage}.json",
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
            fail(_descriptor().error("conflict"))
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
                fail(_descriptor().error("conflict"))
            numeric = {row["array"].split("[", 1)[0], row["merge"].split(".", 1)[0]}
            if seen & numeric:
                fail(_descriptor().error("conflict"))
            seen |= numeric
            for kind in ("array", "merge"):
                step = strict_json_at(
                    submissions_fd,
                    f"{_descriptor().from_stage}_{family}_{kind}.json",
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
                    campaign_fd,
                    f"jobs/{_descriptor().from_stage}/{family}_{kind}.pbs",
                    MAX_FILE,
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
                    fail(_descriptor().error("conflict"))
                previous_completed = step["completed_unix_s"]
        compatibility = json_bytes(
            read_relative_at(
                campaign_fd, _descriptor().source_submission_receipt, MAX_FILE
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
            error=_descriptor().error("conflict"),
        )
        if compatibility != {
            "kind": "mot_3d_selection_stage_submission",
            "stage": _descriptor().from_stage,
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
            fail(_descriptor().error("conflict"))
        return final, jobs
    finally:
        os.close(submissions_fd)


def _exact_linear_submission(campaign_fd: int, submission_key: str, commit: str):
    """Validate the exact durable three-step submission evidence."""
    from workflow_api.mot_3d_linear_submission_remote import (
        ARRAY as LINEAR_ARRAY,
        SCALAR as LINEAR_SCALAR,
        STEPS,
    )

    submissions_fd = _open_submissions(campaign_fd)
    try:
        final = strict_json_at(
            submissions_fd,
            f"{_descriptor().from_stage}.json",
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
        jobs = final.get("jobs")
        if (
            type(final.get("version")) is not int
            or final["version"] != 1
            or final.get("status") != "submitted"
            or final.get("submission_key") != submission_key
            or final.get("commit") != commit
            or type(final.get("nonce")) is not str
            or HEX32.fullmatch(final["nonce"]) is None
            or not stamp(final.get("created_unix_s"))
            or not stamp(final.get("submitted_unix_s"))
            or final["submitted_unix_s"] < final["created_unix_s"]
            or not isinstance(jobs, dict)
            or set(jobs) != set(STEPS)
        ):
            fail(_descriptor().error("conflict"))
        seen = set()
        previous = final["created_unix_s"]
        for index, step_name in enumerate(STEPS):
            job = jobs[step_name]
            pattern = LINEAR_ARRAY if index < 2 else LINEAR_SCALAR
            if type(job) is not str or pattern.fullmatch(job) is None:
                fail(_descriptor().error("conflict"))
            number = job.split("[", 1)[0].split(".", 1)[0]
            if number in seen:
                fail(_descriptor().error("conflict"))
            seen.add(number)
            receipt = strict_json_at(
                submissions_fd,
                f"{_descriptor().from_stage}_{step_name}.json",
                keys={
                    "status",
                    "submission_key",
                    "nonce",
                    "commit",
                    "step",
                    "pbs_sha256",
                    "depends_on",
                    "created_unix_s",
                    "job_id",
                    "completed_unix_s",
                },
            )
            dependency = None if index == 0 else jobs[STEPS[index - 1]]
            pbs = read_relative_at(
                campaign_fd,
                f"jobs/final_validation_inputs/{index + 1:02d}_{('generate_zeeman', 'generate_2d_survivors', 'freeze_inputs')[index]}.pbs",
                MAX_FILE,
            )
            if (
                receipt.get("status") != "submitted"
                or receipt.get("submission_key") != submission_key
                or receipt.get("nonce") != final["nonce"]
                or receipt.get("commit") != commit
                or receipt.get("step") != step_name
                or receipt.get("pbs_sha256") != _sha(pbs)
                or receipt.get("depends_on") != dependency
                or receipt.get("job_id") != job
                or not stamp(receipt.get("created_unix_s"))
                or not stamp(receipt.get("completed_unix_s"))
                or not previous
                <= receipt["created_unix_s"]
                <= receipt["completed_unix_s"]
                <= final["submitted_unix_s"]
            ):
                fail(_descriptor().error("conflict"))
            previous = receipt["completed_unix_s"]
        compatibility = json_bytes(
            read_relative_at(
                campaign_fd, _descriptor().source_submission_receipt, MAX_FILE
            ),
            keys={
                "kind",
                "status",
                "submission_key",
                "nonce",
                "commit",
                "created_unix_s",
                "zeeman_array_job_id",
                "mot_array_job_id",
                "freeze_job_id",
            },
            error=_descriptor().error("conflict"),
        )
        if compatibility != {
            "kind": "mot_3d_final_validation_input_submission",
            "status": "submitted",
            "submission_key": submission_key,
            "nonce": final["nonce"],
            "commit": commit,
            "created_unix_s": final["created_unix_s"],
            "zeeman_array_job_id": jobs["zeeman"],
            "mot_array_job_id": jobs["mot_2d"],
            "freeze_job_id": jobs["freeze"],
        }:
            fail(_descriptor().error("conflict"))
        return final, jobs
    finally:
        os.close(submissions_fd)


def _scheduler(jobs):
    if _descriptor().submission_evidence == "linear_chain":
        from workflow_api.mot_3d_linear_submission_remote import scheduler_state

        return scheduler_state(jobs, run=run)
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
    winner_selection=None,
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
                "winner_selection": winner_selection,
            },
            separators=(",", ":"),
        )
    )


def _terminal_counts() -> tuple[int, int]:
    return (40, 1) if _descriptor().submission_evidence == "linear_chain" else (6, 2)


def _winner_from_validated(validated):
    if _descriptor().workflow_kind == "final_validation_completion":
        return {
            "outcome": validated.outcome,
            "families": [
                {
                    "family": family,
                    "candidate_id": validated.summaries[family]["candidate_id"],
                    "conditional_efficiency": validated.summaries[family][
                        "conditional_efficiency"
                    ],
                    "bootstrap_95_ci": validated.summaries[family]["bootstrap_95_ci"],
                    "ci_half_width": validated.summaries[family]["ci_half_width"],
                    "precision_target_met": validated.summaries[family][
                        "precision_target_met"
                    ],
                }
                for family in FAMILIES
            ],
            "evidence_sha256": validated.evidence_sha256,
        }
    if _descriptor().from_stage != "finalist_selection":
        return None
    return _winner_selection_from_summaries(
        validated.summaries, validated.evidence_sha256
    )


def _winner_selection_from_summaries(summaries, evidence):
    if _descriptor().from_stage != "finalist_selection":
        return None
    from studies.mot_3d.finalists.merge import FINALIST_WINNER_RANKING_RULE

    winners = []
    for family in FAMILIES:
        summary = summaries[family]
        candidate = summary["ranked_candidates"][0]["candidate_id"]
        if (
            type(candidate) is not str
            or re.fullmatch(rf"{re.escape(family)}_finalist_0[1-3]", candidate) is None
        ):
            fail(_descriptor().error("conflict"))
        winners.append({"family": family, "candidate_id": candidate})
    return {
        "rule": FINALIST_WINNER_RANKING_RULE,
        "winners": winners,
        "evidence_sha256": evidence,
    }


def _winner_selection_from_published(campaign_fd, evidence):
    if _descriptor().workflow_kind == "final_validation_completion":
        terminal = None
        outcome = None
        terminals = _completion_terminals(campaign_fd)
        for name, candidate in (
            ("final_report.json", "complete"),
            ("final_validation_status.json", "final_validation_extension_required"),
        ):
            if name not in terminals:
                continue
            value = json_bytes(
                terminals[name], error=_descriptor().error("outcome_unknown")
            )
            if terminal is not None:
                fail(_descriptor().error("outcome_unknown"))
            terminal, outcome = value, candidate
        if terminal is None:
            fail(_descriptor().error("outcome_unknown"))
        return {
            "outcome": outcome,
            "families": [
                {
                    "family": family,
                    "candidate_id": terminal["results"][family]["candidate_id"],
                    "conditional_efficiency": terminal["results"][family][
                        "conditional_efficiency"
                    ],
                    "bootstrap_95_ci": terminal["results"][family]["bootstrap_95_ci"],
                    "ci_half_width": terminal["results"][family]["ci_half_width"],
                    "precision_target_met": terminal["results"][family][
                        "precision_target_met"
                    ],
                }
                for family in FAMILIES
            ],
            "evidence_sha256": evidence,
        }
    if _descriptor().from_stage != "finalist_selection":
        return None
    from studies.mot_3d.finalists.merge import FINALIST_WINNER_RANKING_RULE

    locked = json_bytes(
        read_relative_at(campaign_fd, "selection/locked_nominals.json", MAX_FILE),
        error=_descriptor().error("outcome_unknown"),
    )
    families = locked.get("families")
    if (
        locked.get("kind") != "mot_3d_locked_nominals"
        or not isinstance(families, dict)
        or set(families) != set(FAMILIES)
    ):
        fail(_descriptor().error("outcome_unknown"))
    winners = []
    for family in FAMILIES:
        row = families[family]
        candidate = row.get("candidate_id") if isinstance(row, dict) else None
        if (
            type(candidate) is not str
            or re.fullmatch(rf"{re.escape(family)}_finalist_0[1-3]", candidate) is None
        ):
            fail(_descriptor().error("outcome_unknown"))
        winners.append({"family": family, "candidate_id": candidate})
    return {
        "rule": FINALIST_WINNER_RANKING_RULE,
        "winners": winners,
        "evidence_sha256": evidence,
    }


def _identity(
    payload,
    campaign_fd: int,
    root_fd: int,
    *,
    advanced_campaign_sha256: str | None = None,
):
    identity = payload.get("identity")
    stage1_keys = {"stage1_receipt_sha256", "stage1_bundle_sha256"}
    stage3_keys = {
        "stage3_local_sync_receipt_sha256",
        "stage3_remote_receipt_sha256",
        "stage3_bundle_sha256",
        "stage4_submission_identity",
    }
    extra_keys = (
        stage1_keys if _descriptor().from_stage == "preliminary_check" else stage3_keys
    )
    stage4 = (
        identity.get("stage4_submission_identity")
        if isinstance(identity, dict)
        else None
    )
    stage4_keys = {
        "campaign_sha256",
        "local_transition_receipt_sha256",
        "transition_key",
        "remote_transition_receipt_sha256",
        "bundle_sha256",
        "files",
        "science",
        "physical_model_sha256",
        "upstream_campaign_sha256",
        "upstream_final_report_sha256",
        "timestep_policy_sha256",
        "code_files",
    }
    stage4_valid = _descriptor().from_stage == "preliminary_check" or (
        isinstance(stage4, dict)
        and set(stage4) == stage4_keys
        and all(
            type(stage4[key]) is str and HEX64.fullmatch(stage4[key]) is not None
            for key in stage4_keys - {"files", "science", "code_files"}
        )
        and isinstance(stage4["files"], dict)
        and set(stage4["files"]) == _descriptor().source_identity_paths
        and all(
            type(value) is str and HEX64.fullmatch(value) is not None
            for value in stage4["files"].values()
        )
        and isinstance(stage4["code_files"], dict)
        and all(
            type(name) is str
            and _safe_relative(name)
            and type(value) is str
            and HEX64.fullmatch(value) is not None
            for name, value in stage4["code_files"].items()
        )
        and isinstance(stage4["science"], dict)
        and _stage4_key_matches(payload, stage4)
    )
    if (
        not isinstance(identity, dict)
        or set(identity) != {"source_files", "code_files"} | extra_keys
        or not isinstance(identity["source_files"], dict)
        or set(identity["source_files"]) != _descriptor().source_identity_paths
        or not isinstance(identity["code_files"], dict)
        or set(identity["code_files"]) != _descriptor().code_paths
        or any(
            type(value) is not str or HEX64.fullmatch(value) is None
            for value in identity["source_files"].values()
        )
        or any(
            type(value) is not str or HEX64.fullmatch(value) is None
            for value in identity["code_files"].values()
        )
        or any(
            type(identity[key]) is not str or HEX64.fullmatch(identity[key]) is None
            for key in extra_keys - {"stage4_submission_identity"}
        )
        or not stage4_valid
    ):
        fail("invalid_request")
    frozen = {}
    for name, expected in identity["source_files"].items():
        raw = read_relative_at(campaign_fd, name, MAX_FILE)
        accepted = {expected}
        if name == "campaign.json" and advanced_campaign_sha256 is not None:
            accepted.add(advanced_campaign_sha256)
        if _sha(raw) not in accepted:
            fail(_descriptor().error("conflict"))
        frozen[name] = raw
    for name, expected in identity["code_files"].items():
        if _sha(read_relative_at(root_fd, name, MAX_FILE)) != expected:
            fail(_descriptor().error("conflict"))
    transition = read_relative_at(
        campaign_fd,
        f".mot_ui/transitions/{_descriptor().prior_transition_name}.json",
        MAX_FILE,
    )
    if _descriptor().workflow_kind == "final_validation_completion":
        transition_row = json_bytes(
            transition,
            keys=FINAL_KEYS,
            error=_descriptor().error("conflict"),
        )
    else:
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
            error=_descriptor().error("conflict"),
        )
    stage1_bundle = read_relative_at(
        campaign_fd,
        f".mot_ui/transitions/{_descriptor().prior_transition_name}.bundle.gz",
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
    if _descriptor().workflow_kind == "final_validation_completion":
        if (
            _sha(transition) != identity["stage3_remote_receipt_sha256"]
            or transition_row["status"] != _descriptor().prior_transition_status
            or transition_row["commit"] != payload["commit"]
            or type(transition_row["nonce"]) is not str
            or HEX32.fullmatch(transition_row["nonce"]) is None
            or type(transition_row["transition_key"]) is not str
            or HEX64.fullmatch(transition_row["transition_key"]) is None
            or not stamp(transition_row["completed_unix_s"])
            or not _exact_bundle(
                transition_row["bundle"],
                file_count=_descriptor().prior_transition_file_count,
            )
            or _sha(stage1_bundle) != identity["stage3_bundle_sha256"]
            or transition_row["bundle"]["bundle_sha256"]
            != identity["stage3_bundle_sha256"]
            or transition_row["bundle"]["chunks"] != expected_chunks
        ):
            fail(_descriptor().error("conflict"))
    elif (
        _sha(transition)
        != identity[
            (
                "stage1_receipt_sha256"
                if _descriptor().from_stage == "preliminary_check"
                else "stage3_remote_receipt_sha256"
            )
        ]
        or transition_row["status"] != _descriptor().prior_transition_status
        or transition_row["commit"] != payload["commit"]
        or (
            _descriptor().from_stage == "preliminary_check"
            and transition_row["submission_key"] != payload["submission_key"]
        )
        or type(transition_row["submission_key"]) is not str
        or HEX64.fullmatch(transition_row["submission_key"]) is None
        or type(transition_row["nonce"]) is not str
        or HEX32.fullmatch(transition_row["nonce"]) is None
        or type(transition_row["transition_key"]) is not str
        or HEX64.fullmatch(transition_row["transition_key"]) is None
        or type(transition_row["bootstrap_digest"]) is not str
        or HEX64.fullmatch(transition_row["bootstrap_digest"]) is None
        or not stamp(transition_row["completed_unix_s"])
        or not isinstance(transition_row["chain"], dict)
        or set(transition_row["chain"]) != set(FAMILIES)
        or any(
            not isinstance(transition_row["chain"][family], list)
            or len(transition_row["chain"][family])
            != (2 if family == "angled_donut" else 3)
            or any(
                type(job) is not str or ARRAY.fullmatch(job) is None
                for job in transition_row["chain"][family]
            )
            for family in FAMILIES
        )
        or not _exact_bundle(
            bundle, file_count=_descriptor().prior_transition_file_count
        )
        or bundle["bundle_sha256"]
        != identity[
            (
                "stage1_bundle_sha256"
                if _descriptor().from_stage == "preliminary_check"
                else "stage3_bundle_sha256"
            )
        ]
        or _sha(stage1_bundle)
        != identity[
            (
                "stage1_bundle_sha256"
                if _descriptor().from_stage == "preliminary_check"
                else "stage3_bundle_sha256"
            )
        ]
        or bundle["chunks"] != expected_chunks
    ):
        fail(_descriptor().error("conflict"))
    expected_key = digest(
        {
            "campaign": payload["campaign"],
            "commit": payload["commit"],
            "submission_key": payload["submission_key"],
            "identity": identity,
        }
    )
    if expected_key != payload["transition_key"]:
        fail(_descriptor().error("conflict"))
    return identity, frozen


def _stage4_key_matches(payload: object, stage4_identity: object) -> bool:
    if not isinstance(payload, dict) or not isinstance(stage4_identity, dict):
        return False
    return digest(
        {
            "campaign": payload.get("campaign"),
            "commit": payload.get("commit"),
            **stage4_identity,
        }
    ) == payload.get("submission_key")


def _capture(
    campaign_fd: int,
    project_directory: Path,
    campaign_absolute_path: Path,
    manifest_raw: bytes,
):
    manifest = json_bytes(manifest_raw, error=_descriptor().error("conflict"))
    if _descriptor().workflow_kind == "final_validation_completion":
        from workflow_api.mot_3d_final_input_results import (
            expected_paths as final_input_paths,
        )

        selections = {
            "locked_nominals": read_relative_at(
                campaign_fd, "selection/locked_nominals.json", MAX_FILE
            ),
            "input_manifest": read_relative_at(
                campaign_fd, "final_validation_inputs/input_manifest.json", MAX_FILE
            ),
            "generation_submission": read_relative_at(
                campaign_fd,
                "final_validation_input_generation_submission.json",
                MAX_FILE,
            ),
            "submission": read_relative_at(
                campaign_fd, _descriptor().source_submission_receipt, MAX_FILE
            ),
            "job_files": {
                f"jobs/final_validation/{family}_{kind}.pbs": read_relative_at(
                    campaign_fd,
                    f"jobs/final_validation/{family}_{kind}.pbs",
                    MAX_FILE,
                )
                for family in FAMILIES
                for kind in ("array", "merge")
            },
            "input_files": {
                name: read_relative_at(campaign_fd, name, MAX_REVIEWED_FILE_BYTES)
                for name in final_input_paths()
            },
        }
        parsed = None
    elif _descriptor().submission_evidence == "linear_chain":
        selections = {
            "locked_nominals": read_relative_at(
                campaign_fd, "selection/locked_nominals.json", MAX_FILE
            ),
            "submission": read_relative_at(
                campaign_fd, _descriptor().source_submission_receipt, MAX_FILE
            ),
        }
        parsed = None
    else:
        selections = {
            family: read_relative_at(campaign_fd, _selection_path(family), MAX_FILE)
            for family in FAMILIES
        }
        parsed = {
            family: json_bytes(raw, error=_descriptor().error("conflict"))
            for family, raw in selections.items()
        }
    results = {
        name: read_relative_at(campaign_fd, name, _descriptor().artifact_max_file_bytes)
        for name in _result_paths(parsed)
    }
    manifest, validated = _validate_results(
        manifest_raw, selections, results, project_directory, campaign_absolute_path
    )
    return manifest, results, validated


def _verify_success(campaign_fd: int, transitions_fd: int, payload, receipt):
    if (
        set(receipt) != FINAL_KEYS
        or type(receipt["version"]) is not int
        or receipt["version"] != 1
        or not _receipt_status_valid(receipt["status"])
        or receipt["transition_key"] != payload["transition_key"]
        or receipt["commit"] != payload["commit"]
        or receipt["submission_key"] != payload["submission_key"]
        or receipt["identity_sha256"] != digest(payload["identity"])
        or any(
            type(receipt[key]) is not str or HEX64.fullmatch(receipt[key]) is None
            for key in (
                "identity_sha256",
                "old_campaign_sha256",
                "new_campaign_sha256",
                "evidence_sha256",
            )
        )
        or type(receipt["nonce"]) is not str
        or HEX32.fullmatch(receipt["nonce"]) is None
        or not stamp(receipt["completed_unix_s"])
        or not isinstance(receipt["files"], dict)
        or len(receipt["files"]) != _descriptor().transfer_file_count
        or any(
            not _safe_relative(name)
            or type(value) is not str
            or HEX64.fullmatch(value) is None
            for name, value in receipt["files"].items()
        )
        or not _exact_bundle(
            receipt["bundle"], file_count=_descriptor().transfer_file_count
        )
    ):
        fail(_descriptor().error("outcome_unknown"))
    selections = (
        None
        if _descriptor().submission_evidence == "linear_chain"
        or _descriptor().workflow_kind == "final_validation_completion"
        else {
            family: json_bytes(
                read_relative_at(campaign_fd, _selection_path(family), MAX_FILE),
                error=_descriptor().error("outcome_unknown"),
            )
            for family in FAMILIES
        }
    )
    generated = (
        set(receipt["files"])
        - set(_result_paths(selections))
        - {_descriptor().source_submission_receipt}
    )
    exact_paths = (
        set(_result_paths(selections))
        | {_descriptor().source_submission_receipt}
        | generated
    )
    if set(receipt["files"]) != exact_paths or not _generated_paths_valid(generated):
        fail(_descriptor().error("outcome_unknown"))
    if _descriptor().workflow_kind == "final_validation_completion":
        terminal = _completion_terminals(campaign_fd)
        expected_terminal = generated - {"campaign.json"}
        if set(terminal) != expected_terminal:
            fail(_descriptor().error("outcome_unknown"))
    for name, expected in receipt["files"].items():
        if (
            _sha(
                read_relative_at(
                    campaign_fd, name, _descriptor().artifact_max_file_bytes
                )
            )
            != expected
        ):
            fail(_descriptor().error("outcome_unknown"))
    packed = bounded_at(
        transitions_fd,
        _descriptor().bundle_name,
        _descriptor().bundle_max_total_bytes,
    )
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
        or not _exact_bundle(bundle, file_count=_descriptor().transfer_file_count)
        or bundle.get("chunks") != expected_chunks
        or receipt["new_campaign_sha256"] != receipt["files"].get("campaign.json")
    ):
        fail(_descriptor().error("outcome_unknown"))
    return packed, chunks


def _transition_names(transitions_fd: int) -> set[str]:
    try:
        names = set(os.listdir(transitions_fd))
    except OSError:
        fail(_descriptor().error("outcome_unknown"))
    relevant = {
        name
        for name in names
        if name.startswith(_descriptor().sync_name)
        or name.startswith(f".{_descriptor().sync_name}")
    }
    allowed = {
        _descriptor().lock_name,
        _descriptor().pending_name,
        _descriptor().final_name,
        _descriptor().bundle_name,
    }
    if not relevant <= allowed:
        fail(_descriptor().error("outcome_unknown"))
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
        or type(payload.get("commit")) is not str
        or HEX40.fullmatch(payload["commit"]) is None
        or type(payload.get("submission_key")) is not str
        or HEX64.fullmatch(payload["submission_key"]) is None
        or type(payload.get("transition_key")) is not str
        or HEX64.fullmatch(payload["transition_key"]) is None
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
                fail(_descriptor().error("outcome_unknown"))
        receipt = None
        pending_receipt = None
        transition_names = (
            _transition_names(transitions_fd) if transitions_fd >= 0 else set()
        )
        if (
            _descriptor().final_name in transition_names
            and _descriptor().bundle_name not in transition_names
        ) or (
            _descriptor().bundle_name in transition_names
            and not {
                _descriptor().pending_name,
                _descriptor().final_name,
            }
            & transition_names
        ):
            fail(_descriptor().error("outcome_unknown"))
        if transitions_fd >= 0 and regular_exists_at(
            transitions_fd, _descriptor().final_name
        ):
            receipt = strict_json_at(
                transitions_fd,
                _descriptor().final_name,
                keys=FINAL_KEYS,
                limit=MAX_FILE,
            )
            if (
                receipt["transition_key"] != payload["transition_key"]
                or receipt["commit"] != payload["commit"]
                or receipt["submission_key"] != payload["submission_key"]
                or receipt["identity_sha256"] != digest(payload["identity"])
                or type(receipt["new_campaign_sha256"]) is not str
                or HEX64.fullmatch(receipt["new_campaign_sha256"]) is None
            ):
                fail(_descriptor().error("outcome_unknown"))
        if transitions_fd >= 0 and regular_exists_at(
            transitions_fd, _descriptor().pending_name
        ):
            pending_receipt = strict_json_at(
                transitions_fd,
                _descriptor().pending_name,
                keys=PENDING_KEYS,
                limit=MAX_FILE,
            )
            if (
                type(pending_receipt["version"]) is not int
                or pending_receipt["version"] != 1
                or pending_receipt["status"] != _descriptor().pending_status
                or pending_receipt["transition_key"] != payload["transition_key"]
                or pending_receipt["commit"] != payload["commit"]
                or pending_receipt["submission_key"] != payload["submission_key"]
                or pending_receipt["identity_sha256"] != digest(payload["identity"])
                or type(pending_receipt["nonce"]) is not str
                or HEX32.fullmatch(pending_receipt["nonce"]) is None
                or not stamp(pending_receipt["created_unix_s"])
                or any(
                    type(pending_receipt[key]) is not str
                    or HEX64.fullmatch(pending_receipt[key]) is None
                    for key in (
                        "identity_sha256",
                        "old_campaign_sha256",
                        "new_campaign_sha256",
                        "evidence_sha256",
                    )
                )
                or not isinstance(pending_receipt["files"], dict)
                or len(pending_receipt["files"]) != _descriptor().transfer_file_count
                or any(
                    not _safe_relative(name)
                    or type(value) is not str
                    or HEX64.fullmatch(value) is None
                    for name, value in pending_receipt["files"].items()
                )
                or not isinstance(pending_receipt["bundle"], dict)
            ):
                fail(_descriptor().error("outcome_unknown"))
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
                fail(_descriptor().error("outcome_unknown"))
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
                    fail(_descriptor().error("outcome_unknown"))
                cleanup_lock = os.open(
                    _descriptor().lock_name,
                    os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=transitions_fd,
                )
                try:
                    fcntl.flock(cleanup_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    unlink_at(transitions_fd, _descriptor().pending_name)
                except BlockingIOError:
                    fail(_descriptor().error("busy"))
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
                    receipt["status"],
                    branch,
                    jobs,
                    *_terminal_counts(),
                    validation="valid",
                    evidence=receipt["evidence_sha256"],
                    receipt=receipt,
                    bundle=receipt["bundle"],
                    chunk=chunk,
                    winner_selection=_winner_selection_from_published(
                        campaign_fd, receipt["evidence_sha256"]
                    ),
                )
                return
            _response(
                receipt["status"],
                branch,
                jobs,
                *_terminal_counts(),
                validation="valid",
                evidence=receipt["evidence_sha256"],
                receipt=receipt,
                bundle=receipt["bundle"],
                winner_selection=_winner_selection_from_published(
                    campaign_fd, receipt["evidence_sha256"]
                ),
            )
            return
        if operation == "retrieve":
            fail(_descriptor().error("not_prepared"))
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
                fail(_descriptor().error("outcome_unknown"))
            lock_fd = os.open(
                _descriptor().lock_name,
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
                        "status": _terminal_status(pending_receipt["files"]),
                        "completed_unix_s": int(time.time()),
                    }
                )
                _verify_success(campaign_fd, transitions_fd, payload, receipt)
                _publish_bytes(
                    transitions_fd,
                    _descriptor().final_name,
                    canonical(receipt) + b"\n",
                    identical_ok=True,
                )
                receipt = strict_json_at(
                    transitions_fd,
                    _descriptor().final_name,
                    keys=FINAL_KEYS,
                    limit=MAX_FILE,
                )
                _verify_success(campaign_fd, transitions_fd, payload, receipt)
                unlink_at(transitions_fd, _descriptor().pending_name)
            except BlockingIOError:
                fail(_descriptor().error("busy"))
            finally:
                os.close(lock_fd)
            _response(
                receipt["status"],
                branch,
                jobs,
                *_terminal_counts(),
                validation="valid",
                evidence=receipt["evidence_sha256"],
                receipt=receipt,
                bundle=receipt["bundle"],
                winner_selection=_winner_selection_from_published(
                    campaign_fd, receipt["evidence_sha256"]
                ),
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
                *_terminal_counts(),
                validation="scientifically_invalid",
                reason=getattr(exc, "code", "result_registry_invalid"),
            )
            return
        if operation in {"inspect", "status"}:
            _response(
                "ready_to_advance",
                branch,
                jobs,
                *_terminal_counts(),
                validation="valid",
                evidence=validated.evidence_sha256,
                winner_selection=_winner_from_validated(validated),
            )
            return
        if (
            type(payload.get("nonce")) is not str
            or HEX32.fullmatch(payload["nonce"]) is None
        ):
            fail("invalid_request")
        lock_fd = os.open(
            _descriptor().lock_name,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=transitions_fd,
        )
        try:
            row = os.fstat(lock_fd)
            if not stat.S_ISREG(row.st_mode) or row.st_nlink != 1:
                fail(_descriptor().error("outcome_unknown"))
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for name, raw in frozen.items():
                if read_relative_at(campaign_fd, name, MAX_FILE) != raw:
                    fail(_descriptor().error("conflict"))
            _identity(payload, campaign_fd, root_fd)
            _exact_stage2(campaign_fd, payload["submission_key"], payload["commit"])
            if _scheduler(jobs) != ("completed_success_unvalidated", 6, 2):
                fail(_descriptor().error("conflict"))
            generated, _render_metadata = _render_transition(
                relative, manifest, validated, frozen["campaign.json"]
            )
            terminal_status = _terminal_status(generated)
            if not _generated_paths_valid(set(generated)):
                fail(_descriptor().error("conflict"))
            if _descriptor().workflow_kind == "final_validation_completion":
                existing_terminals = _completion_terminals(campaign_fd)
                selected_terminal = set(generated) - {"campaign.json"}
                if any(name not in selected_terminal for name in existing_terminals):
                    fail(_descriptor().error("conflict"))
                if existing_terminals and pending_receipt is None:
                    fail(_descriptor().error("conflict"))
                if any(
                    existing_terminals[name] != generated[name]
                    for name in existing_terminals
                ):
                    fail(_descriptor().error("conflict"))
            files = dict(results)
            files[_descriptor().source_submission_receipt] = read_relative_at(
                campaign_fd, _descriptor().source_submission_receipt, MAX_FILE
            )
            files.update(generated)
            parsed = (
                None
                if _descriptor().submission_evidence == "linear_chain"
                or _descriptor().workflow_kind == "final_validation_completion"
                else {
                    family: json_bytes(
                        read_relative_at(
                            campaign_fd, _selection_path(family), MAX_FILE
                        ),
                        error=_descriptor().error("conflict"),
                    )
                    for family in FAMILIES
                }
            )
            expected_transfer = (
                frozenset(_result_paths(parsed))
                | {_descriptor().source_submission_receipt}
                | frozenset(generated)
            )
            if (
                set(files) != expected_transfer
                or len(files) != _descriptor().transfer_file_count
            ):
                fail(_descriptor().error("conflict"))
            built = build_artifact_bundle(
                files,
                campaign=relative.name,
                commit=payload["commit"],
                from_stage=_descriptor().from_stage,
                to_stage=(
                    terminal_status
                    if _descriptor().workflow_kind == "final_validation_completion"
                    else _descriptor().to_stage
                ),
                expected_paths=expected_transfer,
                max_total_bytes=_descriptor().bundle_max_total_bytes,
                max_file_bytes=_descriptor().artifact_max_file_bytes,
            )
            hashes = {name: _sha(raw) for name, raw in files.items()}
            pending = {
                "version": 1,
                "status": _descriptor().pending_status,
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
            if regular_exists_at(transitions_fd, _descriptor().pending_name):
                current = strict_json_at(
                    transitions_fd,
                    _descriptor().pending_name,
                    keys=set(pending),
                    limit=MAX_FILE,
                )
                if {k: v for k, v in current.items() if k != "created_unix_s"} != {
                    k: v for k, v in pending.items() if k != "created_unix_s"
                }:
                    fail(_descriptor().error("outcome_unknown"))
                pending = current
            else:
                _publish_bytes(
                    transitions_fd,
                    _descriptor().pending_name,
                    canonical(pending) + b"\n",
                    identical_ok=False,
                )
            for name in sorted(set(generated) - {"campaign.json"}):
                _publish_relative(campaign_fd, name, generated[name])
            _publish_bytes(
                transitions_fd,
                _descriptor().bundle_name,
                built.packed,
                identical_ok=True,
            )
            _replace_campaign(campaign_fd, manifest_raw, generated["campaign.json"])
            receipt = {
                k: v
                for k, v in pending.items()
                if k not in {"status", "created_unix_s", "bundle"}
            }
            receipt.update(
                {
                    "status": terminal_status,
                    "bundle": built.manifest,
                    "completed_unix_s": int(time.time()),
                }
            )
            _verify_success(campaign_fd, transitions_fd, payload, receipt)
            _publish_bytes(
                transitions_fd,
                _descriptor().final_name,
                canonical(receipt) + b"\n",
                identical_ok=True,
            )
            receipt = strict_json_at(
                transitions_fd,
                _descriptor().final_name,
                keys=FINAL_KEYS,
                limit=MAX_FILE,
            )
            _verify_success(campaign_fd, transitions_fd, payload, receipt)
            unlink_at(transitions_fd, _descriptor().pending_name)
        except BlockingIOError:
            fail(_descriptor().error("busy"))
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        _response(
            receipt["status"],
            branch,
            jobs,
            *_terminal_counts(),
            validation="valid",
            evidence=receipt["evidence_sha256"],
            receipt=receipt,
            bundle=receipt["bundle"],
            winner_selection=_winner_selection_from_published(
                campaign_fd, receipt["evidence_sha256"]
            ),
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
