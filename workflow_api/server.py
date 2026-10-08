"""Minimal local HTTP bridge for the read-only workflow API.

The server deliberately exposes no mutation, scheduler, SSH, or simulation
surface. It uses only the Python standard library so the scientific runtime
does not acquire web-framework dependencies.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from workflow_api import list_workflows
from workflow_api.discovery import DiscoveryError, get_campaign, list_campaigns
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
    repository_root = Path(__file__).resolve().parents[1]

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._trusted_request_target():
            return
        target = urlsplit(self.path)
        path = target.path
        if target.query:
            self._error("unsupported_query", "Query parameters are not supported.", HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/health":
            self._json({"api_version": SCHEMA_VERSION, "status": "ok"})
            return
        if path == "/api/workflows":
            self._json(workflow_catalog_payload())
            return
        if path == "/api/v1/campaigns":
            try:
                data = list_campaigns(self.repository_root)
            except Exception:
                self._error("inspection_failed", "Campaign inspection failed safely.", HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._json({"api_version": SCHEMA_VERSION, "data": data})
            return
        prefix = "/api/v1/campaigns/"
        if path.startswith(prefix):
            encoded_id = path[len(prefix):]
            if not encoded_id or "/" in encoded_id or unquote(encoded_id) != encoded_id:
                self._error("invalid_campaign_id", "Campaign identifier is invalid.", HTTPStatus.BAD_REQUEST)
                return
            try:
                campaign = get_campaign(self.repository_root, encoded_id)
            except DiscoveryError as error:
                status = HTTPStatus.NOT_FOUND if error.code == "campaign_not_found" else HTTPStatus.BAD_REQUEST
                self._error(error.code, error.message, status)
                return
            except Exception:
                self._error("inspection_failed", "Campaign inspection failed safely.", HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._json({"api_version": SCHEMA_VERSION, "data": campaign})
            return
        self._error("not_found", "Not found.", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - explicit read-only rejection
        self._method_not_allowed()

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    do_HEAD = do_POST
    do_OPTIONS = do_POST

    def _trusted_request_target(self) -> bool:
        target = urlsplit(self.path)
        if target.scheme or target.netloc:
            self._error("invalid_request_target", "Absolute request targets are not accepted.", HTTPStatus.BAD_REQUEST)
            return False
        host = self.headers.get("Host", "")
        hostname = host.rsplit(":", 1)[0].lower()
        if hostname not in {"127.0.0.1", "localhost"}:
            self._error("untrusted_host", "This local service accepts only localhost requests.", HTTPStatus.BAD_REQUEST)
            return False
        return True

    def _method_not_allowed(self) -> None:
        self._json(
            {"error": {"code": "read_only", "message": "This API milestone is read-only."}},
            status=HTTPStatus.METHOD_NOT_ALLOWED,
            extra_headers={"Allow": "GET"},
        )

    def _error(self, code: str, message: str, status: HTTPStatus) -> None:
        self._json({"error": {"code": code, "message": message}}, status=status)

    def _json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
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
