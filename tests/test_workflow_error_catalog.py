"""Freeze the current v1 error behavior before handlers adopt the catalog."""

from __future__ import annotations

import ast
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import re
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from workflow_api.error_catalog import (
    ERROR_DOMAINS,
    ErrorSpec,
    catalog_payload,
    render_catalog,
    resolve_error,
)
from workflow_api.server import POST_ROUTES, ReadOnlyWorkflowHandler
from workflow_api.zeus_confirmation import ZeusConfirmationError
from workflow_api.zeus_refinement import ZeusRefinementError
from workflow_api.zeus_refinement_submission import ZeusRefinementSubmissionError
from workflow_api.zeus_screen_submission import ZeusScreenSubmissionError
from workflow_api.zeus_screening import ZeusScreeningError
from workflow_api.zeus_snapshot import ZeusSnapshotError
from workflow_api.zeus_submission import ZeusSubmissionError
from workflow_api.zeus_transfer import ZeusPreparationError

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests/contracts/v1/workflow_api_error_catalog.json"


def test_route_unavailable_catalog_matches_active_registry_exactly():
    expected = {
        (route.unavailable_code, 503, route.unavailable_message)
        for route in POST_ROUTES.values()
    }
    observed = {
        (code, int(spec.status), spec.message)
        for code, spec in ERROR_DOMAINS["route_unavailable"].entries.items()
    }
    assert observed == expected


def test_every_literal_coordinator_error_is_explicitly_catalogued():
    file_domains = {
        "zeus_snapshot.py": "snapshot",
        "zeus_transfer.py": "transfer",
        "zeus_submission.py": "smoke_submission",
        "zeus_screening.py": "smoke_transition",
        "zeus_screen_submission.py": "screen_submission",
        "zeus_refinement.py": "refinement_transition",
        "zeus_refinement_submission.py": "refinement_submission",
        "zeus_confirmation.py": "confirmation_transition",
    }
    for filename, domain in file_domains.items():
        tree = ast.parse((ROOT / "workflow_api" / filename).read_text())
        emitted = set()
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Raise)
                or not isinstance(node.exc, ast.Call)
                or not node.exc.args
            ):
                continue
            name = node.exc.func.id if isinstance(node.exc.func, ast.Name) else ""
            if not name.startswith("Zeus") or not name.endswith("Error"):
                continue
            error_code = node.exc.args[0]
            if (
                isinstance(error_code, ast.Constant)
                and isinstance(error_code.value, str)
                and re.fullmatch(r"[a-z0-9_]+", error_code.value)
            ):
                emitted.add(error_code.value)
        missing = emitted - set(ERROR_DOMAINS[domain].entries)
        assert (
            not missing
        ), f"{domain} missing statically emitted/mapped codes: {sorted(missing)}"


def test_propagated_and_remote_receiver_codes_are_explicit_not_hidden_by_fallbacks():
    assert set(ERROR_DOMAINS["transfer"].entries) <= set(
        ERROR_DOMAINS["refinement_transition"].entries
    )
    assert set(ERROR_DOMAINS["refinement_transition"].entries) <= set(
        ERROR_DOMAINS["refinement_submission"].entries
    )
    assert set(ERROR_DOMAINS["refinement_submission"].entries) <= set(
        ERROR_DOMAINS["confirmation_transition"].entries
    )
    receiver_domains = {
        "zeus_screening_remote.py": "smoke_transition",
        "zeus_screen_submission_remote.py": "screen_submission",
        "zeus_refinement_remote.py": "refinement_transition",
        "zeus_refinement_submission_remote.py": "refinement_submission",
        "zeus_confirmation_remote.py": "confirmation_transition",
    }
    pattern = re.compile(r'fail\("([a-z0-9_]+)"')
    for filename, domain in receiver_domains.items():
        emitted = set(pattern.findall((ROOT / "workflow_api" / filename).read_text()))
        missing = emitted - set(ERROR_DOMAINS[domain].entries)
        assert not missing, f"{domain} missing remote receiver codes: {sorted(missing)}"


