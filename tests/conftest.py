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
