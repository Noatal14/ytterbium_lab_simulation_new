"""Read-only transport failures preserve job identity and expose no private data."""

import json
import logging
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from workflow_api.server import WorkflowHandler
from workflow_api.zeeman_zeus_execution import ZeemanZeusError

FAMILIES = [
    ("zeeman", "individual_zeeman_api"),
    ("mot-2d", "individual_mot_2d_api"),
    ("mot-3d", "individual_mot_3d_api"),
]
PRIVATE_DETAIL = "PRIVATE_EXCEPTION_DETAIL_and_private_remote_path"


def _request_failure(tmp_path, caplog, family, attribute, action, code):
    calls = []

    class ExistingJob:
        def _fail(self, action, payload):
            calls.append((action, payload))
            raise ZeemanZeusError(code) from RuntimeError(PRIVATE_DETAIL)

        def refresh_zeus(self, payload, *, session_id):
            self._fail("refresh", payload)

        def recover_zeus(self, payload, *, session_id):
            self._fail("recover", payload)

        def confirm_zeus(self, *args, **kwargs):
            raise AssertionError("A failed status read must not submit work")

    handler = type(
        "Handler",
        (WorkflowHandler,),
        {"repository_root": tmp_path, "sessions": {}, attribute: ExistingJob()},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HTTPConnection("127.0.0.1", server.server_port)
    try:
        client.request(
            "GET", "/api/v1/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        response = client.getresponse()
        cookie = response.getheader("Set-Cookie").split(";")[0]
        csrf = json.loads(response.read())["data"]["csrf_token"]
        payload = {
            "run_id": "existing-owned-test-run",
            "profile": {"username": "private.test.account"},
        }
        route = f"/api/v1/individual-runs/{family}/zeus/{action}"
        with caplog.at_level(logging.WARNING):
            client.request(
                "POST",
                route,
                json.dumps(payload),
                headers={
                    "Sec-Fetch-Site": "same-origin",
                    "Content-Type": "application/json",
                    "Origin": f"http://127.0.0.1:{server.server_port}",
                    "Cookie": cookie,
                    "X-CSRF-Token": csrf,
                },
            )
            response = client.getresponse()
            status, body = response.status, json.loads(response.read())
        assert calls == [(action, payload)]
        assert f"route={route}" in caplog.text
        for secret in (
            payload["run_id"],
            payload["profile"]["username"],
            csrf,
            cookie,
            PRIVATE_DETAIL,
        ):
            assert secret not in caplog.text
            assert secret not in json.dumps(body)
        return status, body
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("family,attribute", FAMILIES)
@pytest.mark.parametrize("action", ["refresh", "recover"])
@pytest.mark.parametrize(
    "code,status",
    [
        ("zeus_unavailable", 503),
        ("job_status_unavailable", 502),
        ("result_unavailable", 409),
        ("remote_response_invalid", 502),
    ],
)
def test_read_transport_failure_is_actionable_without_submission(
    tmp_path, caplog, family, attribute, action, code, status
):
    actual_status, body = _request_failure(
        tmp_path, caplog, family, attribute, action, code
    )
    assert actual_status == status
    assert body["error"]["code"] == code
    assert "Keep this run" in body["error"]["message"]
    assert f"code={code}" in caplog.text


@pytest.mark.parametrize("family,attribute", FAMILIES)
@pytest.mark.parametrize("action", ["refresh", "recover"])
@pytest.mark.parametrize(
    "unclassified_code",
    ["SHORT_PRIVATE_SECRET", "private\ninjected-log-line", "oversized_private_" * 12],
    ids=["unknown-short-ascii", "newline", "oversized"],
)
def test_unclassified_transport_code_and_exception_details_are_not_logged(
    tmp_path, caplog, family, attribute, action, unclassified_code
):
    status, body = _request_failure(
        tmp_path, caplog, family, attribute, action, unclassified_code
    )
    assert status == 500
    assert body["error"]["code"] == "individual_zeus_failed"
    assert "code=unclassified" in caplog.text
    assert unclassified_code not in caplog.text
    assert unclassified_code not in json.dumps(body)
    assert "injected-log-line" not in caplog.text