def test_catalog_snapshot_is_deterministic_and_declares_unversioned_wire_errors():
    assert json.loads(SNAPSHOT.read_text()) == catalog_payload()
    assert SNAPSHOT.read_bytes() == render_catalog().encode()
    assert catalog_payload()["wire_envelope"] == "unversioned-error"
    existing = json.loads(
        (ROOT / "tests/contracts/v1/workflow_api_errors.json").read_text()
    )
    assert all(
        set(case["body"]) == {"error"} and "api_version" not in case["body"]
        for case in existing["cases"]
    )


def test_generator_is_byte_deterministic(tmp_path):
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/generate_workflow_error_catalog.py"),
        "--output",
    ]
    subprocess.run([*command, str(first)], cwd=ROOT, check=True)
    subprocess.run([*command, str(second)], cwd=ROOT, check=True)
    assert first.read_bytes() == second.read_bytes() == SNAPSHOT.read_bytes()
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/generate_workflow_error_catalog.py"),
            "--check",
        ],
        cwd=ROOT,
        check=True,
    )
    first.write_text(first.read_text() + "drift\n")
    drift = subprocess.run([*command, str(first), "--check"], cwd=ROOT, check=False)
    assert drift.returncode != 0


def test_frontend_semantic_catalog_generator_is_checked_and_detects_drift(tmp_path):
    script = ROOT / "scripts/generate_ui_error_catalog.py"
    tracked = ROOT / "ui/src/generated/errorCatalog.v1.ts"
    subprocess.run([sys.executable, str(script), "--check"], cwd=ROOT, check=True)
    generated = tmp_path / "errorCatalog.v1.ts"
    subprocess.run(
        [sys.executable, str(script), "--output", str(generated)], cwd=ROOT, check=True
    )
    assert generated.read_bytes() == tracked.read_bytes()
    generated.write_text(generated.read_text() + "// drift\n")
    result = subprocess.run(
        [sys.executable, str(script), "--output", str(generated), "--check"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode != 0


def test_catalog_is_immutable_and_domain_qualified():
    with pytest.raises(TypeError):
        ERROR_DOMAINS["snapshot"].entries["new"] = ErrorSpec(400, "bad")  # type: ignore[arg-type,index]
    with pytest.raises((FrozenInstanceError, AttributeError)):
        ERROR_DOMAINS["snapshot"].fallback = ErrorSpec(400, "bad")  # type: ignore[misc]
    assert (
        ERROR_DOMAINS["transfer"].entries["confirmation_invalid"].message
        != ERROR_DOMAINS["smoke_submission"].entries["confirmation_invalid"].message
    )


def test_unknown_codes_remain_safe_fallbacks_and_never_enter_snapshot_as_real_codes():
    for domain_name, domain in ERROR_DOMAINS.items():
        assert "unexpected_remote_detail" not in domain.entries
        if domain.fallback is not None:
            assert domain.fallback.message.endswith(("safely.", "failed safely."))
            assert domain.fallback_code
        assert all(code != "<fallback>" for code in domain.entries)
    assert all(case["code"] != "<dynamic>" for case in catalog_payload()["cases"])


@pytest.mark.parametrize(
    "untrusted",
    [
        "unexpected_remote_detail",
        "internal_database_password",
        "x" * 10_000,
        "bad\ncode",
        "bad\x00code",
        "",
        None,
        {"error": "secret"},
    ],
)
def test_unknown_or_untrusted_codes_resolve_to_fixed_allowlisted_fallback(untrusted):
    resolved = resolve_error("smoke_submission", untrusted)
    assert resolved.code == "zeus_submission_failed"
    assert int(resolved.status) == 412
    assert resolved.message == "Zeus smoke submission stopped safely."
    if str(untrusted):
        assert str(untrusted) not in resolved.code
        assert str(untrusted) not in resolved.message


def test_known_case_ids_resolve_exact_wire_codes_including_aliases():
    ordinary = resolve_error("smoke_submission", "confirmation_expired")
    assert ordinary.code == "confirmation_expired"
    assert int(ordinary.status) == 412
    assert (
        ordinary.message
        == "The submission preview has expired. Review it again before continuing."
    )

    aliased = resolve_error("creation", "invalid_request#too_large")
    assert aliased.code == "invalid_request"
    assert int(aliased.status) == 413
    assert aliased.message == "Request body is too large."


def test_dynamic_propagation_boundary_never_inherits_untrusted_wire_codes():
    for domain_name in (
        "snapshot",
        "transfer",
        "smoke_submission",
        "smoke_transition",
        "screen_submission",
        "refinement_transition",
        "refinement_submission",
        "confirmation_transition",
    ):
        catalog = ERROR_DOMAINS[domain_name]
        resolved = resolve_error(domain_name, "remote_secret_from_error.code\n")
        assert resolved.code == catalog.fallback_code
        assert "remote_secret" not in resolved.code
        assert "remote_secret" not in resolved.message


class _RaisingService:
    def __init__(self, error):
        self.error = error

    def snapshot(self, _payload):
        raise self.error

    def status(self, _payload, **_kwargs):
        raise self.error

    def preview(self, _payload, *_args, **_kwargs):
        raise self.error

    def confirm(self, _payload, *_args, **_kwargs):
        raise self.error


@contextmanager
def _real_handler(error):
    handler = type("ErrorCatalogHandler", (ReadOnlyWorkflowHandler,), {})
    handler.sessions = {}
    service = _RaisingService(error)
    handler.creation_service = service
    handler.zeus_service = service
    handler.transfer_service = service
    handler.submission_service = service
    handler.screening_service = service
    handler.screen_submission_service = service
    handler.refinement_service = service
    handler.refinement_submission_service = service
    handler.confirmation_service = service
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    server.block_on_close = False
    thread = threading.Thread(
        target=lambda: [server.handle_request() for _ in range(2)], daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        thread.join(timeout=5)
        server.server_close()


def _request(base, method, path, headers=None, body=None):
    target = urlsplit(base)
    connection = HTTPConnection(target.hostname, target.port, timeout=2)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return (
            response.status,
            {key.lower(): value for key, value in response.headers.items()},
            json.loads(response.read()),
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("domain", "error_type", "path"),
    [
        ("snapshot", ZeusSnapshotError, "/api/v1/zeus/snapshot"),
        ("transfer", ZeusPreparationError, "/api/v1/zeus/transfers/preview"),
        (
            "smoke_submission",
            ZeusSubmissionError,
            "/api/v1/zeus/submissions/smoke/preview",
        ),
        ("smoke_transition", ZeusScreeningError, "/api/v1/zeus/smoke/status"),
        (
            "screen_submission",
            ZeusScreenSubmissionError,
            "/api/v1/zeus/submissions/screening/preview",
        ),
        ("refinement_transition", ZeusRefinementError, "/api/v1/zeus/screen/status"),
        (
            "refinement_submission",
            ZeusRefinementSubmissionError,
            "/api/v1/zeus/submissions/refinement/status",
        ),
        (
            "confirmation_transition",
            ZeusConfirmationError,
            "/api/v1/zeus/refinement-chain/status",
        ),
    ],
)
def test_every_catalogued_coordinator_error_matches_the_real_handler(
    domain, error_type, path
):
    for case, spec in ERROR_DOMAINS[domain].entries.items():
        code = spec.wire_code or case
        with _real_handler(error_type(code)) as base:
            session_status, session_headers, session_body = _request(
                base, "GET", "/api/v1/session", {"Sec-Fetch-Site": "same-origin"}
            )
            assert session_status == 200
            cookie = session_headers["set-cookie"].split(";", 1)[0]
            headers = {
                "Content-Type": "application/json",
                "Origin": base,
                "Sec-Fetch-Site": "same-origin",
                "Cookie": cookie,
                "X-CSRF-Token": session_body["data"]["csrf_token"],
            }
            status, _, body = _request(base, "POST", path, headers, "{}")
        assert status == int(spec.status), (domain, case, body)
        assert body == {"error": {"code": code, "message": spec.message}}, (
            domain,
            case,
        )
        assert "api_version" not in body


def _authorized_headers(base: str) -> dict[str, str]:
    session_status, session_headers, session_body = _request(
        base, "GET", "/api/v1/session", {"Sec-Fetch-Site": "same-origin"}
    )
    assert session_status == 200
    return {
        "Content-Type": "application/json",
        "Origin": base,
        "Sec-Fetch-Site": "same-origin",
        "Cookie": session_headers["set-cookie"].split(";", 1)[0],
        "X-CSRF-Token": session_body["data"]["csrf_token"],
    }


def test_every_catalogued_creation_error_matches_the_real_handler():
    for case, spec in ERROR_DOMAINS["creation"].entries.items():
        if case == "rate_limited":
            error = BlockingIOError()
        elif case == "campaign_exists":
            error = FileExistsError()
        elif case == "creation_failed":
            error = RuntimeError("secret internal failure")
        else:
            error = ValueError(spec.message)
        with _real_handler(error) as base:
            status, _, body = _request(
                base,
                "POST",
                "/api/v1/campaigns/2d/preview",
                _authorized_headers(base),
                "{}",
            )
        assert status == int(spec.status), (case, body)
        assert body == {
            "error": {"code": spec.wire_code or case, "message": spec.message}
        }, case


@pytest.mark.parametrize(
    ("error_type", "path", "expected_code", "expected_message", "status"),
    [
        (
            ZeusSnapshotError,
            "/api/v1/zeus/snapshot",
            "zeus_check_failed",
            "The read-only Zeus check failed safely.",
            502,
        ),
        (
            ZeusPreparationError,
            "/api/v1/zeus/transfers/preview",
            "zeus_preparation_failed",
            "Zeus preparation stopped safely.",
            412,
        ),
        (
            ZeusSubmissionError,
            "/api/v1/zeus/submissions/smoke/preview",
            "zeus_submission_failed",
            "Zeus smoke submission stopped safely.",
            412,
        ),
        (
            ZeusScreeningError,
            "/api/v1/zeus/smoke/status",
            "zeus_screening_failed",
            "Smoke inspection or screening preparation stopped safely.",
            412,
        ),
        (
            ZeusScreenSubmissionError,
            "/api/v1/zeus/submissions/screening/preview",
            "screening_submission_failed",
            "Screening submission stopped safely.",
            412,
        ),
        (
            ZeusRefinementError,
            "/api/v1/zeus/refinement/preview",
            "refinement_preparation_failed",
            "Refinement preparation stopped safely.",
            412,
        ),
        (
            ZeusRefinementSubmissionError,
            "/api/v1/zeus/submissions/refinement/preview",
            "refinement_submission_failed",
            "Refinement submission stopped safely.",
            412,
        ),
        (
            ZeusConfirmationError,
            "/api/v1/zeus/confirmation/preview",
            "confirmation_preparation_failed",
            "Confirmation preparation stopped safely.",
            412,
        ),
    ],
)
def test_unknown_remote_error_codes_fail_closed_in_real_handler(
    error_type, path, expected_code, expected_message, status
):
    with _real_handler(error_type("internal_secret_code\n/absolute/path")) as base:
        observed_status, response_headers, body = _request(
            base, "POST", path, _authorized_headers(base), "{}"
        )
    assert observed_status == status
    assert response_headers["cache-control"] == "no-store"
    assert response_headers["x-content-type-options"] == "nosniff"
    assert body == {"error": {"code": expected_code, "message": expected_message}}
    serialized = json.dumps(body)
    assert "internal_secret" not in serialized
    assert "/absolute/path" not in serialized


def test_unknown_creation_value_error_fails_closed_in_real_handler():
    with _real_handler(ValueError("secret /absolute/path")) as base:
        status, _, body = _request(
            base,
            "POST",
            "/api/v1/campaigns/2d/preview",
            _authorized_headers(base),
            "{}",
        )
    assert status == 412
    assert body == {
        "error": {
            "code": "creation_failed",
            "message": "Local campaign creation failed safely.",
        }
    }
    assert "secret" not in json.dumps(body)
    assert "/absolute/path" not in json.dumps(body)
