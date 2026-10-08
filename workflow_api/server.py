"""Minimal local HTTP bridge for the read-only workflow API.

The server deliberately exposes no mutation, scheduler, SSH, or simulation
surface. It uses only the Python standard library so the scientific runtime
does not acquire web-framework dependencies.
"""

from __future__ import annotations

import json
import time
import threading
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from workflow_api import list_workflows
from workflow_api.discovery import DiscoveryError, get_campaign, list_campaigns
from workflow_api.models import SCHEMA_VERSION
from workflow_api.mot_2d_sources import list_sources
from workflow_api.mutation import CreationService
from workflow_api.repository_snapshot import RepositorySnapshotProvider

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
    creation_service: CreationService | None = None
    sessions: dict[str, tuple[str, float]] = {}
    sessions_lock = threading.Lock()

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
        if path == "/api/v1/session":
            if self.creation_service is None:
                self._error("creation_unavailable", "Local campaign creation is unavailable.", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            if self.headers.get("Sec-Fetch-Site") != "same-origin":
                self._error("untrusted_origin", "Local creation requires a same-origin request.", HTTPStatus.FORBIDDEN)
                return
            now = time.monotonic()
            with type(self).sessions_lock:
                sessions = {key: value for key, value in type(self).sessions.items() if value[1] > now}
                type(self).sessions = sessions
                if len(sessions) >= 64:
                    self._error("rate_limited", "Too many local creation sessions.", HTTPStatus.TOO_MANY_REQUESTS); return
                session, csrf = self.creation_service.new_session(); sessions[session] = (csrf, now + 600)
            self._json({"api_version": SCHEMA_VERSION, "data": {"csrf_token": csrf}}, extra_headers={"Set-Cookie": f"mot_ui_session={session}; HttpOnly; SameSite=Strict; Path=/"})
            return
        if path == "/api/v1/campaigns":
            try:
                data = list_campaigns(self.repository_root)
            except Exception:
                self._error("inspection_failed", "Campaign inspection failed safely.", HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._json({"api_version": SCHEMA_VERSION, "data": data})
            return
        if path == "/api/v1/campaigns/2d/sources":
            try:
                data = list_sources(self.repository_root)
            except Exception:
                self._error("source_inspection_failed", "Zeeman sources could not be inspected safely.", HTTPStatus.INTERNAL_SERVER_ERROR)
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

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._trusted_request_target(): return
        if self.creation_service is None:
            self._method_not_allowed(); return
        target = urlsplit(self.path)
        if target.query or target.path not in {"/api/v1/campaigns/2d/preview", "/api/v1/campaigns/2d/confirm"}:
            self._method_not_allowed(); return
        if not self._trusted_mutation_headers(): return
        try:
            payload = self._read_json_body()
            session = self._session_id()
            if target.path.endswith("/preview"):
                data = self.creation_service.preview(payload, session)
            else:
                if set(payload) != {"preview_token"} or not isinstance(payload.get("preview_token"), str):
                    raise ValueError("Confirmation payload is invalid.")
                data = self.creation_service.confirm(payload["preview_token"], session)
        except PermissionError:
            self._error("invalid_preview", "Preview confirmation is invalid or expired.", HTTPStatus.PRECONDITION_FAILED); return
        except BlockingIOError:
            self._error("rate_limited", "Too many local creation requests.", HTTPStatus.TOO_MANY_REQUESTS); return
        except FileExistsError:
            self._error("campaign_exists", "A campaign already exists at this destination.", HTTPStatus.CONFLICT); return
        except ValueError as error:
            status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE if str(error) == "Request body is too large." else HTTPStatus.BAD_REQUEST
            self._error("invalid_request", str(error), status); return
        except Exception:
            self._error("creation_failed", "Local campaign creation failed safely.", HTTPStatus.PRECONDITION_FAILED); return
        self._json({"api_version": SCHEMA_VERSION, "data": data}, status=HTTPStatus.CREATED if target.path.endswith("/confirm") else HTTPStatus.OK)

    def do_PUT(self) -> None: self._method_not_allowed()  # noqa: N802
    do_PATCH = do_PUT
    do_DELETE = do_PUT
    do_HEAD = do_PUT
    do_OPTIONS = do_PUT

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

    def _session_id(self) -> str:
        cookie = SimpleCookie(self.headers.get("Cookie", "")); morsel = cookie.get("mot_ui_session")
        with type(self).sessions_lock:
            if morsel is None or morsel.value not in type(self).sessions or type(self).sessions[morsel.value][1] <= time.monotonic():
                raise PermissionError("Missing session")
        return morsel.value

    def _trusted_mutation_headers(self) -> bool:
        host = self.headers.get("Host", ""); origin = self.headers.get("Origin", "")
        if origin != f"http://{host}" or self.headers.get("Sec-Fetch-Site") != "same-origin":
            self._error("untrusted_origin", "Local creation requires a same-origin request.", HTTPStatus.FORBIDDEN); return False
        try: session = self._session_id()
        except PermissionError:
            self._error("invalid_session", "Local creation session is missing or expired.", HTTPStatus.FORBIDDEN); return False
        with type(self).sessions_lock:
            expected_csrf = type(self).sessions.get(session, (None, 0))[0]
        if self.headers.get("X-CSRF-Token") != expected_csrf:
            self._error("invalid_csrf", "Local creation request could not be verified.", HTTPStatus.FORBIDDEN); return False
        return True

    def _read_json_body(self) -> dict[str, Any]:
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json" or self.headers.get("Transfer-Encoding"):
            raise ValueError("A bounded JSON request body is required.")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdigit(): raise ValueError("Content-Length is required.")
        length = int(raw_length)
        if length > 32 * 1024: raise ValueError("Request body is too large.")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict): raise ValueError("JSON body must be an object.")
        def depth(value: Any, level: int = 0) -> int:
            if level > 12: raise ValueError("JSON body is too deeply nested.")
            if isinstance(value, dict):
                for key, child in value.items():
                    if not isinstance(key, str): raise ValueError("JSON object keys must be strings.")
                    depth(child, level + 1)
            elif isinstance(value, list):
                for child in value: depth(child, level + 1)
            return level
        depth(payload)
        return payload

    def _method_not_allowed(self) -> None:
        self._json(
            {"error": {"code": "method_not_allowed", "message": "This method is not available."}},
            status=HTTPStatus.METHOD_NOT_ALLOWED,
            extra_headers={"Allow": "GET, POST"},
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
    ReadOnlyWorkflowHandler.creation_service = CreationService(
        ReadOnlyWorkflowHandler.repository_root,
        RepositorySnapshotProvider(ReadOnlyWorkflowHandler.repository_root, Path("/usr/bin/git")),
    )
    server = ThreadingHTTPServer((HOST, PORT), ReadOnlyWorkflowHandler)
    print(f"Local workflow API listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
