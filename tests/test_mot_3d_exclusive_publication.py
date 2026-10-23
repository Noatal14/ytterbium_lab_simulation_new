"""Exclusive reservation keeps strict single-link readers on NFS.

The stale-link-count model is bound to the actual private publication trace;
no workflow operation or external filesystem is exercised by these tests.
"""
import os
from types import SimpleNamespace
from unittest import mock

import pytest

from workflow_api import mot_3d_selection_submission_remote as core
from workflow_api import mot_3d_preliminary_transition_remote as transition

# These are real POSIX dir_fd/flock filesystem integrations for Zeus receivers.
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX receiver filesystem semantics")


def test_no_hardlink_publication_with_immediate_strict_read(tmp_path):
    """Old hardlink path exposes cached nlink2; new publisher never creates it."""
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    real_link, real_fstat = os.link, os.fstat
    hardlinked = [False]
    def link(*args, **kwargs):
        result = real_link(*args, **kwargs)
        hardlinked[0] = True
        return result
    def fstat(target):
        row = real_fstat(target)
        if hardlinked[0] and row.st_size:
            fields = {name: getattr(row, name) for name in dir(row) if name.startswith('st_')}
            fields['st_nlink'] = 2
            return SimpleNamespace(**fields)
        return row
    try:
        with mock.patch.object(os, 'link', side_effect=link), mock.patch.object(os, 'fstat', side_effect=fstat):
            transition._publish_bytes(fd, 'final.json', b'{"value":1}\n', identical_ok=False)
            assert core.strict_json_at(fd, 'final.json') == {'value': 1}
            assert not hardlinked[0]
            # Reproduce the old link/unlink/strict-read ordering, not a reader waiver.
            (tmp_path / 'old.tmp').write_bytes(b'{"value":1}\n')
            os.link('old.tmp', 'old.json', src_dir_fd=fd, dst_dir_fd=fd)
            os.unlink('old.tmp', dir_fd=fd)
            with pytest.raises(SystemExit):
                core.strict_json_at(fd, 'old.json')
    finally:
        os.close(fd)


def test_existing_foreign_target_never_overwritten(tmp_path):
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        (tmp_path / 'final').write_bytes(b'foreign')
        with pytest.raises(FileExistsError):
            core.write_exclusive_at(fd, 'final', b'new')
        assert (tmp_path / 'final').read_bytes() == b'foreign'
        (tmp_path / 'alias').symlink_to(tmp_path / 'final')
        with pytest.raises(FileExistsError):
            core.write_exclusive_at(fd, 'alias', b'new')
    finally:
        os.close(fd)


@pytest.mark.parametrize('attack', ['hardlink', 'replace'])
def test_foreign_target_mutation_fails_closed(tmp_path, attack):
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    real_write = os.write
    def write(target, data):
        result = real_write(target, data)
        if attack == 'hardlink':
            os.link(tmp_path / 'final', tmp_path / 'foreign-link')
        else:
            os.unlink(tmp_path / 'final')
            (tmp_path / 'final').write_bytes(b'foreign')
        return result
    try:
        with mock.patch.object(os, 'write', side_effect=write), pytest.raises(OSError):
            core.write_exclusive_at(fd, 'final', b'new')
        assert (tmp_path / 'final').exists()
        with pytest.raises(SystemExit):
            if attack == 'hardlink':
                core.bounded_at(fd, 'final')
            else:
                transition._publish_bytes(fd, 'final', b'new', identical_ok=False)
    finally:
        os.close(fd)


@pytest.mark.parametrize('fault', ['open', 'write', 'file-fsync', 'dir-fsync'])
def test_acts_then_raises_retains_reservation_without_retry(tmp_path, fault):
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    real_open, real_write, real_fsync = os.open, os.write, os.fsync
    calls = []
    def opened(*args, **kwargs):
        target = real_open(*args, **kwargs)
        if fault == 'open':
            # Caller cannot know returned FD; preserve reservation, no guessed cleanup.
            os.close(target)
            calls.append('open')
            raise OSError('open acted then raised')
        return target
    def written(target, data):
        result = real_write(target, data[:2] if fault == 'write' else data)
        if fault == 'write':
            calls.append('write')
            raise OSError('write acted then raised')
        return result
    def synced(target):
        real_fsync(target)
        if (fault == 'dir-fsync') == (target == fd) and fault in {'file-fsync', 'dir-fsync'}:
            calls.append(fault)
            raise OSError('fsync acted then raised')
    try:
        with mock.patch.object(os, 'open', side_effect=opened), mock.patch.object(os, 'write', side_effect=written), mock.patch.object(os, 'fsync', side_effect=synced):
            with pytest.raises(OSError):
                core.write_exclusive_at(fd, 'final', b'{"value":1}\n')
        assert calls == [fault]
        assert (tmp_path / 'final').is_file()
        with pytest.raises(FileExistsError):
            core.write_exclusive_at(fd, 'final', b'no replay')
    finally:
        os.close(fd)


def test_partial_writes_are_completed_once(tmp_path):
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    real = os.write
    try:
        with mock.patch.object(os, 'write', side_effect=lambda f, data: real(f, data[:2])):
            core.write_exclusive_at(fd, 'final', b'1234567')
        assert core.bounded_at(fd, 'final') == b'1234567'
    finally:
        os.close(fd)


def test_receipt_read_is_fenced_until_publisher_unlocks(tmp_path):
    import fcntl
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    lock = os.open('stage.lock', os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            with core.publication_read_lock(fd, 'stage.lock'):
                pytest.fail('active publisher must fence reader')
        fcntl.flock(lock, fcntl.LOCK_UN)
        with core.publication_read_lock(fd, 'stage.lock'):
            pass
    finally:
        os.close(lock)
        os.close(fd)


def test_selection_and_discovery_publishers_keep_single_link(tmp_path):
    from workflow_api import mot_3d_discovery_transition_remote as discovery
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, 'link', side_effect=AssertionError('hardlink forbidden')):
            core._publish_at_impl(fd, 'selection.json', {'value': 1})
            discovery.publish(tmp_path / 'discovery.json', b'{"value":1}\n')
            discovery.publish(tmp_path / 'discovery.json', b'{"value":1}\n')
        assert core.strict_json_at(fd, 'selection.json') == {'value': 1}
        assert core.strict_json_at(fd, 'discovery.json') == {'value': 1}
        os.link(tmp_path / 'discovery.json', tmp_path / 'foreign')
        with pytest.raises(SystemExit):
            discovery.publish(tmp_path / 'discovery.json', b'{"value":1}\n')
    finally:
        os.close(fd)


def test_all_transition_identity_closures_pin_exclusive_publisher():
    import importlib
    name = 'workflow_api/mot_3d_selection_submission_remote.py'
    for module_name in ('mot_3d_preliminary_transition_remote', 'mot_3d_refinement_transition_remote',
                        'mot_3d_closure_transition_remote', 'mot_3d_finalist_transition_remote',
                        'mot_3d_final_validation_transition_remote', 'mot_3d_final_validation_completion_remote'):
        module = importlib.import_module('workflow_api.' + module_name)
        assert name in module.DESCRIPTOR.code_paths if hasattr(module, 'DESCRIPTOR') else name in module.PRELIMINARY_CODE_PATHS
