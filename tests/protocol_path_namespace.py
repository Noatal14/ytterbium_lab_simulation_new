"""Model a worker's logical mount identity using a native temporary filesystem.

Only hermetic process-boundary tests use this class. Filesystem operations retain
native paths; normal writer string serialization observes the Zeus mount path.
"""
import os
import stat
import sys
from pathlib import Path


def worker_path_type(physical_root, logical_root):
    native_type = type(Path())
    physical = os.fspath(physical_root)
    logical = str(logical_root)

    def within(value, root):
        return value == root or value.startswith(root + '/') or value.startswith(root + os.sep)

    def translate(value, source, destination):
        if within(value, source):
            suffix = value[len(source):]
            if '..' in suffix.replace('\\', '/').split('/'):
                raise ValueError('Worker mount identity escapes its root.')
            return destination + suffix.replace('\\', '/')
        return value

    def native_io_path(value):
        if within(value, physical):
            relative = value[len(physical):].replace('\\', '/').strip('/')
            if '..' in relative.split('/'):
                raise ValueError('Worker mount identity escapes its root.')
            cursor = physical
            for part in ('', *relative.split('/')):
                if part:
                    cursor = os.path.join(cursor, part)
                try:
                    mode = os.lstat(cursor).st_mode
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(mode):
                    raise ValueError('Worker mount identity traverses a symlink.')
        return value

    class WorkerPath(native_type):
        def __new__(cls, *args):
            return object.__new__(cls)

        def __init__(self, *args):
            super().__init__(*(translate(os.fspath(value), logical, physical) for value in args))

        def __str__(self):
            return translate(super().__str__(), physical, logical)

        def __fspath__(self):
            return native_io_path(super().__str__())

        def glob(self, pattern, **kwargs):
            return (type(self)(path) for path in native_type(os.fspath(self)).glob(pattern, **kwargs))

        def rglob(self, pattern, **kwargs):
            return (type(self)(path) for path in native_type(os.fspath(self)).rglob(pattern, **kwargs))

        def iterdir(self):
            return (type(self)(path) for path in native_type(os.fspath(self)).iterdir())

    return WorkerPath


def restore_worker_path_bindings(worker_path):
    """Remove imported mount bindings before returning to the host process."""
    for imported in tuple(sys.modules.values()):
        if getattr(imported, 'Path', None) is worker_path:
            setattr(imported, 'Path', Path)
