"""Make unsupported Windows symlink test fixtures explicit in test reports."""
import sys
import inspect
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def windows_symlink_fixture_permission(monkeypatch):
    if sys.platform != 'win32':
        return
    original = Path.symlink_to

    def symlink_to(self, target, target_is_directory=False):
        try:
            return original(self, target, target_is_directory=target_is_directory)
        except OSError as error:
            if (getattr(error, 'winerror', None) == 1314
                    and Path(inspect.currentframe().f_back.f_code.co_filename).name.startswith('test_')):
                pytest.skip('Fixture needs Windows symlink privilege; junction rejection is tested separately')
            raise

    monkeypatch.setattr(Path, 'symlink_to', symlink_to)


@pytest.fixture(autouse=True)
def deterministic_individual_worker_budget(monkeypatch, request):
    # Individual-run fixtures request eight workers. CPU-limit regression
    # tests explicitly override this deterministic unit-test host again.
    if request.module.__name__.split('.')[-1] in {
        'test_run_execution', 'test_local_execution_lease_concurrency', 'test_individual_run_api',
        'test_zeeman_individual_api', 'test_zeeman_individual_http',
        'test_workflow_api_contracts', 'test_workflow_api_server',
        'test_run_metric_integrity',
    }:
        import workflow_api.zeeman_run_specification as specification
        monkeypatch.setattr(specification.os, 'cpu_count', lambda: 16)
