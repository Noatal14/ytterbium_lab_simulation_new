import json
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from workflow_api.server import ReadOnlyWorkflowHandler, workflow_catalog_payload


@contextmanager
def running_server(request_count=2):
    server = ThreadingHTTPServer(("127.0.0.1", 0), ReadOnlyWorkflowHandler)
    server.daemon_threads = True
    server.block_on_close = False
    server.timeout = 2

    def handle_expected_requests():
        for _ in range(request_count):
            server.handle_request()

    thread = threading.Thread(target=handle_expected_requests, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        thread.join(timeout=5)
        server.server_close()


def request_json(url, *, method="GET"):
    parsed = urlsplit(url)
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        connection.request(method, parsed.path)
        response = connection.getresponse()
        return response.status, response.headers, json.loads(response.read())
    finally:
        connection.close()


def test_local_server_catalog_uses_versioned_workflow_api():
    payload = workflow_catalog_payload()

    assert payload["api_version"] == 1
    assert {item["workflow_id"] for item in payload["data"]} >= {
        "mot_2d_fixed_s0",
        "mot_3d_optimization",
    }
    assert all(item["capabilities"] in (("inspect",), ()) for item in payload["data"])


def test_loopback_health_and_workflow_endpoints_are_read_only_and_uncached():
    with running_server() as base_url:
        status, headers, payload = request_json(f"{base_url}/api/health")
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        assert payload == {"api_version": 1, "status": "ok"}

        status, headers, payload = request_json(f"{base_url}/api/workflows")
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        assert payload["api_version"] == 1
        assert {row["workflow_id"] for row in payload["data"]} >= {
            "mot_2d_fixed_s0",
            "mot_3d_optimization",
        }


def test_loopback_unknown_and_mutating_requests_are_rejected_and_uncached():
    with running_server() as base_url:
        status, headers, payload = request_json(f"{base_url}/api/unknown")
        assert status == 404
        assert headers["Cache-Control"] == "no-store"
        assert payload == {"error": "Not found"}

        status, headers, payload = request_json(
            f"{base_url}/api/workflows", method="POST"
        )
        assert status == 405
        assert headers["Cache-Control"] == "no-store"
        assert payload == {"error": "This API milestone is read-only."}


def test_server_import_does_not_cross_the_simulation_or_study_boundary():
    code = (
        "import sys; import workflow_api.server; "
        "assert not any(name == 'simulations' or name.startswith('simulations.') "
        "or name == 'studies' or name.startswith('studies.') for name in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
