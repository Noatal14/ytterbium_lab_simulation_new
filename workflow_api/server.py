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
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from workflow_api import list_workflows
from workflow_api.discovery import DiscoveryError, get_campaign, list_campaigns
from workflow_api.error_catalog import resolve_error, resolve_wire_error
from workflow_api.models import SCHEMA_VERSION
from workflow_api.mot_2d_sources import list_sources
from workflow_api.mutation import CreationService
from workflow_api.repository_snapshot import RepositorySnapshotProvider
from workflow_api.zeus_snapshot import ZeusSnapshotError, ZeusSnapshotProvider, ZeusSnapshotService
from workflow_api.zeus_transfer import ZeusPreparationCoordinator, ZeusPreparationError
from workflow_api.zeus_submission import ZeusSmokeSubmissionCoordinator, ZeusSubmissionError
from workflow_api.zeus_screening import ZeusScreeningCoordinator, ZeusScreeningError
from workflow_api.zeus_screen_submission import ZeusScreenSubmissionCoordinator, ZeusScreenSubmissionError
from workflow_api.zeus_refinement import ZeusRefinementCoordinator, ZeusRefinementError
from workflow_api.zeus_refinement_submission import ZeusRefinementSubmissionCoordinator, ZeusRefinementSubmissionError
from workflow_api.zeus_confirmation import ZeusConfirmationCoordinator, ZeusConfirmationError

HOST = "127.0.0.1"
PORT = 8765


def workflow_catalog_payload() -> dict[str, Any]:
    return {
        "api_version": SCHEMA_VERSION,
        "data": [workflow.to_dict() for workflow in list_workflows()],
    }


@dataclass(frozen=True)
class PostRoute:
    path: str
    service_attr: str
    operation: str
    call_style: str
    unavailable_code: str
    unavailable_message: str
    success_status: HTTPStatus
    exception_family: type[Exception]


