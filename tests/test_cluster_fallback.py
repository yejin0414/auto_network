"""Cluster failover uses synthetic sessions only, with bounded event-controlled stalls."""
from __future__ import annotations

import copy
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nc.collector import CmdResult, ConnectFailure, DeviceCollection, collect_device, run_spec
from nc.commands import CLUSTER_COMMANDS, CommandSpec
from nc.config import validate
from nc.credentials import Credential, CredentialStore
from nc.engine import Engine, _Abandoned
from nc.evaluate import evaluate_run
from nc.store import Store


SPEC = {spec.id: spec for spec in CLUSTER_COMMANDS}
COMMAND_KEY = {spec.commands[0]: spec.id for spec in CLUSTER_COMMANDS}


def membership(*ips, state="CONNECTED"):
    lines = ["Type IPv4 Address    Priority Connection-Type STATUS",
             "---- --------------- -------- --------------- ------"]
    lines.extend(f"self {ip:<15}      128    L2-Connected {state}" for ip in ips)
    return "\n".join(lines)


def load(*ips):
    return "\n".join(f"{ip} 100 100" for ip in ips)


def result(key, output="", ok=True):
    spec = SPEC[key]
    return CmdResult(key, spec.label, spec.commands[0], output, ok, "" if ok else "synthetic failure")


class SyntheticSession:
    def __init__(self, outputs=None, block=None):
        self.outputs = outputs or {}
        self.block = block
        self.commands = []
        self.timeouts = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.aborted = threading.Event()
        self.closed = threading.Event()

    def stall(self, step):
        if self.block == step:
            self.entered.set()
            if not self.release.wait(3):
                raise TimeoutError("synthetic test gate was not released")

    def run(self, command, timeout):
        key = COMMAND_KEY[command]
        self.commands.append(key)
        self.timeouts.append(timeout)
        self.stall(key)
        value = self.outputs.get(key, "")
        if isinstance(value, Exception):
            raise value
        return value

    def abort(self):
        # Deliberately does not unblock run/close: a badly behaved driver must
        # not keep the caller waiting or publish its eventual late output.
        self.aborted.set()

    def close(self):
        try:
            self.stall("close")
        finally:
            self.closed.set()


class SyntheticDriver:
    def __init__(self, sessions=None, block_open=None):
        self.sessions = sessions or {}
        self.block_open = block_open
        self.opened = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def open(self, device, cred, ssh):
        self.opened.append(device["id"])
        if device["id"] == self.block_open:
            self.entered.set()
            if not self.release.wait(3):
                raise TimeoutError("synthetic open gate was not released")
        session = self.sessions[device["id"]]
        if isinstance(session, Exception):
            raise session
        return session


