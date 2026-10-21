"""NT path and fd ctime differ; each API must still prove an unchanged file."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from workflow_api import smoke_receipt as receipt


def metadata(value, **updates):
    fields = {name:getattr(value,name) for name in ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns')}
    return SimpleNamespace(**(fields | updates))


def setup_nt(monkeypatch, path, fd_mutation=None, path_mutation=None):
    namespace = SimpleNamespace(**vars(os)); namespace.name = 'nt'
    real_fstat = os.fstat; real_lstat = Path.lstat
    fd_calls = path_calls = 0
    def fstat(fd):
        nonlocal fd_calls
        fd_calls += 1
        value = metadata(real_fstat(fd), st_ctime_ns=123456789)
        return metadata(value, **fd_mutation) if fd_mutation and fd_calls > 1 else value
    def lstat(current):
        nonlocal path_calls
        value = real_lstat(current)
        if current != path: return value
        path_calls += 1
        return metadata(value, **path_mutation) if path_mutation and path_calls > 1 else value
    namespace.fstat = fstat
    monkeypatch.setattr(receipt, 'os', namespace)
    monkeypatch.setattr(Path, 'lstat', lstat)


def test_nt_stable_distinct_api_ctime_accepts_without_writes(tmp_path, monkeypatch):
    path = tmp_path/'receipt.json';path.write_bytes(b'{"value":1}')
    before=path.read_bytes();setup_nt(monkeypatch,path)
    assert receipt._receipt_identity(path)=='{"value":1}'
    assert path.read_bytes()==before


@pytest.mark.parametrize('api', ['path','fd'])
def test_nt_same_api_ctime_change_is_rejected(tmp_path, monkeypatch, api):
    path=tmp_path/'receipt.json';path.write_bytes(b'{"value":1}')
    setup_nt(monkeypatch,path,fd_mutation={'st_ctime_ns':987654321} if api=='fd' else None,
             path_mutation={'st_ctime_ns':987654321} if api=='path' else None)
    with pytest.raises(ValueError,match='changed during inspection'):
        receipt._receipt_identity(path)


@pytest.mark.parametrize('field', ['st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns'])
def test_nt_cross_api_common_field_change_is_rejected(tmp_path, monkeypatch, field):
    path=tmp_path/'receipt.json';path.write_bytes(b'{"value":1}')
    namespace=SimpleNamespace(**vars(os));namespace.name='nt';real_fstat=os.fstat
    namespace.fstat=lambda fd: metadata(real_fstat(fd),**{field:getattr(real_fstat(fd),field)+1, 'st_ctime_ns':123456789})
    monkeypatch.setattr(receipt,'os',namespace)
    with pytest.raises(ValueError):receipt._receipt_identity(path)


def test_posix_cross_api_ctime_still_exact(tmp_path, monkeypatch):
    path=tmp_path/'receipt.json';path.write_bytes(b'{"value":1}')
    namespace=SimpleNamespace(**vars(os));namespace.name='posix';real_fstat=os.fstat
    namespace.fstat=lambda fd:metadata(real_fstat(fd),st_ctime_ns=123456789)
    monkeypatch.setattr(receipt,'os',namespace)
    with pytest.raises(ValueError,match='changed during inspection'):receipt._receipt_identity(path)


def test_nt_path_replacement_after_read_is_rejected(tmp_path, monkeypatch):
    path=tmp_path/'receipt.json';path.write_bytes(b'{"value":1}')
    setup_nt(monkeypatch,path,path_mutation={'st_ino':path.stat().st_ino+1})
    with pytest.raises(ValueError,match='changed during inspection'):receipt._receipt_identity(path)
