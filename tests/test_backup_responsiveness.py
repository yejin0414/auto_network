"""A slow backup must not hold the application's settings or query locks."""
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from nc.config import ConfigStore
from nc.credentials import CredentialStore
from nc.engine import Engine
from nc.server import App
from nc.store import Store, _validate_connection, validate_database


class BackupResponsiveness(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='netcheck-backup-responsive-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store(self.root / 'history.sqlite3')
        self.addCleanup(self.store._db.close)
        cfg = ConfigStore(self.root / 'config.json')
        self.engine = Engine(cfg, self.store, CredentialStore(persistent=False), object(), demo=True)
        self.app = App(self.engine, self.root)
        self.store.save_baselines({'synthetic': {'slots': ['1']}})

    def during_validation(self, backup, foreground):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def slow_validation(db, deadline):
            entered.set()
            if not release.wait(5):
                raise AssertionError('test gate was not released')
            _validate_connection(db, deadline)
        def foreground_work():
            try:
                return foreground()
            finally:
                finished.set()
        with patch('nc.store._validate_connection', side_effect=slow_validation), ThreadPoolExecutor(max_workers=2) as pool:
            pending_backup = pool.submit(backup)
            try:
                self.assertTrue(entered.wait(5))
                pending_foreground = pool.submit(foreground_work)
                # The correctness condition is ordering, not a microbenchmark:
                # foreground work must finish while validation remains gated.
                responsive = finished.wait(2)
            finally:
                release.set()
            result = pending_backup.result(5)
            foreground_result = pending_foreground.result(5)
        self.assertTrue(responsive, 'foreground operation waited for backup validation')
        return result, foreground_result

    def test_read_and_atomic_write_continue_while_backup_is_being_validated(self):
        def read_and_write():
            self.assertEqual(self.store.baselines()['synthetic']['slots'], ['1'])
            return self.store.commit_run(1, 2, 'synthetic',
                {'summary': {'overall': 'ok'}, 'devices': {}}, {}, {},
                baseline_updates={'synthetic': {'slots': ['1', '2']}})
        saved, run_id = self.during_validation(self.store.backup, read_and_write)
        self.assertEqual(self.store.get_run(run_id)['trigger'], 'synthetic')
        validate_database(saved)
        db = sqlite3.connect(saved)
        try:
            # The copy completed before the foreground transaction. Validation
            # must not turn it into a mixture of the two snapshots.
            self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)
        finally:
            db.close()

    def test_state_and_shutdown_remain_responsive_after_backup_was_accepted(self):
        def state_and_shutdown():
            state = self.app.state()
            self.app.begin_shutdown()
            self.assertEqual(self.app.handle_post('/api/backup', {})[0], 503)
            return state
        response, state = self.during_validation(lambda: self.app.handle_post('/api/backup', {}), state_and_shutdown)
        self.assertEqual(response[0], 200)
        self.assertEqual(state['baseline_times'].keys(), {'synthetic'})
        self.assertEqual(state['storage_error'], '')

    def test_atomic_writer_can_commit_between_online_backup_steps(self):
        entered, release, committed = threading.Event(), threading.Event(), threading.Event()
        real_connect = sqlite3.connect
        class PausedConnection(sqlite3.Connection):
            def backup(connection, target, **kwargs):
                original_progress = kwargs.get('progress')
                def pause_after_step(status, remaining, total):
                    if original_progress:
                        original_progress(status, remaining, total)
                    if remaining and not entered.is_set():
                        entered.set()
                        if not release.wait(5):
                            raise AssertionError('backup step gate was not released')
                return super(PausedConnection, connection).backup(target, **dict(kwargs, progress=pause_after_step))
        def connection(*args, **kwargs):
            return real_connect(*args, **dict(kwargs, factory=PausedConnection))
        # Enough real pages for more than one backup step, without a large test.
        with self.store._db:
            self.store._db.execute('CREATE TABLE synthetic_payload(value BLOB)')
            self.store._db.executemany('INSERT INTO synthetic_payload VALUES (?)', [(b'x' * 8192,)] * 160)
        def write():
            try:
                return self.store.commit_run(3, 4, 'during-backup',
                    {'summary': {'overall': 'ok'}, 'devices': {}}, {}, {},
                    baseline_updates={'synthetic': {'slots': ['new']}})
            finally:
                committed.set()
        with patch('nc.store.sqlite3.connect', side_effect=connection), ThreadPoolExecutor(max_workers=2) as pool:
            copying = pool.submit(self.store.backup)
            try:
                self.assertTrue(entered.wait(5))
                writing = pool.submit(write)
                responsive = committed.wait(2)
            finally:
                release.set()
            saved = copying.result(5)
            run_id = writing.result(5)
        self.assertTrue(responsive, 'writer waited for the whole backup')
        validate_database(saved)
        db = sqlite3.connect(saved)
        try:
            has_run = db.execute('SELECT COUNT(*) FROM runs WHERE id=?', (run_id,)).fetchone()[0]
            baseline = db.execute("SELECT data FROM baselines WHERE device_id='synthetic'").fetchone()[0]
            # A concurrent backup may represent either consistent snapshot.
            self.assertEqual('new' in baseline, bool(has_run))
        finally:
            db.close()

    def test_custom_backup_rejects_sidecar_names_and_late_sidecar_creation(self):
        for suffix in ('-wal', '-shm', '-journal'):
            with self.subTest(suffix=suffix), self.assertRaises(FileExistsError):
                self.store.backup(self.root / ('other.sqlite3' + suffix))
        destination = self.root / 'new-backup.sqlite3'
        sidecar = Path(str(destination) + '-wal')
        def raced_sidecar(db, deadline):
            _validate_connection(db, deadline)
            sidecar.write_bytes(b'preserve competing sidecar')
        with patch('nc.store._validate_connection', side_effect=raced_sidecar), self.assertRaises(FileExistsError):
            self.store.backup(destination)
        self.assertFalse(destination.exists())
        self.assertEqual(sidecar.read_bytes(), b'preserve competing sidecar')


if __name__ == '__main__':
    unittest.main()
