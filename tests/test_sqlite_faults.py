"""Real SQLite failures on disposable files; no devices, keyring or scheduler.

These exercise SQLite's own result codes, rather than raising injected errors.
The FULL case limits database pages; it does not fill the host's filesystem.
"""
from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from nc.collector import CmdResult, DeviceCollection
from nc.store import Store, validate_database


TS = 1700000000


def evaluation():
    return {
        "summary": {"overall": "ok", "counts": {"ok": 1}},
        "devices": {"synthetic": {"status": "ok", "metrics": {"cpu": 10}, "checks": []}},
    }


def collections():
    result = CmdResult("version", "Version", "display version", "Synthetic output", True)
    return {"synthetic": DeviceCollection("synthetic", True, results={"version": result})}


def event(run_id, text="Synthetic event"):
    return (TS + 10, run_id, "synthetic", "warn", "new", text)


def vrrp(run_id):
    return {"device_id": "synthetic", "device_name": "Synthetic switch", "grp": "Vlan1/1",
            "old": "Master", "new": "Backup", "detected": TS + 10, "run_id": run_id,
            "source": "test", "text": f"Synthetic VRRP event {run_id}"}


def database_rows(db):
    """Include all application tables and AUTOINCREMENT state in the comparison."""
    names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {name: [tuple(row) for row in db.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]
            for name in names}


class AtomicSQLiteFailures(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="netcheck-sqlite-fault-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "history.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store._db.close)
        self.store._db.execute("PRAGMA busy_timeout=50")
        run_id = self.store.save_run(TS, TS + 1, "test", evaluation(), collections(), {})
        self.store.save_baselines({"synthetic": {"slots": ["1"]}})
        self.store.add_events([event(run_id)])
        self.store.add_vrrp([vrrp(run_id)])
        self.original = database_rows(self.store._db)

    def commit(self, events_factory=None):
        return self.store.commit_run(
            TS + 10, TS + 11, "test", evaluation(), collections(), {},
            baseline_updates={"synthetic": {"slots": ["1", "2"]}},
            events_factory=events_factory or (lambda run_id: [event(run_id)]),
            vrrp_factory=lambda run_id: [vrrp(run_id)],
        )

    def assert_rolled_back_and_recoverable(self):
        self.assertFalse(self.store._db.in_transaction)
        self.assertEqual(database_rows(self.store._db), self.original)
        run_id = self.commit()
        self.assertEqual(len(self.store.list_runs()), 2)
        self.assertEqual(self.store.baselines()["synthetic"], {"slots": ["1", "2"]})
        self.assertTrue(any(row["run_id"] == run_id for row in self.store.list_events()))
        self.assertTrue(any(row["run_id"] == run_id for row in self.store.list_vrrp()))
        self.assertEqual(self.store.get_raw(run_id, "synthetic", "version")["output"], "Synthetic output")

    def test_real_full_during_event_insert_rolls_back_entire_run(self):
        db = self.store._db
        original_limit = db.execute("PRAGMA max_page_count").fetchone()[0]

        def full_events(run_id):
            pages = db.execute("PRAGMA page_count").fetchone()[0]
            self.assertEqual(db.execute(f"PRAGMA max_page_count={pages}").fetchone()[0], pages)
            return [event(run_id, "X" * 400000)]

        try:
            with self.assertRaises(sqlite3.Error) as caught:
                self.commit(full_events)
            self.assertEqual(caught.exception.sqlite_errorcode & 0xff, sqlite3.SQLITE_FULL)
        finally:
            db.execute(f"PRAGMA max_page_count={original_limit}")
        self.assert_rolled_back_and_recoverable()

    def test_real_query_only_after_run_insert_rolls_back_entire_run(self):
        def readonly_events(run_id):
            self.store._db.execute("PRAGMA query_only=ON")
            return [event(run_id)]

        try:
            with self.assertRaises(sqlite3.Error) as caught:
                self.commit(readonly_events)
            self.assertEqual(caught.exception.sqlite_errorcode & 0xff, sqlite3.SQLITE_READONLY)
        finally:
            self.store._db.execute("PRAGMA query_only=OFF")
        self.assert_rolled_back_and_recoverable()

    def test_real_busy_from_another_writer_leaves_no_partial_run(self):
        with closing(sqlite3.connect(self.path, timeout=0)) as other:
            other.execute("BEGIN IMMEDIATE")
            try:
                with self.assertRaises(sqlite3.Error) as caught:
                    self.commit()
                self.assertEqual(caught.exception.sqlite_errorcode & 0xff, sqlite3.SQLITE_BUSY)
            finally:
                other.rollback()
        self.assert_rolled_back_and_recoverable()

    def test_real_locked_with_open_reader_rolls_back_entire_run(self):
        def locked_events(run_id):
            # The old and newly inserted runs keep this SELECT cursor active.
            # SQLite refuses DROP TABLE while that table is being read.
            with closing(self.store._db.execute("SELECT * FROM runs")) as cursor:
                self.assertIsNotNone(cursor.fetchone())
                self.store._db.execute("DROP TABLE runs")
            return [event(run_id)]

        with self.assertRaises(sqlite3.Error) as caught:
            self.commit(locked_events)
        self.assertEqual(caught.exception.sqlite_errorcode & 0xff, sqlite3.SQLITE_LOCKED)
        self.assert_rolled_back_and_recoverable()


