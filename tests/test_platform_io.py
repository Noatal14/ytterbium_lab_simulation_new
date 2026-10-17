"""Real cross-platform filesystem behavior, including directory replacement."""
import os as native
import subprocess
import sys

import pytest
from workflow_api.platform_io import os, locking


def test_relative_publication_and_replace(tmp_path):
    parent = os.open(tmp_path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.mkdir('stage', dir_fd=parent)
        stage = os.open('stage', os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0), dir_fd=parent)
        try:
            fd = os.open('payload', os.O_WRONLY | os.O_CREAT | os.O_EXCL, dir_fd=stage)
            os.write(fd, b'complete\x00\r\n')
            os.fsync(fd)
            os.close(fd)
            os.link('payload', 'published', src_dir_fd=stage, dst_dir_fd=stage)
            with pytest.raises(FileExistsError):
                os.link('payload', 'published', src_dir_fd=stage, dst_dir_fd=stage)
            os.replace('payload', 'published', src_dir_fd=stage, dst_dir_fd=stage)
            assert os.stat('published', dir_fd=stage).st_size == 11
            os.unlink('published', dir_fd=stage)
            os.fsync(stage)
            os.rename('stage', 'ready', src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            os.close(stage)
        assert (tmp_path / 'ready').is_dir()
    finally:
        os.close(parent)


def test_relative_handle_stays_bound_when_parent_moves(tmp_path):
    original = tmp_path / 'original'
    original.mkdir()
    fd = os.open(original, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        original.rename(tmp_path / 'moved')
        original.mkdir()
        child = os.open('bound', os.O_WRONLY | os.O_CREAT | os.O_EXCL, dir_fd=fd)
        os.close(child)
        assert (tmp_path / 'moved' / 'bound').is_file()
        assert not (original / 'bound').exists()
    finally:
        os.close(fd)


def test_lock_excludes_another_process(tmp_path):
    lock = tmp_path / 'lock'
    fd = os.open(lock, os.O_RDWR | os.O_CREAT)
    locking.flock(fd, locking.LOCK_EX)
    try:
        script = '''
import os, sys
from workflow_api.platform_io import locking
fd = os.open(sys.argv[1], os.O_RDWR)
try:
    locking.flock(fd, locking.LOCK_EX | locking.LOCK_NB)
except OSError:
    sys.exit(0)
sys.exit(9)
'''
        result = subprocess.run([sys.executable, '-c', script, str(lock)], timeout=15)
        assert result.returncode == 0
    finally:
        locking.flock(fd, locking.LOCK_UN)
        os.close(fd)


def test_windows_junction_is_rejected(tmp_path):
    if sys.platform != 'win32':
        pytest.skip('Windows junction semantics')
    outside = tmp_path / 'outside'
    outside.mkdir()
    junction = tmp_path / 'junction'
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)], check=True, capture_output=True)
    with pytest.raises(OSError):
        fd = os.open(junction, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.close(fd)
