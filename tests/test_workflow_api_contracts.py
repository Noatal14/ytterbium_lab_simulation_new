"""Exact v1 HTTP-envelope contracts collected through the real handler.

Snapshots are verified by default.  Updating requires the explicit command
documented in ``main``; the pytest path never rewrites repository files.
"""
from __future__ import annotations

import argparse
import json
import re
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import workflow_api.server as server_module
from workflow_api.server import ReadOnlyWorkflowHandler
from tests.workflow_api_contract_payloads import fake_service_payloads

CONTRACT_ROOT = Path(__file__).parent / "contracts" / "v1"
COMMON_HEADERS = ("cache-control", "content-type", "x-content-type-options")


class _Creation:
    def __init__(self, ledger, payloads): self.ledger, self.payloads = ledger, payloads
    def preview(self, payload, session): self.ledger.append(("creation-preview", payload, session)); return self.payloads["creation-preview"]
    def confirm(self, token, session): self.ledger.append(("creation-confirm", {"preview_token": token}, session)); return self.payloads["creation-confirm"]


class _Service:
    def __init__(self, prefix, ledger, payloads, status_id=None): self.prefix, self.ledger, self.payloads, self.status_id = prefix, ledger, payloads, status_id
    def _result(self, name, payload, session=None):
        case = self.status_id if name == "status" else f"{self.prefix}-{name}"
        self.ledger.append((case, payload, session)); return self.payloads[case]
    def snapshot(self, payload): return self._result("snapshot", payload)
    def preview(self, payload, *, session_id): return self._result("preview", payload, session_id)
    def confirm(self, payload, *, session_id): return self._result("confirm", payload, session_id)
    def status(self, payload, **kwargs): return self._result("status", payload, kwargs.get("session_id"))


@contextmanager
def _server(request_count, *, services=True, payloads=None):
    ledger = []
    handler = type("ContractHandler", (ReadOnlyWorkflowHandler,), {})
    handler.sessions = {}
    handler.repository_root = Path.cwd()
    values=payloads or {}
    handler.creation_service = _Creation(ledger,values) if services else None
    handler.zeus_service = _Service("zeus",ledger,values) if services else None
    handler.transfer_service = _Service("transfer",ledger,values) if services else None
    handler.submission_service = _Service("smoke-submit",ledger,values) if services else None
    handler.screening_service = _Service("screening",ledger,values,"smoke-status") if services else None
    handler.screen_submission_service = _Service("screen-submit",ledger,values) if services else None
    handler.refinement_service = _Service("refinement",ledger,values,"screen-status") if services else None
    handler.refinement_submission_service = _Service("refinement-submit",ledger,values,"refinement-submit-status") if services else None
    handler.confirmation_service = _Service("confirmation",ledger,values,"confirmation-status") if services else None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True; httpd.block_on_close = False; httpd.timeout = 2
    thread = threading.Thread(target=lambda: [httpd.handle_request() for _ in range(request_count)], daemon=True); thread.start()
    try: yield f"http://127.0.0.1:{httpd.server_port}", ledger
    finally: thread.join(timeout=5); httpd.server_close()


def _request(base, method, path, headers=None, body=None):
    parsed = urlsplit(base); connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse(); raw = response.read()
        return response.status, {key.lower(): value for key, value in response.headers.items()}, json.loads(raw)
    finally: connection.close()


def _captured(case, status, headers, body):
    selected = {key: headers[key] for key in COMMON_HEADERS}
    for key in case.get("headers", {}): selected[key] = headers[key]
    if case["id"] == "session":
        assert re.fullmatch(r"mot_ui_session=[A-Za-z0-9_-]+; HttpOnly; SameSite=Strict; Path=/", headers["set-cookie"])
        assert re.fullmatch(r"[A-Za-z0-9_-]{32,}", body["data"]["csrf_token"])
        selected["set-cookie"] = "<session-cookie>"
        body = {"api_version": body["api_version"], "data": {"csrf_token": "<csrf-token>"}}
    captured_extras = {key: selected[key] for key in case.get("headers", {})}
    return {"id":case["id"],"method":case["method"],"path":case["path"],"status":status,**({"headers":captured_extras} if captured_extras else {}),"body":body}, selected


def _load(name): return json.loads((CONTRACT_ROOT / name).read_text())


