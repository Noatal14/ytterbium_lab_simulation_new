from http import HTTPStatus

from workflow_api.individual_run_discovery import IndividualRunDiscoveryError
from workflow_api.models import SCHEMA_VERSION
from workflow_api.server import WorkflowHandler


RUN_ID = "individual-run-" + ("a" * 24)


class FakeRegistry:
    def __init__(self):
        self.list_payload = {"runs": [], "invalid_count": 0, "total": 0}
        self.detail_payload = {"id": RUN_ID, "record_kind": "individual_simulation_run"}

    def list_runs(self):
        return self.list_payload

    def get_run(self, public_id):
        if len(public_id) != len(RUN_ID):
            raise IndividualRunDiscoveryError(
                "invalid_run_id", "Individual-run identifier is invalid."
            )
        if public_id != RUN_ID:
            raise IndividualRunDiscoveryError("run_not_found", "Individual run was not found.")
        return self.detail_payload


def _invoke(path, service):
    handler = WorkflowHandler.__new__(WorkflowHandler)
    handler.path = path
    handler.individual_run_service = service
    observed = []
    handler._trusted_request_target = lambda: True
    handler._json = lambda body, **kwargs: observed.append((HTTPStatus.OK, body))
    handler._error = lambda code, message, status: observed.append(
        (status, {"error": {"code": code, "message": message}})
    )
    handler._catalog_error = lambda domain, case: observed.append((domain, case))
    handler.do_GET()
    assert len(observed) == 1
    return observed[0]


def test_list_and_detail_are_exact_versioned_read_envelopes():
    service = FakeRegistry()
    assert _invoke("/api/v1/individual-runs", service) == (
        HTTPStatus.OK,
        {"api_version": SCHEMA_VERSION, "data": service.list_payload},
    )
    assert _invoke(f"/api/v1/individual-runs/{RUN_ID}", service) == (
        HTTPStatus.OK,
        {"api_version": SCHEMA_VERSION, "data": service.detail_payload},
    )


def test_invalid_missing_and_unavailable_errors_remain_unversioned():
    assert _invoke("/api/v1/individual-runs/bad%2Fid", FakeRegistry()) == (
        HTTPStatus.BAD_REQUEST,
        {"error": {"code": "invalid_run_id", "message": "Individual-run identifier is invalid."}},
    )
    assert _invoke("/api/v1/individual-runs/" + ("f" * 10), FakeRegistry()) == (
        HTTPStatus.BAD_REQUEST,
        {"error": {"code": "invalid_run_id", "message": "Individual-run identifier is invalid."}},
    )
    assert _invoke("/api/v1/individual-runs", None) == (
        HTTPStatus.SERVICE_UNAVAILABLE,
        {"error": {"code": "individual_runs_unavailable", "message": "Individual-run inspection is unavailable."}},
    )


def test_unexpected_registry_failure_is_sanitized():
    class BrokenRegistry(FakeRegistry):
        def list_runs(self):
            raise RuntimeError("secret /absolute/path")

    status, body = _invoke("/api/v1/individual-runs", BrokenRegistry())
    assert status == HTTPStatus.INTERNAL_SERVER_ERROR
    assert body == {
        "error": {
            "code": "run_inspection_failed",
            "message": "Individual runs could not be inspected safely.",
        }
    }
    assert "secret" not in repr(body)