class ClusterFallback(unittest.TestCase):
    def setUp(self):
        self.cfg = validate({"devices": [
            {"id": did, "name": f"WLC {did}", "host": f"192.0.2.{index}", "role": "WLC",
             "cluster": "B" if did in ("d", "e") else "A", "cluster_primary": did in ("a", "d")}
            for index, did in enumerate(("a", "b", "c", "d", "e"), 11)],
            "ssh": {"retries": 0}, "report": {"excel_auto": False, "notify": False}})
        self.devices = {d["id"]: d for d in self.cfg["devices"]}
        self.groups = {"A": [self.devices[k] for k in ("a", "b", "c")]}
        self.primaries = {"A": self.devices["a"]}
        self.collections = {did: DeviceCollection(did, True) for did in self.devices}
        self.creds = CredentialStore(persistent=False)
        self.creds.set("shared", Credential("synthetic", "test-only"), False)
        self.driver = SyntheticDriver()
        self.engine = Engine(SimpleNamespace(get=lambda: self.cfg), Mock(), self.creds, self.driver, demo=True)
        self.engine.cluster_fallback_seconds = 1
        self.mem = membership("192.0.2.11", "192.0.2.12", "192.0.2.13")
        self.ld = load("192.0.2.11", "192.0.2.12", "192.0.2.13")

    def collect(self, gen=0):
        return self.engine._collect_clusters(self.groups, self.primaries, self.collections, self.cfg["ssh"], gen)

    def primary(self, membership_result=None, load_result=None):
        self.collections["a"].results = {
            "membership": membership_result or result("membership", ok=False),
            "load": load_result or result("load", ok=False),
        }

    def secondary(self, did="b", **outputs):
        session = SyntheticSession(outputs)
        self.driver.sessions[did] = session
        return session

    def test_primary_membership_and_secondary_load_have_separate_sources(self):
        original = result("membership", self.mem)
        self.primary(original)
        session = self.secondary(load=self.ld)
        clusters = self.collect()
        cluster = clusters["A"]
        self.assertIs(cluster["membership"], original)
        self.assertEqual(session.commands, ["load"])
        self.assertEqual(self.driver.opened, ["b"])
        self.assertEqual(cluster["sources"], {"membership": {"id": "a", "name": "WLC a"},
                                             "load": {"id": "b", "name": "WLC b"}})
        self.assertIsNone(cluster["source_id"])
        self.assertIn("멤버십 WLC a", cluster["source"])
        self.assertIn("Client 분배 WLC b", cluster["source"])
        self.assertFalse(self.collections["a"].results["load"].ok)

    def test_primary_load_survives_membership_fallback(self):
        original = result("load", self.ld)
        self.primary(load_result=original)
        session = self.secondary(membership=self.mem)
        cluster = self.collect()["A"]
        self.assertIs(cluster["load"], original)
        self.assertEqual(session.commands, ["membership"])
        self.assertEqual(cluster["sources"]["load"]["id"], "a")

    def test_three_wlcs_complete_only_remaining_command(self):
        self.primary()
        second = self.secondary(membership=self.mem, load=RuntimeError("synthetic failure"))
        third = self.secondary("c", load=self.ld)
        cluster = self.collect()["A"]
        self.assertEqual(second.commands, ["membership", "load"])
        self.assertEqual(third.commands, ["load"])
        self.assertEqual({k: v["id"] for k, v in cluster["sources"].items()}, {"membership": "b", "load": "c"})
        self.assertTrue(cluster["membership"].ok and cluster["load"].ok)
        self.assertFalse(self.collections["b"].results["load"].ok)

    def test_ok_flag_without_parseable_output_does_not_stop_fallback(self):
        raw = result("membership", "unrecognized synthetic output")
        self.primary(raw, result("load", self.ld))
        session = self.secondary(membership=self.mem)
        cluster = self.collect()["A"]
        self.assertEqual(session.commands, ["membership"])
        self.assertEqual(cluster["sources"]["membership"]["id"], "b")
        self.assertIs(self.collections["a"].results["membership"], raw)

    def test_all_missing_membership_status_retries_but_keeps_raw(self):
        raw = result("membership", membership("192.0.2.11", state=""))
        self.primary(raw, result("load", self.ld))
        self.secondary(membership=self.mem)
        cluster = self.collect()["A"]
        self.assertEqual(cluster["sources"]["membership"]["id"], "b")
        self.assertIs(self.collections["a"].results["membership"], raw)

    def test_missing_peer_and_failed_state_are_preserved_as_evidence(self):
        # The primary can see a split cluster: a healthier peer view must not
        # replace its readable DISCONNECTED state or hide missing members.
        original = result("membership", membership("192.0.2.11", state="DISCONNECTED"))
        self.primary(original, result("load", self.ld))
        cluster = self.collect()["A"]
        self.assertIs(cluster["membership"], original)
        self.assertEqual(self.driver.opened, [])
        evaluation, _ = evaluate_run(self.cfg, self.collections, {"A": cluster}, {}, {})
        levels = {did: next(c["level"] for c in d["checks"] if c["key"] == "cluster")
                  for did, d in evaluation["devices"].items()}
        self.assertEqual(levels["a"], "crit")
        self.assertEqual(levels["b"], "warn")

    def test_partly_missing_status_retains_unknown_member(self):
        original = result("membership", membership("192.0.2.11") + "\n" +
                          membership("192.0.2.12", state="").splitlines()[-1])
        self.primary(original, result("load", self.ld))
        cluster = self.collect()["A"]
        self.assertIs(cluster["membership"], original)
        self.assertEqual(self.driver.opened, [])
        evaluation, _ = evaluate_run(self.cfg, self.collections, {"A": cluster}, {}, {})
        check = next(c for c in evaluation["devices"]["b"]["checks"] if c["key"] == "cluster")
        self.assertEqual(check["level"], "unknown")

    def test_complete_primary_never_reopens_secondary(self):
        self.primary(result("membership", self.mem), result("load", self.ld))
        cluster = self.collect()["A"]
        self.assertEqual(self.driver.opened, [])
        self.assertEqual(cluster["source_id"], "a")

    def test_disconnected_candidates_are_skipped_and_clusters_do_not_mix(self):
        self.primary()
        self.collections["b"].connected = False
        third = self.secondary("c", membership=self.mem, load=self.ld)
        other_mem, other_load = membership("192.0.2.14"), load("192.0.2.14")
        self.collections["d"].results = {"membership": result("membership", other_mem), "load": result("load", other_load)}
        self.groups["B"] = [self.devices[k] for k in ("d", "e")]
        self.primaries["B"] = self.devices["d"]
        clusters = self.collect()
        self.assertEqual(self.driver.opened, ["c"])
        self.assertEqual(third.commands, ["membership", "load"])
        self.assertEqual(clusters["A"]["membership"].output, self.mem)
        self.assertEqual(clusters["B"]["membership"].output, other_mem)
        self.assertEqual(clusters["B"]["source_id"], "d")

    def test_no_connected_candidates_leaves_explicit_unknown_results(self):
        for dc in self.collections.values():
            dc.connected = False
        cluster = self.collect()["A"]
        self.assertEqual(self.driver.opened, [])
        self.assertFalse(cluster["membership"].ok)
        self.assertFalse(cluster["load"].ok)
        self.assertTrue(cluster["membership"].error)
        self.assertEqual(cluster["sources"], {})
        evaluation, _ = evaluate_run(self.cfg, self.collections, {"A": cluster}, {}, {})
        checks = [c for c in evaluation["devices"]["a"]["checks"] if c["key"] in ("cluster", "clients")]
        self.assertEqual([c["level"] for c in checks], ["unknown", "unknown"])
        self.assertTrue(all(not c["cmd_id"] for c in checks))

    def test_evaluation_and_sqlite_use_each_commands_actual_owner(self):
        self.primary(result("membership", self.mem))
        self.secondary(load=self.ld)
        clusters = self.collect()
        evaluation, _ = evaluate_run(self.cfg, self.collections, clusters, {}, {})
        for did in ("a", "b", "c"):
            checks = {c["key"]: c for c in evaluation["devices"][did]["checks"]}
            self.assertEqual((checks["cluster"]["source_id"], checks["cluster"]["source"], checks["cluster"]["cmd_id"]),
                             ("a", "WLC a", "membership"))
            self.assertEqual((checks["clients"]["source_id"], checks["clients"]["source"], checks["clients"]["cmd_id"]),
                             ("b", "WLC b", "load"))
        self.assertEqual(evaluation["summary"]["clusters"][0]["sources"], clusters["A"]["sources"])
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "synthetic.sqlite3")
            try:
                run_id = store.save_run(1, 2, "test", evaluation, self.collections, clusters)
                self.assertEqual(store.get_raw(run_id, "a", "membership")["output"], self.mem)
                self.assertEqual(store.get_raw(run_id, "b", "load")["output"], self.ld)
                self.assertFalse(store.get_raw(run_id, "a", "load")["ok"])
                self.assertIsNone(store.get_raw(run_id, "c", "load"))
            finally:
                store._db.close()

    def test_legacy_single_source_remains_supported(self):
        cluster = {"membership": result("membership", self.mem), "load": result("load", self.ld),
                   "source": "WLC a", "source_id": "a"}
        evaluation, _ = evaluate_run(self.cfg, self.collections, {"A": cluster}, {}, {})
        checks = [c for c in evaluation["devices"]["b"]["checks"] if c["key"] in ("cluster", "clients")]
        self.assertEqual([c["source_id"] for c in checks], ["a", "a"])
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "synthetic.sqlite3")
            try:
                run_id = store.save_run(1, 2, "test", evaluation, {}, {"A": cluster})
                self.assertEqual(store.get_raw(run_id, "a", "load")["output"], self.ld)
            finally:
                store._db.close()

    def test_unattempted_command_has_no_borrowed_source_or_raw_record(self):
        self.collections["a"].results = {"membership": result("membership", self.mem)}
        self.engine.cluster_fallback_seconds = 0
        clusters = self.collect()
        evaluation, _ = evaluate_run(self.cfg, self.collections, clusters, {}, {})
        check = next(c for c in evaluation["devices"]["a"]["checks"] if c["key"] == "clients")
        self.assertEqual(check["level"], "unknown")
        self.assertEqual((check["source"], check["source_id"], check["cmd_id"]), ("", "", ""))
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "synthetic.sqlite3")
            try:
                run_id = store.save_run(1, 2, "test", evaluation, self.collections, clusters)
                self.assertIsNone(store.get_raw(run_id, "a", "load"))
                self.assertEqual(store.get_raw(run_id, "a", "membership")["output"], self.mem)
            finally:
                store._db.close()

    def blocking_session(self, block):
        self.primary()
        session = SyntheticSession({"membership": self.mem, "load": self.ld}, block=block)
        self.driver.sessions["b"] = session
        self.engine.cluster_fallback_seconds = 0.15
        self.addCleanup(session.release.set)
        self.addCleanup(self.driver.release.set)
        return session

    def bounded_collect(self):
        started = time.monotonic()
        clusters = self.collect()
        self.assertLess(time.monotonic() - started, 2)
        return clusters

    def test_blocked_second_command_preserves_first_and_rejects_late_result(self):
        session = self.blocking_session("load")
        wall_now = 1761123600.0
        # Equal wall-clock readings are possible on Windows. Adding a 150 ms
        # budget to an epoch float then subtracting it yields 150.000095 ms.
        # Keep the real monotonic watchdog, but test its wall-clock projection
        # against that exact representable bound rather than an arbitrary epsilon.
        with patch("nc.engine.time.time", return_value=wall_now):
            clusters = self.bounded_collect()
        self.assertTrue(session.entered.is_set())
        self.assertTrue(session.aborted.wait(1))
        self.assertTrue(clusters["A"]["membership"].ok)
        self.assertFalse(clusters["A"]["load"].ok)
        self.assertIn("시간 예산", clusters["A"]["load"].error)
        projected_budget = (wall_now + self.engine.cluster_fallback_seconds) - wall_now
        for timeout in session.timeouts:
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, projected_budget)
        before = copy.deepcopy((clusters, self.collections, self.engine.progress))
        session.release.set()
        self.assertTrue(session.closed.wait(1))
        self.assertEqual((clusters, self.collections, self.engine.progress), before)

    def test_open_returning_after_timeout_is_aborted_without_any_command(self):
        session = self.blocking_session(None)
        self.driver.block_open = "b"
        clusters = self.bounded_collect()
        self.assertTrue(self.driver.entered.is_set())
        self.assertFalse(clusters["A"]["membership"].ok)
        before = copy.deepcopy((clusters, self.collections, self.engine.progress))
        self.driver.release.set()
        self.assertTrue(session.closed.wait(1))
        self.assertTrue(session.aborted.is_set())
        self.assertEqual(session.commands, [])
        self.assertEqual((clusters, self.collections, self.engine.progress), before)

    def test_blocked_close_does_not_lose_completed_results(self):
        session = self.blocking_session("close")
        clusters = self.bounded_collect()
        self.assertTrue(session.entered.is_set())
        self.assertTrue(session.aborted.wait(1))
        self.assertTrue(clusters["A"]["membership"].ok)
        self.assertTrue(clusters["A"]["load"].ok)
        session.release.set()
        self.assertTrue(session.closed.wait(1))

    def test_all_clusters_share_one_budget(self):
        session = self.blocking_session("load")
        self.groups["B"] = [self.devices[k] for k in ("d", "e")]
        self.primaries["B"] = self.devices["d"]
        self.secondary("e", membership=membership("192.0.2.14"), load=load("192.0.2.14"))
        clusters = self.bounded_collect()
        self.assertEqual(self.driver.opened, ["b"])
        self.assertFalse(clusters["B"]["membership"].ok)
        self.assertIn("시간 예산", clusters["B"]["load"].error)
        session.release.set()
        self.assertTrue(session.closed.wait(1))

    def test_abandoned_fallback_cannot_publish_partial_or_late_results(self):
        session = self.blocking_session("load")
        self.engine.cluster_fallback_seconds = 5
        self.engine._gen = 1
        outcomes = []

        def collect_old():
            try:
                outcomes.append(self.collect(gen=1))
            except _Abandoned:
                outcomes.append("abandoned")

        worker = threading.Thread(target=collect_old, daemon=True)
        worker.start()
        self.assertTrue(session.entered.wait(1))
        before = copy.deepcopy(self.collections)
        with self.engine._lock:
            self.engine._gen = 2
            self.engine.progress = {"a": "new run"}
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcomes, ["abandoned"])
        self.assertTrue(session.aborted.wait(1))
        session.release.set()
        self.assertTrue(session.closed.wait(1))
        self.assertEqual(self.collections, before)
        self.assertEqual(self.engine.progress, {"a": "new run"})

    def test_cancelled_regular_job_cannot_overwrite_new_progress(self):
        cfg = validate({"devices": [{"id": "a", "name": "WLC a", "role": "WLC", "host": "192.0.2.11"}]})
        self.engine.cfg = SimpleNamespace(get=lambda: cfg)
        self.engine.store.baselines.return_value = {}
        self.engine.store.previous_metrics.return_value = {}
        self.engine.store.get_run.return_value = None
        self.engine._gen = 1
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        outcomes = []

        def specs(*_args):
            entered.set()
            if not release.wait(3):
                raise TimeoutError("synthetic spec gate was not released")
            return []

        def old_run():
            try:
                self.engine._run("test", None, gen=1)
            except _Abandoned:
                outcomes.append("abandoned")

        with patch("nc.engine.commands_for", side_effect=specs):
            worker = threading.Thread(target=old_run, daemon=True)
            worker.start()
            self.assertTrue(entered.wait(1))
            with self.engine._lock:
                self.engine._gen = 2
                self.engine.progress = {"a": "new run finished"}
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcomes, ["abandoned"])
        self.assertEqual(self.engine.progress, {"a": "new run finished"})
        self.assertEqual(self.driver.opened, [])
        self.engine.store.commit_run.assert_not_called()


