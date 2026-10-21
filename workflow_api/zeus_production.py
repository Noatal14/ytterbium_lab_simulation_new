"""Validated, explicit Sensitivity-to-Production preparation on Zeus."""

from __future__ import annotations
from workflow_api.mot_2d_spec import reviewed_job_resources, refinement_targets, trial_budget, sensitivity_task_count

import base64
import math
import hashlib
import json
import re
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol
from types import MappingProxyType

from workflow_api.mot_2d_plan import render_production_transition
from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshProcessError,
    PinnedSshRunner,
    ReceiverOperation,
)
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.zeus_sensitivity_submission import (
    ZeusSensitivitySubmissionCoordinator,
    ZeusSensitivitySubmissionError,
)
from workflow_api.zeus_sensitivity import (
    ZeusSensitivityCoordinator,
    ZeusSensitivityError,
)
from workflow_api.zeus_snapshot import ZeusProfile

TOKEN_LIFETIME_SECONDS = 300
MAX_PENDING_PREVIEWS = 32
JOB_FILE = "jobs/06_production.pbs"
OUTPUT_FILES = frozenset(
    {
        "sensitivity_summary.json",
        "production/tasks.json",
        JOB_FILE,
        "campaign.json",
    }
)


class ZeusProductionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RemoteSensitivityState:
    lifecycle: str
    scheduler: Mapping[str, Any]
    rows: tuple[Mapping[str, Any], ...]
    branch: str
    receipt: Mapping[str, Any] | None = None
    production_plan: Mapping[str, Any] | None = None
    # Internal immutable snapshot; never an additional wire field.
    validated_files: Mapping[str, bytes] | None = None


class ProductionTransport(Protocol):
    def inspect(self, **payload: object) -> RemoteSensitivityState: ...
    def prepare(self, **payload: object) -> RemoteSensitivityState: ...


