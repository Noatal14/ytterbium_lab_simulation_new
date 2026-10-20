"""Explicit at-most-once submission of a prepared 3D Discovery chain."""

from __future__ import annotations

import hashlib, json, os, re, secrets, stat, subprocess, threading, time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Mapping, Protocol

from workflow_api.discovery import build_registry
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshProcessError,
    PinnedSshRunner,
    ReceiverOperation,
)
from workflow_api.zeus_snapshot import ZEUS_HOST, ZeusProfile

TTL = 300
CAPACITY = 32
HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
JOB = re.compile(r"^\d+\[\]\.zeus-master$")
FILES = {
    "campaign.json",
    "jobs/01_smoke_angled_donut.pbs",
    "jobs/01_smoke_single_pass.pbs",
    "jobs/02_submit_discovery_chain.sh",
    "jobs/angled_donut/round_01.pbs",
    "jobs/angled_donut/round_02.pbs",
    "jobs/single_pass/round_01.pbs",
    "jobs/single_pass/round_02.pbs",
    "jobs/single_pass/round_03.pbs",
}
RECEIPT_KEYS = {
    "status",
    "nonce",
    "bootstrap_key",
    "commit",
    "physical_model_sha256",
    "source_2d_campaign_sha256",
    "source_2d_final_report_sha256",
    "input_registry_sha256",
    "timestep_policy_sha256",
    "files",
    "completed_unix_s",
}


