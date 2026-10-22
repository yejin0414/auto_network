"""Offline package maintenance must never initialize the application runtime."""
import contextlib
import hashlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from nc.store import Store


class BackupCLI(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='netcheck-cli-backup-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source.sqlite3'
        store = Store(self.source)
        store.save_baselines({'synthetic': {'slots': ['1', '2']}})
        store._db.close()

    def invoke(self, *args):
        forbidden = AssertionError('offline maintenance initialized runtime')
        with patch.object(sys, 'argv', ['app.py', *map(str, args)]), \
                patch('app.base_dirs', side_effect=forbidden), \
                patch('app.CredentialStore', side_effect=forbidden), \
                patch('app.NetmikoDriver', side_effect=forbidden), \
                patch('app.Engine', side_effect=forbidden), patch('app.message_box'), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return app.main()

    def test_export_transfer_verify_and_restore_without_original_database(self):
        package = self.root / 'export.ncbak'
        self.assertEqual(self.invoke('--export-backup', self.source, '--export-to', package, '--db-timeout', '30'), 0)
        external = self.root / 'isolated-external' / 'received.ncbak'
        external.parent.mkdir()
        shutil.copyfile(package, external)
        self.assertEqual(hashlib.sha256(package.read_bytes()).digest(), hashlib.sha256(external.read_bytes()).digest())
        self.source.rename(self.root / 'original-unavailable.sqlite3')
        package.unlink()
        self.assertEqual(self.invoke('--verify-backup', external), 0)
        destination = self.root / 'new-install' / 'recovered.sqlite3'
        self.assertEqual(self.invoke('--restore-backup', external, '--restore-to', destination), 0)
        restored = Store(destination)
        try:
            self.assertEqual(restored.baselines()['synthetic'], {'slots': ['1', '2']})
        finally:
            restored._db.close()
        before = destination.read_bytes()
        self.assertEqual(self.invoke('--restore-backup', external, '--restore-to', destination), 1)
        self.assertEqual(destination.read_bytes(), before)

    def test_corrupt_package_is_safe_failure_and_never_creates_destination(self):
        invalid = self.root / 'broken.ncbak'
        invalid.write_bytes(b'Synthetic truncated transfer')
        destination = self.root / 'recovered.sqlite3'
        self.assertEqual(self.invoke('--verify-backup', invalid), 1)
        self.assertEqual(self.invoke('--restore-backup', invalid, '--restore-to', destination), 1)
        self.assertFalse(destination.exists())
        self.assertEqual(invalid.read_bytes(), b'Synthetic truncated transfer')

    def test_missing_conflicting_destinations_and_invalid_timeouts_are_rejected(self):
        cases = [('--export-backup', self.source), ('--export-to', self.root / 'missing.ncbak'),
                 ('--restore-backup', self.source), ('--verify-backup', self.source, '--restore-to', self.root / 'new'),
                 ('--verify-db', self.source, '--verify-backup', self.source)]
        cases += [('--verify-db', self.source, '--db-timeout', value) for value in ('0', '-1', 'nan', 'inf')]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit) as caught:
                self.invoke(*arguments)
            self.assertEqual(caught.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
