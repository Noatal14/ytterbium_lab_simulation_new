"""Loopback-only server for the browser-to-backend integration check.

Uses the production HTTP handler and real creation/validation services in a
temporary Git repository containing labelled synthetic inputs. Scheduler and
computation endpoints are disabled. No SSH or production data is accessed.
"""

from __future__ import annotations

import sys
import json
import time

_STARTUP_STARTED = time.monotonic()


def startup_marker(phase: str, **details: object) -> None:
    """Bounded test-fixture diagnostics; never log requests or environment."""
    record = {
        "marker": "SYNTHETIC_UI_FIXTURE",
        "phase": phase,
        "unix_s": round(time.time(), 3),
        "elapsed_s": round(time.monotonic() - _STARTUP_STARTED, 3),
        **details,
    }
    print(json.dumps(record, sort_keys=True), file=sys.stderr, flush=True)


startup_marker(
    "before_imports",
    interpreter=sys.executable[:1024],
    python=sys.version.split()[0],
    fixture_path=__file__[:1024],
)

import tempfile
import shutil
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflow_api.server import HOST, PORT, WorkflowHandler  # noqa: E402
from workflow_api.campaign_deployment import TEAM_CHECKOUT
from workflow_api.loopback_http import LoopbackThreadingHTTPServer as ThreadingHTTPServer
from campaign_fixture import prepare
from workflow_api.mutation import CreationService
from workflow_api.repository_snapshot import RepositorySnapshotProvider, Mot2DIndividualRepositorySnapshotProvider
from workflow_api.mot_3d_bootstrap import Mot3DDiscoveryBootstrapService
from workflow_api.mot_2d_run_creation import Mot2DRunCreationService
from workflow_api.mot_2d_individual_api import IndividualMot2DApi
from workflow_api.mot_2d_zeus_execution import IndividualMot2DZeusCoordinator
from workflow_api.zeeman_zeus_execution import RemoteSubmission
from workflow_api.run_execution import issue_execution_authority
from workflow_api.individual_run_discovery import CanonicalIndividualRunRegistry


startup_marker("imports_complete")


class InspectOnlyTransport:
    operations = frozenset({"inspect", "stage", "submit", "status", "retrieve"})

    def inspect(self, **_payload):
        return RemoteSubmission("absent", None, None)

    def stage(self, **_payload):
        raise AssertionError("Fixture transport cannot stage remote data")

    def submit(self, **_payload):
        raise AssertionError("Fixture transport cannot submit jobs")


class NoLocalComputation:
    def submit(self, *_args):
        raise AssertionError("Browser fixture cannot start simulations")


class FakeZeusSnapshotService:
    """Return one strict snapshot without contacting Zeus."""

    def snapshot(self, payload: dict[str, object]) -> dict[str, object]:
        if set(payload) != {"username", "project_directory"}:
            raise ValueError("Unexpected integration snapshot payload.")
        username = payload["username"]
        project_directory = payload["project_directory"]
        if not isinstance(username, str) or project_directory != (
            f"/home/{username}/{TEAM_CHECKOUT}"
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

    def do_POST(self):
        if self.path not in {
            "/api/v1/zeus/snapshot",
            "/api/v1/campaigns/2d/preview", "/api/v1/campaigns/2d/confirm",
            "/api/v1/campaigns/3d/bootstrap/preview", "/api/v1/campaigns/3d/bootstrap/confirm",
            "/api/v1/campaigns/3d/bootstrap/status",
            "/api/v1/individual-runs/mot-2d/preview", "/api/v1/individual-runs/mot-2d/confirm",
            "/api/v1/individual-runs/mot-2d/zeus/preview",
        }:
            self._error("fixture_execution_disabled", "Execution is disabled in this synthetic fixture.", 503)
            return
        super().do_POST()


def main() -> None:
    fixture = tempfile.TemporaryDirectory(prefix="ui_campaign_SYNTHETIC_")
    startup_marker("prepare_start")
    root = prepare(Path(fixture.name), ROOT)
    startup_marker("prepare_complete")
    startup_marker("services_start")
    git = Path(shutil.which("git"))
    IntegrationHandler.repository_root = root
    IntegrationHandler.creation_service = CreationService(root, RepositorySnapshotProvider(root, git))
    IntegrationHandler.individual_run_service = CanonicalIndividualRunRegistry(root)
    IntegrationHandler.mot_3d_bootstrap_service = Mot3DDiscoveryBootstrapService(root)
    IntegrationHandler.individual_mot_2d_api = IndividualMot2DApi(
        root, Mot2DRunCreationService(root, Mot2DIndividualRepositorySnapshotProvider(root, git)),
        NoLocalComputation(), IndividualMot2DZeusCoordinator(root, issue_execution_authority(), lambda _profile: InspectOnlyTransport()),
    )
    startup_marker("services_complete")
    startup_marker("bind_start", host=HOST, port=PORT)
    server = ThreadingHTTPServer((HOST, PORT), IntegrationHandler)
    startup_marker("bind_complete", host=HOST, port=PORT)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        os.chdir(ROOT)
        fixture.cleanup()


if __name__ == "__main__":
    main()
