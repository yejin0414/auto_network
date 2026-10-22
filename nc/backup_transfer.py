"""Portable, self-contained backup packages with transfer-integrity checks.

The digest detects accidental changes; it does not authenticate the publisher.
All final files use atomic, exclusive publication. Inputs are never modified.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import struct
import tempfile
import time
import zipfile
from pathlib import Path

from .db_maintenance import restore_database
from .file_publish import publish_new_file
from .store import validate_database

_CHUNK_SIZE = 1024 * 1024
_MANIFEST_LIMIT = 4096
_DIRECTORY_LIMIT = 16 * 1024
_ENTRIES = {"manifest.json", "database.sqlite3"}
_SIDECARS = ("-wal", "-shm", "-journal")


def _deadline(timeout: float) -> float:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("백업 전송 제한 시간은 양수여야 합니다.")
    return time.monotonic() + timeout


def _remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("백업 전송/복구 제한 시간을 초과했습니다.")
    return seconds


def _new_destination(destination: Path) -> Path:
    destination = Path(destination).absolute()
    if (os.path.lexists(destination) or str(destination).lower().endswith(_SIDECARS)
            or any(os.path.lexists(str(destination) + suffix) for suffix in _SIDECARS)):
        raise FileExistsError("기존 파일과 SQLite 보조 파일이 없는 새 경로가 필요합니다.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def _cleanup(folder: Path) -> None:
    # A cleanup error must not turn successful publication into reported failure.
    try:
        shutil.rmtree(folder)
    except OSError:
        pass


def _digest(path: Path, deadline: float) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        while True:
            _remaining(deadline)
            chunk = source.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("중복 백업 검증 항목입니다.")
        result[key] = value
    return result


def _manifest(data: bytes, archive_size: int) -> dict:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("백업 검증 정보를 읽을 수 없습니다.") from exc
    if (not isinstance(value, dict) or set(value) != {"formatVersion", "algorithm", "sha256", "size"}
            or type(value["formatVersion"]) is not int or value["formatVersion"] != 1
            or value["algorithm"] != "sha256"
            or not isinstance(value["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
            or type(value["size"]) is not int or not 0 < value["size"] <= archive_size):
        raise ValueError("지원하지 않거나 올바르지 않은 백업 검증 정보입니다.")
    return value


def _preflight_directory(source, deadline: float) -> None:
    """Bound ZIP metadata before ZipFile allocates its complete directory.

    Read only the bounded ZIP footer/comment and fixed ZIP64 footer records.
    The database payload size is not capped. Our format supports a single disk
    and the ordinary 44-byte ZIP64 footer used by Python's ZIP writer.
    """
    _remaining(deadline)
    source.seek(0, os.SEEK_END)
    length = source.tell()
    source.seek(max(0, length - 65557))  # 22-byte footer + maximum ZIP comment.
    tail = source.read(65557)
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or len(tail) - position < 22:
        raise ValueError("백업 ZIP 끝 기록이 없습니다.")
    footer = struct.unpack("<4s4H2LH", tail[position:position + 22])
    _, disk, directory_disk, count_disk, count, directory_size, directory_offset, comment_size = footer
    if position + 22 + comment_size != len(tail):
        raise ValueError("백업 ZIP 끝 기록의 크기가 올바르지 않습니다.")
    directory_end = length - len(tail) + position
    _remaining(deadline)
    if directory_end >= 20:
        source.seek(directory_end - 20)
        locator = source.read(20)
        if locator.startswith(b"PK\x06\x07"):
            _, locator_disk, offset, disks = struct.unpack("<4sLQL", locator)
            if locator_disk != 0 or disks != 1 or offset + 56 != directory_end - 20:
                raise ValueError("지원하지 않는 ZIP64 끝 기록입니다.")
            source.seek(offset)
            record = source.read(56)
            if len(record) != 56:
                raise ValueError("ZIP64 끝 기록이 잘렸습니다.")
            signature, record_size, _, _, disk, directory_disk, count_disk, count, directory_size, directory_offset = \
                struct.unpack("<4sQ2H2L4Q", record)
            if signature != b"PK\x06\x06" or record_size != 44:
                raise ValueError("지원하지 않는 ZIP64 끝 기록입니다.")
            directory_end = offset
    if (disk != 0 or directory_disk != 0 or count_disk != 2 or count != 2
            or not 0 < directory_size <= _DIRECTORY_LIMIT
            or directory_offset + directory_size != directory_end):
        raise ValueError("백업 ZIP 목록의 개수, 크기 또는 위치가 올바르지 않습니다.")
    _remaining(deadline)
    source.seek(0)


def _unpack_verified(package: Path, payload: Path, deadline: float, *, exclusive: bool = True) -> dict:
    """Read only the two fixed entries, with bounded manifest and streamed DB."""
    try:
        with Path(package).open("rb") as source:
            _preflight_directory(source, deadline)
            return _read_verified(source, payload, deadline, exclusive=exclusive)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, UnicodeError, RuntimeError, NotImplementedError) as exc:
        raise ValueError("백업 패키지가 손상되었거나 지원하지 않는 형식입니다.") from exc


def _read_verified(source, payload: Path, deadline: float, *, exclusive: bool) -> dict:
    with zipfile.ZipFile(source, "r") as archive:
        _remaining(deadline)
        entries = archive.infolist()
        if len(entries) != 2 or {entry.filename for entry in entries} != _ENTRIES:
            raise ValueError("백업 파일 구성에 중복 또는 허용되지 않은 항목이 있습니다.")
        if any(entry.flag_bits & 1 or entry.compress_type != zipfile.ZIP_STORED
               or entry.compress_size != entry.file_size
               or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
               for entry in entries):
            raise ValueError("암호화, 압축 또는 일반 파일이 아닌 백업 항목은 지원하지 않습니다.")
        info = archive.getinfo("manifest.json")
        if info.file_size > _MANIFEST_LIMIT:
            raise ValueError("백업 검증 정보가 너무 큽니다.")
        with archive.open(info) as stream:
            manifest = _manifest(stream.read(_MANIFEST_LIMIT + 1), os.fstat(source.fileno()).st_size)
        info = archive.getinfo("database.sqlite3")
        if info.file_size != manifest["size"]:
            raise ValueError("백업 데이터 크기가 검증 정보와 다릅니다.")
        digest, size = hashlib.sha256(), 0
        with archive.open(info) as stream, payload.open("xb" if exclusive else "wb") as output:
            while True:
                _remaining(deadline)
                chunk = stream.read(min(_CHUNK_SIZE, manifest["size"] - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > manifest["size"]:
                    raise ValueError("백업 데이터가 선언된 크기를 초과했습니다.")
                digest.update(chunk)
                output.write(chunk)
        if size != manifest["size"] or digest.hexdigest() != manifest["sha256"]:
            raise ValueError("백업 SHA-256 또는 크기 검증에 실패했습니다.")
    validate_database(payload, timeout=_remaining(deadline))
    _remaining(deadline)
    return manifest


def export_backup(source: Path, destination: Path, *, timeout: float = 300.0) -> Path:
    """Snapshot even a live WAL DB, then publish one verified .ncbak package."""
    deadline = _deadline(timeout)
    source = Path(source).resolve(strict=True)
    destination = _new_destination(destination)
    folder = Path(tempfile.mkdtemp(prefix=".netcheck-export-", dir=destination.parent))
    staged = None
    try:
        fd, name = tempfile.mkstemp(prefix=".netcheck-export-", suffix=".tmp", dir=destination.parent)
        os.close(fd)
        staged = Path(name)
        snapshot = restore_database(source, folder / "snapshot.sqlite3", timeout=_remaining(deadline))
        expected, size = _digest(snapshot, deadline)
        manifest = {"formatVersion": 1, "algorithm": "sha256", "sha256": expected, "size": size}
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            info = zipfile.ZipInfo("database.sqlite3")
            info.file_size = size
            copied = hashlib.sha256()
            with snapshot.open("rb") as input_file, archive.open(info, "w", force_zip64=True) as output:
                while True:
                    _remaining(deadline)
                    chunk = input_file.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    copied.update(chunk)
                    output.write(chunk)
            if copied.hexdigest() != expected:
                raise ValueError("백업 스냅샷이 전송 도중 변경되었습니다.")
            archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True).encode("utf-8"))
        _unpack_verified(staged, folder / "verified.sqlite3", deadline)
        with staged.open("r+b") as output:
            os.fsync(output.fileno())
        _remaining(deadline)
        publish_new_file(staged, destination)
        return destination.resolve()
    finally:
        if staged is not None:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass
        _cleanup(folder)


def verify_backup_package(path: Path, *, timeout: float = 300.0) -> dict:
    """Verify transfer digest, SQLite structure and Netcheck schema, read-only."""
    deadline = _deadline(timeout)
    folder = Path(tempfile.mkdtemp(prefix="netcheck-verify-"))
    try:
        return _unpack_verified(Path(path), folder / "database.sqlite3", deadline)
    finally:
        _cleanup(folder)


def restore_backup(package: Path, destination: Path, *, timeout: float = 300.0) -> Path:
    """Restore a self-contained package to a new standalone DB, never replace."""
    deadline = _deadline(timeout)
    destination = _new_destination(destination)
    fd, name = tempfile.mkstemp(prefix=".netcheck-restore-package-", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    staged = Path(name)
    try:
        _unpack_verified(Path(package), staged, deadline, exclusive=False)
        with staged.open("r+b") as output:
            os.fsync(output.fileno())
        _remaining(deadline)
        # A sidecar appearing during validation must also prevent publication.
        _new_destination(destination)
        publish_new_file(staged, destination)
        return destination.resolve()
    finally:
        for path in (staged, *(Path(str(staged) + suffix) for suffix in _SIDECARS)):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
