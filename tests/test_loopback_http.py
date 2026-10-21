"""Numeric-loopback startup and unchanged real-handler trust boundaries."""
import http.client
import json
import socket
import threading
import importlib
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer

import pytest

from workflow_api.loopback_http import LoopbackThreadingHTTPServer


def forbid_reverse_dns(*_args):
    raise AssertionError("Numeric-loopback startup must not resolve hostnames")


@pytest.mark.parametrize("host", ["localhost", "0.0.0.0", "::", "::1", "192.0.2.1", "example.invalid"])
def test_non_numeric_loopback_rejected_before_bind(monkeypatch, host):
    calls = []
    monkeypatch.setattr(TCPServer, "server_bind", lambda server: calls.append(server))
    monkeypatch.setattr(socket, "getfqdn", forbid_reverse_dns)
    with pytest.raises(ValueError, match="numeric loopback"):
        LoopbackThreadingHTTPServer((host, 0), BaseHTTPRequestHandler)
    assert calls == []


def test_bind_once_without_dns_retains_actual_port_and_threaded_lifecycle(monkeypatch):
    original_bind = TCPServer.server_bind
    original_activate = TCPServer.server_activate
    calls = []
    activated = []

    def observe_activate(server):
        activated.append(server)
        original_activate(server)

    def observe_bind(server):
        calls.append(server)
        original_bind(server)

    monkeypatch.setattr(TCPServer, "server_bind", observe_bind)
    monkeypatch.setattr(TCPServer, "server_activate", observe_activate)
    monkeypatch.setattr(socket, "getfqdn", forbid_reverse_dns)
    monkeypatch.setattr(socket, "gethostbyaddr", forbid_reverse_dns)
    with LoopbackThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler) as server:
        assert calls == [server]
        assert server.server_address == server.socket.getsockname()
        assert server.server_name == "127.0.0.1"
        assert server.server_port == server.server_address[1] > 0
        assert server.allow_reuse_address == ThreadingHTTPServer.allow_reuse_address
        assert server.daemon_threads == ThreadingHTTPServer.daemon_threads
        assert activated == [server]


def test_production_entry_retains_shared_threading_server_symbol():
    import workflow_api.server as application

    assert application.ThreadingHTTPServer is LoopbackThreadingHTTPServer


def test_synthetic_browser_fixture_uses_same_server(monkeypatch):
    integration = Path(__file__).resolve().parents[1] / "ui" / "integration"
    monkeypatch.syspath_prepend(str(integration))
    fixture = importlib.import_module("real_backend_server")
    assert fixture.ThreadingHTTPServer is LoopbackThreadingHTTPServer


def test_real_health_host_origin_query_and_csrf_gates_without_dns(monkeypatch):
    from workflow_api.server import WorkflowHandler

    class NoCreation:
        calls = []

        def preview(self, *_args):
            self.calls.append("preview")
            raise AssertionError("Rejected requests must never reach an action")

    class Handler(WorkflowHandler):
        creation_service = NoCreation()
        sessions = {}
        sessions_lock = threading.Lock()

        def log_message(self, *_args):
            pass

    monkeypatch.setattr(socket, "getfqdn", forbid_reverse_dns)
    monkeypatch.setattr(socket, "gethostbyaddr", forbid_reverse_dns)
    server = LoopbackThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_port
    assert port not in {8765, 5175, 8766, 5176, 5177, 5178, 18665, 18765}
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()

    def request(method, target, headers=None, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request(method, target, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), json.loads(response.read())
        finally:
            connection.close()

    try:
        status, _, payload = request("GET", "/api/health")
        assert status == 200 and payload == {"api_version": 1, "status": "ok"}
        status, _, payload = request("GET", "/api/health", {"Host": "evil.example"})
        assert status == 400 and payload["error"]["code"] == "untrusted_host"
        status, _, payload = request("GET", "/api/health?unsafe=1")
        assert status == 400 and payload["error"]["code"] == "unsupported_query"
        host = f"127.0.0.1:{port}"
        status, _, payload = request("POST", "/api/v1/campaigns/2d/preview", {
            "Host": host, "Origin": "http://evil.example", "Sec-Fetch-Site": "same-origin",
            "Content-Type": "application/json",
        }, "{}")
        assert status == 403 and payload["error"]["code"] == "untrusted_origin"
        status, headers, payload = request("GET", "/api/v1/session", {"Sec-Fetch-Site": "same-origin"})
        assert status == 200 and payload["data"]["csrf_token"]
        status, _, payload = request("POST", "/api/v1/campaigns/2d/preview", {
            "Host": host, "Origin": f"http://{host}", "Sec-Fetch-Site": "same-origin",
            "Cookie": headers["Set-Cookie"].split(";", 1)[0],
            "X-CSRF-Token": "wrong-token", "Content-Type": "application/json",
        }, "{}")
        assert status == 403 and payload["error"]["code"] == "invalid_csrf"
        assert Handler.creation_service.calls == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert not thread.is_alive()
