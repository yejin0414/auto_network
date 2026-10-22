"""Maintenance never discovers credentials, starts a scheduler or contacts a device."""
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from nc.db_maintenance import restore_database
from nc.store import Store, validate_database


class DatabaseRestore(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.source = self.folder / 'source.sqlite3'
        store = Store(self.source)
        try:
            store.save_baselines({'synthetic': {'slots': ['1']}})
            self.backup = store.backup(self.folder / 'backup.sqlite3')
        finally:
            store._db.close()
        self.digest = hashlib.sha256(self.backup.read_bytes()).hexdigest()
        self.destination = self.folder / 'restored.sqlite3'

    def assert_source_intact(self):
        self.assertEqual(hashlib.sha256(self.backup.read_bytes()).hexdigest(), self.digest)
        self.assertFalse(list(self.folder.glob('.netcheck-restore-*')))

    def test_restore_is_valid_standalone_database_and_existing_target_is_never_replaced(self):
        self.assertEqual(restore_database(self.backup, self.destination), self.destination.resolve())
        validate_database(self.destination)
        db = sqlite3.connect(self.destination)
        try:
            row = db.execute('SELECT data FROM baselines').fetchone()[0]
            self.assertEqual(json.loads(row), {'slots': ['1']})
        finally:
            db.close()
        before = self.destination.read_bytes()
        with self.assertRaises(FileExistsError):
            restore_database(self.backup, self.destination)
        self.assertEqual(self.destination.read_bytes(), before)
        self.assert_source_intact()

    def test_live_sidecar_or_reserved_filename_is_rejected(self):
        for suffix in ('-wal', '-shm', '-journal'):
            sidecar = Path(str(self.destination) + suffix)
            sidecar.write_bytes(b'synthetic sidecar')
            with self.assertRaises(FileExistsError):
                restore_database(self.backup, self.destination)
            self.assertEqual(sidecar.read_bytes(), b'synthetic sidecar')
            sidecar.unlink()
            with self.assertRaises(FileExistsError):
                restore_database(self.backup, sidecar)
        self.assert_source_intact()

    def test_samefile_hardlink_and_dangling_symlink_are_not_overwritten(self):
        with self.assertRaises(FileExistsError):
            restore_database(self.backup, self.backup)
        os.link(self.backup, self.destination)
        with self.assertRaises(FileExistsError):
            restore_database(self.backup, self.destination)
        self.destination.unlink()
        try:
            self.destination.symlink_to(self.folder / 'missing')
        except OSError:
            # Windows runners can disallow symlinks without administrator rights.
            return
        with self.assertRaises(FileExistsError):
            restore_database(self.backup, self.destination)
        self.assertTrue(self.destination.is_symlink())
        self.destination.unlink()
        self.assert_source_intact()

    def test_wrong_schema_and_corrupt_backup_are_rejected_without_target(self):
        other = self.folder / 'other.sqlite3'
        db = sqlite3.connect(other)
        db.execute('CREATE TABLE unrelated(value TEXT)')
        db.close()
        for source in (other, self.folder / 'broken.sqlite3'):
            if source != other:
                source.write_bytes(b'not a database')
            before = source.read_bytes()
            with self.assertRaises(sqlite3.Error):
                restore_database(source, self.destination)
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse(self.destination.exists())
        self.assert_source_intact()

    def test_publish_failure_cleans_temporary_database_and_preserves_source(self):
        with patch('nc.db_maintenance.os.link', side_effect=PermissionError('synthetic failure')):
            with self.assertRaises(PermissionError):
                restore_database(self.backup, self.destination)
        self.assertFalse(self.destination.exists())
        self.assert_source_intact()

    def test_cli_restore_and_verify_exit_before_any_runtime_setup(self):
        forbidden = AssertionError('maintenance must not initialize runtime')
        with patch('app.CredentialStore', side_effect=forbidden), patch('app.Engine', side_effect=forbidden), \
                patch('app.base_dirs', side_effect=forbidden), patch('app.message_box'), patch('builtins.print'):
            with patch.object(sys, 'argv', ['app.py', '--restore-db', str(self.backup), '--restore-to', str(self.destination)]):
                self.assertEqual(app.main(), 0)
            with patch.object(sys, 'argv', ['app.py', '--verify-db', str(self.destination)]):
                self.assertEqual(app.main(), 0)
            with patch.object(sys, 'argv', ['app.py', '--restore-db', str(self.backup), '--restore-to', str(self.destination)]):
                self.assertEqual(app.main(), 1)
        self.assert_source_intact()


if __name__ == '__main__':
    unittest.main()
