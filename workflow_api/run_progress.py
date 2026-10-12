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

    def start(self, family: str, run_id: str, total: int) -> None:
        if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
            raise ValueError("Progress total must be a positive integer.")
        with self._lock:
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
