"""Disposable SQLite lifecycle and backup tests; no external services or devices."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from nc.collector import CmdResult, DeviceCollection
from nc.store import Store, validate_database


TS = 1700000000


def configuration():
    return {"devices": [
        {"id": "bb", "host": "192.0.2.1", "role": "BB", "port": 22, "protocol": "ssh", "device_type": "hp_comware"},
        {"id": "w1", "host": "192.0.2.2", "role": "WLC", "port": 22, "protocol": "ssh", "cluster": "synthetic"},
        {"id": "w2", "host": "192.0.2.3", "role": "WLC", "port": 22, "protocol": "ssh", "cluster": "synthetic"},
    ], "_baseline_epochs": {"bb": "bb-first", "w1": "w1-first", "w2": "w2-first"}}


def evaluation(epoch="bb-first"):
    return {"summary": {"overall": "ok", "counts": {"ok": 1}}, "devices": {
        "bb": {"status": "ok", "metrics": {"uptime": 100}, "checks": [], "baseline_epoch": epoch}}}


def collections():
    result = CmdResult("version", "Version", "display version", "Synthetic output", True)
    return {"bb": DeviceCollection("bb", True, results={"version": result})}


def events(run_id):
    return [(TS + 10, run_id, "bb", "warn", "new", "Synthetic event")]


def vrrp(run_id):
    return [{"device_id": "bb", "device_name": "Synthetic switch", "grp": "Vlan1/1", "old": "Master",
             "new": "Backup", "detected": TS + 10, "run_id": run_id, "source": "test", "text": f"Synthetic {run_id}"}]


def rows(db):
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {name: [tuple(r) for r in db.execute(f'SELECT * FROM "{name}" ORDER BY rowid')] for name in names}


class StoreCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="netcheck-store-recovery-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "history.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store._db.close)

    def commit(self, **kwargs):
        return self.store.commit_run(TS, TS + 1, "test", evaluation(), collections(), {},
                                     events_factory=events, vrrp_factory=vrrp, **kwargs)


class InventoryLifecycle(StoreCase):
    def seed(self):
        self.store.save_baselines({
            "bb": {"vrrp": {"Vlan1/1": "Master"}, "slots": ["1"]},
            "w1": {"clients": 3}, "w2": {"clients": 4}, "removed": {"slots": ["9"]},
            "__cluster__": {"conn_type": {"192.0.2.2": "L2", "192.0.2.3": "L3", "192.0.2.9": "L2"}},
        })

    def test_legacy_cleanup_retains_current_disabled_devices_and_all_history(self):
        self.seed()
        self.commit()
        before = rows(self.store._db)
        cfg = configuration()
        cfg["devices"][1]["enabled"] = False
        revision = self.store.sync_inventory(cfg)
        self.assertEqual(revision, 1)
        self.assertEqual(set(self.store.baselines()), {"bb", "w1", "w2", "__cluster__"})
        self.assertEqual(self.store.baselines()["__cluster__"]["conn_type"], {"192.0.2.2": "L2", "192.0.2.3": "L3"})
        after = rows(self.store._db)
        for table in ("runs", "device_results", "raw_outputs", "events", "vrrp_history", "sqlite_sequence"):
            self.assertEqual(after[table], before[table], table)

    def test_cosmetic_enabled_and_primary_changes_preserve_revision_and_baselines(self):
        cfg = configuration()
        revision = self.store.sync_inventory(cfg)
        self.seed()
        self.store.sync_inventory(cfg)
        revision = self.store.inventory_revision()
        before, timestamps = self.store.baselines(), self.store.baseline_times()
        for dev in cfg["devices"]:
            dev.update(name="Renamed", enabled=False, cluster_primary=True)
        self.assertEqual(self.store.sync_inventory(cfg), revision)
        self.assertEqual(self.store.baselines(), before)
        self.assertEqual(self.store.baseline_times(), timestamps)

    def test_each_identity_change_removes_only_replaced_device_and_shared_host(self):
        alternatives = {"host": "192.0.2.20", "role": "BB", "port": 2222, "protocol": "telnet",
                        "device_type": "aruba_os", "cluster": "another"}
        for key, value in alternatives.items():
            with self.subTest(key=key):
                cfg = configuration()
                self.store.sync_inventory(cfg)
                self.seed()
                self.store.sync_inventory(cfg)
                cfg["devices"][1][key] = value
                self.store.sync_inventory(cfg)
                baseline = self.store.baselines()
                self.assertNotIn("w1", baseline)
                self.assertIn("bb", baseline)
                self.assertIn("w2", baseline)
                self.assertEqual(baseline["__cluster__"]["conn_type"], {"192.0.2.3": "L3"})

    def test_epoch_detects_delete_readd_even_if_intermediate_sync_was_missed(self):
        cfg = configuration()
        first = self.store.sync_inventory(cfg)
        self.seed()
        # ConfigStore changes the epoch even if SQLite was unavailable at deletion.
        cfg["_baseline_epochs"]["w1"] = "w1-readded"
        self.assertGreater(self.store.sync_inventory(cfg), first)
        self.assertNotIn("w1", self.store.baselines())
        self.assertEqual(self.store.baselines()["__cluster__"]["conn_type"], {"192.0.2.3": "L3"})
        self.store._db.close()
        reopened = Store(self.path)
        self.addCleanup(reopened._db.close)
        revision = reopened.inventory_revision()
        self.assertEqual(reopened.sync_inventory(cfg), revision)

    def test_legacy_metadata_without_epoch_preserves_first_epoch_assignment(self):
        cfg = configuration()
        cfg.pop("_baseline_epochs")
        self.store.sync_inventory(cfg)
        self.seed()
        self.store.sync_inventory(configuration())
        self.assertIn("bb", self.store.baselines())
        self.assertIn("w1", self.store.baselines())

    def test_delete_all_cleans_shared_row_and_stale_run_cannot_recreate_it(self):
        revision = self.store.sync_inventory(configuration())
        self.seed()
        self.store.sync_inventory({"devices": [], "_baseline_epochs": {}})
        self.assertEqual(self.store.baselines(), {})
        run_id = self.commit(expected_revision=revision, baseline_updates={"bb": {"slots": ["1"]},
                                                                              "__cluster__": {"conn_type": {"192.0.2.2": "L2"}}})
        self.assertEqual(self.store.baselines(), {})
        self.assertIsNotNone(self.store.get_run(run_id))
        self.assertEqual(self.store.list_events()[0]["run_id"], run_id)
        self.assertEqual(self.store.list_vrrp()[0]["run_id"], run_id)

    def test_reset_and_ack_invalidate_inflight_updates_even_without_existing_rows(self):
        revision = self.store.sync_inventory(configuration())
        self.store.reset_baseline("bb")
        self.assertEqual(self.store.inventory_revision(), revision + 1)
        self.commit(expected_revision=revision, baseline_updates={"bb": {"slots": ["1"]}})
        self.assertEqual(self.store.baselines(), {})
        revision = self.store.inventory_revision()
        self.store.ack_vrrp("missing")
        self.assertEqual(self.store.inventory_revision(), revision + 1)
        self.commit(expected_revision=revision, baseline_updates={"bb": {"vrrp": {"1": "Master"}}})
        self.assertEqual(self.store.baselines(), {})

    def test_ack_preserves_other_baselines_and_revision_failure_rolls_back(self):
        self.seed()
        self.commit()
        before = rows(self.store._db)
        with patch.object(self.store, "_bump_revision", side_effect=RuntimeError("Synthetic failure")):
            with self.assertRaises(RuntimeError):
                self.store.ack_vrrp("bb")
            self.assertEqual(rows(self.store._db), before)
            with self.assertRaises(RuntimeError):
                self.store.reset_baseline("bb")
            self.assertEqual(rows(self.store._db), before)
        self.store.ack_vrrp("bb")
        self.assertEqual(self.store.baselines()["bb"], {"slots": ["1"]})
        self.assertEqual(self.store.vrrp_unacked(), 0)

    def test_empty_ack_revision_updates_are_not_lost_across_connections(self):
        second = Store(self.path)
        self.addCleanup(second._db.close)
        with ThreadPoolExecutor(max_workers=2) as workers:
            jobs = [workers.submit(store.ack_vrrp, "missing") for store in [self.store, second] * 10]
            for job in jobs:
                job.result(timeout=5)
        self.assertEqual(self.store.inventory_revision(), 20)
        self.assertEqual(second.inventory_revision(), 20)


class RunTransactions(StoreCase):
    def test_bundle_saves_all_data_and_epoch_together(self):
        revision = self.store.sync_inventory(configuration())
        run_id = self.commit(expected_revision=revision, baseline_updates={"bb": {"slots": ["1"]}})
        self.assertEqual(self.store.baselines()["bb"], {"slots": ["1"]})
        self.assertEqual(self.store.get_raw(run_id, "bb", "version")["output"], "Synthetic output")
        self.assertEqual(self.store.list_events()[0]["run_id"], run_id)
        self.assertEqual(self.store.list_vrrp()[0]["run_id"], run_id)
        self.assertEqual(self.store.previous_metrics()["bb"], {"uptime": 100, "ts": TS, "baseline_epoch": "bb-first"})

    def test_vrrp_factory_failure_rolls_back_events_baselines_raw_and_run(self):
        self.commit(baseline_updates={"bb": {"slots": ["1"]}})
        before = rows(self.store._db)
        with self.assertRaisesRegex(RuntimeError, "Synthetic"):
            self.store.commit_run(TS + 10, TS + 11, "test", evaluation(), collections(), {},
                                  baseline_updates={"bb": {"slots": ["1", "2"]}}, events_factory=events,
                                  vrrp_factory=lambda _: (_ for _ in ()).throw(RuntimeError("Synthetic failure")))
        self.assertEqual(rows(self.store._db), before)
        self.assertFalse(self.store._db.in_transaction)
        self.commit(baseline_updates={"bb": {"slots": ["1", "2"]}})
        self.assertEqual(len(self.store.list_runs()), 2)

    def test_legacy_epoch_absence_is_explicit(self):
        old = evaluation()
        old["devices"]["bb"].pop("baseline_epoch")
        self.store.save_run(TS, TS + 1, "test", old, {}, None)
        self.assertIsNone(self.store.previous_metrics()["bb"]["baseline_epoch"])


class ManagedBackups(StoreCase):
    def assert_no_temporary_files(self):
        self.assertFalse([p for p in self.path.parent.rglob("*") if ".tmp" in p.name])

    def test_backup_is_valid_complete_and_daily_reused(self):
        self.store.sync_inventory(configuration())
        self.commit(baseline_updates={"bb": {"slots": ["1"]}})
        original = rows(self.store._db)
        saved = self.store.backup_if_due()
        validate_database(saved)
        copied = sqlite3.connect(saved)
        try:
            self.assertEqual(rows(copied), original)
        finally:
            copied.close()
        self.assertEqual(self.store.backup_if_due(), saved)
        self.assert_no_temporary_files()

    def test_stale_or_corrupt_daily_backup_is_not_reused(self):
        stale = self.store.backup()
        os.utime(stale, (TS, TS))
        fresh = self.store.backup_if_due()
        self.assertNotEqual(fresh, stale)
        fresh.write_bytes(b"Synthetic invalid SQLite")
        repaired = self.store.backup_if_due()
        self.assertNotEqual(repaired, fresh)
        validate_database(repaired)

    def test_rotation_is_scoped_and_custom_destination_does_not_rotate(self):
        saved = [self.store.backup(keep=2) for _ in range(3)]
        self.assertFalse(saved[0].exists())
        self.assertTrue(saved[1].exists())
        self.assertTrue(saved[2].exists())
        unrelated = self.store.backup_directory / "unrelated.sqlite3"
        unrelated.write_bytes(b"preserve")
        custom = self.path.parent / "custom.sqlite3"
        self.assertEqual(self.store.backup(custom, keep=1), custom)
        self.assertTrue(saved[1].exists())
        self.assertTrue(saved[2].exists())
        self.assertEqual(unrelated.read_bytes(), b"preserve")

    def test_clock_rollback_never_rotates_just_published_backup(self):
        future = self.store.backup()
        future_name = future.name.replace(future.name.split("-backup-")[1][:8], "29990101", 1)
        future = future.rename(future.with_name(future_name))
        current = self.store.backup(keep=1)
        self.assertTrue(current.exists())
        self.assertFalse(future.exists())

    def test_existing_target_and_live_database_sidecars_are_never_overwritten(self):
        existing = self.path.parent / "existing.sqlite3"
        existing.write_bytes(b"preserve")
        for destination in [existing, self.path, *(Path(str(self.path) + suffix) for suffix in ("-wal", "-shm", "-journal"))]:
            with self.subTest(destination=destination.name), self.assertRaises(FileExistsError):
                self.store.backup(destination)
        self.assertEqual(existing.read_bytes(), b"preserve")
        self.assert_no_temporary_files()

    def test_publish_race_preserves_winner_and_removes_only_own_temporary(self):
        destination = self.path.parent / "raced.sqlite3"
        def competitor(_source, target):
            Path(target).write_bytes(b"winner")
            raise FileExistsError("Synthetic publish race")
        with patch("nc.store.os.link", side_effect=competitor), self.assertRaises(FileExistsError):
            self.store.backup(destination)
        self.assertEqual(destination.read_bytes(), b"winner")
        self.assert_no_temporary_files()

    def test_existing_sidecar_blocks_new_target(self):
        for suffix in ("-wal", "-shm", "-journal"):
            destination = self.path.parent / f"other{suffix}.sqlite3"
            sidecar = Path(str(destination) + suffix)
            sidecar.write_bytes(b"preserve")
            with self.subTest(suffix=suffix), self.assertRaises(FileExistsError):
                self.store.backup(destination)
            self.assertFalse(destination.exists())
            self.assertEqual(sidecar.read_bytes(), b"preserve")

    def test_temporary_cleanup_error_does_not_mask_publication_or_primary_failure(self):
        real_unlink = Path.unlink
        def blocked_cleanup(path, *args, **kwargs):
            if ".tmp" in path.name:
                raise PermissionError("Synthetic cleanup failure")
            return real_unlink(path, *args, **kwargs)
        destination = self.path.parent / "published.sqlite3"
        with patch("nc.store.Path.unlink", autospec=True, side_effect=blocked_cleanup), self.assertLogs("netcheck", "WARNING"):
            self.assertEqual(self.store.backup(destination), destination)
            with patch("nc.store._validate_connection", side_effect=sqlite3.DatabaseError("Primary validation failure")):
                with self.assertRaisesRegex(sqlite3.DatabaseError, "Primary validation failure"):
                    self.store.backup()
        validate_database(destination)

    def test_validation_failure_keeps_prior_backups_and_never_publishes(self):
        prior = self.store.backup()
        content = prior.read_bytes()
        with patch("nc.store._validate_connection", side_effect=sqlite3.DatabaseError("Synthetic invalid backup")):
            with self.assertRaises(sqlite3.DatabaseError):
                self.store.backup(keep=1)
        self.assertEqual(list(self.store.backup_directory.iterdir()), [prior])
        self.assertEqual(prior.read_bytes(), content)
        self.assert_no_temporary_files()

    def test_own_transaction_is_rejected_without_hanging_and_preserved(self):
        self.store._db.execute("INSERT INTO baselines VALUES ('pending','{}',?)", (TS,))
        try:
            started = time.monotonic()
            with self.assertRaises(ValueError):
                self.store.backup(timeout=0.1)
            self.assertLess(time.monotonic() - started, 1)
            self.assertTrue(self.store._db.in_transaction)
        finally:
            self.store._db.rollback()
        self.assert_no_temporary_files()

    def test_shared_and_backup_lock_waits_obey_total_timeout(self):
        for lock in (self.store._lock, self.store._backup_lock):
            with self.subTest(lock=lock):
                lock.acquire()
                try:
                    started = time.monotonic()
                    with self.assertRaises(TimeoutError):
                        self.store.backup(timeout=0.03)
                    self.assertLess(time.monotonic() - started, 1)
                    self.assertTrue(lock.locked())
                finally:
                    lock.release()
                self.assert_no_temporary_files()

    def test_read_only_validation_does_not_create_missing_database(self):
        missing = self.path.parent / "missing.sqlite3"
        with self.assertRaises(sqlite3.Error):
            validate_database(missing)
        self.assertFalse(missing.exists())
        unrelated = self.path.parent / "unrelated.sqlite3"
        db = sqlite3.connect(unrelated)
        db.execute("CREATE TABLE unrelated (value TEXT)")
        db.close()
        with self.assertRaises(sqlite3.DatabaseError):
            validate_database(unrelated)


if __name__ == "__main__":
    unittest.main()
