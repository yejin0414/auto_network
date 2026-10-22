"""Publish a fully written, closed staging file without replacing any target."""
from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path


def _rename_noreplace(source: Path, destination: Path) -> None:
    if sys.platform == "win32":
        # Windows rename fails if the destination exists. Both names are in the
        # same directory, so this cannot become a cross-volume copy operation.
        os.rename(source, destination)
    elif sys.platform == "darwin":
        # Darwin's renamex_np(RENAME_EXCL), declared in SDK sys/stdio.h. Plain
        # POSIX rename would replace a target that appeared after our check.
        library = ctypes.CDLL(None, use_errno=True)
        try:
            rename = library.renamex_np
        except AttributeError as exc:
            raise OSError(errno.ENOTSUP, "Exclusive rename is unavailable") from exc
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        if rename(os.fsencode(source), os.fsencode(destination), 0x00000004):
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(destination))
    else:
        raise OSError(errno.ENOTSUP, "Exclusive rename is unsupported on this platform")


def publish_new_file(staged: Path, destination: Path) -> None:
    """Atomically expose a new file; never use check-then-replace or direct copy.

    The caller must stage in the destination directory, flush/close all handles,
    and clean up the staging name afterwards (rename may already have removed
    it). A filesystem without either safe primitive fails without publication.
    """
    staged, destination = Path(staged), Path(destination)
    if staged.parent.resolve() != destination.parent.resolve():
        raise ValueError("Staging and destination must share a directory")
    if os.path.lexists(destination):
        raise FileExistsError(errno.EEXIST, "Destination already exists", str(destination))
    try:
        os.link(staged, destination)
    except OSError as exc:
        unsupported = {errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS}
        if exc.errno not in unsupported and getattr(exc, "winerror", None) not in (1, 50):
            raise
        _rename_noreplace(staged, destination)
