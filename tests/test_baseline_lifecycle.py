"""Inventory lifetimes and Engine persistence use temporary SQLite and fake collection."""
import copy
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nc.collector import DeviceCollection
from nc.config import ConfigError, ConfigStore, validate
from nc.engine import Engine
from nc.store import Store


TS = time.time() - 60
DEVICE = {'id': 'bb', 'name': 'Synthetic BB', 'role': 'BB', 'host': '192.0.2.1'}


class InventoryEpochs(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = ConfigStore(Path(temp.name) / 'config.json')
        self.initial = self.config.save({'devices': [DEVICE]})
        self.epoch = self.initial['_baseline_epochs']['bb']

    def test_client_cannot_rewrite_epoch_and_display_enable_changes_preserve_it(self):
        cfg = copy.deepcopy(self.initial)
        cfg['_baseline_epochs'] = {'bb': '0' * 32}
        cfg['devices'][0].update(name='Renamed', enabled=False, cluster_primary=True)
        result = self.config.save(cfg)
        self.assertEqual(result['_baseline_epochs']['bb'], self.epoch)
        self.assertEqual(ConfigStore(self.config.path).get(), result)

    def test_identity_replacement_and_delete_readd_receive_new_epochs(self):
        for key, value in [('host', '192.0.2.2'), ('port', 2222), ('device_type', 'hp_comware')]:
            old = self.config.get()
            changed = copy.deepcopy(old)
            changed['devices'][0][key] = value
            result = self.config.save(changed)
            self.assertNotEqual(result['_baseline_epochs'], old['_baseline_epochs'])
        self.config.save({'devices': []})
        self.assertEqual(self.config.get()['_baseline_epochs'], {})
        self.assertNotEqual(self.config.save(self.initial)['_baseline_epochs']['bb'], self.epoch)

    def test_failed_config_write_preserves_file_and_epoch(self):
        before = self.config.path.read_bytes()
        with patch('nc.config.Path.replace', side_effect=OSError('synthetic write failure')):
            with self.assertRaises(OSError):
                self.config.save({'devices': []})
        self.assertEqual(self.config.get(), self.initial)
        self.assertEqual(self.config.path.read_bytes(), before)

    def test_reserved_cluster_id_is_rejected(self):
        with self.assertRaises(ConfigError):
            validate({'devices': [{**DEVICE, 'id': '__cluster__'}]})

    def test_offline_config_identity_edit_receives_a_new_epoch(self):
        changed = copy.deepcopy(self.initial)
        changed['devices'][0]['host'] = '192.0.2.20'
        self.config.path.write_text(json.dumps(changed), encoding='utf-8')
        reloaded = ConfigStore(self.config.path).get()
        self.assertNotEqual(reloaded['_baseline_epochs']['bb'], self.epoch)


class EnginePersistence(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.cfg = ConfigStore(self.folder / 'config.json')
        self.initial = self.cfg.save({'devices': [DEVICE], 'report': {'excel_auto': False, 'notify': False}})
        self.store = Store(self.folder / 'history.sqlite3')
        self.addCleanup(self.store._db.close)
        self.engine = Engine(self.cfg, self.store, SimpleNamespace(get=lambda _: None), SimpleNamespace())
        self.engine.reconcile_inventory()
        self.store.save_baselines({'bb': {'slots': ['old']}})
        self.seen = []
        def evaluate(cfg, collections, clusters, baselines, previous, now):
            self.seen.append((baselines, previous))
            devices = {d['id']: {'name': d['name'], 'status': 'ok', 'metrics': {'uptime': 100, 'vrrp': {'Vlan1/1': 'Master'}},
                                'checks': []} for d in cfg['devices']}
            return {'summary': {'overall': 'ok', 'counts': {'ok': len(devices)}}, 'devices': devices}, {'bb': {'slots': ['new']}}
        for name, value in [('nc.engine.evaluate_run', evaluate),
                            ('nc.engine.collect_device', lambda driver, d, *a, **kw: DeviceCollection(d['id'], True))]:
            patched = patch(name, side_effect=value)
            patched.start()
            self.addCleanup(patched.stop)

    def test_delete_while_collecting_cannot_recreate_baseline_and_keeps_history(self):
        def delete(_):
            self.cfg.save({**self.initial, 'devices': []})
            self.engine.reconcile_inventory()
        self.engine.driver.begin_run = delete
        run_id = self.engine.run_blocking(now=TS)
        self.assertIsNotNone(run_id, self.engine.last_error)
        self.assertEqual(self.store.baselines(), {})
        self.assertIn('bb', self.store.get_run(run_id)['devices'])

    def test_delete_readd_during_database_outage_is_detected_after_restart(self):
        def replace(_):
            # Both config writes succeed while DB reconciliation is unavailable.
            self.cfg.save({**self.initial, 'devices': []})
            self.cfg.save(self.initial)
            self.engine.cfg = ConfigStore(self.cfg.path)
        self.engine.driver.begin_run = replace
        first = self.engine.run_blocking(now=TS)
        self.assertIsNotNone(first, self.engine.last_error)
        self.assertEqual(self.store.baselines(), {})
        self.assertNotEqual(self.engine.cfg.get()['_baseline_epochs'], self.initial['_baseline_epochs'])
        del self.engine.driver.begin_run
        second = self.engine.run_blocking(now=TS + 1000)
        self.assertIsNotNone(second, self.engine.last_error)
        self.assertEqual(self.seen[-1], ({}, {}), 'old device uptime must not become the new device baseline')
        self.assertEqual(self.store.baselines()['bb'], {'slots': ['new']})
        self.assertEqual(self.store.list_vrrp(), [])

    def test_manual_reset_during_collection_cannot_be_undone_by_old_run(self):
        self.engine.driver.begin_run = lambda _: self.store.reset_baseline('bb')
        self.assertIsNotNone(self.engine.run_blocking(now=TS), self.engine.last_error)
        self.assertEqual(self.store.baselines(), {})

    def test_late_sqlite_failure_does_not_publish_any_run_or_send_completion(self):
        self.store._db.execute("CREATE TRIGGER synthetic_failure BEFORE INSERT ON baselines BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        self.store._db.commit()
        with patch.object(self.engine, '_after_run') as after:
            self.assertIsNone(self.engine.run_blocking(now=TS))
            after.assert_not_called()
        self.assertIn('저장하지 못했습니다', self.engine.last_error)
        self.assertFalse(self.engine.running)
        self.assertEqual(self.store.list_runs(), [])
        self.assertEqual(self.store.baselines()['bb'], {'slots': ['old']})
        self.store._db.execute('DROP TRIGGER synthetic_failure')
        self.store._db.commit()
        self.assertIsNotNone(self.engine.run_blocking(now=TS + 1000), self.engine.last_error)

    def test_backup_failure_keeps_successful_run_and_skips_retention(self):
        with patch.object(self.store, 'backup_if_due', side_effect=OSError('synthetic full backup disk')), \
                patch.object(self.store, 'prune') as prune:
            run_id = self.engine.run_blocking(now=TS)
        self.assertIsNotNone(run_id)
        self.assertIsNotNone(self.store.get_run(run_id))
        prune.assert_not_called()
        self.assertIn('점검은 저장했습니다', self.engine.last_error)

    def test_prune_failure_does_not_turn_committed_run_into_failure(self):
        with patch.object(self.store, 'prune', side_effect=sqlite3.OperationalError('synthetic locked')):
            run_id = self.engine.run_blocking(now=TS)
        self.assertIsNotNone(run_id)
        self.assertIsNotNone(self.store.get_run(run_id))
        self.assertIn('정리를 완료하지 못했습니다', self.engine.last_error)


if __name__ == '__main__':
    unittest.main()
