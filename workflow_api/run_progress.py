"""Process-local, non-authoritative progress telemetry for individual runs."""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable


class IndividualRunProgressRegistry:
    """Share live worker observations without changing scientific records."""

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._lock = threading.RLock()
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}
        self._failures: dict[tuple[str, str], str] = {}
        self._failure_limit = 4096
        self._scheduled: set[tuple[str, str]] = set()

    def start(self, family: str, run_id: str, total: int) -> None:
        if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
            raise ValueError("Progress total must be a positive integer.")
        with self._lock:
            self._failures.pop((family, run_id), None)
            self._rows[(family, run_id)] = {
                "completed": 0, "total": total, "started": self._monotonic()
            }

    def update(self, family: str, run_id: str, completed: int, total: int) -> None:
        if (isinstance(completed, bool) or not isinstance(completed, int)
                or isinstance(total, bool) or not isinstance(total, int)
                or total <= 0 or not 0 <= completed <= total):
            raise ValueError("Progress observation is invalid.")
        with self._lock:
            row = self._rows.get((family, run_id))
            if row is None:
                return
            if row["total"] != total or completed < row["completed"]:
                raise ValueError("Progress observation is inconsistent.")
            row["completed"] = completed

    def snapshot(self, family: str, run_id: str) -> dict[str, int | float] | None:
        with self._lock:
            row = self._rows.get((family, run_id))
            if row is None:
                return None
            runtime = self._monotonic() - row["started"]
            if not math.isfinite(runtime) or runtime < 0:
                return None
            completed, total = int(row["completed"]), int(row["total"])
            return {"completed_particles": completed, "total_particles": total,
                    "fraction": completed / total, "runtime_s": float(runtime)}

    def fail(self, family: str, run_id: str, code: str) -> None:
        """Forget stale live progress and retain bounded diagnostic evidence only."""
        if not isinstance(code, str) or not code or len(code) > 128 or not code.isprintable():
            raise ValueError("Progress failure code is invalid.")
        with self._lock:
            key = (family, run_id)
            self._rows.pop(key, None)
            self._scheduled.discard(key)
            if key not in self._failures and len(self._failures) >= self._failure_limit:
                self._failures.pop(next(iter(self._failures)))
            self._failures[key] = code

    def failure(self, family: str, run_id: str) -> str | None:
        """Return observed background failure, without changing durable run truth."""
        with self._lock:
            return self._failures.get((family, run_id))

    def schedule(self, family: str, run_id: str) -> None:
        """Reserve process-owned queue observation before executor admission."""
        with self._lock:
            key = (family, run_id)
            if key in self._scheduled:
                raise ValueError("Local run is already observed as scheduled.")
            self._scheduled.add(key)

    def finish(self, family: str, run_id: str) -> None:
        """Clear queue observation when its owning future finishes or rolls back."""
        with self._lock:
            self._scheduled.discard((family, run_id))

    def is_scheduled(self, family: str, run_id: str) -> bool:
        with self._lock:
            return (family, run_id) in self._scheduled
