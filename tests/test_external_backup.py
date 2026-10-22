"""Isolated transfer/recovery and injected failures; no external storage used."""
import errno
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import struct
import sys
import tempfile
import unittest
import warnings
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from nc.backup_transfer import export_backup, restore_backup, verify_backup_package
from nc.db_maintenance import restore_database
from nc.file_publish import publish_new_file
from nc.store import Store, validate_database


class ExternalBackup(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.work = self.folder / "original-work"
        self.work.mkdir()
        self.source = self.work / "netcheck.sqlite3"
        store = Store(self.source)
        try:
            store.save_baselines({"synthetic": {"slots": ["1"], "name": "fixture"}})
            store._db.execute("INSERT INTO events(ts,level,kind,text) VALUES(1,'ok','fixture','isolated')")
            store._db.commit()
        finally:
            store._db.close()
        self.original_hash = self.digest(self.source)
        self.package = self.folder / "export" / "transfer.ncbak"
        self.destination = self.folder / "recovered" / "netcheck.sqlite3"

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def assert_original_preserved(self):
        self.assertEqual(self.digest(self.source), self.original_hash)
        self.assertFalse(list(self.folder.rglob(".netcheck-*")))

    def create_package(self):
        export_backup(self.source, self.package)
        with zipfile.ZipFile(self.package) as archive:
            return json.loads(archive.read("manifest.json")), archive.read("database.sqlite3")

    def rewrite_package(self, manifest, payload, *, entries=None, compression=zipfile.ZIP_STORED):
        self.package.parent.mkdir(exist_ok=True)
        with warnings.catch_warnings(), zipfile.ZipFile(self.package, "w", compression=compression) as archive:
            warnings.simplefilter("ignore", UserWarning)
            if entries is None:
                entries = [("manifest.json", json.dumps(manifest).encode()), ("database.sqlite3", payload)]
            for name, data in entries:
                archive.writestr(name, data)

    def test_isolated_transfer_recovers_without_original_work_folder(self):
        manifest, _ = self.create_package()
        transferred = self.folder / "separate-storage" / "transfer.ncbak"
        transferred.parent.mkdir()
        shutil.copyfile(self.package, transferred)
        self.assertEqual(self.digest(self.package), self.digest(transferred))
        self.assertEqual(verify_backup_package(transferred), manifest)
        shutil.rmtree(self.work)
        self.package.unlink()
        self.assertEqual(restore_backup(transferred, self.destination), self.destination.resolve())
        validate_database(self.destination)
        with closing(sqlite3.connect(self.destination)) as db:
            self.assertEqual(json.loads(db.execute("SELECT data FROM baselines").fetchone()[0]),
                             {"slots": ["1"], "name": "fixture"})
            self.assertEqual(db.execute("SELECT text FROM events").fetchone()[0], "isolated")
        self.assertEqual(self.digest(self.destination), manifest["sha256"])
        self.assertFalse(any(Path(str(self.destination) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")))

    def test_export_reads_committed_live_wal_into_standalone_package(self):
        with closing(sqlite3.connect(self.source)) as db:
            db.execute("PRAGMA journal_mode=WAL").fetchall()
            db.execute("PRAGMA wal_autocheckpoint=0")
            db.execute("UPDATE events SET text='committed in WAL'")
            db.commit()
            self.assertTrue(Path(str(self.source) + "-wal").exists())
            export_backup(self.source, self.package)
        restore_backup(self.package, self.destination)
        with closing(sqlite3.connect(self.destination)) as db:
            self.assertEqual(db.execute("SELECT text FROM events").fetchone()[0], "committed in WAL")
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")

    def test_valid_sqlite_payload_change_fails_digest_before_restore(self):
        manifest, payload = self.create_package()
        altered = self.folder / "altered.sqlite3"
        altered.write_bytes(payload)
        with closing(sqlite3.connect(altered)) as db:
            db.execute("UPDATE events SET text='altered payload'")
            db.commit()
        validate_database(altered)  # Structure alone cannot detect this change.
        self.rewrite_package(manifest, altered.read_bytes())
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            restore_backup(self.package, self.destination)
        self.assertFalse(self.destination.exists())
        self.assert_original_preserved()

    def test_truncation_and_crc_bitflip_are_rejected(self):
        self.create_package()
        original = self.package.read_bytes()
        with zipfile.ZipFile(self.package) as archive:
            info = archive.getinfo("database.sqlite3")
            offset = info.header_offset + 30 + len(info.filename.encode())
        for damaged in (original[:-30], original[:offset + 100] + bytes([original[offset + 100] ^ 1]) + original[offset + 101:]):
            with self.subTest(length=len(damaged)):
                self.package.write_bytes(damaged)
                with self.assertRaises(ValueError):
                    restore_backup(self.package, self.destination)
                self.assertFalse(self.destination.exists())
        self.assert_original_preserved()

    def test_manifest_digest_size_version_and_duplicate_keys_are_rejected(self):
        manifest, payload = self.create_package()
        changes = [{"sha256": "0" * 64}, {"size": len(payload) + 1}, {"size": True},
                   {"formatVersion": True}, {"formatVersion": 2}, {"algorithm": "md5"}, {"extra": "x"}]
        for change in changes:
            with self.subTest(change=change):
                self.rewrite_package(dict(manifest, **change), payload)
                with self.assertRaises(ValueError):
                    verify_backup_package(self.package)
        for raw in (b'{"size":1,"size":2}', b'\xff', b'[' * 1100 + b']' * 1100, b' ' * 4097):
            with self.subTest(raw_length=len(raw)):
                self.rewrite_package(manifest, payload, entries=[("manifest.json", raw), ("database.sqlite3", payload)])
                with self.assertRaises(ValueError):
                    verify_backup_package(self.package)
        self.assert_original_preserved()

    def test_unexpected_duplicate_path_and_compressed_entries_are_rejected(self):
        manifest, payload = self.create_package()
        good = [("manifest.json", json.dumps(manifest).encode()), ("database.sqlite3", payload)]
        for entries in (good + [("extra", b"x")], good + [good[1]], [good[0], ("../database.sqlite3", payload)]):
            with self.subTest(names=[entry[0] for entry in entries]):
                self.rewrite_package(manifest, payload, entries=entries)
                with self.assertRaises(ValueError):
                    verify_backup_package(self.package)
        self.rewrite_package(manifest, payload, compression=zipfile.ZIP_DEFLATED)
        with self.assertRaises(ValueError):
            verify_backup_package(self.package)
        self.assert_original_preserved()

    def test_wrong_sqlite_schema_with_matching_digest_is_rejected(self):
        self.create_package()
        other = self.folder / "unrelated.sqlite3"
        with closing(sqlite3.connect(other)) as db:
            db.execute("CREATE TABLE other(value TEXT)")
        payload = other.read_bytes()
        manifest = {"formatVersion": 1, "algorithm": "sha256", "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest()}
        self.rewrite_package(manifest, payload)
        with self.assertRaises(sqlite3.DatabaseError):
            restore_backup(self.package, self.destination)
        self.assertFalse(self.destination.exists())
        self.assert_original_preserved()

    def test_symlink_and_encrypted_entry_metadata_are_rejected(self):
        manifest, payload = self.create_package()
        link = zipfile.ZipInfo("database.sqlite3")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.rewrite_package(manifest, payload, entries=[("manifest.json", json.dumps(manifest).encode()), (link, payload)])
        with self.assertRaises(ValueError):
            verify_backup_package(self.package)
        self.rewrite_package(manifest, payload)
        content = bytearray(self.package.read_bytes())
        # Set the encryption flag in both the local and central record, without
        # relying on a ZIP writer that intentionally does not support encryption.
        local, central = content.index(b"PK\x03\x04"), content.index(b"PK\x01\x02")
        content[local + 6] |= 1
        content[central + 8] |= 1
        self.package.write_bytes(content)
        with self.assertRaises(ValueError):
            verify_backup_package(self.package)
        self.assert_original_preserved()

    def test_staging_allocation_collision_never_deletes_an_unowned_file(self):
        self.create_package()
        collision = self.folder / "someone-elses-file.tmp"
        collision.write_bytes(b"must remain")
        def fail_allocation(*args, **kwargs):
            raise FileExistsError(errno.EEXIST, "synthetic staging collision", str(collision))
        with patch("nc.backup_transfer.tempfile.mkstemp", side_effect=fail_allocation):
            for operation in (lambda: export_backup(self.source, self.folder / "another.ncbak"),
                              lambda: restore_backup(self.package, self.destination)):
                with self.assertRaises(FileExistsError): operation()
                self.assertEqual(collision.read_bytes(), b"must remain")
        self.assertFalse(self.destination.exists())
        self.assert_original_preserved()

    def test_directory_entry_count_size_and_offsets_are_checked_before_zipfile(self):
        self.create_package()
        original = self.package.read_bytes()
        footer = list(struct.unpack("<4s4H2LH", original[-22:]))
        # These tiny files merely claim excessive metadata. A full ZIP parser
        # must never receive them, regardless of any payload-memory cap.
        for changes in ({3: 60000, 4: 60000}, {5: 2 ** 31}, {6: 2 ** 31}):
            changed = footer.copy()
            for index, value in changes.items(): changed[index] = value
            self.package.write_bytes(original[:-22] + struct.pack("<4s4H2LH", *changed))
            with self.subTest(changes=changes), patch("nc.backup_transfer.zipfile.ZipFile",
                                                    side_effect=AssertionError("metadata preflight was skipped")):
                with self.assertRaises(ValueError):
                    verify_backup_package(self.package)
        self.assert_original_preserved()

    def test_zip64_footer_is_supported_and_bounded_before_full_zip_parse(self):
        # Force the same ZIP64 footer used by >2 GiB output without allocating
        # a multi-gigabyte fixture in the unit suite.
        with patch("zipfile.ZIP64_LIMIT", 1024):
            export_backup(self.source, self.package)
        original = self.package.read_bytes()
        self.assertIn(b"PK\x06\x06", original[-98:])
        metadata = verify_backup_package(self.package)
        restore_backup(self.package, self.destination)
        self.assertEqual(self.digest(self.destination), metadata["sha256"])
        record_offset = original.rfind(b"PK\x06\x06")
        record = list(struct.unpack("<4sQ2H2L4Q", original[record_offset:record_offset + 56]))
        for changes in ({6: 30000, 7: 30000}, {8: 2 ** 40}, {1: 2 ** 40}, {9: 2 ** 40}):
            changed = record.copy()
            for index, value in changes.items(): changed[index] = value
            self.package.write_bytes(original[:record_offset] + struct.pack("<4sQ2H2L4Q", *changed)
                                     + original[record_offset + 56:])
            with self.subTest(changes=changes), patch("nc.backup_transfer.zipfile.ZipFile",
                                                    side_effect=AssertionError("ZIP64 preflight was skipped")):
                with self.assertRaises(ValueError):
                    verify_backup_package(self.package)
        self.assert_original_preserved()

    def test_plain_restore_rejects_sidecar_created_during_validation(self):
        self.destination.parent.mkdir()
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(self.destination) + suffix)
            def validation(path, **kwargs):
                validate_database(path, **kwargs)
                if Path(path) != self.source:
                    sidecar.write_bytes(b"raced sidecar")
            with self.subTest(suffix=suffix), patch("nc.db_maintenance.validate_database", side_effect=validation):
                with self.assertRaises(FileExistsError):
                    restore_database(self.source, self.destination)
            self.assertFalse(self.destination.exists())
            self.assertEqual(sidecar.read_bytes(), b"raced sidecar")
            sidecar.unlink()
        self.assert_original_preserved()

    def test_plain_restore_late_busy_uses_zero_busy_handler_and_shared_deadline(self):
        # Gate after a real backup step, take an actual SQLite exclusive lock,
        # then move a fake clock across the total deadline on the BUSY step.
        real_connect = sqlite3.connect
        now = [100.0]
        blockers = []
        statuses = []
        with closing(real_connect(self.source)) as db:
            db.execute("PRAGMA journal_mode=DELETE").fetchall()
            db.execute("CREATE TABLE padding(value BLOB)")
            db.executemany("INSERT INTO padding VALUES (?)", [(b'x' * 8192,)] * 160)
            db.commit()
        self.original_hash = self.digest(self.source)
        testcase = self
        class LateBusyConnection(sqlite3.Connection):
            def backup(connection, target, **kwargs):
                testcase.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 0)
                testcase.assertEqual(target.execute("PRAGMA busy_timeout").fetchone()[0], 0)
                progress = kwargs['progress']
                def gated(status, remaining, total):
                    statuses.append(status)
                    if status == sqlite3.SQLITE_OK and remaining and not blockers:
                        now[0] = 100.49
                        blocker = real_connect(testcase.source, timeout=0)
                        blocker.execute("BEGIN EXCLUSIVE")
                        blockers.append(blocker)
                    elif status == sqlite3.SQLITE_BUSY:
                        now[0] = 100.51
                    progress(status, remaining, total)
                return super().backup(target, **dict(kwargs, progress=gated))
        def connect(*args, **kwargs):
            return real_connect(*args, **dict(kwargs, factory=LateBusyConnection))
        try:
            with patch("nc.db_maintenance.sqlite3.connect", side_effect=connect), \
                    patch("nc.db_maintenance.time.monotonic", side_effect=lambda: now[0]):
                with self.assertRaises(TimeoutError):
                    restore_database(self.source, self.destination, timeout=0.5)
        finally:
            for blocker in blockers:
                blocker.rollback()
                blocker.close()
        self.assertIn(sqlite3.SQLITE_BUSY, statuses)
        self.assertFalse(self.destination.exists())
        self.assert_original_preserved()

    def test_export_transfer_failure_full_and_permission_leave_no_final_file(self):
        original_write = zipfile._ZipWriteFile.write
        for code in (errno.EIO, errno.ENOSPC, errno.EACCES):
            calls = 0
            def failing_write(stream, data):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError(code, "synthetic transfer failure")
                return original_write(stream, data)
            with self.subTest(code=code), patch("nc.backup_transfer._CHUNK_SIZE", 4096), \
                    patch("nc.backup_transfer.zipfile._ZipWriteFile.write", failing_write):
                with self.assertRaises(OSError):
                    export_backup(self.source, self.package)
            self.assertFalse(self.package.exists())
            self.assert_original_preserved()

    def test_restore_write_full_or_permission_failure_cleans_partial_file(self):
        self.create_package()
        expected = self.digest(self.package)
        original_open = Path.open
        for code in (errno.ENOSPC, errno.EACCES):
            class FailingOutput:
                def __init__(self, stream): self.stream = stream
                def __enter__(self): return self
                def __exit__(self, *args): self.stream.close()
                def write(self, data):
                    self.stream.write(data[:8])
                    raise OSError(code, "synthetic disk failure")
            def open_file(path, mode="r", *args, **kwargs):
                stream = original_open(path, mode, *args, **kwargs)
                if mode == "wb" and path.name.startswith(".netcheck-restore-package-"):
                    return FailingOutput(stream)
                return stream
            with self.subTest(code=code), patch.object(Path, "open", open_file):
                with self.assertRaises(OSError):
                    restore_backup(self.package, self.destination)
            self.assertFalse(self.destination.exists())
            self.assertEqual(self.digest(self.package), expected)
            self.assert_original_preserved()

    def test_timeout_is_shared_and_no_final_file_is_published(self):
        self.create_package()
        for operation in (lambda: verify_backup_package(self.package),
                          lambda: restore_backup(self.package, self.destination),
                          lambda: export_backup(self.source, self.folder / "timed-out.ncbak")):
            with patch("nc.backup_transfer.time.monotonic", side_effect=[0, 301]):
                with self.assertRaises(TimeoutError): operation()
            self.assertFalse(self.destination.exists())
            self.assertFalse((self.folder / "timed-out.ncbak").exists())
        self.assert_original_preserved()

    def test_existing_target_sidecars_and_publish_race_preserve_existing_bytes(self):
        self.create_package()
        original_package = self.package.read_bytes()
        with self.assertRaises(FileExistsError):
            export_backup(self.source, self.package)
        self.assertEqual(self.package.read_bytes(), original_package)
        self.destination.parent.mkdir()
        for suffix in ("", "-wal", "-shm", "-journal"):
            target = Path(str(self.destination) + suffix)
            target.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                restore_backup(self.package, self.destination)
            self.assertEqual(target.read_bytes(), b"existing")
            target.unlink()
        original_link = os.link
        def colliding_link(source, destination):
            Path(destination).write_bytes(b"appeared during validation")
            return original_link(source, destination)
        with patch("nc.file_publish.os.link", colliding_link):
            with self.assertRaises(FileExistsError):
                restore_backup(self.package, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"appeared during validation")
        self.assert_original_preserved()


class ExclusivePublication(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.staged = self.folder / "staged.tmp"
        self.staged.write_bytes(b"complete staged contents")
        self.destination = self.folder / "published.bin"

    @unittest.skipUnless(sys.platform in ("win32", "darwin"), "native exclusive rename targets Windows/macOS")
    def test_unsupported_hardlink_uses_real_native_exclusive_rename(self):
        with patch("nc.file_publish.os.link", side_effect=OSError(errno.ENOTSUP, "synthetic unsupported")):
            publish_new_file(self.staged, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"complete staged contents")
        self.assertFalse(self.staged.exists())

    @unittest.skipUnless(sys.platform in ("win32", "darwin"), "native exclusive rename targets Windows/macOS")
    def test_native_fallback_collision_does_not_overwrite_late_target(self):
        def unsupported_with_collision(*args):
            self.destination.write_bytes(b"existing late target")
            raise OSError(errno.ENOTSUP, "synthetic unsupported")
        with patch("nc.file_publish.os.link", side_effect=unsupported_with_collision):
            with self.assertRaises(FileExistsError):
                publish_new_file(self.staged, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"existing late target")
        self.assertEqual(self.staged.read_bytes(), b"complete staged contents")

    def test_permission_error_never_uses_fallback_and_retains_stage(self):
        with patch("nc.file_publish.os.link", side_effect=PermissionError(errno.EACCES, "denied")), \
                patch("nc.file_publish._rename_noreplace") as fallback:
            with self.assertRaises(PermissionError): publish_new_file(self.staged, self.destination)
        fallback.assert_not_called()
        self.assertFalse(self.destination.exists())
        self.assertTrue(self.staged.exists())

    def test_different_directories_are_rejected_before_any_publication(self):
        with self.assertRaises(ValueError):
            publish_new_file(self.staged, self.folder / "other" / "file")
        self.assertTrue(self.staged.exists())

    @unittest.skipUnless(sys.platform in ("win32", "darwin"), "native exclusive rename targets Windows/macOS")
    def test_plain_restore_uses_native_fallback_on_unsupported_hardlink(self):
        source = self.folder / "source.sqlite3"
        store = Store(source)
        store._db.close()
        destination = self.folder / "restored.sqlite3"
        with patch("nc.file_publish.os.link", side_effect=OSError(errno.ENOTSUP, "unsupported")):
            restore_database(source, destination)
        validate_database(destination)


if __name__ == "__main__":
    unittest.main()