class CollectorCancellation(unittest.TestCase):
    def test_fractional_timeout_matches_exact_epoch_deadline_difference(self):
        wall_now, budget = 1761123600.0, 0.15
        session = Mock()
        session.run.return_value = "192.0.2.11 100 100"
        with patch("nc.collector.time.time", return_value=wall_now):
            actual = run_spec(session, SPEC["load"], {}, deadline=wall_now + budget)
        requested = session.run.call_args.args[1]
        self.assertTrue(actual.ok)
        self.assertEqual(requested, (wall_now + budget) - wall_now)
        # Reproduce the exact strict-bound failure without relying on OS timing.
        self.assertGreater(requested, budget)

    def test_cancellation_prevents_alternate_command(self):
        cancelled = threading.Event()
        session = Mock()

        def first_command(*_args):
            cancelled.set()
            raise TimeoutError("synthetic stall ended")

        session.run.side_effect = first_command
        actual = run_spec(session, CommandSpec("alternate", "alternate", ("show first", "show second")),
                          {}, cancelled=cancelled.is_set)
        self.assertFalse(actual.ok)
        session.run.assert_called_once()

    def test_expired_budget_does_not_attempt_connection(self):
        driver = Mock()
        actual = collect_device(driver, {"id": "a", "name": "A", "role": "WLC"}, [],
                                Credential("synthetic", "test-only"), {}, deadline=time.time() - 1)
        self.assertFalse(actual.connected)
        self.assertEqual(actual.error_kind, "timeout")
        driver.open.assert_not_called()

    def test_retry_wait_is_cancellable(self):
        cancelled = threading.Event()
        driver = Mock()

        def failure(*_args):
            cancelled.set()
            raise ConnectFailure("connection", "synthetic failure")

        driver.open.side_effect = failure
        actual = collect_device(driver, {"id": "a", "name": "A", "role": "WLC"}, [],
                                Credential("synthetic", "test-only"), {"retries": 3}, cancelled=cancelled.is_set)
        self.assertFalse(actual.connected)
        driver.open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
