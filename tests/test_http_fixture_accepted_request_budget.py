"""The real local HTTP fixture budgets accepted requests, not idle timeouts."""
import threading
import time
from http.server import ThreadingHTTPServer

from tests.test_workflow_api_server import running_server, request_json


def test_idle_accept_cycle_does_not_consume_real_request_budget(monkeypatch):
    idle = threading.Event()
    original = ThreadingHTTPServer.handle_timeout
    def observed_timeout(server):
        idle.set()
        return original(server)
    monkeypatch.setattr(ThreadingHTTPServer, 'handle_timeout', observed_timeout)
    with running_server(request_count=1) as base:
        assert idle.wait(timeout=4), 'Fixture did not exercise its actual two-second idle timeout.'
        status, _, _ = request_json(base+'/api/health')
        assert status == 200


def test_partial_expected_budget_stops_own_accept_worker_within_existing_bound(monkeypatch):
    owned = []
    original = threading.Thread.start
    def remember(thread):
        if getattr(getattr(thread, '_target', None), '__name__', '') == 'handle_expected_requests':
            owned.append(thread)
        return original(thread)
    monkeypatch.setattr(threading.Thread, 'start', remember)
    start = time.monotonic()
    with running_server(request_count=2) as base:
        status, _, _ = request_json(base+'/api/health')
        assert status == 200
    assert time.monotonic()-start < 5
    assert len(owned) == 1 and not owned[0].is_alive()
