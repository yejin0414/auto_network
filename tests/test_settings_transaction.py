"""Settings/account transactions use temporary files and a fake keyring only."""
from __future__ import annotations

import copy
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nc.config import ConfigStore
from nc.credentials import Credential, CredentialError, CredentialStore, SERVICE
from nc.server import App


class MemoryKeyring:
    def __init__(self):
        self.values = {}
        self.calls = []
        self.after_write = None

    def get_password(self, service, profile):
        self.calls.append(('get', service, profile))
        return self.values.get(profile)

    def set_password(self, service, profile, raw):
        self.calls.append(('set', service, profile))
        self.values[profile] = raw
        if self.after_write:
            self.after_write('set', profile)

    def delete_password(self, service, profile):
        self.calls.append(('delete', service, profile))
        del self.values[profile]
        if self.after_write:
            self.after_write('delete', profile)


def change(username='new-user', password='synthetic-new-password', remember=True):
    return {'profile': 'shared', 'username': username, 'password': password, 'remember': remember}


class SettingsTransaction(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.backend = MemoryKeyring()
        backend_patch = patch('nc.credentials._keyring', return_value=self.backend)
        backend_patch.start()
        self.addCleanup(backend_patch.stop)
        self.creds = CredentialStore()
        self.creds.apply([change('old-user', 'synthetic-old-password')])
        self.cfg = ConfigStore(self.folder / 'config.json')
        self.cfg.save({**self.cfg.get(), 'site_name': 'old-site'})
        store = Mock()
        store.baseline_times.return_value = {}
        store.vrrp_unacked.return_value = 0
        store.list_runs.return_value = []
        self.engine = SimpleNamespace(cfg=self.cfg, creds=self.creds, reschedule=Mock(), store=store,
                                      report_folder=lambda cfg: self.folder, last_report=None, status=lambda: {})
        self.app = App(self.engine, self.folder)
        self.app.on_config_saved = Mock()
        self.old_cfg = self.cfg.get()
        self.old_file = self.cfg.path.read_bytes()
        self.old_keyring = dict(self.backend.values)
        self.backend.calls.clear()

    def request(self, *, config=None, changes=None):
        return self.app.handle_post('/api/settings', {
            'config': config if config is not None else {**self.old_cfg, 'site_name': 'new-site'},
            'credentials': changes if changes is not None else [change()],
        })

    def assert_original(self):
        self.assertEqual(self.cfg.get(), self.old_cfg)
        self.assertEqual(self.cfg.path.read_bytes(), self.old_file)
        self.assertEqual(self.creds.get(), Credential('old-user', 'synthetic-old-password'))
        self.assertEqual(self.backend.values, self.old_keyring)
        self.assertTrue(self.creds.status()['shared']['remembered'])
        self.engine.reschedule.assert_not_called()
        self.app.on_config_saved.assert_not_called()

    def test_invalid_config_is_rejected_before_any_account_access(self):
        cfg = copy.deepcopy(self.old_cfg)
        cfg['thresholds']['cpu_warn'] = 90
        code, payload = self.request(config=cfg)
        self.assertEqual(code, 400)
        self.assertNotIn('synthetic-new-password', json.dumps(payload))
        self.assertEqual(self.backend.calls, [])
        self.assert_original()

    def test_invalid_accounts_reject_entire_request_without_backend_access(self):
        for changes in [[change('different-user', '')], [change(), change()],
                        [{'profile': 'unknown'}], [dict(change(), remember='false')], {}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.request(changes=changes)[0], 400)
                self.assertEqual(self.backend.calls, [])
                self.assert_original()

    def test_secret_fields_are_not_written_or_echoed_as_configuration(self):
        for secret_cfg in [{'password': 'synthetic-secret-marker'},
                           {'report': {'credentials': {'password': 'synthetic-secret-marker'}}},
                           {'ssh': {'connect_timeout': 'synthetic-secret-marker'}}]:
            with self.subTest(secret_cfg=secret_cfg):
                cfg = {**self.old_cfg, **secret_cfg}
                code, payload = self.request(config=cfg)
                self.assertEqual(code, 400)
                self.assertNotIn('synthetic-secret-marker', json.dumps(payload))
                self.assertEqual(self.backend.calls, [])
                self.assert_original()

    def test_success_commits_both_and_exposes_no_password(self):
        code, payload = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(self.cfg.get()['site_name'], 'new-site')
        self.assertEqual(json.loads(self.cfg.path.read_text())['site_name'], 'new-site')
        self.assertEqual(self.creds.get().username, 'new-user')
        self.assertEqual(json.loads(self.backend.values['shared'])['p'], 'synthetic-new-password')
        self.assertNotIn('synthetic-new-password', json.dumps(payload))
        self.assertNotIn('synthetic-new-password', self.cfg.path.read_text())
        self.engine.reschedule.assert_called_once()
        self.app.on_config_saved.assert_called_once()

    def test_config_replace_failure_restores_keyring_memory_and_restarted_account(self):
        with patch('nc.config.Path.replace', side_effect=PermissionError('synthetic-secret-marker')):
            code, payload = self.request()
        self.assertEqual(code, 500)
        self.assertNotIn('synthetic-secret-marker', json.dumps(payload))
        self.assert_original()
        self.assertEqual(list(self.folder.glob('*.tmp')), [])
        reopened = CredentialStore()
        reopened.load_saved(['shared'])
        self.assertEqual(reopened.get(), self.creds.get())

    def test_keyring_set_that_mutates_then_raises_is_compensated(self):
        def fail_once(*_):
            self.backend.after_write = None
            raise RuntimeError('synthetic-secret-marker')
        self.backend.after_write = fail_once
        code, payload = self.request()
        self.assertEqual(code, 503)
        self.assertFalse(payload['rollback_failed'])
        self.assertNotIn('synthetic-secret-marker', json.dumps(payload))
        self.assert_original()

    def test_remember_off_and_clear_delete_failures_restore_every_saved_profile(self):
        self.backend.values.update(backbone='legacy-backbone', aruba='legacy-aruba')
        self.old_keyring = dict(self.backend.values)
        for update in [change('old-user', '', False), {'profile': 'shared', 'clear': True}]:
            with self.subTest(update=update):
                def fail_once(operation, profile):
                    if profile == 'aruba':
                        self.backend.after_write = None
                        raise PermissionError('synthetic-secret-marker')
                self.backend.after_write = fail_once
                code, payload = self.app.handle_post('/api/credentials', update)
                self.assertEqual(code, 503)
                self.assertFalse(payload['rollback_failed'])
                self.assert_original()

    def test_blank_password_preserves_password_and_allows_remember_change(self):
        self.backend.values.update(backbone='legacy-backbone', aruba='legacy-aruba')
        code, _ = self.request(changes=[change('old-user', '', False)])
        self.assertEqual(code, 200)
        self.assertEqual(self.creds.get(), Credential('old-user', 'synthetic-old-password'))
        self.assertFalse(self.creds.status()['shared']['remembered'])
        self.assertEqual(self.backend.values, {})
        restarted = CredentialStore()
        restarted.load_saved(['shared'])
        self.assertIsNone(restarted.get())
        self.assertEqual(self.app.handle_post('/api/credentials', change('old-user', '', True))[0], 200)
        self.assertEqual(json.loads(self.backend.values['shared'])['p'], 'synthetic-old-password')

    def test_clear_removes_memory_and_legacy_accounts(self):
        self.backend.values.update(backbone='legacy-backbone', aruba='legacy-aruba')
        self.assertEqual(self.app.handle_post('/api/credentials', {'profile': 'shared', 'clear': True})[0], 200)
        self.assertIsNone(self.creds.get())
        self.assertEqual(self.backend.values, {})
        self.assertEqual(self.cfg.path.read_bytes(), self.old_file)
        self.assertEqual(self.app.handle_post('/api/credentials', {'profile': 'shared', 'clear': True})[0], 200)

    def test_rollback_failure_is_visible_even_without_a_memory_account(self):
        self.creds.clear('shared')
        def fail_every_write(*_):
            raise RuntimeError('synthetic-secret-marker')
        self.backend.after_write = fail_every_write
        code, payload = self.request()
        self.assertEqual(code, 503)
        self.assertTrue(payload['rollback_failed'])
        self.assertIsNone(self.creds.get())
        self.assertTrue(self.app.state()['credential_storage_uncertain'])
        self.assertEqual(self.cfg.get(), self.old_cfg)
        self.assertNotIn('synthetic-secret-marker', json.dumps(payload))
        self.backend.after_write = None
        self.assertEqual(self.app.handle_post('/api/credentials', {'profile': 'shared', 'clear': True})[0], 200)
        self.assertFalse(self.app.state()['credential_storage_uncertain'])

    def test_read_failure_and_unavailable_keyring_do_not_change_settings(self):
        with patch.object(self.backend, 'get_password', side_effect=PermissionError('synthetic-secret-marker')):
            code, payload = self.request()
            self.assertEqual(code, 503)
            self.assertNotIn('synthetic-secret-marker', json.dumps(payload))
        self.assert_original()
        with patch('nc.credentials._keyring', return_value=None):
            self.assertEqual(self.request()[0], 503)
        self.assert_original()

    def test_concurrent_saves_and_state_observer_see_complete_pairs(self):
        entered, release, observer_started = threading.Event(), threading.Event(), threading.Event()
        saved = self.cfg.save
        def gated_save(cfg):
            if cfg['site_name'] == 'new-site':
                entered.set()
                self.assertTrue(release.wait(5))
            return saved(cfg)
        def observe():
            observer_started.set()
            return self.app.state()
        with patch.object(self.cfg, 'save', side_effect=gated_save), ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(self.request)
            self.assertTrue(entered.wait(5))
            observer = pool.submit(observe)
            self.assertTrue(observer_started.wait(5))
            second = pool.submit(self.request, config={**self.old_cfg, 'site_name': 'last-site'},
                                 changes=[change('last-user')])
            self.assertFalse(observer.done())
            release.set()
            self.assertEqual(first.result(5)[0], 200)
            self.assertEqual(second.result(5)[0], 200)
            state = observer.result(5)
        self.assertIn((state['config']['site_name'], state['credentials']['shared']['username']),
                      [('new-site', 'new-user'), ('last-site', 'last-user')])
        self.assertEqual(self.cfg.get()['site_name'], 'last-site')
        self.assertEqual(self.creds.get().username, 'last-user')
        self.assertEqual(json.loads(self.backend.values['shared'])['u'], 'last-user')

    def test_shutdown_rejects_all_account_and_config_writes(self):
        self.app.begin_shutdown()
        self.assertEqual(self.request()[0], 503)
        self.assertEqual(self.app.handle_post('/api/credentials', {'profile': 'shared', 'clear': True})[0], 503)
        self.assertEqual(self.app.handle_post('/api/config', self.old_cfg)[0], 503)
        self.assert_original()

    def test_legacy_account_is_migrated_and_get_returns_an_independent_copy(self):
        self.backend.values = {'backbone': json.dumps({'u': 'legacy-user', 'p': 'synthetic-legacy-password'})}
        store = CredentialStore()
        store.load_saved(['shared'])
        self.assertEqual(set(self.backend.values), {'shared'})
        self.assertEqual(json.loads(self.backend.values['shared'])['u'], 'legacy-user')
        copy_of_credential = store.get()
        copy_of_credential.password = 'changed-by-caller'
        self.assertEqual(store.get().password, 'synthetic-legacy-password')

    def test_ephemeral_store_never_accesses_keyring(self):
        with patch('nc.credentials._keyring', side_effect=AssertionError('real keyring forbidden')):
            store = CredentialStore(persistent=False)
            store.apply([change(remember=False)])
            with self.assertRaises(CredentialError):
                store.apply([change(remember=True)])
            self.assertEqual(store.get().password, 'synthetic-new-password')
            store.clear('shared')
            self.assertIsNone(store.get())

    def test_cleanup_cannot_turn_success_into_failure_or_hide_write_error(self):
        with patch('nc.config.Path.unlink', side_effect=PermissionError('cleanup failure')) as unlink:
            self.assertEqual(self.request()[0], 200)
            unlink.assert_not_called()
        self.assertEqual(self.cfg.get()['site_name'], 'new-site')
        self.assertEqual(self.creds.get().username, 'new-user')
        with patch('nc.config.Path.replace', side_effect=PermissionError('primary write failure')), \
                patch('nc.config.Path.unlink', side_effect=PermissionError('cleanup failure')):
            with self.assertRaisesRegex(PermissionError, 'primary write failure'):
                self.cfg.save(self.old_cfg)
        self.assertEqual(self.cfg.get()['site_name'], 'new-site')

    def test_postcommit_callback_failure_is_not_reported_as_save_failure(self):
        self.app.on_config_saved.side_effect = RuntimeError('synthetic callback failure')
        with self.assertLogs('netcheck', level='ERROR'):
            self.assertEqual(self.request()[0], 200)
        self.assertEqual(self.cfg.get()['site_name'], 'new-site')
        self.assertEqual(self.creds.get().username, 'new-user')


if __name__ == '__main__':
    unittest.main()