def collect_success(monkeypatch):
    expected = _load("workflow_api_success.json")
    payloads = fake_service_payloads()
    monkeypatch.setattr(server_module, "list_workflows", lambda: payloads["workflows"])
    monkeypatch.setattr(server_module, "list_campaigns", lambda _root: payloads["campaigns"])
    monkeypatch.setattr(server_module, "list_sources", lambda _root: payloads["sources"])
    monkeypatch.setattr(server_module, "get_campaign", lambda _root, _id: payloads["campaign-detail"])
    observed=[]; header_rows=[]
    with _server(len(expected["cases"]),payloads=payloads) as (base, ledger):
        cookie=csrf=None
        for case in expected["cases"]:
            headers={}
            if case["id"]=="session": headers={"Sec-Fetch-Site":"same-origin"}
            elif case["method"]=="POST": headers={"Content-Type":"application/json","Origin":base,"Sec-Fetch-Site":"same-origin","Cookie":cookie,"X-CSRF-Token":csrf}
            status,response_headers,body=_request(base,case["method"],case["path"],headers,json.dumps({"preview_token":"token"}) if case["id"]=="creation-confirm" else "{}" if case["method"]=="POST" else None)
            if case["id"]=="session": cookie=response_headers["set-cookie"].split(";",1)[0];csrf=body["data"]["csrf_token"]
            row,selected=_captured(case,status,response_headers,body);observed.append(row);header_rows.append(selected)
    return {"schema_version":1,"common_headers":expected["common_headers"],"cases":observed}, ledger, header_rows


def collect_errors():
    expected=_load("workflow_api_errors.json");observed=[];header_rows=[]
    with _server(len(expected["cases"]),services=False) as (base,_):
        for case in expected["cases"]:
            headers={"Content-Type":"application/json"} if case["method"]=="POST" else {}
            status,response_headers,body=_request(base,case["method"],case["path"],headers,"{}" if case["method"]=="POST" else None)
            row,selected=_captured(case,status,response_headers,body);observed.append(row);header_rows.append(selected)
    return {"schema_version":1,"common_headers":expected["common_headers"],"cases":observed},header_rows


def test_v1_success_contracts_are_exact_and_deterministic(monkeypatch):
    expected=_load("workflow_api_success.json");first,ledger,headers=collect_success(monkeypatch);second,_,_=collect_success(monkeypatch)
    assert first==second==expected
    assert len(first["cases"])==27 and len({(row["method"],row["path"]) for row in first["cases"]})==27
    assert all(row["body"].get("api_version")==1 for row in first["cases"])
    assert all(all(value==expected["common_headers"][key] for key,value in header.items() if key in expected["common_headers"]) for header in headers)
    assert [entry[0] for entry in ledger] == [
        "creation-preview", "creation-confirm", "zeus-snapshot",
        "transfer-preview", "transfer-confirm", "smoke-submit-preview",
        "smoke-submit-confirm", "smoke-status", "screening-preview",
        "screening-confirm", "screen-submit-preview", "screen-submit-confirm",
        "screen-status", "refinement-preview", "refinement-confirm",
        "refinement-submit-status", "refinement-submit-preview",
        "refinement-submit-confirm", "confirmation-status",
        "confirmation-preview", "confirmation-confirm",
    ]
    session_ids={entry[2] for entry in ledger if entry[2] is not None};assert len(session_ids)==1
    assert all(entry[1] == ({"preview_token": "token"} if entry[0] == "creation-confirm" else {}) for entry in ledger)


def test_v1_error_contracts_remain_unversioned():
    expected=_load("workflow_api_errors.json");observed,headers=collect_errors()
    assert observed==expected
    assert all(set(row["body"])=={"error"} and "api_version" not in row["body"] for row in observed["cases"])
    assert all(all(value==expected["common_headers"][key] for key,value in header.items() if key in expected["common_headers"]) for header in headers)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--verify",action="store_true",help="run pytest verification; snapshots are never rewritten")
    args=parser.parse_args()
    if not args.verify: parser.error("only --verify is supported; snapshot updates require reviewed apply_patch changes")
    raise SystemExit("Run: python -m pytest -q tests/test_workflow_api_contracts.py")


if __name__=="__main__": main()