def canonical_digest(value: object) -> str:
    """Hash the closed submission records without importing simulation code."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ZeusMot3DDiscoverySubmissionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RemoteDiscoveryState:
    lifecycle: str
    branch: str
    chain: Mapping[str, list[str]]
    nonce: str | None
    submitted_unix_s: int | None


class DiscoveryTransport(Protocol):
    def inspect(self, **payload: object) -> RemoteDiscoveryState: ...
    def submit(self, **payload: object) -> RemoteDiscoveryState: ...
    def status(self, **payload: object) -> RemoteDiscoveryState: ...


@dataclass(frozen=True)
class _Pending:
    session_id: str
    campaign_id: str
    profile: ZeusProfile
    relative: str
    commit: str
    receipt_digest: str
    bootstrap_key: str
    bootstrap_nonce: str
    files: Mapping[str, str]
    submission_key: str
    nonce: str
    expires: float
    result: Mapping[str, object] | None = None
    terminal_error: str | None = None


def _strict_json(path: Path) -> dict[str, object]:
    try:

        def pairs(rows):
            out = {}
            for key, value in rows:
                if key in out:
                    raise ValueError
                out[key] = value
            return out

        value = json.loads(
            _bounded_bytes(path).decode("utf-8", "strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except ZeusMot3DDiscoverySubmissionError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ZeusMot3DDiscoverySubmissionError(
            "discovery_preparation_invalid"
        ) from exc
    if not isinstance(value, dict):
        raise ZeusMot3DDiscoverySubmissionError("discovery_preparation_invalid")
    return value


def _bounded_bytes(path: Path, limit: int = 8 * 1024 * 1024) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise OSError
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(descriptor)
        identity = lambda row: (
            row.st_dev,
            row.st_ino,
            row.st_size,
            row.st_mtime_ns,
            row.st_ctime_ns,
        )
        if len(data) != before.st_size or identity(before) != identity(after):
            raise OSError
        return bytes(data)
    except OSError as exc:
        raise ZeusMot3DDiscoverySubmissionError(
            "discovery_preparation_invalid"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _reject_symlink_components(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ZeusMot3DDiscoverySubmissionError(
            "discovery_preparation_invalid"
        ) from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ZeusMot3DDiscoverySubmissionError("discovery_preparation_invalid")


def bootstrap_input_hashes(manifest):
    """The exact sealed twenty-ensemble and upstream-report transfer closure."""
    from workflow_api.mot_3d_provenance import input_registry_digest

    roles = manifest.get("input_roles")
    upstream = manifest.get("upstream_2d_campaign")
    if not isinstance(roles, dict) or set(roles) != {"discovery", "refinement", "preliminary_check"} or not isinstance(upstream, dict):
        raise ValueError("Invalid bootstrap source closure")
    def relative(value):
        if type(value) is not str or not value or "\\" in value or not value.isprintable():
            raise ValueError("Unsafe bootstrap source path")
        path = PurePosixPath(value)
        if path.is_absolute() or path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("Unsafe bootstrap source path")
        return path
    directory = relative(manifest.get("input_directory"))
    allowed_input_roots = {("data", "particle_states", "after_2d_mot"), ("data", "optimization", "mot_2d")}
    if manifest.get("kind") == "mot_3d_ui_acceptance_v1":
        allowed_input_roots.add(("data", "particle_states", "after_mot_2d"))
    if directory.parts[:3] not in allowed_input_roots:
        raise ValueError("Invalid bootstrap input namespace")
    selected = {}
    seeds = set()
    for role, count in (("discovery", 12), ("refinement", 4), ("preliminary_check", 4)):
        rows = roles[role]
        if not isinstance(rows, list) or len(rows) != count:
            raise ValueError("Invalid bootstrap role cardinality")
        for row in rows:
            if not isinstance(row, dict) or type(row.get("zeeman_seed")) is not int or row["zeeman_seed"] in seeds:
                raise ValueError("Invalid bootstrap seed registry")
            seeds.add(row["zeeman_seed"])
            for key, digest_key in (("path", "sha256"), ("metadata_path", "metadata_sha256")):
                name, digest = row.get(key), row.get(digest_key)
                if relative(name).parent != directory or type(digest) is not str or not HEX64.fullmatch(digest) or name in selected:
                    raise ValueError("Invalid bootstrap frozen source")
                selected[name] = digest
    source_campaign = relative(upstream.get("campaign_path"))
    source_report = relative(upstream.get("final_report_path"))
    if source_campaign.parts[:3] != ("data", "optimization", "mot_2d") or source_campaign.name != "campaign.json" or source_report != source_campaign.with_name("final_report.json"):
        raise ValueError("Invalid bootstrap upstream namespace")
    for path, key in ((source_campaign, "campaign_sha256"), (source_report, "final_report_sha256")):
        digest = upstream.get(key)
        if type(digest) is not str or not HEX64.fullmatch(digest) or path.as_posix() in selected:
            raise ValueError("Invalid bootstrap upstream hash")
        selected[path.as_posix()] = digest
    if len(selected) != 42:
        raise ValueError("Invalid bootstrap source count")
    evidence = manifest.get("design", {}).get("timestep_evidence", {})
    handoff = evidence.get("source_handoff", {})
    if handoff != {"campaign_sha256": upstream["campaign_sha256"], "final_report_sha256": upstream["final_report_sha256"], "input_registry_sha256": input_registry_digest(roles)}:
        raise ValueError("Bootstrap input registry identity changed")
    return selected


def validate_discovery_bootstrap(root: Path, campaign: Path, manifest, receipt, *, campaign_relative: str, validate_inputs: bool = False):
    """Authenticate the existing exact bootstrap registry without submitting jobs.

    ``campaign`` may be a private staging directory; ``campaign_relative`` is the
    independently authorized final namespace used by the canonical renderer.
    """
    relative = campaign_relative
    from workflow_api.mot_3d_workload import validate_location
    validate_location(manifest, relative)
    if validate_inputs:
        bootstrap_input_hashes(manifest)
        upstream = manifest["upstream_2d_campaign"]
        evidence = manifest["design"]["timestep_evidence"]
        expected_digests = {
            "physical_model_sha256": manifest.get("provenance", {}).get("physical_model_sha256"),
            "source_2d_campaign_sha256": upstream["campaign_sha256"],
            "source_2d_final_report_sha256": upstream["final_report_sha256"],
            "input_registry_sha256": evidence["source_handoff"]["input_registry_sha256"],
            "timestep_policy_sha256": evidence["policy_sha256"],
        }
        if any(receipt.get(key) != value for key, value in expected_digests.items()):
            raise ValueError("Bootstrap receipt identity changed")
    if (
        set(receipt) != RECEIPT_KEYS
        or receipt.get("status") != "discovery_prepared"
        or manifest.get("stage") != "discovery"
        or manifest.get("name") != Path(relative).name
    ):
        raise ZeusMot3DDiscoverySubmissionError("discovery_not_prepared")
    commit = receipt.get("commit")
    nonce = receipt.get("nonce")
    files = receipt.get("files")
    digests = (
        "physical_model_sha256",
        "source_2d_campaign_sha256",
        "source_2d_final_report_sha256",
        "input_registry_sha256",
        "timestep_policy_sha256",
    )
    if (
        not isinstance(commit, str)
        or not HEX40.fullmatch(commit)
        or not isinstance(nonce, str)
        or not HEX32.fullmatch(nonce)
        or not isinstance(files, dict)
        or set(files) != FILES
        or any(
            not isinstance(v, str) or not HEX64.fullmatch(v) for v in files.values()
        )
        or any(
            not isinstance(receipt.get(k), str) or not HEX64.fullmatch(receipt[k])
            for k in digests
        )
        or not isinstance(receipt.get("completed_unix_s"), (int, float))
        or isinstance(receipt.get("completed_unix_s"), bool)
        or not 0 <= receipt["completed_unix_s"] <= 253402300799
    ):
        raise ZeusMot3DDiscoverySubmissionError("discovery_preparation_invalid")
    if manifest.get("provenance", {}).get("git_commit") != commit:
        raise ZeusMot3DDiscoverySubmissionError("discovery_preparation_invalid")
    expected = canonical_digest(
        {
            "campaign_name": Path(relative).name,
            "commit": commit,
            **{k: receipt[k] for k in digests},
            "files": files,
            "nonce": nonce,
        }
    )
    if receipt.get("bootstrap_key") != expected:
        raise ZeusMot3DDiscoverySubmissionError("discovery_preparation_invalid")
    for name, digest in files.items():
        path = campaign.joinpath(*Path(name).parts)
        _reject_symlink_components(root, path)
        raw = _bounded_bytes(path)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ZeusMot3DDiscoverySubmissionError("discovery_preparation_invalid")
    # Review numbers are policy-derived only after exact frozen PBS parity.
    from workflow_api.mot_3d_workload import (
        discovery_review,
        validate_discovery_job_bytes,
    )

    _, science = discovery_review(manifest)
    design = manifest.get("design", {})
    if any(
        design.get(field) != science[value]
        for field, value in (
            ("screening_dt_s", "dt_s"),
            ("t_max_s", "t_max_s"),
            ("solver", "solver"),
        )
    ):
        raise ZeusMot3DDiscoverySubmissionError("discovery_preparation_invalid")
    try:
        validate_discovery_job_bytes(
            manifest,
            commit,
            relative,
            {
                name: _bounded_bytes(campaign / name)
                for name in files
                if name != "campaign.json"
            },
        )
    except ValueError as error:
        raise ZeusMot3DDiscoverySubmissionError(
            "discovery_preparation_invalid"
        ) from error
    return commit, nonce, dict(files), expected


class ZeusMot3DDiscoverySubmissionCoordinator:
    def __init__(
        self,
        repository_root: Path,
        ssh_executable: Path,
        git_executable: Path,
        *,
        clock=time.time,
        token_factory=None,
        transport_factory=None,
    ):
        self.root = repository_root.resolve(strict=True)
        self.ssh = ssh_executable.resolve(strict=True)
        self.git = git_executable.resolve(strict=True)
        self.clock = clock
        self.transport_factory = transport_factory or (
            lambda profile: PinnedSshMot3DDiscoverySubmissionTransport(
                self.root, self.ssh, profile
            )
        )
        self._previews = PreviewRegistry[_Pending](
            clock=clock, token_factory=token_factory
        )
        self._confirm = threading.Lock()

    def _plan(self, request: Mapping[str, object]):
        if (
            not isinstance(request, Mapping)
            or set(request) != {"campaign_id", "username", "project_directory"}
            or not isinstance(request.get("campaign_id"), str)
        ):
            raise ZeusMot3DDiscoverySubmissionError("request_invalid")
        try:
            profile = ZeusProfile.parse(
                {
                    "username": request["username"],
                    "project_directory": request["project_directory"],
                }
            )
        except (ValueError, KeyError) as exc:
            raise ZeusMot3DDiscoverySubmissionError("profile_invalid") from exc
        campaign_id = str(request["campaign_id"])
        entry = build_registry(self.root).get(campaign_id)
        if entry is None or entry.family != "mot_3d":
            raise ZeusMot3DDiscoverySubmissionError("campaign_not_found")
        campaign = entry.manifest.parent
        try:
            _reject_symlink_components(self.root, campaign)
            _reject_symlink_components(
                self.root, campaign / ".mot_ui/transitions/discovery_bootstrap.json"
            )
            manifest = _strict_json(campaign / "campaign.json")
            receipt = _strict_json(
                campaign / ".mot_ui/transitions/discovery_bootstrap.json"
            )
            relative = campaign.relative_to(self.root).as_posix()
            from workflow_api.mot_3d_workload import validate_location

            validate_location(manifest, relative)
            from workflow_api.acceptance_remote import assert_campaign_target

            if "kind" in manifest:
                assert_campaign_target(
                    manifest, profile.username, profile.project_directory, relative
                )
        except (ValueError, OSError) as exc:
            raise ZeusMot3DDiscoverySubmissionError(
                "discovery_preparation_invalid"
            ) from exc
        commit, nonce, files, expected = validate_discovery_bootstrap(
            self.root, campaign, manifest, receipt, campaign_relative=relative
        )
        receipt_digest = canonical_digest(receipt)
        key = canonical_digest(
            {
                "campaign": relative,
                "commit": commit,
                "bootstrap_digest": receipt_digest,
                "bootstrap_key": expected,
                "bootstrap_nonce": nonce,
                "files": files,
            }
        )
        return (
            campaign_id,
            profile,
            campaign,
            manifest,
            commit,
            dict(files),
            nonce,
            receipt_digest,
            expected,
            key,
        )

    def _remote(self, plan, nonce=None):
        (
            campaign_id,
            profile,
            campaign,
            manifest,
            commit,
            files,
            bootstrap_nonce,
            digest,
            bootstrap_key,
            key,
        ) = plan
        payload = {
            "campaign": campaign.relative_to(self.root).as_posix(),
            "commit": commit,
            "bootstrap_digest": digest,
            "bootstrap_key": bootstrap_key,
            "bootstrap_nonce": bootstrap_nonce,
            "files": files,
            "submission_key": key,
        }
        if nonce is not None:
            payload["nonce"] = nonce
        return self.transport_factory(profile), payload

    @staticmethod
    def _public(state: RemoteDiscoveryState) -> str:
        return {
            "eligible": "not_submitted",
            "submitted": "submitted",
            "queued": "queued",
            "running": "running",
            "held": "held",
            "completed_success": "completed_success",
            "completed_failed": "completed_failed",
            "status_unknown": "status_unknown",
            "outcome_unknown": "outcome_unknown",
        }.get(state.lifecycle, "invalid")

    def status(self, request):
        plan = self._plan(request)
        transport, payload = self._remote(plan)
        state = transport.status(**payload)
        public = self._public(state)
        if public == "invalid":
            raise ZeusMot3DDiscoverySubmissionError("remote_response_invalid")
        return {
            "source": "zeus",
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "campaign": {"id": plan[0], "name": plan[3]["name"], "stage": "discovery"},
            "submission": {"status": public, "chain": dict(state.chain)},
            "next_action": (
                "review_submission"
                if public == "not_submitted"
                else (
                    "wait"
                    if public in {"queued", "running", "submitted"}
                    else (
                        "validate_outputs"
                        if public == "completed_success"
                        else "inspect_zeus"
                    )
                )
            ),
            "local_sync": {"status": "not_synchronized"},
        }

    def preview(self, request, *, session_id: str):
        plan = self._plan(request)
        transport, payload = self._remote(plan)
        state = transport.inspect(**payload)
        if state.lifecycle == "submitted":
            raise ZeusMot3DDiscoverySubmissionError("discovery_already_submitted")
        if state.lifecycle == "outcome_unknown":
            raise ZeusMot3DDiscoverySubmissionError(
                "discovery_submission_outcome_unknown"
            )
        if state.lifecycle != "eligible":
            raise ZeusMot3DDiscoverySubmissionError("remote_response_invalid")
        expires = self.clock() + TTL
        pending = _Pending(
            session_id,
            plan[0],
            plan[1],
            plan[2].relative_to(self.root).as_posix(),
            plan[4],
            plan[7],
            plan[8],
            plan[6],
            plan[5],
            plan[9],
            secrets.token_hex(16),
            expires,
        )
        try:
            token = self._previews.add(pending, expires_at=expires, capacity=CAPACITY)
        except OverflowError as exc:
            raise ZeusMot3DDiscoverySubmissionError(
                "too_many_pending_previews"
            ) from exc
        from workflow_api.mot_3d_workload import discovery_review

        resources, science = discovery_review(plan[3])
        return {
            "preview_token": token,
            "expires_in_seconds": TTL,
            "campaign": {"id": plan[0], "name": plan[3]["name"], "git_commit": plan[4]},
            "stage": {"id": "discovery", "label": "Discovery"},
            "chain": {
                "families": [
                    {"id": "angled_donut", "rounds": 2},
                    {"id": "single_pass", "rounds": 3},
                ],
                "arrays": 5,
                "tasks_per_array": 3,
                "dependency": "afterok within each family",
            },
            "resources": resources,
            "science": science,
            "remote": {
                "host": ZEUS_HOST,
                "project_directory": plan[1].project_directory,
                "commit": plan[4],
                "branch": state.branch,
                "dirty": False,
            },
            "effects": {
                "submit_discovery_chain": True,
                "submit_smoke": False,
                "submit_later_stages": False,
                "modify_campaign_files": False,
                "record_submission_receipt": True,
            },
        }

    def confirm(self, request, *, session_id: str):
        if (
            not isinstance(request, Mapping)
            or set(request) != {"preview_token"}
            or not isinstance(request.get("preview_token"), str)
        ):
            raise ZeusMot3DDiscoverySubmissionError("request_invalid")
        token = request["preview_token"]
        with self._confirm:
            record = self._previews.get(token)
            pending = record.value if record else None
            if pending is None or not secrets.compare_digest(
                pending.session_id, session_id
            ):
                raise ZeusMot3DDiscoverySubmissionError("discovery_invalid")
            if pending.result is not None:
                return dict(pending.result)
            if pending.terminal_error:
                raise ZeusMot3DDiscoverySubmissionError(pending.terminal_error)
            if self.clock() > pending.expires:
                raise ZeusMot3DDiscoverySubmissionError("discovery_expired")
            plan = self._plan(
                {
                    "campaign_id": pending.campaign_id,
                    "username": pending.profile.username,
                    "project_directory": pending.profile.project_directory,
                }
            )
            identity = (
                plan[2].relative_to(self.root).as_posix(),
                plan[4],
                plan[7],
                plan[8],
                plan[6],
                plan[5],
                plan[9],
            )
            if identity != (
                pending.relative,
                pending.commit,
                pending.receipt_digest,
                pending.bootstrap_key,
                pending.bootstrap_nonce,
                pending.files,
                pending.submission_key,
            ):
                raise ZeusMot3DDiscoverySubmissionError("local_files_changed")
            transport, payload = self._remote(plan, pending.nonce)
            try:
                state = transport.submit(**payload)
            except ZeusMot3DDiscoverySubmissionError as exc:
                if exc.code in {
                    "discovery_submission_outcome_unknown",
                    "discovery_already_submitted",
                    "remote_response_invalid",
                }:
                    self._previews.replace(
                        token, replace(pending, terminal_error=exc.code)
                    )
                raise
            if (
                state.lifecycle != "submitted"
                or state.nonce != pending.nonce
                or state.submitted_unix_s is None
            ):
                self._previews.replace(
                    token,
                    replace(
                        pending, terminal_error="discovery_submission_outcome_unknown"
                    ),
                )
                raise ZeusMot3DDiscoverySubmissionError(
                    "discovery_submission_outcome_unknown"
                )
            try:
                submitted_at = datetime.fromtimestamp(
                    state.submitted_unix_s, tz=timezone.utc
                ).isoformat()
            except (OverflowError, OSError, ValueError):
                self._previews.replace(
                    token,
                    replace(
                        pending, terminal_error="discovery_submission_outcome_unknown"
                    ),
                )
                raise ZeusMot3DDiscoverySubmissionError(
                    "discovery_submission_outcome_unknown"
                ) from None
            result = {
                "status": "submitted",
                "campaign_id": pending.campaign_id,
                "stage": "discovery",
                "chain": dict(state.chain),
                "submitted_at": submitted_at,
                "local_sync": {"status": "not_synchronized"},
            }
            self._previews.replace(token, replace(pending, result=result))
            return result


class PinnedSshMot3DDiscoverySubmissionTransport:
    def __init__(self, root: Path, ssh: Path, profile: ZeusProfile, *, timeout=60):
        self.profile = profile
        self.runner = PinnedSshRunner(
            PinnedSshPolicy.mot_3d_discovery_submission(root, ssh, timeout=timeout)
        )

    def _call(self, operation: str, payload):
        op = {
            "inspect": ReceiverOperation.INSPECT,
            "submit": ReceiverOperation.SUBMIT,
            "status": ReceiverOperation.STATUS,
        }[operation]
        try:
            result = self.runner.run(op, self.profile, payload)
        except (subprocess.TimeoutExpired, PinnedSshProcessError):
            raise ZeusMot3DDiscoverySubmissionError(
                "discovery_submission_outcome_unknown"
                if operation == "submit"
                else "zeus_timeout"
            ) from None
        if result.returncode or result.stderr:
            raise ZeusMot3DDiscoverySubmissionError(
                "discovery_submission_outcome_unknown"
                if operation == "submit"
                else "remote_response_invalid"
            )
        try:
            data = json.loads(result.stdout)
        except Exception:
            raise ZeusMot3DDiscoverySubmissionError("remote_response_invalid") from None
        if not isinstance(data, dict):
            raise ZeusMot3DDiscoverySubmissionError("remote_response_invalid")
        if set(data) == {"error"}:
            code = data["error"]
            allowed_errors = {
                "invalid_request",
                "remote_checkout_mismatch",
                "discovery_preparation_invalid",
                "discovery_submission_outcome_unknown",
            }
            if not isinstance(code, str) or code not in allowed_errors:
                raise ZeusMot3DDiscoverySubmissionError("remote_response_invalid")
            raise ZeusMot3DDiscoverySubmissionError(code)
        if set(data) != {
            "lifecycle",
            "branch",
            "chain",
            "submission_nonce",
            "submitted_unix_s",
        }:
            raise ZeusMot3DDiscoverySubmissionError("remote_response_invalid")
        lifecycle = data["lifecycle"]
        allowed = {
            "inspect": {"eligible", "submitted", "outcome_unknown"},
            "submit": {"submitted", "outcome_unknown"},
            "status": {
                "eligible",
                "queued",
                "running",
                "held",
                "completed_success",
                "completed_failed",
                "status_unknown",
                "outcome_unknown",
            },
        }[operation]
        chain = data["chain"]
        if (
            lifecycle not in allowed
            or not isinstance(data["branch"], str)
            or not data["branch"]
            or len(data["branch"]) > 256
            or not data["branch"].isprintable()
            or not isinstance(chain, dict)
            or set(chain) != {"angled_donut", "single_pass"}
        ):
            raise ZeusMot3DDiscoverySubmissionError("remote_response_invalid")
        expected = {"angled_donut": 2, "single_pass": 3}
        populated = lifecycle not in {"eligible", "outcome_unknown"}
        if any(
            not isinstance(chain[k], list)
            or len(chain[k]) != (expected[k] if populated else 0)
            or any(not isinstance(j, str) or not JOB.fullmatch(j) for j in chain[k])
            for k in expected
        ):
            raise ZeusMot3DDiscoverySubmissionError("remote_response_invalid")
        nonce = data["submission_nonce"]
        stamp = data["submitted_unix_s"]
        if populated and (
            not isinstance(nonce, str)
            or not HEX32.fullmatch(nonce)
            or not isinstance(stamp, int)
            or isinstance(stamp, bool)
            or not 0 <= stamp <= 253402300799
            or operation == "submit"
            and nonce != payload.get("nonce")
        ):
            raise ZeusMot3DDiscoverySubmissionError(
                "discovery_submission_outcome_unknown"
                if operation == "submit"
                else "remote_response_invalid"
            )
        if not populated and (nonce is not None or stamp is not None):
            raise ZeusMot3DDiscoverySubmissionError("remote_response_invalid")
        return RemoteDiscoveryState(lifecycle, data["branch"], chain, nonce, stamp)

    def inspect(self, **payload):
        return self._call("inspect", payload)

    def submit(self, **payload):
        return self._call("submit", payload)

    def status(self, **payload):
        return self._call("status", payload)
