"""Ordinary device collection stays bounded without opening real connections.

Sessions have event-controlled open/run/close/abort stalls. The real collector,
evaluator, and a temporary SQLite store exercise cancellation through persistence.
Cleanup releases every gate and joins every test-owned worker, even on failure.
"""
from __future__ import annotations

import copy
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nc.engine as E
from nc.config import validate
from nc.credentials import Credential, CredentialStore
from nc.store import Store


COMMANDS = ["show version", "show cpu", "show memory", "show switches"]
OUTPUTS = {
    "show version": "ArubaOS Version 8.10.0.7\nSwitch uptime is 2 days 0 hours 0 minutes 0 seconds",
    "show cpu": "user 1%, system 2%, idle 97%",
    "show memory": "Memory (Kb): total: 1000, used: 200, free: 800",
    "show switches": "IP Address      Status\n--------------- ------\n192.0.2.1       Up",
}


class ControlledSession:
    def __init__(self, block=None, *, cooperative=False, block_abort=False):
        self.block = block
        self.cooperative = cooperative
        self.block_abort = block_abort
        self.opened = threading.Event()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.aborted = threading.Event()
        self.abort_release = threading.Event()
        self.closed = threading.Event()
        self.commands = []
        self.timeouts = []
        self.abort_calls = 0
        self.abort_threads = []
        self.worker = None
        self.opened_at = None
        self.aborted_at = None
        self.gate_expired = False

    def stall(self, step):
        if self.block == step:
            self.entered.set()
            if not self.release.wait(8):
                self.gate_expired = True
                raise TimeoutError("synthetic gate was not released by test cleanup")

    def run(self, command, timeout):
        self.commands.append(command)
        self.timeouts.append(timeout)
        self.stall("run")
        return OUTPUTS[command]

    def abort(self):
        self.abort_calls += 1
        self.abort_threads.append(threading.current_thread())
        self.aborted_at = time.monotonic()
        self.aborted.set()
        if self.cooperative:
            self.release.set()
        if self.block_abort and not self.abort_release.wait(8):
            self.gate_expired = True
            raise TimeoutError("synthetic abort gate was not released by test cleanup")

    def close(self):
        try:
            self.stall("close")
        finally:
            self.closed.set()


class ControlledDriver:
    def __init__(self, devices, sessions=None):
        self.sessions = {}
        self.all_sessions = []
        self.open_calls = []
        self.workers = []
        self.max_live_workers = 0
        self.lock = threading.Lock()
        for device in devices:
            self.set_session(device["id"], (sessions or {}).get(device["id"], ControlledSession()))

    def set_session(self, device_id, session, host=None):
        self.sessions[(device_id, host)] = session
        self.all_sessions.append(session)

    def open(self, device, cred, ssh):
        key = (device["id"], device["host"])
        session = self.sessions.get(key) or self.sessions[(device["id"], None)]
        worker = threading.current_thread()
        with self.lock:
            self.open_calls.append(key)
            self.workers.append(worker)
            self.max_live_workers = max(self.max_live_workers,
                                        sum(t.is_alive() for t in set(self.workers)))
        session.worker = worker
        session.opened_at = time.monotonic()
        session.opened.set()
        session.stall("open")
        return session

    def release_all(self):
        for session in self.all_sessions:
            session.release.set()
            session.abort_release.set()

    def join(self, timeout=2):
        threads = set(self.workers)
        for session in self.all_sessions:
            threads.update(session.abort_threads)
        deadline = time.monotonic() + timeout
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        return [thread for thread in threads if thread.is_alive()]


