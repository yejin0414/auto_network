"""Synthetic Store query/retention semantics and VM-work regressions.

VM work and query plans are checked instead of host-dependent latency limits.
Large 1,000/10,000-run evidence is measured separately by the benchmark runner.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nc.store import Store


TS = 1700000000


def count_vm(db, function):
    steps, statements = [0], []
    def progress():
        steps[0] += 100
        return 0
    db.set_progress_handler(progress, 100)
    db.set_trace_callback(statements.append)
    try:
        result = function()
    finally:
        db.set_progress_handler(None, 0)
        db.set_trace_callback(None)
    return result, steps[0], statements


def plans(db, statements):
    return [row[3] for sql in statements if sql.lstrip().upper().startswith("SELECT")
            for row in db.execute("EXPLAIN QUERY PLAN " + sql)]


def snapshot(db):
    return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in ("runs", "device_results", "raw_outputs", "events", "vrrp_history", "baselines")}


class StoreScalingCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="netcheck-store-scaling-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "history.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store._db.close)

    def seed(self, runs, devices=25):
        db = self.store._db
        with db:
            db.executemany("INSERT INTO runs(id,started,finished,trigger,overall,summary) VALUES(?,?,?,?,?,?)",
                           ((rid, TS + rid * 60, TS + rid * 60 + 1, "synthetic", "ok", "{}") for rid in range(1, runs + 1)))
            for rid in range(1, runs + 1):
                values = []
                for did in range(devices):
                    uptime = None if did == 0 or rid > runs - 3 else rid * 60
                    data = json.dumps({"metrics": {"uptime": uptime}, "baseline_epoch": "synthetic"})
                    values.append((rid, f"synthetic-{did}", "ok", 20, 30, data))
                db.executemany("INSERT INTO device_results VALUES(?,?,?,?,?,?)", values)


class PreviousMetricsScaling(StoreScalingCase):
    def test_latest_nonnull_sample_keeps_epoch_and_run_order_semantics(self):
        db = self.store._db
        with db:
            db.executemany("INSERT INTO runs(id,started,summary) VALUES(?,?,?)",
                           [(1, TS + 100, "{}"), (2, TS + 90, "{}"), (3, TS + 80, "{}"), (4, TS + 70, "{}")])
            entries = [
                (1, "a", {"metrics": {"uptime": 90}, "baseline_epoch": "old"}),
                (2, "a", {"metrics": {"uptime": 0}, "baseline_epoch": "new"}),
                (3, "a", {"metrics": {"uptime": None}, "baseline_epoch": "failed"}),
                (4, "a", {"metrics": {}, "baseline_epoch": "missing"}),
                (1, "no-sample", {"metrics": {"uptime": None}}),
                (4, "no-sample", {}),
                (1, "legacy", {"metrics": {"uptime": 12}}),
                (1, "orphan", {"metrics": {"uptime": 15}}),
                (99, "orphan", {"metrics": {"uptime": 20}}),
            ]
            db.executemany("INSERT INTO device_results(run_id,device_id,status,data) VALUES(?,?,?,?)",
                           ((rid, did, "unknown", json.dumps(data)) for rid, did, data in entries))
        self.assertEqual(self.store.previous_metrics(), {
            "a": {"uptime": 0, "ts": TS + 90, "baseline_epoch": "new"},
            "legacy": {"uptime": 12, "ts": TS + 100, "baseline_epoch": None},
        })

    def test_uptime_seek_has_linear_index_work_even_for_always_null_device(self):
        self.seed(1600)
        actual, steps, statements = count_vm(self.store._db, self.store.previous_metrics)
        self.assertEqual(len(actual), 24)
        self.assertNotIn("synthetic-0", actual)
        self.assertEqual(actual["synthetic-1"]["uptime"], 1597 * 60)
        # The old correlated MAX runs once for every historical row and scans
        # all 1,600 samples again for the always-null device (millions of steps).
        self.assertLess(steps, 40000 * 8 + 50000)
        detail = "\n".join(plans(self.store._db, statements))
        self.assertIn("ix_dr_uptime", detail)
        self.assertIn("SEARCH dr", detail)
        self.assertNotIn("SCAN dr", detail)


class TrendWindows(StoreScalingCase):
    def test_small_window_work_does_not_scan_all_device_history(self):
        self.seed(1600)
        since = TS + 1598 * 60
        result, steps, statements = count_vm(self.store._db, lambda: self.store.trend("synthetic-1", since))
        self.assertEqual([r["t"] for r in result], [TS + rid * 60 for rid in (1598, 1599, 1600)])
        self.assertLess(steps, 500)
        self.assertIn("ix_runs_started", "\n".join(plans(self.store._db, statements)))
        all_results, all_steps, queries = count_vm(self.store._db, lambda: self.store.trends_all(since))
        self.assertEqual(len(all_results), 25)
        self.assertEqual(all_results["synthetic-1"], [
            {"run": rid, "t": TS + rid * 60, "status": "ok", "cpu": 20.0, "mem": 30.0}
            for rid in (1598, 1599, 1600)])
        self.assertLess(all_steps, 3000)
        self.assertIn("ix_runs_started", "\n".join(plans(self.store._db, queries)))

    def test_out_of_order_timestamps_still_return_run_id_order(self):
        self.seed(4, devices=2)
        with self.store._db:
            self.store._db.execute("UPDATE runs SET started=? WHERE id=1", (TS + 1000,))
            self.store._db.execute("UPDATE runs SET started=? WHERE id=3", (TS + 5,))
        result = self.store.trend("synthetic-1", TS + 100)
        self.assertEqual([r["t"] for r in result], [TS + 1000, TS + 120, TS + 240])
        result = self.store.trends_all(TS + 100)
        self.assertEqual([r["run"] for r in result["synthetic-1"]], [1, 2, 4])


class VrrpIndexSemantics(StoreScalingCase):
    def test_order_uses_log_time_when_present_then_id_with_nulls_last(self):
        cases = [(None, TS + 10), (TS + 30, TS + 1), (TS + 20, TS + 100),
                 (None, TS + 30), (0, TS + 999), (None, None), (None, None)]
        self.store.add_vrrp([{"device_id": "a", "log_ts": log_ts, "detected": detected, "text": str(n)}
                             for n, (log_ts, detected) in enumerate(cases)])
        self.assertEqual([r["id"] for r in self.store.list_vrrp()], [4, 2, 3, 1, 5, 7, 6])
        self.assertEqual([r["id"] for r in self.store.list_vrrp(2)], [4, 2])

    def test_dedup_and_ack_semantics_survive_indexes(self):
        first = {"device_id": "a", "log_ts": TS, "text": "same evidence"}
        self.assertEqual(self.store.add_vrrp([first, first, {**first, "device_id": "b"}]), 2)
        self.assertEqual(self.store.add_vrrp([{**first, "text": ""}, {**first, "text": ""}]), 2)
        self.store.save_baselines({"a": {"vrrp": {"Vlan1/1": "Master"}, "slots": ["1"]}})
        self.assertEqual(self.store.vrrp_unacked(), 4)
        self.assertEqual(self.store.ack_vrrp("a"), ["a"])
        self.assertEqual(self.store.vrrp_unacked(), 1)
        self.assertEqual(self.store.baselines()["a"], {"slots": ["1"]})
        self.assertEqual(self.store.add_vrrp([first]), 0)
        self.assertEqual(self.store.ack_vrrp(), ["a", "b"])
        self.assertEqual(self.store.vrrp_unacked(), 0)

    def test_recent_limit_pending_count_and_dedup_avoid_history_scan(self):
        db = self.store._db
        with db:
            db.executemany("INSERT INTO vrrp_history(device_id,log_ts,detected,text,acked) VALUES(?,?,?,?,?)",
                           (("a", None if n % 2 else TS + n, TS + n, f"Synthetic {n}", None if n >= 19990 else TS)
                            for n in range(20000)))
        recent, steps, statements = count_vm(db, lambda: self.store.list_vrrp(30))
        self.assertEqual([r["id"] for r in recent], list(range(20000, 19970, -1)))
        self.assertLess(steps, 1500)
        details = "\n".join(plans(db, statements))
        self.assertIn("ix_vrrp_order", details)
        self.assertNotIn("TEMP B-TREE", details)
        pending, steps, statements = count_vm(db, self.store.vrrp_unacked)
        self.assertEqual(pending, 10)
        self.assertLess(steps, 200)
        self.assertIn("ix_vrrp_unacked", "\n".join(plans(db, statements)))
        added, steps, statements = count_vm(db, lambda: self.store.add_vrrp([{"device_id": "a", "text": "Synthetic 19999"}]))
        self.assertEqual(added, 0)
        self.assertLess(steps, 200)
        self.assertIn("ix_vrrp_text", "\n".join(plans(db, statements)))


class RetentionScaling(StoreScalingCase):
    def test_prune_keeps_boundary_unknown_time_and_unacked_evidence(self):
        db = self.store._db
        self.seed(3, devices=2)
        cutoff = TS + 120
        with db:
            db.executemany("INSERT INTO raw_outputs(run_id,device_id,cmd_id,output) VALUES(?,?,?,?)",
                           [(rid, "synthetic-1", "version", b"Synthetic") for rid in (1, 2, 3, 99)])
            db.executemany("INSERT INTO events(ts,run_id,text) VALUES(?,?,?)",
                           [(cutoff - 1, 3, "old event on retained run"), (cutoff, 1, "boundary event on expired run"),
                            (None, 1, "unknown timestamp")])
            db.executemany("INSERT INTO vrrp_history(device_id,log_ts,detected,acked,text) VALUES(?,?,?,?,?)",
                           [("a", cutoff - 1, cutoff + 10, TS, "expired acknowledged log"),
                            ("a", None, cutoff - 1, None, "expired unacknowledged"),
                            ("a", cutoff, cutoff - 100, TS, "boundary acknowledged log"),
                            ("a", None, cutoff - 1, TS, "expired acknowledged detection"),
                            ("a", None, None, TS, "unknown timestamp"),
                            ("a", cutoff + 1, cutoff - 100, TS, "new log beats old detection")])
        self.store.save_baselines({"a": {"slots": ["1"]}})
        with patch("nc.store.time.time", return_value=cutoff + 86400):
            self.store.prune(1)
        self.assertEqual([r[0] for r in db.execute("SELECT id FROM runs ORDER BY id")], [2, 3])
        self.assertEqual([r[0] for r in db.execute("SELECT DISTINCT run_id FROM device_results ORDER BY run_id")], [2, 3])
        self.assertEqual([r[0] for r in db.execute("SELECT run_id FROM raw_outputs ORDER BY run_id")], [2, 3, 99])
        self.assertEqual([r[0] for r in db.execute("SELECT text FROM events ORDER BY id")],
                         ["boundary event on expired run", "unknown timestamp"])
        self.assertEqual([r[0] for r in db.execute("SELECT text FROM vrrp_history ORDER BY id")],
                         ["expired unacknowledged", "boundary acknowledged log", "unknown timestamp", "new log beats old detection"])
        self.assertEqual(self.store.baselines(), {"a": {"slots": ["1"]}})

    def test_prune_uses_fixed_statement_count_and_rolls_back_all_deletes(self):
        self.seed(1000, devices=2)
        db = self.store._db
        with db:
            db.execute("INSERT INTO events(ts,text) VALUES(?,?)", (TS, "Synthetic"))
            db.execute("CREATE TEMP TRIGGER reject_event_delete BEFORE DELETE ON events "
                       "BEGIN SELECT RAISE(ABORT,'Synthetic delete failure'); END")
        original = snapshot(db)
        with patch("nc.store.time.time", return_value=TS + 1001 * 60 + 86400):
            with self.assertRaisesRegex(sqlite3.IntegrityError, "Synthetic delete failure"):
                self.store.prune(1)
        self.assertEqual(snapshot(db), original)
        db.execute("DROP TRIGGER reject_event_delete")
        with patch("nc.store.time.time", return_value=TS + 1001 * 60 + 86400):
            _, _, statements = count_vm(db, lambda: self.store.prune(1))
        self.assertEqual(len([sql for sql in statements if sql.startswith("DELETE")]), 5)
        self.assertLessEqual(len(statements), 7)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