class SQLiteBackupAndCorruption(unittest.TestCase):
    def test_online_backup_contains_latest_uncheckpointed_wal_commit(self):
        with tempfile.TemporaryDirectory(prefix="netcheck-wal-backup-") as directory:
            path = Path(directory) / "history.sqlite3"
            store = Store(path)
            try:
                # This isolated fixture tests backup of pending WAL pages, not
                # Store's runtime journal policy. Even on affected SQLite there
                # is only one connection to this source, with no concurrent
                # writer or checkpoint; the copied DB is a different file.
                self.assertEqual(store._db.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
                store._db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
                run_id = store.save_run(TS, TS + 1, "test", evaluation(), collections(), {})
                self.assertGreater(Path(str(path) + "-wal").stat().st_size, 32)
                destination = Path(directory) / "complete-backup.sqlite3"
                saved = store.backup(destination, timeout=10)
                self.assertTrue(destination.samefile(saved))
                validate_database(saved)
                with closing(sqlite3.connect(saved.as_uri() + "?mode=ro", uri=True)) as copied:
                    self.assertEqual(copied.execute("PRAGMA quick_check").fetchall(), [("ok",)])
                    self.assertEqual(copied.execute("SELECT id FROM runs").fetchall(), [(run_id,)])
                    self.assertEqual(copied.execute("SELECT COUNT(*) FROM raw_outputs").fetchone()[0], 1)
                saved.unlink()  # No backup/validation handle may survive on Windows.
                self.assertIsNotNone(store.get_run(run_id))
            finally:
                store._db.close()

    def test_corrupt_or_foreign_bytes_are_rejected_without_replacing_original(self):
        with tempfile.TemporaryDirectory(prefix="netcheck-corrupt-") as directory:
            for kind, code in (("notadb", sqlite3.SQLITE_NOTADB), ("corrupt", sqlite3.SQLITE_CORRUPT)):
                with self.subTest(kind=kind):
                    path = Path(directory) / (kind + ".sqlite3")
                    if kind == "notadb":
                        path.write_bytes(b"SYNTHETIC-NOT-A-DATABASE" * 100)
                    else:
                        with closing(sqlite3.connect(path)) as db, db:
                            db.execute("CREATE TABLE synthetic(value TEXT)")
                        content = bytearray(path.read_bytes())
                        content[100] = 0  # Invalid page-1 B-tree type, valid SQLite header.
                        path.write_bytes(content)
                    digest = hashlib.sha256(path.read_bytes()).digest()
                    with self.assertRaises(sqlite3.Error) as caught:
                        Store(path)
                    self.assertEqual(caught.exception.sqlite_errorcode & 0xff, code)
                    self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), digest)
                    path.unlink()  # Keep caught exception alive to detect leaked Windows handles.


if __name__ == "__main__":
    unittest.main()
