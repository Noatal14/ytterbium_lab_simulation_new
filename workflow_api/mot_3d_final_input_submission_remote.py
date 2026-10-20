"""Pinned receiver for the canonical three-step final-input chain."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import time

from workflow_api import mot_3d_linear_submission_remote as linear
from workflow_api.mot_3d_final_input_submission import CODE_FILES, FILES
from workflow_api.mot_3d_finalist_results import expected_paths
from workflow_api.mot_3d_preliminary_transition_remote import FINAL_KEYS, _exact_bundle
from workflow_api.mot_3d_selection_submission_remote import (
    DIR_FLAGS,
    bounded_at,
    canonical,
    digest,
    exact_match,
    json_bytes,
    open_dir_at,
    read_relative_at,
    regular_exists_at,
    run,
    strict_json_at,
)
from workflow_api.verified_artifact_bundle import unpack_artifact_bundle

HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
STAGE = "final_validation_input_generation"
TRANSITION = "finalist_selection_to_final_validation_inputs.json"
JOB_PATHS = {
    "zeeman": "jobs/final_validation_inputs/01_generate_zeeman.pbs",
    "mot_2d": "jobs/final_validation_inputs/02_generate_2d_survivors.pbs",
    "freeze": "jobs/final_validation_inputs/03_freeze_inputs.pbs",
}
DESCRIPTOR = linear.LinearDescriptor(
    stage=STAGE,
    receipt_kind="mot_3d_final_validation_input_submission",
    error_prefix="final_input_submission",
    steps=(
        linear.LinearStep("zeeman", JOB_PATHS["zeeman"], "array", 20, None),
        linear.LinearStep("mot_2d", JOB_PATHS["mot_2d"], "array", 20, "zeeman"),
        linear.LinearStep("freeze", JOB_PATHS["freeze"], "scalar", 1, "mot_2d"),
    ),
)
IDENTITY_KEYS = {
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


def fail(code: str, status: int = 20) -> None:
    print(json.dumps({"error": code}))
    raise SystemExit(status)


def _safe_identity(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == IDENTITY_KEYS
        and all(
            exact_match(HEX64, value.get(key))
            for key in IDENTITY_KEYS - {"files", "science", "code_files"}
        )
        and isinstance(value["files"], dict)
        and set(value["files"]) == FILES
        and all(exact_match(HEX64, digest) for digest in value["files"].values())
        and isinstance(value["code_files"], dict)
        and set(value["code_files"]) == CODE_FILES
        and all(exact_match(HEX64, digest) for digest in value["code_files"].values())
        and isinstance(value["science"], dict)
    )


def _expected_science(manifest: dict) -> dict:
    from workflow_api.mot_3d_workload import generation_science

    return generation_science(
        manifest,
        {
            "classification": "new_unopened_inputs_after_nominal_lock",
            "zeeman_seeds": list(range(3035, 3055)),
            "mot_seeds": list(range(43035, 43055)),
            "zeeman_tasks": 20,
            "mot_tasks": 20,
            "npools": 200,
            "dependency": "afterok linear chain",
            "resources": {
                "zeeman": {"ncpus": 200, "memory_gb": 64, "walltime": "08:00:00"},
                "mot_2d": {"ncpus": 200, "memory_gb": 64, "walltime": "12:00:00"},
                "freeze": {"ncpus": 1, "memory_gb": 8, "walltime": "00:30:00"},
            },
        },
    )


def _response(state: linear.LinearState) -> None:
    print(
        json.dumps(
            {
                "lifecycle": state.lifecycle,
                "branch": state.branch,
                "jobs": dict(state.jobs),
                "nonce": state.nonce,
                "submitted_unix_s": state.submitted_unix_s,
                "completed_array_tasks": state.completed_array_tasks,
                "completed_scalar_jobs": state.completed_scalar_jobs,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def main(*, trusted_root_override=None):
    if len(sys.argv) != 5 or sys.argv[1] not in {"inspect", "submit", "status"}:
        fail("invalid_request")
    operation, username, project, encoded = sys.argv[1:]
    if re.fullmatch(
        r"[A-Za-z][A-Za-z0-9._-]{0,31}", username
    ) is None or project not in {
        f"/home/{username}/ytterbium_lab_simulation_new",
        f"/home/{username}/ytterbium_lab_simulation_ui_acceptance",
    }:
        fail("invalid_request")
    try:
        raw = (
            sys.stdin.buffer.read(1024 * 1024 + 1)
            if encoded == "-"
            else base64.urlsafe_b64decode(encoded)
        )
        if len(raw) > 1024 * 1024:
            raise ValueError
        payload = json.loads(raw.decode("utf-8", "strict"))
        relative = PurePosixPath(payload["campaign"])
        requested = Path(project)
        root = (
            Path(trusted_root_override).resolve(strict=True)
            if trusted_root_override is not None
            else requested.resolve(strict=True)
        )
    except Exception:
        fail("invalid_request")
    keys = {"campaign", "commit", "submission_key", "identity"} | (
        {"nonce"} if operation == "submit" else set()
    )
    if (
        not isinstance(payload, dict)
        or set(payload) != keys
        or (trusted_root_override is None and root != requested)
        or relative.is_absolute()
        or not (
            len(relative.parts) == 4
            or (len(relative.parts) == 5 and relative.parts[3] == "ui_acceptance")
        )
        or relative.parts[:3] != ("data", "optimization", "mot_3d")
        or any(part in {"", ".", ".."} for part in relative.parts)
        or not exact_match(HEX40, payload.get("commit"))
        or not exact_match(HEX64, payload.get("submission_key"))
        or (operation == "submit" and not exact_match(HEX32, payload.get("nonce")))
        or not _safe_identity(payload.get("identity"))
    ):
        fail("invalid_request")
    identity = payload["identity"]
    root_fd = os.open(root, DIR_FLAGS)
    opened: list[int] = []
    campaign_fd = root_fd
    try:
        for part in relative.parts:
            campaign_fd = open_dir_at(campaign_fd, part)
            opened.append(campaign_fd)
        revision = run(
            ["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"], limit=4096
        )
        branch_row = run(
            ["/usr/bin/git", "-C", str(root), "branch", "--show-current"], limit=4096
        )
        dirty = run(
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
        branch = (
            branch_row[1].decode("utf-8", "strict").strip()
            if not branch_row[0] and not branch_row[2]
            else ""
        )
        if (
            revision[0]
            or revision[2]
            or revision[1].decode("ascii", "strict").strip() != payload["commit"]
            or not branch
            or len(branch) > 256
            or not branch.isprintable()
            or dirty[0]
            or dirty[2]
            or dirty[1]
        ):
            fail("remote_checkout_mismatch")
        manifest_raw = read_relative_at(campaign_fd, "campaign.json")
        manifest = json_bytes(manifest_raw, error="final_input_preparation_invalid")
        from workflow_api.acceptance_remote import assert_campaign_target

        try:
            from workflow_api.mot_3d_workload import assert_receiver_target

            assert_receiver_target(
                manifest,
                username,
                project,
                relative,
                trusted_root_override=trusted_root_override,
            )
        except ValueError:
            fail("final_input_preparation_invalid")
        upstream = manifest.get("upstream_2d_campaign", {})
        stage = manifest.get("stages", {}).get(STAGE, {})
        logical = relative.as_posix()
        if (
            manifest.get("stage") != STAGE
            or manifest.get("name") != relative.name
            or manifest.get("provenance", {}).get("git_commit") != payload["commit"]
            or manifest.get("provenance", {}).get("physical_model_sha256")
            != identity["physical_model_sha256"]
            or upstream.get("campaign_sha256") != identity["upstream_campaign_sha256"]
            or upstream.get("final_report_sha256")
            != identity["upstream_final_report_sha256"]
            or manifest.get("design", {})
            .get("timestep_evidence", {})
            .get("policy_sha256")
            != identity["timestep_policy_sha256"]
            or identity["science"] != _expected_science(manifest)
            or identity["campaign_sha256"] != hashlib.sha256(manifest_raw).hexdigest()
            or stage.get("classification") != "new_unopened_inputs_after_nominal_lock"
            or stage.get("zeeman_seeds") != list(range(3035, 3055))
            or stage.get("mot_seeds") != list(range(43035, 43055))
            or stage.get("locked_nominals")
            != f"{logical}/selection/locked_nominals.json"
            or stage.get("zeeman_job") != f"{logical}/{JOB_PATHS['zeeman']}"
            or stage.get("mot_job") != f"{logical}/{JOB_PATHS['mot_2d']}"
            or stage.get("freeze_job") != f"{logical}/{JOB_PATHS['freeze']}"
            or stage.get("input_manifest")
            != f"{logical}/final_validation_inputs/input_manifest.json"
        ):
            fail("final_input_preparation_invalid")
        transition_raw = read_relative_at(
            campaign_fd, f".mot_ui/transitions/{TRANSITION}"
        )
        transition = json_bytes(transition_raw, error="final_input_preparation_invalid")
        bundle_raw = read_relative_at(
            campaign_fd,
            ".mot_ui/transitions/finalist_selection_to_final_validation_inputs.bundle.gz",
            64 * 1024 * 1024,
        )
        if (
            set(transition) != FINAL_KEYS
            or transition_raw != canonical(transition) + b"\n"
            or digest(transition) != identity["remote_transition_receipt_sha256"]
            or transition.get("status") != "final_validation_input_generation_prepared"
            or transition.get("transition_key") != identity["transition_key"]
            or transition.get("bundle", {}).get("bundle_sha256")
            != identity["bundle_sha256"]
            or transition.get("commit") != payload["commit"]
            or not isinstance(transition.get("files"), dict)
            or len(transition["files"]) != 50
            or any(
                not exact_match(HEX64, value) for value in transition["files"].values()
            )
            or not _exact_bundle(transition.get("bundle"), file_count=50)
            or hashlib.sha256(bundle_raw).hexdigest() != identity["bundle_sha256"]
        ):
            fail("final_input_preparation_invalid")
        try:
            selections = {
                family: json_bytes(
                    read_relative_at(campaign_fd, f"selection/finalists/{family}.json"),
                    error="final_input_preparation_invalid",
                )
                for family in ("angled_donut", "single_pass")
            }
            expected_bundle_paths = (
                frozenset(expected_paths(selections))
                | {"finalist_selection_submission.json"}
                | FILES
            )
            unpacked = unpack_artifact_bundle(
                bundle_raw,
                transition["bundle"],
                campaign=relative.name,
                commit=payload["commit"],
                from_stage="finalist_selection",
                to_stage=STAGE,
                expected_paths=expected_bundle_paths,
            )
        except Exception:
            fail("final_input_preparation_invalid")
        if (
            set(transition["files"]) != expected_bundle_paths
            or any(
                hashlib.sha256(unpacked[name]).hexdigest() != transition["files"][name]
                for name in expected_bundle_paths
            )
            or any(
                unpacked[name] != read_relative_at(campaign_fd, name) for name in FILES
            )
        ):
            fail("final_input_preparation_invalid")
        frozen: dict[str, bytes] = {}
        for name, expected in identity["files"].items():
            current = read_relative_at(campaign_fd, name)
            if hashlib.sha256(current).hexdigest() != expected:
                fail("final_input_preparation_invalid")
            frozen[name] = current
        for name, expected in identity["code_files"].items():
            current = read_relative_at(root_fd, name)
            if hashlib.sha256(current).hexdigest() != expected:
                fail("final_input_preparation_invalid")
        if (
            linear.submission_key(relative.as_posix(), payload["commit"], identity)
            != payload["submission_key"]
        ):
            fail("final_input_preparation_invalid")
        mot_ui_fd = open_dir_at(campaign_fd, ".mot_ui")
        opened.append(mot_ui_fd)
        submissions_fd = open_dir_at(
            mot_ui_fd, "submissions", create=operation == "submit"
        )
        opened.append(submissions_fd)
        lock_name = f"{STAGE}.lock"
        if operation == "submit":
            lock_fd = os.open(
                lock_name,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=submissions_fd,
            )
        elif regular_exists_at(submissions_fd, lock_name):
            lock_fd = os.open(
                lock_name,
                os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=submissions_fd,
            )
        else:
            lock_fd = os.dup(submissions_fd)
        opened.append(lock_fd)
        row = os.fstat(lock_fd)
        if operation == "submit" and (
            not stat.S_ISREG(row.st_mode) or row.st_nlink != 1
        ):
            fail("final_input_submission_conflict")
        nonce = payload.get("nonce")
        if nonce is None:
            for receipt_name in (f"{STAGE}.json", f"{STAGE}.pending.json"):
                if regular_exists_at(submissions_fd, receipt_name):
                    receipt = strict_json_at(submissions_fd, receipt_name)
                    nonce = receipt.get("nonce")
                    break
        nonce = nonce or "0" * 32
        if not exact_match(HEX32, nonce):
            fail("final_input_submission_conflict")
        plan = linear.FrozenLinearPlan(
            relative.as_posix(),
            payload["commit"],
            payload["submission_key"],
            nonce,
            {name: frozen[path] for name, path in JOB_PATHS.items()},
        )

        def reattest():
            if (
                read_relative_at(campaign_fd, "campaign.json") != manifest_raw
                or read_relative_at(campaign_fd, f".mot_ui/transitions/{TRANSITION}")
                != transition_raw
                or read_relative_at(
                    campaign_fd,
                    ".mot_ui/transitions/finalist_selection_to_final_validation_inputs.bundle.gz",
                    64 * 1024 * 1024,
                )
                != bundle_raw
            ):
                raise ValueError("evidence changed")
            for name, expected in frozen.items():
                if read_relative_at(campaign_fd, name) != expected:
                    raise ValueError("evidence changed")
            for name, expected in identity["code_files"].items():
                if (
                    hashlib.sha256(read_relative_at(root_fd, name)).hexdigest()
                    != expected
                ):
                    raise ValueError("evidence changed")

        try:
            state = linear.reconcile_operation(
                operation,
                DESCRIPTOR,
                plan,
                branch=branch,
                lock_fd=lock_fd,
                submissions_fd=submissions_fd,
                campaign_fd=campaign_fd,
                run=run,
                reattest=reattest,
                now=lambda: int(time.time()),
            )
        except RuntimeError as exc:
            fail(
                "final_input_submission_busy"
                if str(exc) == "submission_busy"
                else "final_input_submission_outcome_unknown"
            )
        except Exception:
            fail("final_input_submission_conflict")
        _response(state)
    finally:
        for fd in reversed(opened):
            os.close(fd)
        os.close(root_fd)


if __name__ == "__main__":
    main()
