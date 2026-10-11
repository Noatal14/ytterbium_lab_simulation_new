"""Read-only API mapping for D3-authoritative individual-run snapshots.

This module makes no independent package, artifact, or scientific-validity
decision. D3 discovery owns those decisions; this boundary only maps its
immutable evidence to stable public DTOs.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from workflow_api.run_discovery import (
    DiscoveredRun,
    InspectedRun,
    discover_run_snapshot,
    inspect_run,
)
from workflow_api.run_records import RunRecordError


MAX_DISCOVERED_RUNS = 500


class IndividualRunDiscoveryError(Exception):
    """A fixed public failure from the individual-run read boundary."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class IndividualRunRegistry(Protocol):
    """Narrow service contract used by the HTTP adapter and its test fakes."""

    def list_runs(self) -> dict[str, Any]: ...

    def get_run(self, public_id: str) -> dict[str, Any]: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_id(family: str, run_id: str) -> str:
    digest = hashlib.sha256(f"{family}:{run_id}".encode("utf-8")).hexdigest()[:24]
    return f"individual-run-{digest}"


def _safe_public_id(value: object) -> str:
    prefix = "individual-run-"
    if (
        not isinstance(value, str)
        or len(value) != len(prefix) + 24
        or not value.startswith(prefix)
        or any(
            character not in "0123456789abcdef"
            for character in value[len(prefix) :]
        )
    ):
        raise IndividualRunDiscoveryError(
            "invalid_run_id", "Individual-run identifier is invalid."
        )
    return value


def _plain(value: Any) -> Any:
    """Copy D3's immutable evidence into JSON-native response values."""
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain(child) for child in value]
    return value


class CanonicalIndividualRunRegistry:
    """Map D3's authoritative trust decision without mutating packages."""

    def __init__(
        self,
        repository_root: Path,
        *,
        clock: Callable[[], str] = _utc_now,
    ):
        self.repository_root = repository_root.resolve(strict=True)
        self.clock = clock

    def _snapshot(self) -> tuple[dict[str, DiscoveredRun], int, bool]:
        snapshot = discover_run_snapshot(
            self.repository_root, maximum_runs=MAX_DISCOVERED_RUNS
        )
        entries: dict[str, DiscoveredRun] = {}
        invalid = 0
        for record in snapshot.records:
            if record.integrity == "invalid":
                invalid += 1
                continue
            public_id = _public_id(record.family, record.run_id)
            if public_id in entries:
                invalid += 1
                continue
            entries[public_id] = record
        return entries, invalid, snapshot.truncated

    @staticmethod
    def _public_error(inspected: InspectedRun) -> dict[str, str] | None:
        # Stored executor messages are deliberately not part of the public API.
        if inspected.state == "failed" and inspected.status["error"] is not None:
            return {"code": "run_failed", "message": "The individual run failed."}
        if inspected.state == "outcome_unknown":
            return {
                "code": "run_outcome_unknown",
                "message": "The individual run outcome requires manual inspection.",
            }
        return None

    def _map(
        self, public_id: str, inspected: InspectedRun, queried_at: str
    ) -> dict[str, Any]:
        run = inspected.run
        configuration = inspected.configuration
        inputs = inspected.inputs
        status = inspected.status
        results = inspected.results
        if inspected.integrity == "complete_verified":
            lifecycle, next_action, availability = (
                "results_ready",
                "view_results",
                "verified",
            )
            retention_status = (
                "retained" if results and results["states_retained"] else "not_retained"
            )
        elif inspected.integrity == "incomplete_publication":
            lifecycle, next_action, availability = (
                "incomplete_publication",
                "wait",
                "incomplete_publication",
            )
            retention_status = "publication_pending"
        else:
            lifecycle = inspected.state
            next_action = (
                "wait"
                if inspected.state in {"queued", "running"}
                else "inspect_execution"
                if inspected.state == "outcome_unknown"
                else "none"
            )
            availability = "not_ready"
            retention_status = "pending"

        item = {
            "id": public_id,
            "record_kind": "individual_simulation_run",
            "run_kind": inspected.family,
            "display_name": inspected.run_id,
            "stage_semantics": "single-run-lifecycle",
            "source": "local",
            "queried_at": queried_at,
            # D3 verifies storage integrity. This does not claim scientific
            # validation or suitability as campaign input.
            "trust": "verified-package",
            "scientific_role": "individual-only",
            "record_state": inspected.state,
            "integrity": inspected.integrity,
            "lifecycle": lifecycle,
            "next_action": next_action,
            "created_at": run["created_utc"],
            "updated_at": status["updated_utc"],
            "execution": {
                "mode": status["execution"]["mode"],
                "zeus_job_id": status["execution"]["zeus_job_id"],
            },
            "retention": {
                "particle_states_requested": run["retention"]["particle_states"],
                "status": retention_status,
            },
            "results": {
                "availability": availability,
                "completed_at": results["completed_utc"] if results else None,
            },
            "warnings": (
                ["Result publication is not yet terminal."]
                if inspected.integrity == "incomplete_publication"
                else []
            ),
        }
        return {
            **item,
            "provenance": {
                "git_revision": run["git_revision"],
                "configuration_sha256": run["configuration_sha256"],
                "inputs_sha256": run["inputs_sha256"],
                "laboratory_spec": _plain(configuration["laboratory_spec"]),
                "numerical_policy": _plain(configuration["numerical_policy"]),
            },
            "configuration": {
                "status": "complete",
                "resolved": _plain(configuration["resolved"]),
            },
            "inputs": {
                "status": "complete",
                "artifacts": _plain(inputs["artifacts"]),
            },
            "artifacts": _plain(results["artifacts"]) if results else [],
            "metrics": _plain(results["metrics"]) if results else None,
            "error": self._public_error(inspected),
        }

    @staticmethod
    def _list_item(detail: dict[str, Any]) -> dict[str, Any]:
        excluded = {
            "provenance",
            "configuration",
            "inputs",
            "artifacts",
            "metrics",
            "error",
        }
        return {key: value for key, value in detail.items() if key not in excluded}

    def list_runs(self) -> dict[str, Any]:
        entries, invalid, truncated = self._snapshot()
        queried_at = self.clock()
        runs = []
        for public_id, record in entries.items():
            try:
                inspected = inspect_run(
                    self.repository_root, record.family, record.run_id
                )
                runs.append(self._list_item(self._map(public_id, inspected, queried_at)))
            except (OSError, RunRecordError, ValueError, TypeError, KeyError):
                invalid += 1
        runs.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
        return {
            "runs": runs,
            "invalid_count": invalid,
            "total": len(runs),
            "truncated": truncated,
        }

    def get_run(self, public_id: str) -> dict[str, Any]:
        identifier = _safe_public_id(public_id)
        entries, _, _ = self._snapshot()
        record = entries.get(identifier)
        if record is None:
            raise IndividualRunDiscoveryError(
                "run_not_found", "Individual run was not found."
            )
        try:
            inspected = inspect_run(
                self.repository_root, record.family, record.run_id
            )
            return self._map(identifier, inspected, self.clock())
        except (OSError, RunRecordError, ValueError, TypeError, KeyError) as error:
            raise IndividualRunDiscoveryError(
                "run_inspection_failed", "Individual run could not be inspected safely."
            ) from error