@dataclass(frozen=True)
class _Pending:
    session_id: str
    campaign_id: str
    profile: ZeusProfile
    commit: str
    relative: str
    submission_key: str
    submission_nonce: str
    job_id: str
    rows_digest: str
    files: Mapping[str, str]
    transition_key: str
    nonce: str
    expires: float
    result: Mapping[str, object] | None = None


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def _validated_production_plan(bundle, payload, manifest, campaign, root, confirmation, rows):
    """Validate remote numerical authority without local statistical recomputation."""
    from workflow_api.mot_2d_plan import encode_production_plan, render_production_artifacts
    def require(value):
        if not value:
            raise ZeusProductionError("remote_response_invalid")
    def same(left, right):
        return json.dumps(left, sort_keys=True, separators=(",", ":"), allow_nan=False) == json.dumps(right, sort_keys=True, separators=(",", ":"), allow_nan=False)
    def finite(value):
        require(type(value) is float and math.isfinite(value))
    def strict_json(raw):
        def pairs(items):
            result = {}
            for key, value in items:
                require(key not in result)
                result[key] = value
            return result
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: require(False))
    try:
        require(isinstance(bundle, dict) and set(bundle) == {"version", "source_digest", "confirmation_rows_digest", "sensitivity_rows_digest", "files"})
        require(type(bundle["version"]) is int and bundle["version"] == 1)
        files = bundle["files"]
        require(isinstance(files, dict) and set(files) == OUTPUT_FILES)
        require(all(isinstance(record, dict) and type(record.get("base64")) is str for record in files.values()))
        require(sum(len(record["base64"]) for record in files.values()) <= 24 * 1024 * 1024)
        rendered = {}
        for name, record in files.items():
            require(isinstance(record, dict) and set(record) == {"sha256", "base64"})
            require(type(record["base64"]) is str and len(record["base64"]) <= 12 * 1024 * 1024)
            raw = base64.b64decode(record["base64"], validate=True)
            require(0 < len(raw) <= 8 * 1024 * 1024 and base64.b64encode(raw).decode("ascii") == record["base64"])
            require(hashlib.sha256(raw).hexdigest() == record["sha256"])
            rendered[name] = raw
        require(sum(map(len, rendered.values())) <= 16 * 1024 * 1024)
        expected_bundle = encode_production_plan(payload, rendered, confirmation, rows)
        require(same(bundle, expected_bundle))
        summary = strict_json(rendered["sensitivity_summary.json"])
        values = manifest["s0_values"]
        require(isinstance(summary, dict) and set(summary) == {f"s0_{float(v):.6f}".replace(".", "p") for v in values})
        selected = {}
        for value in values:
            key = f"s0_{float(value):.6f}".replace(".", "p")
            entry = summary[key]
            require(isinstance(entry, dict) and set(entry) == {"reference", "points", "production_selection", "robustness_status", "near_optimality_status"})
            confirmed = sorted([r for r in confirmation if r["s0"] == value], key=lambda r: (-r["evaluation"]["statistics"]["conditional_95_ci"][0], -r["evaluation"]["statistics"]["mean_conditional_efficiency"], r["candidate_index"]))
            require(len(confirmed) == 5 and same(entry["reference"], confirmed[0]["parameters"]))
            source = [r for r in rows if r["s0"] == value]
            center = next(r for r in source if r["offsets"] == {"detuning_gamma": 0.0, "magnet_radius_m": 0.0})
            points = entry["points"]
            require(type(points) is list and len(points) == len(source))
            for point, row in zip(points, source):
                require(type(point) is dict and set(point) == {"parameters", "offsets", "mean_efficiency", "comparison_to_reference", "within_loss_margin_at_95_percent"})
                require(same(point["parameters"], row["parameters"]) and same(point["offsets"], row["offsets"]))
                finite(point["mean_efficiency"])
                require(same(point["mean_efficiency"], row["evaluation"]["statistics"]["mean_conditional_efficiency"]))
                comparison = point["comparison_to_reference"]
                require(type(comparison) is dict and set(comparison) == {"mean_difference_fraction", "95_ci_fraction", "95_ci_half_width_fraction", "differences_fraction"})
                left = row["evaluation"]["replicates"]; right = center["evaluation"]["replicates"]
                require(type(left) is list and type(right) is list and len(left) == len(right) == 5)
                for index, (a, b) in enumerate(zip(left, right)):
                    identity = ("zeeman_seed", "mot_seed", "n_input", "subset_seed")
                    require(all(type(a[k]) is int and type(b[k]) is int and a[k] == b[k] for k in identity))
                    require(a["zeeman_seed"] == manifest["seed_roles"]["held_out_confirmation"][index]
                            and a["mot_seed"] == manifest["mot_seeds"]["held_out_confirmation"][index]
                            and a["n_input"] == manifest["fixed_design"]["particle_counts"]["sensitivity"]
                            and a["subset_seed"] == 100000 + a["zeeman_seed"])
                    finite(a["conditional_efficiency"]); finite(b["conditional_efficiency"])
                    require(0.0 <= a["conditional_efficiency"] <= 1.0 and 0.0 <= b["conditional_efficiency"] <= 1.0)
                differences = [a["conditional_efficiency"] - b["conditional_efficiency"] for a, b in zip(left, right)]
                require(same(comparison["differences_fraction"], differences))
                mean = comparison["mean_difference_fraction"]; half = comparison["95_ci_half_width_fraction"]; ci = comparison["95_ci_fraction"]
                finite(mean); finite(half)
                require(half >= 0 and -1.0 <= mean <= 1.0)
                require(type(ci) is list and len(ci) == 2)
                for endpoint in ci: finite(endpoint)
                require(same(ci, [mean - half, mean + half]))
                require(type(point["within_loss_margin_at_95_percent"]) is bool and point["within_loss_margin_at_95_percent"] == (ci[0] >= -float(manifest["fixed_design"]["target_95_half_width_fraction"])))
            better = [p for p in points if p["comparison_to_reference"]["95_ci_fraction"][0] > 0.0]
            chosen = max(better, key=lambda p: (p["comparison_to_reference"]["95_ci_fraction"][0], p["mean_efficiency"])) if better else next(p for p in points if p["offsets"] == {"detuning_gamma": 0.0, "magnet_radius_m": 0.0})
            expected_selection = {"parameters": chosen["parameters"], "offsets_from_confirmed_winner": chosen["offsets"], "mean_efficiency": chosen["mean_efficiency"], "comparison_to_confirmed_winner": chosen["comparison_to_reference"], "selection_reason": "sensitivity_neighbor_clearly_better_at_95_percent" if better else "no_sensitivity_neighbor_clearly_better_at_95_percent", "familywise_method": "Bonferroni simultaneous paired intervals", "familywise_confidence_per_comparison": 1.0 - 0.05 / max(1, len(source) - 1)}
            require(same(entry["production_selection"], expected_selection))
            require(entry["robustness_status"] == "not_established_pending_adaptive_challenger_validation" and entry["near_optimality_status"] == "not_established_pending_domain_challenger_elimination")
            selected[value] = chosen["parameters"]
        sealed = manifest["seed_roles"]["sealed_validation"]
        mot_seeds = manifest["mot_seeds"]["sealed_validation"]
        require(len(sealed) == len(mot_seeds) == 20)
        tasks = [{"s0": value, "zeeman_seed": seed, "mot_seed": mot_seeds[index], "parameters": selected[value]} for value in values for index, seed in enumerate(sealed)]
        expected_files = render_production_artifacts(manifest, campaign, root, summary, tasks)
        require(rendered == expected_files)
        return rendered
    except ZeusProductionError:
        raise
    except (ValueError, TypeError, KeyError, StopIteration, OverflowError):
        raise ZeusProductionError("remote_response_invalid") from None


