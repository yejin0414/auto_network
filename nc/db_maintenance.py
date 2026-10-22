"""Offline recovery to a new file. Never replace a running or existing database."""
from __future__ import annotations

import math
import os
import sqlite3
import tempfile
import time
from pathlib import Path

from .store import validate_database


def restore_database(source: Path, destination: Path, *, timeout: float = 30.0) -> Path:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("복원 제한 시간은 양수여야 합니다.")
    deadline = time.monotonic() + timeout

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("데이터베이스 복원 제한 시간을 초과했습니다.")
        return seconds

    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    if (os.path.lexists(destination) or source == destination.resolve()
            or str(destination).lower().endswith(("-wal", "-shm", "-journal"))
            or any(os.path.lexists(str(destination) + suffix) for suffix in ("-wal", "-shm", "-journal"))):
        raise FileExistsError("복원은 기존 DB와 보조 파일이 없는 새 경로에만 가능합니다.")
    validate_database(source, timeout=remaining())
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".netcheck-restore-", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    src = target = None
    try:
        src = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=remaining())
        src.execute("PRAGMA query_only=ON")
        target = sqlite3.connect(temporary, timeout=remaining())
        src.backup(target, pages=128, progress=lambda *_: remaining(), sleep=0.01)
        target.execute("PRAGMA journal_mode=DELETE").fetchall()
        target.close()
        target = None
        src.close()
        src = None
        validate_database(temporary, timeout=remaining())
        with temporary.open("r+b") as file:
            os.fsync(file.fileno())
        remaining()
        # Atomic no-overwrite publication also handles a target appearing while
        # the backup was being checked. Windows handles are already closed.
        os.link(temporary, destination)
        return destination.resolve()
    finally:
        if target is not None:
            target.close()
        if src is not None:
            src.close()
        for path in (temporary, *(Path(str(temporary) + suffix) for suffix in ("-wal", "-shm", "-journal"))):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
