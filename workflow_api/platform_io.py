"""Host filesystem primitives. POSIX keeps its native descriptor semantics.

Windows uses NT directory-relative handles, not a dir_fd-to-path substitution.
Reparse points are rejected for no-follow opens. Directory fsync is unavailable
on Windows: file contents are flushed, but crash durability of directory metadata
is weaker than on POSIX (atomic visibility is retained).
"""
import os as _os
import shutil
import sys


def executable(name):
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(f"Required executable is unavailable: {name}")
    from pathlib import Path
    return Path(path)


if sys.platform != 'win32':
    os = _os
    import fcntl as locking
else:
    import ctypes as c
    from ctypes import wintypes as w
    import errno
    import msvcrt
    import stat as _stat
    import threading

    nt = c.WinDLL('ntdll')
    kernel = c.WinDLL('kernel32', use_last_error=True)
    H = w.HANDLE
    P = c.c_void_p
    U = w.ULONG

    class UnicodeString(c.Structure):
        _fields_ = [('Length', w.USHORT), ('MaximumLength', w.USHORT), ('Buffer', P)]

    class ObjectAttributes(c.Structure):
        _fields_ = [('Length', U), ('RootDirectory', H), ('ObjectName', c.POINTER(UnicodeString)),
                    ('Attributes', U), ('SecurityDescriptor', P), ('SecurityQualityOfService', P)]

    class IoStatus(c.Structure):
        _fields_ = [('Status', P), ('Information', c.c_size_t)]

    class RenameInfo(c.Structure):
        _fields_ = [('ReplaceIfExists', w.BOOLEAN), ('RootDirectory', H), ('FileNameLength', U), ('FileName', w.WCHAR * 1)]

    class Overlapped(c.Structure):
        _fields_ = [('Internal', c.c_size_t), ('InternalHigh', c.c_size_t),
                    ('Offset', w.DWORD), ('OffsetHigh', w.DWORD), ('hEvent', H)]

    nt.NtCreateFile.argtypes = [c.POINTER(H), U, c.POINTER(ObjectAttributes), c.POINTER(IoStatus), P, U, U, U, U, P, U]
    nt.NtCreateFile.restype = w.LONG
    nt.NtSetInformationFile.argtypes = [H, c.POINTER(IoStatus), P, U, U]
    nt.NtSetInformationFile.restype = w.LONG
    nt.RtlNtStatusToDosError.argtypes = [w.LONG]
    nt.RtlNtStatusToDosError.restype = U
    kernel.CloseHandle.argtypes = [H]
    kernel.GetFileAttributesW.argtypes = [w.LPCWSTR]
    kernel.GetFinalPathNameByHandleW.argtypes = [H, w.LPWSTR, w.DWORD, w.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = w.DWORD
    kernel.LockFileEx.argtypes = [H, w.DWORD, w.DWORD, w.DWORD, w.DWORD, c.POINTER(Overlapped)]
    kernel.UnlockFileEx.argtypes = [H, w.DWORD, w.DWORD, w.DWORD, c.POINTER(Overlapped)]

    def check(status):
        if status < 0:
            raise c.WinError(nt.RtlNtStatusToDosError(status))

    def handle(fd):
        return msvcrt.get_osfhandle(fd)

    def native_open(path, *, parent=None, access=0x80100000, disposition=1, options=0x20):
        name = _os.fsdecode(path)
        if parent is not None:
            # Only a single trusted component is admitted at each traversal step.
            if name in ('', '.', '..') or any(x in name for x in ('/', '\\', ':', '\x00')):
                raise OSError(errno.EINVAL, 'Invalid relative component', name)
            root = handle(parent)
        else:
            name = _os.path.abspath(name)
            name = '\\??\\UNC\\' + name[2:] if name.startswith('\\\\') else '\\??\\' + name
            root = None
        buffer = c.create_unicode_buffer(name)
        text = UnicodeString(len(name.encode('utf-16-le')), len(name.encode('utf-16-le')) + 2, c.cast(buffer, P))
        attrs = ObjectAttributes(c.sizeof(ObjectAttributes), root, c.pointer(text), 0x40, None, None)
        result, ios = H(), IoStatus()
        check(nt.NtCreateFile(c.byref(result), access, c.byref(attrs), c.byref(ios), None,
                              0x80, 7, disposition, options, None, 0))
        return result.value

    def fd_path(fd):
        size = kernel.GetFinalPathNameByHandleW(handle(fd), None, 0, 0)
        if not size:
            raise c.WinError(c.get_last_error())
        buffer = c.create_unicode_buffer(size + 1)
        if not kernel.GetFinalPathNameByHandleW(handle(fd), buffer, len(buffer), 0):
            raise c.WinError(c.get_last_error())
        return buffer.value

    class WindowsOS:
        O_DIRECTORY = 0x10000000
        O_NOFOLLOW = 0x20000000
        O_NONBLOCK = 0

        def __getattr__(self, name):
            return getattr(_os, name)

        def open(self, path, flags, mode=0o777, *, dir_fd=None):
            access = 0x100080  # SYNCHRONIZE | FILE_READ_ATTRIBUTES
            access |= 0xC0000000 if flags & _os.O_RDWR else (0x40000000 if flags & _os.O_WRONLY else 0x80000000)
            disposition = 1
            if flags & _os.O_CREAT:
                disposition = 2 if flags & _os.O_EXCL else (5 if flags & _os.O_TRUNC else 3)
            elif flags & _os.O_TRUNC:
                disposition = 4
            options = 0x20 | 0x4000  # synchronous, backup intent (directory handles)
            if flags & self.O_DIRECTORY:
                options |= 1
            if flags & self.O_NOFOLLOW:
                options |= 0x200000
            raw = native_open(path, parent=dir_fd, access=access, disposition=disposition, options=options)
            try:
                fd = msvcrt.open_osfhandle(raw, (flags & (_os.O_RDONLY | _os.O_WRONLY | _os.O_RDWR | _os.O_APPEND)) | _os.O_BINARY)
            except BaseException:
                kernel.CloseHandle(raw)
                raise
            try:
                if flags & self.O_NOFOLLOW:
                    # fstat exposes native reparse attributes, including junctions.
                    info = _os.fstat(fd)
                    if getattr(info, 'st_file_attributes', 0) & 0x400:
                        raise OSError(errno.ELOOP, 'Reparse points are not trusted', path)
                return fd
            except BaseException:
                _os.close(fd)
                raise

        def stat(self, path, *, dir_fd=None, follow_symlinks=True):
            if dir_fd is None:
                return _os.stat(path, follow_symlinks=follow_symlinks)
            fd = self.open(path, _os.O_RDONLY | (0 if follow_symlinks else self.O_NOFOLLOW), dir_fd=dir_fd)
            try:
                return _os.fstat(fd)
            finally:
                _os.close(fd)

        def mkdir(self, path, mode=0o777, *, dir_fd=None):
            if dir_fd is None:
                return _os.mkdir(path, mode)
            raw = native_open(path, parent=dir_fd, access=0x100001, disposition=2, options=0x20 | 1 | 0x200000)
            kernel.CloseHandle(raw)

        def fsync(self, fd):
            if not _stat.S_ISDIR(_os.fstat(fd).st_mode):
                _os.fsync(fd)

        def scandir(self, path):
            return _os.scandir(fd_path(path) if isinstance(path, int) else path)

        def listdir(self, path='.'):
            return _os.listdir(fd_path(path) if isinstance(path, int) else path)

        def _move(self, src, dst, src_dir_fd, dst_dir_fd, replace, link=False):
            # NT rename/link target is relative to a pinned directory handle.
            parent = None
            if dst_dir_fd is None:
                dst = _os.path.abspath(dst)
                parent = self.open(_os.path.dirname(dst), self.O_DIRECTORY)
                dst_dir_fd, dst = parent, _os.path.basename(dst)
            name = _os.fsdecode(dst)
            if name in ('', '.', '..') or any(x in name for x in ('/', '\\', ':', '\x00')):
                if parent is not None:
                    _os.close(parent)
                raise OSError(errno.EINVAL, 'Invalid destination component')
            raw = None
            try:
                raw = native_open(src, parent=src_dir_fd, access=0x10000 | 0x100000 | 0x80, options=0x20 | 0x4000 | 0x200000)
                encoded = name.encode('utf-16-le')
                size = RenameInfo.FileName.offset + len(encoded)
                storage = c.create_string_buffer(max(size, c.sizeof(RenameInfo)))
                info = c.cast(storage, c.POINTER(RenameInfo)).contents
                info.ReplaceIfExists = replace
                info.RootDirectory = handle(dst_dir_fd)
                info.FileNameLength = len(encoded)
                c.memmove(c.addressof(storage) + RenameInfo.FileName.offset, encoded, len(encoded))
                ios = IoStatus()
                check(nt.NtSetInformationFile(raw, c.byref(ios), storage, size, 11 if link else 10))
            finally:
                if raw is not None:
                    kernel.CloseHandle(raw)
                if parent is not None:
                    _os.close(parent)

        def rename(self, src, dst, *, src_dir_fd=None, dst_dir_fd=None):
            return self._move(src, dst, src_dir_fd, dst_dir_fd, False)

        def replace(self, src, dst, *, src_dir_fd=None, dst_dir_fd=None):
            return self._move(src, dst, src_dir_fd, dst_dir_fd, True)

        def link(self, src, dst, *, src_dir_fd=None, dst_dir_fd=None, follow_symlinks=True):
            return self._move(src, dst, src_dir_fd, dst_dir_fd, False, link=True)

        def rmdir(self, path, *, dir_fd=None):
            if dir_fd is None:
                return _os.rmdir(path)
            return self.unlink(path, dir_fd=dir_fd)

        def unlink(self, path, *, dir_fd=None):
            if dir_fd is None:
                return _os.unlink(path)
            raw = native_open(path, parent=dir_fd, access=0x10000 | 0x100000, options=0x20 | 0x4000 | 0x200000)
            try:
                ios, delete = IoStatus(), w.BOOLEAN(True)
                check(nt.NtSetInformationFile(raw, c.byref(ios), c.byref(delete), c.sizeof(delete), 13))
            finally:
                kernel.CloseHandle(raw)

    os = WindowsOS()

    class WindowsLocking:
        LOCK_EX, LOCK_NB, LOCK_UN = 2, 4, 8

        @staticmethod
        def flock(fd, operation):
            overlapped = Overlapped()
            if operation & 8:
                result = kernel.UnlockFileEx(handle(fd), 0, 1, 0, c.byref(overlapped))
                # An acquisition may have failed before cleanup.
                if not result and c.get_last_error() != 158:
                    raise c.WinError(c.get_last_error())
            elif not kernel.LockFileEx(handle(fd), 2 | (1 if operation & 4 else 0), 0, 1, 0, c.byref(overlapped)):
                raise c.WinError(c.get_last_error())

    locking = WindowsLocking()
