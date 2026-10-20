import os
import pytest
from pathlib import Path

from protocol_path_namespace import worker_path_type


def test_worker_mount_identity_preserves_real_native_io(tmp_path):
    physical = tmp_path / 'checkout'
    physical.mkdir()
    logical = '/home/tal.noa/ytterbium_lab_simulation_ui_acceptance'
    worker_path = worker_path_type(physical, logical)
    path = worker_path(logical) / 'data' / 'result.json'
    path.parent.mkdir()
    path.write_bytes(b'actual writer bytes\n')
    assert str(path) == logical + '/data/result.json'
    assert path.as_posix() == logical + '/data/result.json'
    assert os.fspath(path) == str(physical / 'data/result.json')
    assert (physical / 'data/result.json').read_bytes() == b'actual writer bytes\n'
    assert str(path.resolve()) == logical + '/data/result.json'
    assert worker_path(physical / 'data/result.json').read_bytes() == path.read_bytes()
    assert str(worker_path(str(physical) + '_other')) == str(physical) + '_other'
    assert str(worker_path(logical + '_other')) == logical + '_other'
    assert path.relative_to(worker_path(logical)).as_posix() == 'data/result.json'
    assert list(worker_path(logical).glob('data/*.json')) == [path]
    assert list(worker_path(logical).rglob('*.json')) == [path]
    assert list(path.parent.iterdir()) == [path]


def test_worker_mount_rejects_escaping_and_symlink_io(tmp_path):
    physical = tmp_path / 'checkout'
    physical.mkdir()
    logical = '/home/tal.noa/ytterbium_lab_simulation_ui_acceptance'
    worker_path = worker_path_type(physical, logical)
    with pytest.raises(ValueError, match='escapes'):
        worker_path(logical + '/../foreign.json')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (physical / 'linked').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        (worker_path(logical) / 'linked' / 'foreign.json').write_text('blocked')
    assert not (outside / 'foreign.json').exists()


def test_worker_path_import_binding_preserves_constructor(monkeypatch, tmp_path):
    import pathlib
    physical = tmp_path / 'checkout'
    physical.mkdir()
    worker_path = worker_path_type(physical, '/home/tal.noa/isolated')
    with monkeypatch.context() as child:
        child.setattr(pathlib, 'Path', worker_path)
        path = pathlib.Path('/home/tal.noa/isolated/value.txt')
        path.write_text('native bytes')
        assert path.read_text() == 'native bytes'
        assert str(path) == '/home/tal.noa/isolated/value.txt'
    assert (physical / 'value.txt').read_text() == 'native bytes'


def test_fresh_import_binding_is_removed_after_worker(monkeypatch, tmp_path):
    import pathlib
    import sys
    import types
    from protocol_path_namespace import restore_worker_path_bindings
    physical = tmp_path / 'checkout'
    physical.mkdir()
    worker_path = worker_path_type(physical, '/home/tal.noa/isolated')
    fresh = types.ModuleType('_protocol_fresh_worker_import')
    with monkeypatch.context() as child:
        child.setattr(pathlib, 'Path', worker_path)
        child.setitem(sys.modules, fresh.__name__, fresh)
        try:
            exec('from pathlib import Path', fresh.__dict__)
            assert fresh.Path is worker_path
        finally:
            restore_worker_path_bindings(worker_path)
        assert fresh.Path is Path
    assert pathlib.Path is Path
