import json
from pathlib import Path

import pytest

from workflow_api.smoke_receipt import resolve_smoke_receipt


def _write(campaign, namespace, value=None):
    path = campaign / namespace / 'submissions/smoke.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value or {'version': 1, 'job_id': '123.zeus-master'}))
    return path


@pytest.mark.parametrize('namespace', ['.mot_ui', '.workflow'])
def test_receipt_namespace_recovery_is_read_only(tmp_path, namespace):
    receipt = _write(tmp_path, namespace)
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    assert resolve_smoke_receipt(tmp_path) == receipt
    assert {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()} == before


def test_equal_dual_receipts_prefer_canonical_without_migration(tmp_path):
    canonical = _write(tmp_path, '.mot_ui')
    legacy = _write(tmp_path, '.workflow')
    legacy.write_text('{"job_id":"123.zeus-master", "version":1}')
    assert resolve_smoke_receipt(tmp_path) == canonical
    assert legacy.exists()


@pytest.mark.parametrize('changed', [{'version': 1, 'job_id': '999.zeus-master'}, {'version': True, 'job_id': '123.zeus-master'}])
def test_conflicting_dual_receipts_fail_closed(tmp_path, changed):
    _write(tmp_path, '.mot_ui')
    _write(tmp_path, '.workflow', changed)
    with pytest.raises(ValueError, match='Conflicting'):
        resolve_smoke_receipt(tmp_path)


@pytest.mark.parametrize('final_namespace', ['.mot_ui', '.workflow', None])
@pytest.mark.parametrize('pending_namespace', ['.mot_ui', '.workflow'])
def test_any_unresolved_intent_blocks_readiness(tmp_path, final_namespace, pending_namespace):
    if final_namespace:
        _write(tmp_path, final_namespace)
    pending = tmp_path / pending_namespace / 'submissions/smoke.pending.json'
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_bytes(b'{}')
    with pytest.raises(ValueError, match='Unresolved'):
        resolve_smoke_receipt(tmp_path)
    assert pending.read_bytes() == b'{}'


@pytest.mark.parametrize('namespace', ['.mot_ui', '.workflow'])
@pytest.mark.parametrize('component', ['namespace', 'submissions', 'receipt', 'pending'])
def test_symlink_parents_and_files_never_authorize_receipt(tmp_path, namespace, component):
    campaign = tmp_path / 'campaign'
    campaign.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    if component == 'namespace':
        (campaign / namespace).symlink_to(outside, target_is_directory=True)
    elif component == 'submissions':
        (campaign / namespace).mkdir()
        (campaign / namespace / 'submissions').symlink_to(outside, target_is_directory=True)
    else:
        path = _write(campaign, namespace)
        target = path if component == 'receipt' else path.with_name('smoke.pending.json')
        if target.exists():
            target.unlink()
        target.symlink_to(outside / 'missing.json')
    with pytest.raises(ValueError):
        resolve_smoke_receipt(campaign)


@pytest.mark.parametrize('raw', [b'{"version":1,"version":1}', b'{"value":NaN}', b'[]', b'x' * 16385])
def test_malformed_or_unbounded_receipts_fail_closed(tmp_path, raw):
    path = _write(tmp_path, '.mot_ui')
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        resolve_smoke_receipt(tmp_path)


def test_missing_receipts_have_no_publication_side_effect(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_smoke_receipt(tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('change', ['same_size_content', 'mtime_only'])
def test_in_place_receipt_changes_during_read_fail_closed(tmp_path, monkeypatch, change):
    import os
    from workflow_api import smoke_receipt
    path = _write(tmp_path, '.mot_ui')
    before = path.stat()
    native_fdopen = os.fdopen
    class ChangingReader:
        def __init__(self, descriptor, mode):
            self.stream = native_fdopen(descriptor, mode)
        def __enter__(self):
            return self
        def __exit__(self, *arguments):
            return self.stream.__exit__(*arguments)
        def fileno(self):
            return self.stream.fileno()
        def read(self, limit):
            raw = self.stream.read(limit)
            if change == 'same_size_content':
                path.write_bytes(raw.replace(b'123', b'999'))
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
            return raw
    monkeypatch.setattr(smoke_receipt.os, 'fdopen', ChangingReader)
    with pytest.raises(ValueError, match='changed'):
        resolve_smoke_receipt(tmp_path)


def test_fifo_swap_after_lstat_uses_nonblocking_open_and_rejects_opened_type(tmp_path, monkeypatch):
    import os
    import stat
    from types import SimpleNamespace
    from workflow_api import smoke_receipt
    _write(tmp_path, '.mot_ui')
    native_open = os.open
    flags_seen = []
    def observe_open(path, flags):
        flags_seen.append(flags)
        return native_open(path, flags)
    monkeypatch.setattr(smoke_receipt.os, 'open', observe_open)
    # Model a regular-file→FIFO race at open, without creating a blocking FIFO
    # on a native Windows host. The opened object must be rejected before read.
    monkeypatch.setattr(smoke_receipt.os, 'fstat', lambda descriptor: SimpleNamespace(st_mode=stat.S_IFIFO))
    with pytest.raises(ValueError, match='changed'):
        resolve_smoke_receipt(tmp_path)
    assert len(flags_seen) == 1
    assert flags_seen[0] & getattr(os, 'O_NONBLOCK', 0) == getattr(os, 'O_NONBLOCK', 0)
