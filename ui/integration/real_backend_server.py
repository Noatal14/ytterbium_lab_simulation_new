"""Loopback-only server for the browser-to-backend integration check.

This harness uses the production HTTP handler with one read-only fake Zeus
service.  It never opens SSH, invokes a scheduler, or writes campaign data.
The fake returns a fresh timestamp because the production parser intentionally
rejects stale scheduler snapshots.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflow_api.server import HOST, PORT, WorkflowHandler  # noqa: E402


class FakeZeusSnapshotService:
    """Return one strict snapshot without contacting Zeus."""

    def snapshot(self, payload: dict[str, object]) -> dict[str, object]:
        if set(payload) != {"username", "project_directory"}:
            raise ValueError("Unexpected integration snapshot payload.")
        username = payload["username"]
        project_directory = payload["project_directory"]
        if not isinstance(username, str) or project_directory != (
            f"/home/{username}/ytterbium_lab_simulation_new"
        ):
            raise ValueError("Unexpected integration snapshot profile.")
        return {
            "connection_status": "connected",
            "profile": {
                "host": "zeus.technion.ac.il",
                "username": username,
                "project_directory": project_directory,
                "authentication": "ssh-key-or-agent",
            },
            "remote": {
                "project_directory": project_directory,
                "git_commit": "a" * 40,
                "branch": "integration-fake",
                "dirty": False,
            },
            "scheduler": {
                "status": "available",
                "queried_at": datetime.now(timezone.utc).isoformat(),
                "jobs": [],
            },
        }


class IntegrationHandler(WorkflowHandler):
    repository_root = ROOT
    sessions: dict[str, tuple[str, float]] = {}
    creation_service = None
    zeus_service = FakeZeusSnapshotService()
    transfer_service = None
    submission_service = None
    screening_service = None
    screen_submission_service = None
    refinement_service = None
    refinement_submission_service = None
    confirmation_service = None


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), IntegrationHandler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
