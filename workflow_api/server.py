"""Minimal localhost bridge for workflow inspection and guarded actions.

Remote surfaces are explicit and CSRF-protected: a read-only Zeus snapshot and
review-before-write campaign preparation and smoke submission.  There is no
generic command endpoint or caller-controlled scheduler operation.
"""

from __future__ import annotations

import json
import secrets
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
from workflow_api.zeus_snapshot import ZeusSnapshotError, ZeusSnapshotProvider, ZeusSnapshotService
from workflow_api.zeus_transfer import ZeusPreparationCoordinator, ZeusPreparationError
from workflow_api.zeus_submission import ZeusSmokeSubmissionCoordinator, ZeusSubmissionError

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
    zeus_service: ZeusSnapshotService | None = None
    transfer_service: ZeusPreparationCoordinator | None = None
    submission_service: ZeusSmokeSubmissionCoordinator | None = None
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
            if self.creation_service is None and self.zeus_service is None and self.transfer_service is None and self.submission_service is None:
                self._error("session_unavailable", "Local actions are unavailable.", HTTPStatus.SERVICE_UNAVAILABLE)
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
                session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                sessions[session] = (csrf, now + 600)
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
        target = urlsplit(self.path)
        transfer_paths = {"/api/v1/zeus/transfers/preview", "/api/v1/zeus/transfers/confirm"}
        submission_paths = {"/api/v1/zeus/submissions/smoke/preview", "/api/v1/zeus/submissions/smoke/confirm"}
        allowed = {"/api/v1/campaigns/2d/preview", "/api/v1/campaigns/2d/confirm", "/api/v1/zeus/snapshot", *transfer_paths, *submission_paths}
        if target.query or target.path not in allowed:
            self._method_not_allowed(); return
        if target.path == "/api/v1/zeus/snapshot" and self.zeus_service is None:
            self._error("zeus_unavailable", "Read-only Zeus inspection is unavailable.", HTTPStatus.SERVICE_UNAVAILABLE); return
        if target.path in transfer_paths and self.transfer_service is None:
            self._error("zeus_preparation_unavailable", "Zeus campaign preparation is unavailable.", HTTPStatus.SERVICE_UNAVAILABLE); return
        if target.path in submission_paths and self.submission_service is None:
            self._error("zeus_submission_unavailable", "Zeus smoke submission is unavailable.", HTTPStatus.SERVICE_UNAVAILABLE); return
        if target.path not in transfer_paths | submission_paths and target.path != "/api/v1/zeus/snapshot" and self.creation_service is None:
            self._error("creation_unavailable", "Local campaign creation is unavailable.", HTTPStatus.SERVICE_UNAVAILABLE); return
        if not self._trusted_mutation_headers(): return
        try:
            payload = self._read_json_body()
            session = self._session_id()
            if target.path == "/api/v1/zeus/snapshot":
                data = self.zeus_service.snapshot(payload)  # type: ignore[union-attr]
            elif target.path == "/api/v1/zeus/transfers/preview":
                data = self.transfer_service.preview(payload, session_id=session)  # type: ignore[union-attr]
            elif target.path == "/api/v1/zeus/transfers/confirm":
                data = self.transfer_service.confirm(payload, session_id=session)  # type: ignore[union-attr]
            elif target.path == "/api/v1/zeus/submissions/smoke/preview":
                data = self.submission_service.preview(payload, session_id=session)  # type: ignore[union-attr]
            elif target.path == "/api/v1/zeus/submissions/smoke/confirm":
                data = self.submission_service.confirm(payload, session_id=session)  # type: ignore[union-attr]
            elif target.path.endswith("/preview"):
                data = self.creation_service.preview(payload, session)
            else:
                if set(payload) != {"preview_token"} or not isinstance(payload.get("preview_token"), str):
                    raise ValueError("Confirmation payload is invalid.")
                data = self.creation_service.confirm(payload["preview_token"], session)
        except PermissionError:
            self._error("invalid_preview", "Preview confirmation is invalid or expired.", HTTPStatus.PRECONDITION_FAILED); return
        except ZeusSnapshotError as error:
            statuses = {
                "rate_limited": HTTPStatus.TOO_MANY_REQUESTS,
                "zeus_authentication_required": HTTPStatus.UNAUTHORIZED,
                "zeus_host_key_untrusted": HTTPStatus.PRECONDITION_FAILED,
                "zeus_timeout": HTTPStatus.GATEWAY_TIMEOUT,
                "zeus_unreachable": HTTPStatus.SERVICE_UNAVAILABLE,
                "remote_project_missing": HTTPStatus.PRECONDITION_FAILED,
                "scheduler_unavailable": HTTPStatus.SERVICE_UNAVAILABLE,
                "malformed_remote_response": HTTPStatus.BAD_GATEWAY,
            }
            messages = {
                "rate_limited": "Wait before checking Zeus again.",
                "zeus_authentication_required": "An existing SSH key or agent is required.",
                "zeus_host_key_untrusted": "The Zeus host key must be verified outside this application.",
                "zeus_timeout": "The read-only Zeus check timed out.",
                "zeus_unreachable": "Zeus could not be reached.",
                "remote_project_missing": "The remote project directory could not be verified.",
                "scheduler_unavailable": "The Zeus scheduler is unavailable.",
                "malformed_remote_response": "Zeus returned an invalid read-only snapshot.",
                "zeus_check_failed": "The read-only Zeus check failed safely.",
            }
            self._error(error.code, messages.get(error.code, messages["zeus_check_failed"]), statuses.get(error.code, HTTPStatus.BAD_GATEWAY)); return
        except ZeusPreparationError as error:
            statuses = {
                "request_invalid": HTTPStatus.BAD_REQUEST,
                "profile_invalid": HTTPStatus.BAD_REQUEST,
                "campaign_not_found": HTTPStatus.NOT_FOUND,
                "confirmation_invalid": HTTPStatus.PRECONDITION_FAILED,
                "confirmation_expired": HTTPStatus.PRECONDITION_FAILED,
                "too_many_pending_previews": HTTPStatus.TOO_MANY_REQUESTS,
                "zeus_authentication_required": HTTPStatus.UNAUTHORIZED,
                "zeus_host_key_untrusted": HTTPStatus.PRECONDITION_FAILED,
                "zeus_timeout": HTTPStatus.GATEWAY_TIMEOUT,
                "zeus_unreachable": HTTPStatus.SERVICE_UNAVAILABLE,
                "remote_project_missing": HTTPStatus.PRECONDITION_FAILED,
                "target_exists": HTTPStatus.CONFLICT,
                "remote_input_conflict": HTTPStatus.CONFLICT,
                "remote_campaign_conflict": HTTPStatus.CONFLICT,
                "local_checkout_mismatch": HTTPStatus.PRECONDITION_FAILED,
                "remote_checkout_mismatch": HTTPStatus.PRECONDITION_FAILED,
            }
            messages = {
                "request_invalid": "The Zeus preparation request is invalid.",
                "profile_invalid": "The Zeus connection profile is invalid.",
                "campaign_not_found": "The selected campaign was not found.",
                "confirmation_invalid": "The preparation preview is invalid or belongs to another session.",
                "confirmation_expired": "The preparation preview has expired. Review it again before continuing.",
                "too_many_pending_previews": "Too many preparation previews are pending.",
                "zeus_authentication_required": "An existing SSH key or agent is required.",
                "zeus_host_key_untrusted": "The Zeus host key must be verified outside this application.",
                "zeus_timeout": "The Zeus preparation check timed out.",
                "zeus_unreachable": "Zeus could not be reached.",
                "remote_project_missing": "The remote project directory could not be verified.",
                "target_exists": "A remote file appeared after review. Review the preparation again.",
                "remote_input_conflict": "A required Zeus input differs from the frozen campaign input.",
                "remote_campaign_conflict": "The Zeus campaign destination already contains different or incomplete files.",
                "local_checkout_mismatch": "The local checkout is not clean at the campaign commit.",
                "remote_checkout_mismatch": "The Zeus checkout is not clean at the campaign commit.",
            }
            self._error(error.code, messages.get(error.code, "Zeus preparation stopped safely."), statuses.get(error.code, HTTPStatus.PRECONDITION_FAILED)); return
        except ZeusSubmissionError as error:
            statuses = {
                "request_invalid": HTTPStatus.BAD_REQUEST, "profile_invalid": HTTPStatus.BAD_REQUEST,
                "campaign_not_found": HTTPStatus.NOT_FOUND, "campaign_not_smoke": HTTPStatus.PRECONDITION_FAILED,
                "campaign_not_canonical": HTTPStatus.PRECONDITION_FAILED,
                "confirmation_invalid": HTTPStatus.PRECONDITION_FAILED, "confirmation_expired": HTTPStatus.PRECONDITION_FAILED,
                "too_many_pending_previews": HTTPStatus.TOO_MANY_REQUESTS,
                "zeus_authentication_required": HTTPStatus.UNAUTHORIZED,
                "zeus_host_key_untrusted": HTTPStatus.PRECONDITION_FAILED, "zeus_timeout": HTTPStatus.GATEWAY_TIMEOUT,
                "zeus_unreachable": HTTPStatus.SERVICE_UNAVAILABLE, "remote_project_missing": HTTPStatus.PRECONDITION_FAILED,
                "local_checkout_mismatch": HTTPStatus.PRECONDITION_FAILED, "local_files_changed": HTTPStatus.PRECONDITION_FAILED,
                "remote_preparation_invalid": HTTPStatus.PRECONDITION_FAILED,
                "submission_outcome_unknown": HTTPStatus.CONFLICT, "already_submitted": HTTPStatus.CONFLICT,
                "smoke_already_started": HTTPStatus.CONFLICT,
                "submission_record_invalid": HTTPStatus.CONFLICT,
                "submission_busy": HTTPStatus.CONFLICT,
            }
            messages = {
                "request_invalid": "The smoke-submission request is invalid.", "profile_invalid": "The Zeus connection profile is invalid.",
                "campaign_not_found": "The selected campaign was not found.", "campaign_not_smoke": "Only a campaign awaiting its smoke stage can be submitted.",
                "campaign_not_canonical": "The campaign does not match the canonical portable smoke plan.",
                "confirmation_invalid": "The submission preview is invalid or belongs to another session.",
                "confirmation_expired": "The submission preview has expired. Review it again before continuing.",
                "too_many_pending_previews": "Too many submission previews are pending.",
                "zeus_authentication_required": "An existing SSH key or agent is required.",
                "zeus_host_key_untrusted": "The Zeus host key must be verified outside this application.",
                "zeus_timeout": "The read-only submission check timed out.", "zeus_unreachable": "Zeus could not be reached.",
                "remote_project_missing": "The remote project directory could not be verified.",
                "local_checkout_mismatch": "The local checkout is not clean at the campaign commit.",
                "local_files_changed": "The campaign changed after review. Review it again before submitting.",
                "remote_preparation_invalid": "The exact prepared campaign could not be verified on Zeus.",
                "submission_outcome_unknown": "A previous submission attempt has an uncertain outcome. Automatic retry is blocked to prevent a duplicate job.",
                "already_submitted": "This smoke stage already has a durable Zeus submission record.",
                "smoke_already_started": "Smoke-stage outputs already exist on Zeus, so automatic submission is blocked.",
                "submission_record_invalid": "The durable Zeus submission record is invalid or conflicting.",
                "submission_busy": "Another submission operation is already checking this campaign.",
            }
            self._error(error.code, messages.get(error.code, "Zeus smoke submission stopped safely."), statuses.get(error.code, HTTPStatus.PRECONDITION_FAILED)); return
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
    ReadOnlyWorkflowHandler.zeus_service = ZeusSnapshotService(
        ZeusSnapshotProvider(ReadOnlyWorkflowHandler.repository_root, Path("/usr/bin/ssh")),
    )
    ReadOnlyWorkflowHandler.transfer_service = ZeusPreparationCoordinator(
        ReadOnlyWorkflowHandler.repository_root, Path("/usr/bin/ssh"), Path("/usr/bin/git"),
    )
    ReadOnlyWorkflowHandler.submission_service = ZeusSmokeSubmissionCoordinator(
        ReadOnlyWorkflowHandler.repository_root, Path("/usr/bin/ssh"), Path("/usr/bin/git"),
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
