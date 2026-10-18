"""Native Windows OpenSSH needs OS paths even with user config disabled."""
from types import SimpleNamespace
import workflow_api.pinned_ssh as ssh


def test_windows_pinned_environment_retains_required_os_paths_only(monkeypatch):
    paths = {"PROGRAMDATA": r"C:\ProgramData", "SystemRoot": r"C:\Windows",
             "USERPROFILE": r"C:\Users\test"}
    monkeypatch.setattr(ssh, "os", SimpleNamespace(name="nt", environ={
        **paths, "UNTRUSTED_SETTING": "ignored"}))
    assert ssh._windows_ssh_environment() == paths


def test_posix_pinned_environment_stays_unchanged(monkeypatch):
    monkeypatch.setattr(ssh, "os", SimpleNamespace(name="posix", environ={
        "PROGRAMDATA": "ignored"}))
    assert ssh._windows_ssh_environment() == {}
