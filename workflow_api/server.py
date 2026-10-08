"""Minimal local HTTP bridge for the read-only workflow API.

The server deliberately exposes no mutation, scheduler, SSH, or simulation
surface. It uses only the Python standard library so the scientific runtime
does not acquire web-framework dependencies.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from workflow_api import list_workflows
from workflow_api.models import SCHEMA_VERSION

HOST = "127.0.0.1"
PORT = 8765


def workflow_catalog_payload() -> dict[str, Any]:
    return {
        "api_version": SCHEMA_VERSION,
        "data": [workflow.to_dict() for workflow in list_workflows()],
    }


class ReadOnlyWorkflowHandler(BaseHTTPRequestHandler):
    """Serve allowlisted JSON endpoints without filesystem mutation."""

    server_version = "WorkflowAPI/1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path == "/api/health":
            self._json({"api_version": SCHEMA_VERSION, "status": "ok"})
            return
        if self.path == "/api/workflows":
            self._json(workflow_catalog_payload())
            return
        self._json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - explicit read-only rejection
        self._json(
            {"error": "This API milestone is read-only."},
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), ReadOnlyWorkflowHandler)
    print(f"Read-only workflow API listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
