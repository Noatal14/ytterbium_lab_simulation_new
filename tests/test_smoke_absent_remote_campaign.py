"""An absent receiver directory is distinct from invalid existing preparation."""
import json
import os
import subprocess
from types import SimpleNamespace
import pytest
from workflow_api import zeus_screening_remote as receiver
from workflow_api.zeus_screening import PinnedSshScreeningTransport, ZeusScreeningError

@pytest.fixture
def campaign(tmp_path):
    root = tmp_path / "project with spaces"
    target = root / "data/optimization/mot_2d/ui_acceptance/TESTONLY_fresh"
    target.parent.mkdir(parents=True)
    return root, target

def observed_error(capsys, root, target, operation="inspect"):
    with pytest.raises(SystemExit) as error:
        receiver.require_campaign_directory(root, target, operation)
    assert error.value.code == 20
    return json.loads(capsys.readouterr().out)["error"]

posix_receiver = pytest.mark.skipif(os.name == "nt", reason="Zeus receiver uses POSIX directory-relative descriptors")

@posix_receiver
def test_only_exact_absent_inspect_leaf_is_not_submitted(campaign, capsys):
    root, target = campaign
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    assert observed_error(capsys, root, target) == "smoke_not_submitted"
    assert observed_error(capsys, root, target, "prepare") == "remote_preparation_invalid"
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before

@posix_receiver
@pytest.mark.parametrize("kind", ["file", "dangling_link", "directory_link", "parent_link", "parent_file"])
def test_unsafe_parent_is_never_fresh(campaign, capsys, kind, tmp_path):
    root, target = campaign
    if kind == "file": target.write_bytes(b"not a directory")
    elif kind == "dangling_link": target.symlink_to(tmp_path / "absent")
    elif kind == "directory_link": target.symlink_to(target.parent, target_is_directory=True)
    else:
        target.parent.rmdir()
        if kind == "parent_link": target.parent.symlink_to(tmp_path, target_is_directory=True)
        elif kind == "parent_file": target.parent.write_bytes(b"not a parent")
    assert observed_error(capsys, root, target) == "remote_preparation_invalid"

@posix_receiver
def test_existing_bad_manifest_retains_original_error(campaign, capsys):
    root, target = campaign
    target.mkdir()
    (target / "campaign.json").write_bytes(b"{corrupt")
    receiver.require_campaign_directory(root, target, "inspect")
    with pytest.raises(SystemExit): receiver._authorize_acceptance_campaign(target, root)
    assert json.loads(capsys.readouterr().out)["error"] == "remote_preparation_invalid"
    assert (target / "campaign.json").read_bytes() == b"{corrupt"

@posix_receiver
def test_access_failure_is_not_absence(campaign, capsys, monkeypatch):
    root, target = campaign
    original = receiver.os.open
    def denied(path, *args, **kwargs):
        if str(path) == "ui_acceptance": raise PermissionError("not accessible")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(receiver.os, "open", denied)
    assert observed_error(capsys, root, target) == "remote_preparation_invalid"

@pytest.mark.parametrize("code", ["smoke_not_submitted", "remote_preparation_invalid"])
def test_existing_typed_inspect_transport_preserves_distinction(code):
    transport = object.__new__(PinnedSshScreeningTransport)
    transport.profile = object()
    transport.runner = SimpleNamespace(run=lambda *args: subprocess.CompletedProcess([], 20, json.dumps({"error": code}).encode(), b""))
    with pytest.raises(ZeusScreeningError) as error: transport.inspect()
    assert error.value.code == code

