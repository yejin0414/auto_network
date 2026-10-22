"""Storage API contracts without equipment, network listeners, or OS keyring."""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nc.config import ConfigStore
from nc.credentials import Credential, CredentialStore
from nc.server import App, make_handler


class StorageApi(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cfg = ConfigStore(self.root / 'config.json')
        self.cfg.save({**self.cfg.get(), 'devices': [{'id': 'bb', 'name': 'Synthetic BB', 'role': 'BB', 'host': '192.0.2.1'}]})
        self.creds = CredentialStore(persistent=False)
        self.creds.set('shared', Credential('synthetic-user', 'synthetic-old'), False)
        self.store = Mock()
        self.store.baseline_times.return_value = {'bb': 1}
        self.store.vrrp_unacked.return_value = 2
        self.store.list_runs.return_value = [{'id': 3}]
        self.engine = SimpleNamespace(
            cfg=self.cfg, creds=self.creds, store=self.store, persistence_lock=threading.RLock(),
            reschedule=Mock(), reconcile_inventory=Mock(return_value=2),
            backup_database=Mock(return_value=self.root / 'backups' / 'synthetic.sqlite3'),
            last_error='', last_report='', report_folder=lambda *_: self.root, running=False,
            start_check=Mock(return_value=True), status=lambda: {'last_error': self.engine.last_error})
        self.app = App(self.engine, self.root)
        self.app.on_config_saved = Mock()

    def settings(self):
        return {'config': {**self.cfg.get(), 'devices': []}, 'credentials': [
            {'profile': 'shared', 'username': 'synthetic-user', 'password': 'synthetic-new', 'remember': False}]}

    def test_inventory_reconciliation_follows_the_successful_combined_commit(self):
        order = []
        def reconcile(cfg):
            self.assertEqual(self.cfg.get()['devices'], [])
            self.assertEqual(json.loads(self.cfg.path.read_text())['devices'], [])
            self.assertEqual(self.creds.get().password, 'synthetic-new')
            order.append('inventory')
            return 2
        self.engine.reconcile_inventory.side_effect = reconcile
        self.app.on_config_saved.side_effect = lambda _: order.append('schedule')
        code, payload = self.app.handle_post('/api/settings', self.settings())
        self.assertEqual(code, 200)
        self.assertNotIn('warning', payload)
        self.assertEqual(order, ['inventory', 'schedule'])
        self.engine.reconcile_inventory.assert_called_once_with(payload['config'])

    def test_cleanup_failure_keeps_committed_settings_and_credentials_with_warning(self):
        self.engine.reconcile_inventory.side_effect = sqlite3.OperationalError('sensitive path marker')
        code, payload = self.app.handle_post('/api/settings', self.settings())
        self.assertEqual(code, 200)
        self.assertTrue(payload['ok'])
        self.assertIn('저장했지만', payload['warning'])
        self.assertNotIn('sensitive path marker', json.dumps(payload))
        self.assertEqual(self.cfg.get()['devices'], [])
        self.assertEqual(self.creds.get().password, 'synthetic-new')
        self.assertEqual(self.engine.last_error, payload['warning'])
        self.app.on_config_saved.assert_called_once()

    def test_failed_configuration_never_reconciles_or_changes_account(self):
        body = self.settings()
        body['config']['schedule']['interval_minutes'] = 1
        self.assertEqual(self.app.handle_post('/api/settings', body)[0], 400)
        self.engine.reconcile_inventory.assert_not_called()
        self.assertEqual(self.creds.get().password, 'synthetic-old')
        with patch.object(self.cfg, 'save', side_effect=PermissionError('synthetic write failure')):
            self.assertEqual(self.app.handle_post('/api/settings', self.settings())[0], 500)
        self.engine.reconcile_inventory.assert_not_called()
        self.assertEqual(self.creds.get().password, 'synthetic-old')

    def test_successful_cleanup_clears_only_its_previous_warning(self):
        self.engine.reconcile_inventory.side_effect = sqlite3.OperationalError('synthetic failure')
        code, payload = self.app.handle_post('/api/settings', self.settings())
        self.assertEqual(code, 200)
        self.assertEqual(self.engine.last_error, payload['warning'])
        self.engine.reconcile_inventory.side_effect = None
        code, payload = self.app.handle_post('/api/settings', self.settings())
        self.assertEqual(code, 200)
        self.assertNotIn('warning', payload)
        self.assertEqual(self.engine.last_error, '')
        self.engine.last_error = 'A separate run could not be saved'
        self.app.handle_post('/api/settings', self.settings())
        self.assertEqual(self.engine.last_error, 'A separate run could not be saved')

    def test_backup_uses_managed_location_and_rejects_extra_arguments(self):
        code, payload = self.app.handle_post('/api/backup', {})
        self.assertEqual(code, 200)
        self.assertEqual(payload, {'ok': True, 'path': str(self.engine.backup_database.return_value)})
        self.engine.backup_database.assert_called_once_with()
        for body in [{'path': '/synthetic/elsewhere'}, {'overwrite': True}]:
            self.assertEqual(self.app.handle_post('/api/backup', body)[0], 400)
        self.assertEqual(self.engine.backup_database.call_count, 1)

    def test_backup_failure_never_claims_success_or_exposes_backend_detail(self):
        for error in [sqlite3.OperationalError('sensitive path marker'), PermissionError('sensitive path marker')]:
            with self.subTest(error=type(error).__name__):
                self.engine.backup_database.side_effect = error
                code, payload = self.app.handle_post('/api/backup', {})
                self.assertEqual(code, 503)
                self.assertNotIn('path', payload)
                self.assertNotIn('sensitive path marker', json.dumps(payload))
                self.assertIn('기존 DB는 유지', payload['error'])
                self.assertTrue(self.engine.last_error)

    def test_engine_persistence_lock_serializes_config_cleanup_and_backup(self):
        self.assertIs(self.app._config_lock, self.engine.persistence_lock)
        entered, release, backup_requested = threading.Event(), threading.Event(), threading.Event()
        def reconcile(_):
            entered.set()
            self.assertTrue(release.wait(5))
            return 2
        def backup():
            backup_requested.set()
            return self.app.handle_post('/api/backup', {})
        self.engine.reconcile_inventory.side_effect = reconcile
        with ThreadPoolExecutor(max_workers=2) as pool:
            save = pool.submit(self.app.handle_post, '/api/settings', self.settings())
            self.assertTrue(entered.wait(5))
            pending_backup = pool.submit(backup)
            self.assertTrue(backup_requested.wait(5))
            self.engine.backup_database.assert_not_called()
            release.set()
            self.assertEqual(save.result(5)[0], 200)
            self.assertEqual(pending_backup.result(5)[0], 200)

    def test_shutdown_rejects_backup_reset_and_ack_without_storage_changes(self):
        self.app.begin_shutdown()
        for path in ['/api/backup', '/api/baseline/reset', '/api/vrrp/ack']:
            self.assertEqual(self.app.handle_post(path, {})[0], 503)
        self.engine.backup_database.assert_not_called()
        self.store.reset_baseline.assert_not_called()
        self.store.ack_vrrp.assert_not_called()

    def test_baseline_and_ack_storage_failure_are_safe_errors(self):
        self.store.reset_baseline.side_effect = sqlite3.OperationalError('sensitive path marker')
        self.store.ack_vrrp.side_effect = PermissionError('sensitive path marker')
        for path in ['/api/baseline/reset', '/api/vrrp/ack']:
            code, payload = self.app.handle_post(path, {'device': 'bb', 'recheck': True})
            self.assertEqual(code, 503)
            self.assertNotIn('sensitive path marker', json.dumps(payload))
        self.engine.start_check.assert_not_called()

    def test_state_retains_configuration_and_error_when_database_cannot_be_read(self):
        self.store.baseline_times.side_effect = sqlite3.DatabaseError('sensitive path marker')
        self.engine.last_error = 'Earlier write did not complete'
        code, payload = self.app.handle_get('/api/state', {})
        self.assertEqual(code, 200)
        self.assertEqual(payload['config']['devices'][0]['id'], 'bb')
        self.assertTrue(payload['storage_error'])
        self.assertEqual(payload['engine']['last_error'], 'Earlier write did not complete')
        self.assertIsNone(payload['vrrp_unacked'])
        self.assertIsNone(payload['latest_run_id'])
        self.assertNotIn('sensitive path marker', json.dumps(payload))
        self.store.baseline_times.side_effect = None
        self.assertEqual(self.app.state()['storage_error'], '')

    def test_record_api_and_report_download_read_errors_return_503(self):
        self.store.get_run.side_effect = sqlite3.DatabaseError('sensitive path marker')
        self.store.get_report_snapshot.side_effect = sqlite3.DatabaseError('sensitive path marker')
        self.assertEqual(self.app.handle_get('/api/run', {})[0], 503)
        for path in ['/report', '/report.xlsx']:
            handler = object.__new__(make_handler(self.app))
            handler.path = path + '?t=' + self.app.token
            handler.headers = {'Host': 'localhost:8875'}
            handler._send = Mock()
            handler.do_GET()
            self.assertEqual(handler._send.call_args.args[0], 503)
            self.assertNotIn('sensitive path marker', json.dumps(handler._send.call_args.args[1]))


if __name__ == '__main__':
    unittest.main()