class ZeusProductionCoordinator:
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
            lambda profile: PinnedSshProductionTransport(self.root, self.ssh, profile)
        )
        self._previews = PreviewRegistry[_Pending](
            clock=clock, token_factory=token_factory
        )
        self._confirm = threading.Lock()

    def _base_plan(self, request: Mapping[str, object], *, allow_incomplete: bool = False):
        try:
            coordinator = ZeusSensitivitySubmissionCoordinator(
                self.root, self.ssh, self.git
            )
            plan = coordinator._plan(request)
            (
                campaign_id,
                profile,
                campaign,
                manifest,
                commit,
                files,
                transition_nonce,
                transition_digest,
                submission_key,
            ) = plan
            transport, payload = coordinator._remote(
                profile,
                campaign.relative_to(self.root).as_posix(),
                commit,
                files,
                transition_nonce,
                transition_digest,
                submission_key,
                None,
            )
            state = transport.status(**payload)
        except ZeusSensitivitySubmissionError as error:
            raise ZeusProductionError(error.code) from error
        if (
            state.status not in ({"submitted", "queued", "running", "held",
                                  "completed_success", "completed_failed", "status_unknown"}
                                 if allow_incomplete else {"completed_success"})
            or not state.job_id or not state.nonce
        ):
            raise ZeusProductionError("sensitivity_not_complete")
        return (*plan, state.nonce, state.job_id)

    def _confirmation_rows(self, request: Mapping[str, object], base: tuple[Any, ...]):
        try:
            _, state = ZeusSensitivityCoordinator(
                self.root, self.ssh, self.git
            )._inspect(request)
        except ZeusSensitivityError as error:
            raise ZeusProductionError(error.code) from error
        if (
            state.lifecycle != "sensitivity_prepared"
            or not isinstance(state.receipt, dict)
            or state.receipt.get("nonce") != base[6]
        ):
            raise ZeusProductionError("sensitivity_preparation_invalid")
        return [dict(row) for row in state.receipt["rows"]]

    def _remote_payload(self, plan: tuple[Any, ...]) -> dict[str, object]:
        (
            _,
            _,
            campaign,
            _,
            commit,
            files,
            transition_nonce,
            transition_digest,
            submission_key,
            submission_nonce,
            job_id,
        ) = plan[:11]
        return {
            "campaign": campaign.relative_to(self.root).as_posix(),
            "commit": commit,
            "sensitivity_files": files,
            "sensitivity_transition_nonce": transition_nonce,
            "sensitivity_transition_digest": transition_digest,
            "sensitivity_submission_key": submission_key,
            "sensitivity_submission_nonce": submission_nonce,
            "sensitivity_job_id": job_id,
        }

    def _inspect(self, request: Mapping[str, object], *, allow_incomplete: bool = False):
        base = (self._base_plan(request, allow_incomplete=True)
                if allow_incomplete else self._base_plan(request))
        state = self.transport_factory(base[1]).inspect(**self._remote_payload(base))
        self._validate_state(state, base[3])
        rows = [dict(row) for row in state.rows]
        files = {}
        rows_digest = ""
        transition_key = ""
        if state.lifecycle in {"ready_to_prepare_production", "production_prepared"}:
            confirmation = self._confirmation_rows(request, base)
            rendered = _validated_production_plan(
                state.production_plan, self._remote_payload(base), base[3], base[2], self.root, confirmation, rows
            )
            files = {
                name: hashlib.sha256(data).hexdigest()
                for name, data in rendered.items()
            }
            rows_digest = _digest(rows)
            transition_key = _digest(
                {
                    "campaign": base[2].relative_to(self.root).as_posix(),
                    "commit": base[4],
                    "sensitivity_submission_key": base[8],
                    "sensitivity_submission_nonce": base[9],
                    "sensitivity_job_id": base[10],
                    "rows_digest": rows_digest,
                    "files": files,
                }
            )
        if state.lifecycle not in {"ready_to_prepare_production", "production_prepared"} and state.production_plan is not None:
            raise ZeusProductionError("remote_response_invalid")
        state = replace(state, validated_files=MappingProxyType(dict(rendered)) if files else None)
        plan = (*base[:9], files, rows_digest, transition_key)
        if state.lifecycle == "production_prepared":
            self._validate_receipt(state, plan, base)
        return plan, state

    @staticmethod
    def _validate_state(
        state: RemoteSensitivityState, manifest: Mapping[str, Any]
    ) -> None:
        allowed = {
            "queued",
            "running",
            "held",
            "failed",
            "status_unknown",
            "awaiting_outputs",
            "outputs_invalid",
            "ready_to_prepare_production",
            "production_prepared",
        }
        scheduler = state.scheduler
        try: expected = sensitivity_task_count(dict(manifest))
        except ValueError as error: raise ZeusProductionError("remote_response_invalid") from error
        if (
            state.lifecycle not in allowed
            or not state.branch
            or len(state.branch) > 256
            or not state.branch.isprintable()
            or not isinstance(scheduler, dict)
            or set(scheduler)
            != {"state", "task_count", "counts", "job_id", "submission_nonce"}
        ):
            raise ZeusProductionError("remote_response_invalid")
        if (
            scheduler.get("task_count") != expected
            or not re.fullmatch(
                r"\d+\[\]\.zeus-master", str(scheduler.get("job_id", ""))
            )
            or not re.fullmatch(
                r"[0-9a-f]{32}", str(scheduler.get("submission_nonce", ""))
            )
        ):
            raise ZeusProductionError("remote_response_invalid")
        counts = scheduler.get("counts")
        if (
            not isinstance(counts, dict)
            or set(counts) != {"queued", "running", "held", "succeeded", "failed"}
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in counts.values()
            )
        ):
            raise ZeusProductionError("remote_response_invalid")
        scheduler_state = scheduler.get("state")
        if scheduler_state not in {
            "queued",
            "running",
            "held",
            "completed_success",
            "completed_failed",
            "unknown",
        }:
            raise ZeusProductionError("remote_response_invalid")
        if sum(counts.values()) != (0 if scheduler_state == "unknown" else expected):
            raise ZeusProductionError("remote_response_invalid")
        ready = state.lifecycle in {
            "ready_to_prepare_production",
            "production_prepared",
        }
        if (ready and len(state.rows) != expected) or (not ready and state.rows):
            raise ZeusProductionError("remote_response_invalid")
        coherent = (
            ready
            and scheduler_state == "completed_success"
            and counts["succeeded"] == expected
            or state.lifecycle == "queued"
            and scheduler_state == "queued"
            and counts["queued"] > 0
            or state.lifecycle == "running"
            and scheduler_state == "running"
            and counts["running"] > 0
            or state.lifecycle == "held"
            and scheduler_state == "held"
            and counts["held"] > 0
            or state.lifecycle == "failed"
            and scheduler_state == "completed_failed"
            and counts["failed"] > 0
            or state.lifecycle == "status_unknown"
            and scheduler_state == "unknown"
            or state.lifecycle in {"awaiting_outputs", "outputs_invalid"}
            and scheduler_state == "completed_success"
            and counts["succeeded"] == expected
        )
        if not coherent:
            raise ZeusProductionError("remote_response_invalid")

    @staticmethod
    def _validate_receipt(
        state: RemoteSensitivityState, plan: tuple[Any, ...], base: tuple[Any, ...]
    ) -> None:
        receipt = state.receipt
        exact = {
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
            not isinstance(receipt, dict)
            or set(receipt) != exact
            or receipt.get("status") != "production_prepared"
            or receipt.get("transition_key") != plan[11]
            or receipt.get("commit") != plan[4]
            or receipt.get("sensitivity_submission_key") != base[8]
            or receipt.get("sensitivity_submission_nonce") != base[9]
            or receipt.get("sensitivity_job_id") != base[10]
            or receipt.get("rows_digest") != plan[10]
            or receipt.get("rows") != [dict(row) for row in state.rows]
            or receipt.get("files") != plan[9]
            or receipt.get("scheduler") != dict(state.scheduler)
            or not re.fullmatch(r"[0-9a-f]{32}", str(receipt.get("nonce", "")))
            or not isinstance(receipt.get("completed_unix_s"), int)
            or isinstance(receipt.get("completed_unix_s"), bool)
            or not 0 <= receipt["completed_unix_s"] <= 253402300799
        ):
            raise ZeusProductionError("transition_outcome_unknown")

    def status(self, request):
        plan, state = self._inspect(request, allow_incomplete=True)
        expected = sensitivity_task_count(plan[3])
        valid = state.lifecycle in {
            "ready_to_prepare_production",
            "production_prepared",
        }
        return {
            "source": "zeus",
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "campaign": {
                "id": plan[0],
                "name": plan[3]["name"],
                "stage": (
                    "production"
                    if state.lifecycle == "production_prepared"
                    else "sensitivity"
                ),
            },
            "sensitivity": {
                "status": state.lifecycle,
                "job_id": state.scheduler["job_id"],
                "scheduler": dict(state.scheduler),
            },
            "validation": {
                "status": (
                    "valid"
                    if valid
                    else (
                        "invalid"
                        if state.lifecycle == "outputs_invalid"
                        else "not_ready"
                    )
                ),
                "completed_points": expected if valid else 0,
                "expected_points": expected,
            },
            "next_action": (
                "review_production_preparation"
                if state.lifecycle == "ready_to_prepare_production"
                else "none" if state.lifecycle == "production_prepared" else "wait"
            ),
            "local_sync": {"status": "not_synchronized"},
        }

    def preview(self, request, *, session_id: str):
        plan, state = self._inspect(request)
        if state.lifecycle != "ready_to_prepare_production":
            raise ZeusProductionError("sensitivity_not_complete")
        expires = self.clock() + TOKEN_LIFETIME_SECONDS
        pending = _Pending(
            session_id,
            plan[0],
            plan[1],
            plan[4],
            plan[2].relative_to(self.root).as_posix(),
            plan[8],
            state.scheduler["submission_nonce"],
            state.scheduler["job_id"],
            plan[10],
            plan[9],
            plan[11],
            secrets.token_hex(16),
            expires,
        )
        token = self._previews.add(
            pending, expires_at=expires, capacity=MAX_PENDING_PREVIEWS
        )
        tasks = json.loads(state.validated_files["production/tasks.json"])
        return {
            "preview_token": token,
            "expires_in_seconds": TOKEN_LIFETIME_SECONDS,
            "campaign": {
                "id": plan[0],
                "name": plan[3]["name"],
                "git_commit": plan[4],
                "s0_values": plan[3]["s0_values"],
            },
            "from_stage": "sensitivity",
            "to_stage": "production",
            "sensitivity": {
                "job_id": state.scheduler["job_id"],
                "completed_points": len(state.rows),
                "expected_points": len(state.rows),
            },
            "artifacts": {
                "create": [
                    "sensitivity_summary.json",
                    "production/tasks.json",
                    JOB_FILE,
                ],
                "update": ["campaign.json"],
            },
            "job": {
                "file": JOB_FILE,
                "kind": "array",
                "task_count": len(tasks),
                "array_throttle": 4,
                "queue": "zeus_combined_q",
                **reviewed_job_resources(plan[3], 'production', {"cores_per_task":150, "memory_per_task_bytes":68719476736, "walltime_seconds":43200}),
            },
            "effects": {
                "prepare_production": True,
                "submit_production": False,
                "start_simulation": False,
                "overwrite_existing": False,
            },
            "local_sync": {"status": "not_synchronized"},
        }

    def confirm(self, request, *, session_id: str):
        if set(request) != {"preview_token"}:
            raise ZeusProductionError("request_invalid")
        token = request["preview_token"]
        with self._confirm:
            record = self._previews.get(token)
            pending = None if record is None else record.value
            if pending is None or not secrets.compare_digest(
                pending.session_id, session_id
            ):
                raise ZeusProductionError("confirmation_invalid")
            if pending.result is not None:
                return dict(pending.result)
            if self.clock() > pending.expires:
                raise ZeusProductionError("confirmation_expired")
            plan, state = self._inspect(
                {
                    "campaign_id": pending.campaign_id,
                    "username": pending.profile.username,
                    "project_directory": pending.profile.project_directory,
                }
            )
            identity = (
                plan[4],
                plan[8],
                state.scheduler["submission_nonce"],
                state.scheduler["job_id"],
                plan[10],
                plan[9],
                plan[11],
            )
            expected = (
                pending.commit,
                pending.submission_key,
                pending.submission_nonce,
                pending.job_id,
                pending.rows_digest,
                pending.files,
                pending.transition_key,
            )
            if state.lifecycle != "ready_to_prepare_production" or identity != expected:
                raise ZeusProductionError("local_files_changed")
            payload = self._remote_payload(
                self._base_plan(
                    {
                        "campaign_id": pending.campaign_id,
                        "username": pending.profile.username,
                        "project_directory": pending.profile.project_directory,
                    }
                )
            )
            payload.update(
                {
                    "rows_digest": pending.rows_digest,
                    "production_files": dict(pending.files),
                    "transition_key": pending.transition_key,
                    "nonce": pending.nonce,
                }
            )
            transport = self.transport_factory(plan[1])
            try:
                result_state = transport.prepare(**payload)
                self._validate_state(result_state, plan[3])
                current_request = {"campaign_id": pending.campaign_id, "username": pending.profile.username,
                                   "project_directory": pending.profile.project_directory}
                current_base = self._base_plan(current_request)
                confirmed_files = _validated_production_plan(
                    result_state.production_plan, self._remote_payload(current_base), plan[3], plan[2], self.root,
                    self._confirmation_rows(current_request, current_base), [dict(row) for row in result_state.rows],
                )
                if {name: hashlib.sha256(raw).hexdigest() for name, raw in confirmed_files.items()} != pending.files:
                    raise ZeusProductionError("transition_outcome_unknown")
                self._validate_receipt(result_state, plan, current_base)
            except Exception as error:
                raise ZeusProductionError("transition_outcome_unknown") from error
            result = {
                "status": "production_prepared",
                "campaign_id": pending.campaign_id,
                "stage": "production",
                "artifacts": {"created": 3, "updated": 1},
                "submitted_to_zeus": False,
                "simulation_started": False,
                "local_sync": {"status": "not_synchronized"},
            }
            self._previews.replace(token, replace(pending, result=result))
            return result