@posix_receiver
@pytest.mark.parametrize("operation,kind,head,expected", [
    ("inspect", "absent", "a" * 40, "smoke_not_submitted"),
    ("inspect", "missing_parents", "a" * 40, "smoke_not_submitted"),
    ("prepare", "missing_parents", "a" * 40, "remote_preparation_invalid"),
    ("inspect", "missing_parents", "b" * 40, "remote_checkout_mismatch"),
    ("prepare", "absent", "a" * 40, "remote_preparation_invalid"),
    ("inspect", "corrupt", "a" * 40, "remote_preparation_invalid"),
    ("inspect", "dangling", "a" * 40, "remote_preparation_invalid"),
    ("inspect", "absent", "b" * 40, "remote_checkout_mismatch"),
])
def test_actual_receiver_entry_distinguishes_absence_after_pinned_checkout(tmp_path, monkeypatch, capsys, operation, kind, head, expected):
    import base64
    import sys
    from pathlib import Path
    home = tmp_path / "home"
    root = home / "tal.noa/ytterbium_lab_simulation_ui_acceptance"
    target = root / "data/optimization/mot_2d/ui_acceptance/TESTONLY_fresh"
    if kind == "missing_parents": root.mkdir(parents=True)
    else: target.parent.mkdir(parents=True)
    if kind == "corrupt":
        target.mkdir()
        (target / "campaign.json").write_bytes(b"bad json")
    elif kind == "dangling":
        target.symlink_to(tmp_path / "absent")
    relative = target.relative_to(root).as_posix()
    payload = {"campaign": relative, "commit": "a" * 40, "prepared_files": {}, "submission_key": "b" * 64, "transition_files": {}}
    if operation == "prepare": payload.update(smoke_digest="c" * 64, nonce="d" * 32)
    monkeypatch.setattr(sys, "argv", ["receiver", operation, "tal.noa", str(root), base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()])
    calls = []
    def git(argv, **kwargs):
        calls.append(argv)
        assert argv[0] == "/usr/bin/git"
        return subprocess.CompletedProcess(argv, 0, head if "rev-parse" in argv else "", "")
    monkeypatch.setattr(subprocess, "run", git)
    # Execute the real receiver, changing ONLY its /home anchor for private tests.
    source = Path(receiver.__file__).read_text().replace('Path("/home")', 'Path(test_home)')
    namespace = {"__name__": "receiver_test", "test_home": str(home)}
    exec(compile(source, receiver.__file__, "exec"), namespace)
    # Preserve the genuine deployment allowlist, mapping only its /home anchor.
    checkout_paths = namespace["campaign_checkout_paths"]
    namespace["campaign_checkout_paths"] = lambda username: frozenset(
        home / path.relative_to("/home") for path in checkout_paths(username)
    )
    with pytest.raises(SystemExit) as error: namespace["main"]()
    assert error.value.code == 20
    assert json.loads(capsys.readouterr().out)["error"] == expected
    assert len(calls) == 2
    assert not (target / ".mot_ui").exists()


@posix_receiver
@pytest.mark.parametrize("depth", [0, 1, 2, 3])
def test_first_missing_canonical_parent_is_neutral_only_for_inspect(tmp_path, capsys, depth):
    root = tmp_path / "clean-team-root"; root.mkdir()
    target = root / "data/optimization/mot_2d/fresh"
    current = root
    for part in target.relative_to(root).parts[:depth]:
        current /= part; current.mkdir()
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob('*'))
    assert observed_error(capsys, root, target) == "smoke_not_submitted"
    assert observed_error(capsys, root, target, "prepare") == "remote_preparation_invalid"
    assert before == sorted(p.relative_to(root).as_posix() for p in root.rglob('*'))


@posix_receiver
@pytest.mark.parametrize("component", ["data", "optimization", "mot_2d"])
@pytest.mark.parametrize("kind", ["file", "dangling", "directory_link"])
def test_first_parent_alias_or_non_directory_is_not_absence(tmp_path, capsys, component, kind):
    root = tmp_path / 'root'; root.mkdir()
    target = root / 'data/optimization/mot_2d/fresh'
    current = root
    for part in target.relative_to(root).parts:
        current /= part
        if part == component: break
        current.mkdir()
    if kind == 'file': current.write_text('not a directory')
    elif kind == 'dangling': current.symlink_to(tmp_path/'absent')
    else: current.symlink_to(tmp_path, target_is_directory=True)
    assert observed_error(capsys, root, target) == 'remote_preparation_invalid'


@posix_receiver
@pytest.mark.parametrize('replace_root', [False, True])
def test_missing_component_cannot_hide_ancestor_replacement(campaign, capsys, monkeypatch, replace_root):
    root, target = campaign
    original = receiver.os.stat
    changed = False
    def raced(path, *args, **kwargs):
        nonlocal changed
        if not changed and str(path) == target.name:
            changed = True
            ancestor = root if replace_root else target.parent
            ancestor.rename(ancestor.with_name(ancestor.name+'-original'))
            ancestor.mkdir()
            raise FileNotFoundError('missing leaf after rename')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(receiver.os, 'stat', raced)
    assert observed_error(capsys, root, target) == 'remote_preparation_invalid'