def _post_routes() -> tuple[PostRoute, ...]:
    rows = [
        ("/api/v1/campaigns/2d/preview","creation_service","preview","creation_preview","creation_unavailable","Local campaign creation is unavailable.",HTTPStatus.OK,Exception),
        ("/api/v1/campaigns/2d/confirm","creation_service","confirm","creation_confirm","creation_unavailable","Local campaign creation is unavailable.",HTTPStatus.CREATED,Exception),
        ("/api/v1/zeus/snapshot","zeus_service","snapshot","payload","zeus_unavailable","Read-only Zeus inspection is unavailable.",HTTPStatus.OK,ZeusSnapshotError),
        ("/api/v1/zeus/transfers/preview","transfer_service","preview","session_kw","zeus_preparation_unavailable","Zeus campaign preparation is unavailable.",HTTPStatus.OK,ZeusPreparationError),
        ("/api/v1/zeus/transfers/confirm","transfer_service","confirm","session_kw","zeus_preparation_unavailable","Zeus campaign preparation is unavailable.",HTTPStatus.CREATED,ZeusPreparationError),
        ("/api/v1/zeus/submissions/smoke/preview","submission_service","preview","session_kw","zeus_submission_unavailable","Zeus smoke submission is unavailable.",HTTPStatus.OK,ZeusSubmissionError),
        ("/api/v1/zeus/submissions/smoke/confirm","submission_service","confirm","session_kw","zeus_submission_unavailable","Zeus smoke submission is unavailable.",HTTPStatus.CREATED,ZeusSubmissionError),
        ("/api/v1/zeus/smoke/status","screening_service","status","session_kw","zeus_screening_unavailable","Zeus smoke inspection is unavailable.",HTTPStatus.OK,ZeusScreeningError),
        ("/api/v1/zeus/screening/preview","screening_service","preview","session_kw","zeus_screening_unavailable","Zeus smoke inspection is unavailable.",HTTPStatus.OK,ZeusScreeningError),
        ("/api/v1/zeus/screening/confirm","screening_service","confirm","session_kw","zeus_screening_unavailable","Zeus smoke inspection is unavailable.",HTTPStatus.CREATED,ZeusScreeningError),
        ("/api/v1/zeus/submissions/screening/preview","screen_submission_service","preview","session_kw","zeus_screen_submission_unavailable","Zeus screening submission is unavailable.",HTTPStatus.OK,ZeusScreenSubmissionError),
        ("/api/v1/zeus/submissions/screening/confirm","screen_submission_service","confirm","session_kw","zeus_screen_submission_unavailable","Zeus screening submission is unavailable.",HTTPStatus.CREATED,ZeusScreenSubmissionError),
        ("/api/v1/zeus/screen/status","refinement_service","status","payload","zeus_refinement_unavailable","Zeus refinement preparation is unavailable.",HTTPStatus.OK,ZeusRefinementError),
        ("/api/v1/zeus/refinement/preview","refinement_service","preview","session_kw","zeus_refinement_unavailable","Zeus refinement preparation is unavailable.",HTTPStatus.OK,ZeusRefinementError),
        ("/api/v1/zeus/refinement/confirm","refinement_service","confirm","session_kw","zeus_refinement_unavailable","Zeus refinement preparation is unavailable.",HTTPStatus.CREATED,ZeusRefinementError),
        ("/api/v1/zeus/submissions/refinement/status","refinement_submission_service","status","payload","zeus_refinement_submission_unavailable","Zeus refinement submission is unavailable.",HTTPStatus.OK,ZeusRefinementSubmissionError),
        ("/api/v1/zeus/submissions/refinement/preview","refinement_submission_service","preview","session_kw","zeus_refinement_submission_unavailable","Zeus refinement submission is unavailable.",HTTPStatus.OK,ZeusRefinementSubmissionError),
        ("/api/v1/zeus/submissions/refinement/confirm","refinement_submission_service","confirm","session_kw","zeus_refinement_submission_unavailable","Zeus refinement submission is unavailable.",HTTPStatus.CREATED,ZeusRefinementSubmissionError),
        ("/api/v1/zeus/refinement-chain/status","confirmation_service","status","payload","zeus_confirmation_unavailable","Zeus confirmation preparation is unavailable.",HTTPStatus.OK,ZeusConfirmationError),
        ("/api/v1/zeus/confirmation/preview","confirmation_service","preview","session_kw","zeus_confirmation_unavailable","Zeus confirmation preparation is unavailable.",HTTPStatus.OK,ZeusConfirmationError),
        ("/api/v1/zeus/confirmation/confirm","confirmation_service","confirm","session_kw","zeus_confirmation_unavailable","Zeus confirmation preparation is unavailable.",HTTPStatus.CREATED,ZeusConfirmationError),
    ]
    return tuple(PostRoute(*row) for row in rows)


POST_ROUTES = {route.path: route for route in _post_routes()}


def _invoke_post_route(route: PostRoute, service: object, payload: dict[str, Any], session: str) -> Any:
    operation = getattr(service, route.operation)
    if route.call_style == "payload": return operation(payload)
    if route.call_style == "session_kw": return operation(payload, session_id=session)
    if route.call_style == "creation_preview": return operation(payload, session)
    if route.call_style == "creation_confirm":
        if set(payload) != {"preview_token"} or not isinstance(payload.get("preview_token"), str):
            raise ValueError("Confirmation payload is invalid.")
        return operation(payload["preview_token"], session)
    raise RuntimeError("Invalid closed route call style.")