class RunHarness:
    def __init__(self, ids=("a", "b"), parallel=1, sessions=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.configuration = validate({
            "devices": [{"id": did, "name": f"MM {did}", "role": "MM", "host": f"192.0.2.{i}"}
                        for i, did in enumerate(ids, 1)],
            "ssh": {"parallel": parallel, "retries": 0},
            "report": {"excel_auto": False, "notify": False},
        })
        self.cfg = SimpleNamespace(get=lambda: copy.deepcopy(self.configuration))
        self.store = Store(Path(self.tmp.name) / "synthetic.sqlite3")
        self.creds = CredentialStore(persistent=False)
        self.creds.set("shared", Credential("synthetic", "test-only"), False)
        self.driver = ControlledDriver(self.configuration["devices"], sessions)
        self.engine = E.Engine(self.cfg, self.store, self.creds, self.driver, demo=True)
        self.engine.demo_quiet = True
        self.engine.device_grace = 0.05
        self.runners = []

    def start(self):
        state = {}

        def run():
            try:
                state["run_id"] = self.engine.run_blocking()
            except BaseException as exc:
                state["exception"] = exc

        runner = threading.Thread(target=run, name="test-engine-run", daemon=True)
        self.runners.append(runner)
        runner.start()
        return runner, state

    def close(self):
        self.engine.stop()
        self.driver.release_all()
        for runner in self.runners:
            runner.join(2)
        # A late open may reach abort/close after the runner has exited.
        self.driver.release_all()
        alive = self.driver.join()
        alive.extend(runner for runner in self.runners if runner.is_alive())
        try:
            if alive:
                raise AssertionError("test cleanup left synthetic threads alive")
            if any(session.gate_expired for session in self.driver.all_sessions):
                raise AssertionError("a test gate expired instead of being released")
        finally:
            self.store._db.close()
            self.tmp.cleanup()


class DeviceTimeouts(unittest.TestCase):
    def setUp(self):
        self.default_limit = 0.08
        self.limits = {}
        for patcher in (
            patch.object(E, "_DEVICE_POLL_SECONDS", 0.01, create=True),
            patch.object(E, "device_time_limit", side_effect=lambda d, _ssh: self.limits.get(d["id"], self.default_limit)),
            patch("nc.credentials._keyring", side_effect=AssertionError("OS credentials accessed")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def harness(self, *args, **kwargs):
        harness = RunHarness(*args, **kwargs)
        self.addCleanup(harness.close)
        return harness

    def finished(self, harness, running, *, saved=True, timeout=1.5):
        thread, state = running
        thread.join(timeout)
        self.assertFalse(thread.is_alive(), "a blocked collector stranded the run/queue")
        self.assertNotIn("exception", state, state.get("exception"))
        if saved:
            self.assertIsNotNone(state.get("run_id"), harness.engine.last_error)
            return harness.store.get_run(state["run_id"])
        self.assertIsNone(state.get("run_id"))
        return None

    def timeout_result(self, run, device_id):
        result = run["devices"][device_id]
        self.assertFalse(result["connected"])
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["checks"][0]["source"], "timeout")
        self.assertTrue(result["error"])
        self.assertEqual(result["commands"], [])
        return result

    def assert_normal(self, harness, run, device_id):
        result = run["devices"][device_id]
        self.assertTrue(result["connected"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["metrics"]["cpu"], 3.0)
        self.assertEqual(result["metrics"]["mem"], 20.0)
        self.assertEqual([cmd["command"] for cmd in result["commands"]], COMMANDS)
        self.assertEqual(harness.engine.progress[device_id], "완료")

    def test_blocked_worker_does_not_strand_queued_device_or_publish_late_results(self):
        """The old executor leaves b queued forever while a never returns."""
        first = ControlledSession(block="run")
        harness = self.harness(sessions={"a": first})
        running = harness.start()
        self.assertTrue(first.entered.wait(1))
        run = self.finished(harness, running)
        self.assertEqual([did for did, _ in harness.driver.open_calls], ["a"])
        self.timeout_result(run, "a")
        queued = self.timeout_result(run, "b")
        self.assertRegex(queued["error"], r"대기|정리|이전|미시도|생략|시도하지")
        self.assertEqual(harness.engine.progress["a"], "응답 없음")
        self.assertNotEqual(harness.engine.progress["b"], "대기")
        self.assertEqual(first.abort_calls, 1)
        before = (copy.deepcopy(run), harness.store.baselines(), dict(harness.engine.progress))
        first.release.set()
        self.assertEqual(harness.driver.join(), [])
        self.assertEqual(first.commands, ["show version"])
        self.assertEqual((harness.store.get_run(run["id"]), harness.store.baselines(),
                          harness.engine.progress), before)
        self.assertEqual(len(harness.store.list_runs()), 1)

    def test_cooperative_run_or_close_abort_allows_next_device(self):
        for phase in ("run", "close"):
            with self.subTest(phase=phase):
                first = ControlledSession(block=phase, cooperative=True)
                harness = self.harness(sessions={"a": first})
                run = self.finished(harness, harness.start())
                self.timeout_result(run, "a")
                self.assert_normal(harness, run, "b")
                self.assertEqual([did for did, _ in harness.driver.open_calls], ["a", "b"])
                self.assertEqual(first.abort_calls, 1)
                self.assertTrue(first.closed.is_set())
                # The grace interval remains in addition to the collection budget.
                self.assertGreaterEqual(first.aborted_at - first.opened_at,
                                        self.default_limit + harness.engine.device_grace - 0.02)

    def test_late_open_is_closed_without_commands_or_state_changes(self):
        first = ControlledSession(block="open")
        harness = self.harness(sessions={"a": first})
        running = harness.start()
        self.assertTrue(first.entered.wait(1))
        run = self.finished(harness, running)
        self.timeout_result(run, "a")
        self.timeout_result(run, "b")
        self.assertEqual(first.abort_calls, 0)  # No session was available to abort yet.
        before = (copy.deepcopy(run), dict(harness.engine.progress))
        first.release.set()
        self.assertEqual(harness.driver.join(), [])
        self.assertEqual(first.commands, [])
        self.assertEqual(first.abort_calls, 1)
        self.assertTrue(first.closed.is_set())
        self.assertEqual((harness.store.get_run(run["id"]), harness.engine.progress), before)

    def test_serial_success_preserves_order_commands_and_results(self):
        self.default_limit = 2
        harness = self.harness(ids=("a", "b", "c"))
        run = self.finished(harness, harness.start())
        self.assertEqual([did for did, _ in harness.driver.open_calls], ["a", "b", "c"])
        self.assertEqual(harness.driver.max_live_workers, 1)
        for did in ("a", "b", "c"):
            self.assert_normal(harness, run, did)
        self.assertTrue(all(thread.daemon for thread in harness.driver.workers))

    def test_parallel_limit_does_not_admit_queued_device_early(self):
        self.default_limit = 2
        first, second = ControlledSession(block="run"), ControlledSession(block="run")
        harness = self.harness(ids=("a", "b", "c", "d"), parallel=2,
                               sessions={"a": first, "b": second})
        third = harness.driver.sessions[("c", None)]
        running = harness.start()
        self.assertTrue(first.entered.wait(1))
        self.assertTrue(second.entered.wait(1))
        self.assertFalse(third.opened.wait(0.04))
        first.release.set()
        self.assertTrue(third.opened.wait(1))
        second.release.set()
        run = self.finished(harness, running)
        self.assertEqual(harness.driver.max_live_workers, 2)
        self.assertEqual(set(did for did, _ in harness.driver.open_calls[:2]), {"a", "b"})
        for did in ("a", "b", "c", "d"):
            self.assert_normal(harness, run, did)

    def test_queued_budget_starts_when_its_collection_actually_starts(self):
        self.limits.update(a=2, b=0.10)
        first = ControlledSession(block="run")
        harness = self.harness(sessions={"a": first})
        second = harness.driver.sessions[("b", None)]
        running = harness.start()
        self.assertTrue(first.entered.wait(1))
        # b waits longer than its own collection budget, without consuming it.
        self.assertFalse(second.opened.wait(0.20))
        first.release.set()
        run = self.finished(harness, running)
        self.assert_normal(harness, run, "a")
        self.assert_normal(harness, run, "b")
        self.assertEqual(second.abort_calls, 0)

    def test_repeated_runs_do_not_duplicate_busy_identity_or_abort_helpers(self):
        first = ControlledSession(block="run", block_abort=True)
        harness = self.harness(ids=("a",), parallel=2, sessions={"a": first})
        first_run = self.finished(harness, harness.start())
        self.timeout_result(first_run, "a")
        self.assertTrue(first.aborted.wait(1))
        # Display changes do not turn the same configured endpoint into a new device.
        harness.configuration["devices"][0]["name"] = "renamed synthetic MM"
        for _ in range(3):
            run = self.finished(harness, harness.start())
            self.timeout_result(run, "a")
        self.assertEqual(len(harness.driver.open_calls), 1)
        self.assertEqual(first.abort_calls, 1)
        self.assertEqual(sum(t.is_alive() for t in harness.driver.workers), 1)
        self.assertEqual(sum(t.is_alive() for t in first.abort_threads), 1)
        self.assertTrue(first.worker.daemon)
        self.assertTrue(first.abort_threads[0].daemon)
        harness.driver.release_all()
        self.assertEqual(harness.driver.join(), [])
        harness.driver.set_session("a", ControlledSession())
        recovered = self.finished(harness, harness.start())
        self.assert_normal(harness, recovered, "a")
        self.assertEqual(len(harness.driver.open_calls), 2)

    def test_changed_identity_can_use_free_capacity_while_old_worker_is_busy(self):
        first = ControlledSession(block="run")
        harness = self.harness(ids=("a",), parallel=2, sessions={"a": first})
        self.finished(harness, harness.start())
        harness.configuration["devices"][0]["host"] = "192.0.2.101"
        replacement = ControlledSession()
        harness.driver.set_session("a", replacement, host="192.0.2.101")
        run = self.finished(harness, harness.start())
        self.assert_normal(harness, run, "a")
        self.assertEqual(harness.driver.open_calls, [("a", "192.0.2.1"), ("a", "192.0.2.101")])
        self.assertTrue(first.worker.is_alive())
        first.release.set()
        self.assertEqual(harness.driver.join(), [])
        self.assertEqual(harness.store.get_run(run["id"]), run)

    def test_abort_helper_keeps_slot_and_prior_cleanup_deadline_is_not_renewed(self):
        first = ControlledSession(block="run", cooperative=True, block_abort=True)
        harness = self.harness(sessions={"a": first})
        run = self.finished(harness, harness.start())
        self.timeout_result(run, "b")
        first.worker.join(1)
        self.assertFalse(first.worker.is_alive())
        self.assertTrue(first.abort_threads[0].is_alive())
        self.assertEqual([did for did, _ in harness.driver.open_calls], ["a"])
        # The first run already exhausted this attempt's fixed cleanup window.
        # A later grace setting cannot create another wait for the same helper.
        harness.engine.device_grace = 2
        next_run = self.finished(harness, harness.start(), timeout=1.2)
        self.timeout_result(next_run, "b")
        self.assertEqual(first.abort_calls, 1)
        self.assertEqual([did for did, _ in harness.driver.open_calls], ["a"])
        first.abort_release.set()
        self.assertEqual(harness.driver.join(), [])
        harness.configuration["devices"] = [harness.configuration["devices"][1]]
        recovered = self.finished(harness, harness.start())
        self.assert_normal(harness, recovered, "b")

    def test_reduced_parallel_limit_counts_workers_left_by_previous_run(self):
        first, second = ControlledSession(block="run"), ControlledSession(block="run")
        harness = self.harness(ids=("a", "b"), parallel=2, sessions={"a": first, "b": second})
        self.finished(harness, harness.start())
        harness.configuration["ssh"]["parallel"] = 1
        harness.configuration["devices"] = validate({"devices": [
            {"id": "c", "name": "MM c", "role": "MM", "host": "192.0.2.3"}
        ]})["devices"]
        third = ControlledSession()
        harness.driver.set_session("c", third)
        first.release.set()
        first.worker.join(1)
        run = self.finished(harness, harness.start())
        self.timeout_result(run, "c")
        self.assertFalse(third.opened.is_set())
        second.release.set()
        self.assertEqual(harness.driver.join(), [])
        recovered = self.finished(harness, harness.start())
        self.assert_normal(harness, recovered, "c")

    def test_abandoned_generation_cannot_publish_or_reconnect_same_device(self):
        self.default_limit = 3
        first = ControlledSession(block="run")
        harness = self.harness(ids=("a",), parallel=2, sessions={"a": first})
        old = harness.start()
        self.assertTrue(first.entered.wait(1))
        harness.engine.max_run_seconds = 0
        self.assertTrue(harness.engine.abandon_stuck_run())
        current = self.finished(harness, harness.start())
        self.finished(harness, old, saved=False)
        self.timeout_result(current, "a")
        self.assertEqual(len(harness.driver.open_calls), 1)
        self.assertEqual(first.abort_calls, 1)
        before = dict(harness.engine.progress)
        first.release.set()
        self.assertEqual(harness.driver.join(), [])
        self.assertEqual(harness.engine.progress, before)
        self.assertEqual(harness.store.get_run(), current)
        self.assertEqual(len(harness.store.list_runs()), 1)
        self.assertFalse(harness.engine.running)

    def test_stop_discards_run_and_late_worker_output(self):
        self.default_limit = 3
        first = ControlledSession(block="run")
        harness = self.harness(ids=("a",), sessions={"a": first})
        running = harness.start()
        self.assertTrue(first.entered.wait(1))
        harness.engine.stop()
        self.finished(harness, running, saved=False)
        self.assertTrue(first.aborted.wait(1))
        before = dict(harness.engine.progress)
        first.release.set()
        self.assertEqual(harness.driver.join(), [])
        self.assertEqual(harness.store.list_runs(), [])
        self.assertEqual(harness.engine.progress, before)
        self.assertEqual(first.abort_calls, 1)
        self.assertFalse(harness.engine.running)

    def test_worker_start_failure_does_not_leave_a_reserved_slot(self):
        harness = self.harness(ids=("a",))
        real_start = threading.Thread.start
        failed = []

        def start(thread):
            if thread.name.startswith("netcheck-dev") and not failed:
                failed.append(thread)
                raise RuntimeError("synthetic worker start failure")
            return real_start(thread)

        with patch.object(threading.Thread, "start", start):
            self.finished(harness, harness.start(), saved=False)
        self.assertEqual(len(failed), 1)
        # Thread startup already failed the whole run before this change.
        # Preserve that contract while releasing its reservation for a retry.
        self.assertEqual(harness.store.list_runs(), [])
        self.assertFalse(harness.engine.running)
        self.assertEqual(harness.driver.open_calls, [])
        recovered = self.finished(harness, harness.start())
        self.assert_normal(harness, recovered, "a")
        self.assertEqual(len(harness.driver.open_calls), 1)

    def test_abort_start_failure_keeps_timeout_bounded_and_does_not_retry_helper(self):
        first = ControlledSession(block="run")
        harness = self.harness(sessions={"a": first})
        real_start = threading.Thread.start
        failed = []

        def start(thread):
            if thread.name == "netcheck-abort":
                failed.append(thread)
                raise RuntimeError("synthetic abort start failure")
            return real_start(thread)

        with patch.object(threading.Thread, "start", start):
            run = self.finished(harness, harness.start())
            self.timeout_result(run, "a")
            self.timeout_result(run, "b")
            repeated = self.finished(harness, harness.start())
            self.timeout_result(repeated, "a")
            self.timeout_result(repeated, "b")
        self.assertEqual(len(failed), 1)
        self.assertEqual(first.abort_calls, 0)
        self.assertTrue(first.worker.is_alive())
        self.assertEqual([did for did, _ in harness.driver.open_calls], ["a"])
        self.assertEqual(sum(t.is_alive() for t in harness.driver.workers), 1)
        before = dict(harness.engine.progress)
        first.release.set()
        self.assertEqual(harness.driver.join(), [])
        self.assertEqual(harness.engine.progress, before)
        self.assertEqual(harness.store.get_run(run["id"]), run)
        self.assertEqual(harness.store.get_run(), repeated)
        self.assertEqual(len(harness.store.list_runs()), 2)

    def test_interpreter_exits_with_noncooperative_collection_and_abort(self):
        """Process exit, rather than a daemon flag alone, covers shutdown safety."""
        root = Path(__file__).resolve().parents[1]
        script = textwrap.dedent("""\
            import sys
            import threading
            from unittest.mock import patch
            sys.path.insert(0, sys.argv[1])
            from test_engine_timeouts import ControlledSession, RunHarness
            import nc.engine as E

            class NeverReturningSession(ControlledSession):
                def stall(self, step):
                    if self.block == step:
                        self.entered.set()
                        self.release.wait()

                def abort(self):
                    self.abort_calls += 1
                    self.abort_threads.append(threading.current_thread())
                    self.aborted.set()
                    self.abort_release.wait()

            first = NeverReturningSession(block="run")
            with patch.object(E, "_DEVICE_POLL_SECONDS", 0.01, create=True), \\
                    patch.object(E, "device_time_limit", return_value=0.05):
                harness = RunHarness(sessions={"a": first})
                harness.engine.device_grace = 0.03
                run_id = harness.engine.run_blocking()
                assert run_id is not None, harness.engine.last_error
                run = harness.store.get_run(run_id)
                assert all(d["status"] == "unknown" for d in run["devices"].values())
                assert first.entered.is_set() and first.aborted.wait(1)
                harness.store._db.close()
                harness.tmp.cleanup()
                print("bounded run stored; interpreter can exit", flush=True)
            # Do not release these synthetic gates: normal interpreter exit
            # must succeed with both workers still blocked in this child only.
            """)
        result = subprocess.run(
            [sys.executable, "-B", "-c", script, str(root / "tests")],
            cwd=root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"),
            capture_output=True, text=True, timeout=8,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("bounded run stored; interpreter can exit", result.stdout)


if __name__ == "__main__":
    unittest.main()