class PinnedSshProductionTransport:
    def __init__(self, root: Path, ssh: Path, profile: ZeusProfile, *, timeout=90):
        self.profile = profile
        self.runner = PinnedSshRunner(
            PinnedSshPolicy.production_preparation(root, ssh, timeout=timeout)
        )

    def _call(self, operation, payload):
        if operation not in {"inspect", "prepare"}:
            raise ZeusProductionError("remote_response_invalid")
        try:
            return self._call_response(operation, payload)
        except Exception as error:
            if operation == "prepare":
                raise ZeusProductionError("transition_outcome_unknown") from error
            raise

    def _call_response(self, operation: str, payload: Mapping[str, object]):
        pinned = {
            "inspect": ReceiverOperation.INSPECT,
            "prepare": ReceiverOperation.PREPARE,
        }[operation]
        try:
            result = self.runner.run(pinned, self.profile, payload)
        except (subprocess.TimeoutExpired, PinnedSshProcessError):
            raise ZeusProductionError(
                "transition_outcome_unknown"
                if operation == "prepare"
                else "zeus_timeout"
            ) from None
        response_error = "transition_outcome_unknown" if operation == "prepare" else "remote_response_invalid"
        if result.returncode or result.stderr:
            raise ZeusProductionError(response_error)
        try:
            def unique(items):
                value = {}
                for key, item in items:
                    if key in value:
                        raise ValueError("Duplicate remote field")
                    value[key] = item
                return value
            def nonfinite(_):
                raise ValueError("Nonfinite remote field")
            data = json.loads(result.stdout, object_pairs_hook=unique, parse_constant=nonfinite)
        except Exception:
            raise ZeusProductionError(response_error) from None
        if not isinstance(data, dict) or set(data) != {
            "lifecycle",
            "scheduler",
            "rows",
            "branch",
            "receipt",
            "production_plan",
        } or not isinstance(data["rows"], list):
            raise ZeusProductionError(response_error)
        return RemoteSensitivityState(
            data["lifecycle"],
            data["scheduler"],
            tuple(data["rows"]),
            data["branch"],
            data["receipt"],
            data["production_plan"],
        )

    def inspect(self, **payload):
        return self._call("inspect", payload)

    def prepare(self, **payload):
        return self._call("prepare", payload)