class WorkflowHandler(BaseHTTPRequestHandler):
    """Serve allowlisted inspection and explicitly confirmed action endpoints."""

    server_version = "WorkflowAPI/1"
    repository_root = Path(__file__).resolve().parents[1]
    creation_service: CreationService | None = None
    zeus_service: ZeusSnapshotService | None = None
    transfer_service: ZeusPreparationCoordinator | None = None
    submission_service: ZeusSmokeSubmissionCoordinator | None = None
    screening_service: ZeusScreeningCoordinator | None = None
    screen_submission_service: ZeusScreenSubmissionCoordinator | None = None
    refinement_service: ZeusRefinementCoordinator | None = None
    refinement_submission_service: ZeusRefinementSubmissionCoordinator | None = None
    confirmation_service: ZeusConfirmationCoordinator | None = None
    sessions: dict[str, tuple[str, float]] = {}
    sessions_lock = threading.Lock()

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._trusted_request_target():
            return
        target = urlsplit(self.path)
        path = target.path
        if target.query:
            self._catalog_error("protocol", "unsupported_query")
            return
        if path == "/api/health":
            self._json({"api_version": SCHEMA_VERSION, "status": "ok"})
            return
        if path == "/api/workflows":
            self._json(workflow_catalog_payload())
            return
        if path == "/api/v1/session":
            if self.creation_service is None and self.zeus_service is None and self.transfer_service is None and self.submission_service is None and self.screening_service is None and self.screen_submission_service is None and self.refinement_service is None and self.refinement_submission_service is None and self.confirmation_service is None:
                self._catalog_error("protocol", "session_unavailable")
                return
            if self.headers.get("Sec-Fetch-Site") != "same-origin":
                self._catalog_error("protocol", "untrusted_origin")
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
                self._catalog_error("protocol", "inspection_failed")
                return
            self._json({"api_version": SCHEMA_VERSION, "data": data})
            return
        if path == "/api/v1/campaigns/2d/sources":
            try:
                data = list_sources(self.repository_root)
            except Exception:
                self._catalog_error("protocol", "source_inspection_failed")
                return
            self._json({"api_version": SCHEMA_VERSION, "data": data})
            return
        prefix = "/api/v1/campaigns/"
        if path.startswith(prefix):
            encoded_id = path[len(prefix):]
            if not encoded_id or "/" in encoded_id or unquote(encoded_id) != encoded_id:
                self._catalog_error("protocol", "invalid_campaign_id")
                return
            try:
                campaign = get_campaign(self.repository_root, encoded_id)
            except DiscoveryError as error:
                resolved = resolve_wire_error("local_read", error.code, error.message)
                self._error(resolved.code, resolved.message, resolved.status)
                return
            except Exception:
                self._catalog_error("protocol", "inspection_failed")
                return
            self._json({"api_version": SCHEMA_VERSION, "data": campaign})
            return
        self._catalog_error("protocol", "not_found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._trusted_request_target(): return
        target = urlsplit(self.path)
        route = POST_ROUTES.get(target.path)
        if target.query or route is None:
            self._method_not_allowed(); return
        service = getattr(self, route.service_attr)
        if service is None:
            self._error(route.unavailable_code, route.unavailable_message, HTTPStatus.SERVICE_UNAVAILABLE); return
        if not self._trusted_mutation_headers(): return
        try:
            payload = self._read_json_body()
            session = self._session_id()
            data = _invoke_post_route(route, service, payload, session)
        except PermissionError:
            self._catalog_error("protocol", "invalid_preview"); return
        except ZeusSnapshotError as error:
            resolved = resolve_error("snapshot", error.code)
            self._error(resolved.code, resolved.message, resolved.status); return
        except ZeusPreparationError as error:
            resolved = resolve_error("transfer", error.code)
            self._error(resolved.code, resolved.message, resolved.status); return
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
        except ZeusScreeningError as error:
            if error.code in {"request_invalid", "profile_invalid"}: status = HTTPStatus.BAD_REQUEST
            elif error.code == "campaign_not_found": status = HTTPStatus.NOT_FOUND
            elif error.code == "zeus_authentication_required": status = HTTPStatus.UNAUTHORIZED
            elif error.code in {"zeus_unreachable", "scheduler_unavailable"}: status = HTTPStatus.SERVICE_UNAVAILABLE
            elif error.code == "zeus_timeout": status = HTTPStatus.GATEWAY_TIMEOUT
            elif error.code in {"transition_busy", "transition_conflict", "transition_outcome_unknown", "screening_already_prepared"}: status = HTTPStatus.CONFLICT
            else: status = HTTPStatus.PRECONDITION_FAILED
            messages = {
                "smoke_running": "The smoke check is still running.", "smoke_held": "The smoke job needs attention on Zeus.",
                "smoke_failed": "The smoke job finished with an error.", "smoke_status_unknown": "The smoke outcome could not be established safely.",
                "smoke_outputs_pending": "The smoke job succeeded; its output files are still becoming visible.",
                "smoke_outputs_invalid": "The smoke outputs failed validation.", "screening_already_prepared": "Screening is already prepared on Zeus.",
                "transition_outcome_unknown": "Screening preparation may have changed Zeus. Inspect it before retrying.",
                "confirmation_invalid": "The screening preview is invalid or belongs to another session.",
                "confirmation_expired": "The screening preview expired. Review it again.",
                "local_checkout_mismatch": "The local checkout no longer matches the campaign commit.",
                "remote_checkout_mismatch": "The Zeus checkout no longer matches the campaign commit.",
                "zeus_authentication_required": "An existing SSH key or agent is required.",
                "zeus_host_key_untrusted": "The Zeus host key must be verified outside this application.",
                "zeus_timeout": "The Zeus inspection timed out.", "zeus_unreachable": "Zeus could not be reached.",
                "scheduler_unavailable": "The Zeus scheduler history could not be read.", "transition_busy": "Another screening preparation is in progress.",
                "transition_conflict": "A screening artifact conflicts with the reviewed plan.",
            }
            self._error(error.code, messages.get(error.code, "Smoke inspection or screening preparation stopped safely."), status); return
        except ZeusScreenSubmissionError as error:
            if error.code in {"request_invalid","profile_invalid"}: status=HTTPStatus.BAD_REQUEST
            elif error.code=="campaign_not_found": status=HTTPStatus.NOT_FOUND
            elif error.code=="zeus_authentication_required": status=HTTPStatus.UNAUTHORIZED
            elif error.code in {"zeus_unreachable"}: status=HTTPStatus.SERVICE_UNAVAILABLE
            elif error.code=="zeus_timeout": status=HTTPStatus.GATEWAY_TIMEOUT
            elif error.code in {"screening_already_submitted","screening_already_started","screening_submission_busy","screening_submission_record_invalid","screening_submission_outcome_unknown"}: status=HTTPStatus.CONFLICT
            else: status=HTTPStatus.PRECONDITION_FAILED
            messages={"campaign_not_canonical":"The selected campaign does not match its frozen design.","screening_not_prepared":"The exact Screening plan is not prepared on Zeus.","screening_already_submitted":"Screening already has a durable Zeus submission record.","screening_already_started":"Screening outputs already exist, so submission is blocked.","screening_submission_busy":"Another Screening submission check is in progress.","screening_submission_record_invalid":"The Screening submission record is invalid or conflicting.","screening_submission_outcome_unknown":"A Screening submission attempt has an uncertain outcome. Automatic retry is blocked.","confirmation_invalid":"The submission preview is invalid or belongs to another session.","confirmation_expired":"The submission preview expired. Review it again.","local_checkout_mismatch":"The local checkout no longer matches the campaign commit.","local_files_changed":"The campaign changed after review. Review it again.","remote_checkout_mismatch":"The Zeus checkout no longer matches the campaign commit.","zeus_authentication_required":"An existing SSH key or agent is required.","zeus_host_key_untrusted":"The Zeus host key must be verified outside this application.","zeus_timeout":"The Zeus submission check timed out.","zeus_unreachable":"Zeus could not be reached."}
            self._error(error.code,messages.get(error.code,"Screening submission stopped safely."),status);return
        except ZeusRefinementError as error:
            status=HTTPStatus.BAD_REQUEST if error.code in {"request_invalid","profile_invalid"} else HTTPStatus.NOT_FOUND if error.code=="campaign_not_found" else HTTPStatus.UNAUTHORIZED if error.code=="zeus_authentication_required" else HTTPStatus.CONFLICT if error.code in {"transition_busy","transition_conflict","transition_outcome_unknown","refinement_already_prepared"} else HTTPStatus.PRECONDITION_FAILED
            self._error(error.code,"Refinement preparation stopped safely.",status);return
        except ZeusRefinementSubmissionError as error:
            status=HTTPStatus.BAD_REQUEST if error.code in {"request_invalid","profile_invalid"} else HTTPStatus.NOT_FOUND if error.code=="campaign_not_found" else HTTPStatus.UNAUTHORIZED if error.code=="zeus_authentication_required" else HTTPStatus.CONFLICT if error.code in {"refinement_chain_already_submitted","refinement_chain_partially_submitted","refinement_submission_busy","refinement_submission_outcome_unknown","refinement_already_started"} else HTTPStatus.PRECONDITION_FAILED
            self._error(error.code,"Refinement submission stopped safely.",status);return
        except ZeusConfirmationError as error:
            status=HTTPStatus.BAD_REQUEST if error.code in {"request_invalid","profile_invalid"} else HTTPStatus.NOT_FOUND if error.code=="campaign_not_found" else HTTPStatus.CONFLICT if error.code in {"transition_busy","transition_conflict","transition_outcome_unknown","confirmation_already_prepared"} else HTTPStatus.PRECONDITION_FAILED
            self._error(error.code,"Confirmation preparation stopped safely.",status);return
        except BlockingIOError:
            self._catalog_error("creation", "rate_limited"); return
        except FileExistsError:
            self._catalog_error("creation", "campaign_exists"); return
        except ValueError as error:
            resolved = resolve_wire_error("creation", "invalid_request", str(error))
            self._error(resolved.code, resolved.message, resolved.status); return
        except Exception:
            self._catalog_error("creation", "creation_failed"); return
        self._json({"api_version": SCHEMA_VERSION, "data": data}, status=route.success_status)

    def do_PUT(self) -> None: self._method_not_allowed()  # noqa: N802
    do_PATCH = do_PUT
    do_DELETE = do_PUT
    do_HEAD = do_PUT
    do_OPTIONS = do_PUT

    def _trusted_request_target(self) -> bool:
        target = urlsplit(self.path)
        if target.scheme or target.netloc:
            self._catalog_error("protocol", "invalid_request_target")
            return False
        host = self.headers.get("Host", "")
        hostname = host.rsplit(":", 1)[0].lower()
        if hostname not in {"127.0.0.1", "localhost"}:
            self._catalog_error("protocol", "untrusted_host")
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
            self._catalog_error("protocol", "untrusted_origin"); return False
        try: session = self._session_id()
        except PermissionError:
            self._catalog_error("protocol", "invalid_session"); return False
        with type(self).sessions_lock:
            expected_csrf = type(self).sessions.get(session, (None, 0))[0]
        if self.headers.get("X-CSRF-Token") != expected_csrf:
            self._catalog_error("protocol", "invalid_csrf"); return False
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
        error = resolve_error("protocol", "method_not_allowed")
        self._json(
            {"error": {"code": error.code, "message": error.message}},
            status=error.status,
            extra_headers={"Allow": "GET, POST"},
        )

    def _catalog_error(self, domain: str, case: str) -> None:
        error = resolve_error(domain, case)
        self._error(error.code, error.message, error.status)

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


# Compatibility for external imports and existing test harnesses.
ReadOnlyWorkflowHandler = WorkflowHandler


def main() -> None:
    WorkflowHandler.creation_service = CreationService(
        WorkflowHandler.repository_root,
        RepositorySnapshotProvider(WorkflowHandler.repository_root, Path("/usr/bin/git")),
    )
    WorkflowHandler.zeus_service = ZeusSnapshotService(
        ZeusSnapshotProvider(WorkflowHandler.repository_root, Path("/usr/bin/ssh")),
    )
    WorkflowHandler.transfer_service = ZeusPreparationCoordinator(
        WorkflowHandler.repository_root, Path("/usr/bin/ssh"), Path("/usr/bin/git"),
    )
    WorkflowHandler.submission_service = ZeusSmokeSubmissionCoordinator(
        WorkflowHandler.repository_root, Path("/usr/bin/ssh"), Path("/usr/bin/git"),
    )
    WorkflowHandler.screening_service = ZeusScreeningCoordinator(
        WorkflowHandler.repository_root, Path("/usr/bin/ssh"), Path("/usr/bin/git"),
    )
    WorkflowHandler.screen_submission_service = ZeusScreenSubmissionCoordinator(
        WorkflowHandler.repository_root, Path("/usr/bin/ssh"), Path("/usr/bin/git"),
    )
    WorkflowHandler.refinement_service = ZeusRefinementCoordinator(
        WorkflowHandler.repository_root, Path("/usr/bin/ssh"), Path("/usr/bin/git"),
    )
    WorkflowHandler.refinement_submission_service = ZeusRefinementSubmissionCoordinator(
        WorkflowHandler.repository_root, Path("/usr/bin/ssh"), Path("/usr/bin/git"),
    )
    WorkflowHandler.confirmation_service = ZeusConfirmationCoordinator(
        WorkflowHandler.repository_root, Path("/usr/bin/ssh"), Path("/usr/bin/git"),
    )
    server = ThreadingHTTPServer((HOST, PORT), WorkflowHandler)
    print(f"Local workflow API listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
