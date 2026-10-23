"""Malformed device numbers affect their own metric, without losing the run.

All inputs are synthetic or the existing Demo driver. Tests use memory-only
credentials and temporary SQLite databases; no real device connection is allowed.
"""
from __future__ import annotations

import copy
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nc import parsers as P
from nc.collector import CmdResult, DeviceCollection
from nc.config import validate
from nc.credentials import Credential, CredentialStore
from nc.demo import DEMO_CONFIG, DemoWorld
from nc.engine import Engine
from nc.evaluate import eval_backbone, eval_common, evaluate_run
from nc.store import Store


LONG = "9" * 5000
FLOAT_OVERFLOW = "9" * 400
NOW = 1700000000.0
CPU_TABLE = "Slot CPU Last 5 sec Last 1 min Last 5 min\n"
GOOD_COMMON = {
    "version": "MODEL: Aruba7240XM), Version 8.10.0.10\nSwitch uptime is 2 days 3 hours",
    "cpu": "user 1% system 2% idle 97%",
    "memory": "total: 1000, used: 200, free: 800",
}


def command(key, output):
    return CmdResult(key, key, "show " + key, output, True, "")


def common(overrides=None, previous=None):
    outputs = dict(GOOD_COMMON)
    outputs.update(overrides or {})
    dc = DeviceCollection("d", True, results={key: command(key, value) for key, value in outputs.items()})
    metrics, checks = {}, []
    eval_common(dc, "MM", validate({})["thresholds"], previous, metrics, checks, NOW)
    return metrics, {item["key"]: item for item in checks}


def vrrp_log(interface="Vlan-interface20", vrid="1"):
    return ("%Oct 22 10:15:32:123 2026 BB VRRP4/6/VRRP_STATUS_CHANGE: "
            f"The status of IPv4 virtual router {vrid} (configured on {interface}) "
            "changed from Master to Backup.")


class NumericParserSafety(unittest.TestCase):
    def test_integer_helper_rejects_non_decimal_digits_without_raising(self):
        for value in ("²", "①", "2²", LONG, "-1", "1.5", "1e2"):
            with self.subTest(value=value[:30]):
                self.assertIsNone(P.to_int(value))
        self.assertEqual(P.to_int(" 1,234 "), 1234)
        self.assertEqual(P.to_int("０１２"), 12)
        self.assertEqual(P.to_int("0"), 0)

    def test_uptime_does_not_reinterpret_invalid_number_suffixes(self):
        for value in (LONG, FLOAT_OVERFLOW, "-5", "1.5", ".5", "1e2", "1e-2", "NaN", "inf"):
            with self.subTest(value=value[:30]):
                self.assertIsNone(P.parse_uptime("uptime is " + value + " days"))
                self.assertIsNone(P.parse_uptime("uptime is 1 day " + value + " hours"))

    def test_normal_uptime_units_zero_and_punctuation_are_preserved(self):
        samples = {
            "Switch uptime is 0 seconds": 0,
            "uptime is 2days,3hours 4mins 5secs": 2 * 86400 + 3 * 3600 + 4 * 60 + 5,
            "uptime is 1 year 2 weeks 3 days 4 hours 5 minutes 6 seconds":
                365 * 86400 + 14 * 86400 + 3 * 86400 + 4 * 3600 + 5 * 60 + 6,
            "uptime is 0002 days": 172800,
            "uptime is +2 days": 172800,
        }
        for text, expected in samples.items():
            with self.subTest(text=text):
                self.assertEqual(P.parse_uptime(text), expected)

    def test_aruba_cpu_rejects_invalid_explicit_percentages(self):
        for field in ("user", "system", "idle"):
            for value in ("-1", "101", "1e2", "1.5.2", "NaN", "inf", FLOAT_OVERFLOW):
                values = {"user": "1", "system": "2", "idle": "97"}
                values[field] = value
                text = " ".join(f"{name} {values[name]}%" for name in ("user", "system", "idle"))
                with self.subTest(field=field, value=value[:30]):
                    self.assertIsNone(P.parse_cpu_aruba(text))

    def test_aruba_cpu_missing_idle_and_normal_rounding_keep_existing_contract(self):
        self.assertEqual(P.parse_cpu_aruba("user 1.1% system 2.2%"),
                         {"user": 1.1, "system": 2.2, "idle": 96.7, "1m": 3.3})
        self.assertEqual(P.parse_cpu_aruba("user 0% system 0% idle 100%"),
                         {"user": 0.0, "system": 0.0, "idle": 100.0, "1m": 0.0})
        self.assertEqual(P.parse_cpu_aruba("user 100% system 0% idle 0%"),
                         {"user": 100.0, "system": 0.0, "idle": 0.0, "1m": 100.0})
        # A new exact sum-to-100 policy would change existing rounded outputs.
        self.assertEqual(P.parse_cpu_aruba("user 1% system 2% idle 96.9%")["1m"], 3.1)

    def test_comware_cpu_rejects_invalid_table_and_detail_values(self):
        for value in ("-2", "101", "1,000", "1e2", "1.5.2", "NaN", "inf", FLOAT_OVERFLOW):
            samples = (
                CPU_TABLE + f"1 0 1% {value}% 3%",
                f"Slot 1 CPU 0 CPU usage:\n1% in last 5 seconds\n{value}% in last 1 minute\n3% in last 5 minutes",
                f"Slot 1 CPU 0 CPU usage:\n5 seconds: 1%\n1 minute: {value}%\n5 minutes: 3%",
            )
            for index, text in enumerate(samples):
                with self.subTest(value=value[:30], form=index):
                    self.assertIsNone(P.parse_cpu_comware(text))

    def test_comware_cpu_normal_slots_and_partial_detail_are_preserved(self):
        expected = {
            "slots": [{"slot": "1/0", "5s": 12.0, "1m": 11.0, "5m": 9.0},
                      {"slot": "2/0", "5s": 8.0, "1m": 10.0, "5m": 7.0}],
            "5s": 12.0, "1m": 11.0, "5m": 9.0,
        }
        self.assertEqual(P.parse_cpu_comware(CPU_TABLE + "1 0 12% 11% 9%\n2 0 8% 10% 7%"), expected)
        self.assertEqual(P.parse_cpu_comware("Slot 1 CPU 0 CPU usage:\n0% in last 5 seconds"),
                         {"slots": [{"slot": "1/0", "5s": 0.0}], "5s": 0.0})
        self.assertEqual(P.parse_cpu_comware("6% in last 5 seconds,5% in last 1 minute,4% in last 5 minutes"),
                         {"slots": [{"slot": "1", "5s": 6.0, "1m": 5.0, "5m": 4.0}],
                          "5s": 6.0, "1m": 5.0, "5m": 4.0})
        self.assertEqual(P.parse_cpu_comware("5 seconds:+5%,1 minute:2%,5 minutes:1%"),
                         {"slots": [{"slot": "1", "1m": 2.0, "5m": 1.0}],
                          "1m": 2.0, "5m": 1.0})

    def test_aruba_memory_rejects_invalid_bounds_and_integer_overflow(self):
        samples = (
            "total: 0, used: 0, free: 0", "total: 100, used: 101, free: 0",
            "total: 100, used: 0, free: 101", "total: 100, used: -1, free: 100",
            f"total: {LONG}, used: 1, free: 0", f"total: 1, used: {FLOAT_OVERFLOW}, free: 0",
            f"total: 100, used: 0, free: {LONG}",
            "total:100, used:20, free:8.5", "total:100, used:20, free:8e2",
        )
        for text in samples:
            with self.subTest(text=text[:70]):
                self.assertIsNone(P.parse_mem_aruba(text))

    def test_aruba_memory_normal_zero_full_and_existing_components_are_preserved(self):
        for used, free in ((0, 100), (100, 0), (20, 80), (20, 85)):
            with self.subTest(used=used, free=free):
                self.assertEqual(P.parse_mem_aruba(f"total: 100, used: {used}, free: {free}"),
                                 {"total_kb": 100, "used_kb": used, "free_kb": free,
                                  "used_pct": float(used), "free_ratio": float(100 - used)})

    def test_comware_memory_fallback_rejects_oversized_counts(self):
        for text in (f"Total {LONG} Used 1", f"Total 100 Used {LONG}",
                     f"Total {FLOAT_OVERFLOW} Used 1", "Total 100 Used 101",
                     "Total 100 Used 1.5", "Total 100 Used 1e2"):
            with self.subTest(text=text[:70]):
                self.assertIsNone(P.parse_mem_comware(text))

    def test_comware_memory_invalid_explicit_cells_do_not_become_derived_values(self):
        header = "Slot Total Used Free FreeRatio\n"
        for used, ratio in (("NaN", "40%"), ("inf", "40%"), ("-1", "40%"),
                            (FLOAT_OVERFLOW, "40%"), ("60", "NaN"), ("60", "inf"),
                            ("60", "-1%"), ("60", "101%")):
            bad = f"1 100 {used} 40 {ratio}"
            with self.subTest(used=used[:25], ratio=ratio):
                self.assertIsNone(P.parse_mem_comware(header + bad))
                parsed = P.parse_mem_comware(header + bad + "\n2 100 60 40 40%")
                self.assertEqual(parsed["used_pct"], 60.0)
                self.assertEqual(parsed["slots"], [{"slot": "2", "total_kb": 100, "used_kb": 60,
                                                    "free_kb": 40, "free_ratio": 40.0}])

    def test_comware_memory_normal_missing_columns_and_fallback_are_preserved(self):
        expected = {"free_ratio": 72.0, "used_pct": 28.0, "total_kb": 1000, "used_kb": 280,
                    "free_kb": 720, "slots": [{"slot": "1", "total_kb": 1000, "used_kb": 280,
                                                "free_kb": 720, "free_ratio": 72.0}]}
        self.assertEqual(P.parse_mem_comware("Total 1000 Used 280"), expected)
        self.assertEqual(P.parse_mem_comware("Slot Total Free\n1 1000 720"), expected)
        self.assertEqual(P.parse_mem_comware("FreeRatio 72%"),
                         {"free_ratio": 72.0, "used_pct": 28.0, "slots": []})

    def test_vrrp_snapshot_rejects_oversized_totals_and_group_numbers(self):
        for text in (f"Total number of virtual routers : {LONG}", f"Vlan20 {LONG} Master 120",
                     f"Vlan{LONG} 1 Master 120", f"Vlan20 1 Master 120\nVlan30 {LONG} Backup 100"):
            with self.subTest(text=text[:70]):
                self.assertIsNone(P.parse_vrrp_snapshot(text))

    def test_vrrp_logs_discard_only_the_invalid_numeric_row(self):
        good = vrrp_log()
        expected = P.parse_vrrp_logs(good, now=NOW)
        self.assertEqual(len(expected), 1)
        self.assertEqual(expected[0]["group"], "Vlan20/1")
        for bad in (vrrp_log(vrid=LONG), vrrp_log(interface="Vlan-interface" + LONG)):
            for text in (bad + "\n" + good, good + "\n" + bad):
                with self.subTest(bad=bad[:80], good_first=text.startswith(good)):
                    self.assertEqual(P.parse_vrrp_logs(text, now=NOW), expected)

    def test_vrrp_group_key_normalizes_without_building_unbounded_integers(self):
        self.assertEqual(P.vrrp_group_key(" Vlan-interface０２０ ", "００１"), "Vlan20/1")
        self.assertEqual(P.vrrp_group_key("Bridge-Aggregation10", "1"), "bridge-aggregation10/1")
        self.assertEqual(P.vrrp_group_key("Vlan20", "²"), "Vlan20/²")
        self.assertEqual(P.vrrp_group_key("Vlan" + "0" * 5000 + "20", "0" * 5000 + "1"), "Vlan20/1")
        self.assertEqual(P.vrrp_group_key("Vlan20", LONG), "Vlan20/" + LONG)


class NumericEvaluationSafety(unittest.TestCase):
    def test_invalid_uptime_is_unknown_and_keeps_model_and_other_metrics(self):
        normal, normal_checks = common()
        for suffix in (LONG + " days", "-5 days", "1.5 days", "not available"):
            with self.subTest(suffix=suffix[:40]):
                metrics, checks = common({"version": "MODEL: Aruba7240XM), Version 8.10.0.10\nSwitch uptime is " + suffix})
                self.assertIsNone(metrics["uptime"])
                self.assertEqual(checks["uptime"]["level"], "unknown")
                self.assertEqual(checks["uptime"]["cmd_id"], "version")
                self.assertEqual(checks["uptime"]["command"], "show version")
                self.assertTrue(checks["uptime"]["evidence"])
                for key in ("model", "version", "cpu", "cpu_detail", "mem", "mem_detail"):
                    self.assertEqual(metrics[key], normal[key])
                self.assertEqual(checks["cpu"], normal_checks["cpu"])
                self.assertEqual(checks["memory"], normal_checks["memory"])
                json.dumps(metrics, allow_nan=False)

    def test_invalid_cpu_or_memory_preserves_the_other_common_checks(self):
        normal, normal_checks = common()
        samples = ("cpu", "user 1% system 2% idle " + FLOAT_OVERFLOW + "%", "cpu", "cpu_detail"), (
            "memory", "total: 1, used: " + FLOAT_OVERFLOW + ", free: 0", "mem", "mem_detail")
        for key, output, metric, detail in samples:
            with self.subTest(key=key):
                metrics, checks = common({key: output})
                self.assertEqual(checks[key]["level"], "unknown")
                self.assertNotIn(metric, metrics)
                self.assertNotIn(detail, metrics)
                expected = {k: v for k, v in normal.items() if k not in (metric, detail)}
                self.assertEqual(metrics, expected)
                for other in normal_checks.keys() - {key}:
                    self.assertEqual(checks[other], normal_checks[other])
                json.dumps({"metrics": metrics, "checks": checks}, allow_nan=False)

    def test_unusable_previous_numbers_skip_only_reboot_comparison(self):
        bad_values = (int(FLOAT_OVERFLOW), float("inf"), float("-inf"), float("nan"), "bad", -1)
        for key in ("uptime", "ts"):
            values = bad_values if key == "uptime" else bad_values[:-1]
            for value in values:
                previous = {"uptime": 172800, "ts": NOW - 60}
                previous[key] = value
                for uptime in ("2 hours", "1 minute"):
                    output = {"version": "Switch uptime is " + uptime}
                    with self.subTest(key=key, value_type=type(value).__name__, uptime=uptime):
                        expected = common(output, None)
                        self.assertEqual(common(output, previous), expected)

    def test_normal_recent_and_previous_reboot_contracts_are_preserved(self):
        cases = (
            ("0 seconds", None, "warn"), ("3599 seconds", None, "warn"),
            ("3600 seconds", None, "ok"),
            ("1 hour", {"uptime": 100000, "ts": NOW - 60}, "warn"),
            ("2 days", {"uptime": 172740, "ts": NOW - 60}, "ok"),
            ("1 minute", {"uptime": 0, "ts": NOW - 60}, "ok"),
            ("1 minute", {"uptime": 100000, "ts": 0}, "warn"),
        )
        for uptime, previous, level in cases:
            with self.subTest(uptime=uptime, previous=previous):
                metrics, checks = common({"version": "Switch uptime is " + uptime}, previous)
                self.assertEqual(checks["uptime"]["level"], level)
                self.assertIsNotNone(metrics["uptime"])

    def test_unknown_numeric_metric_does_not_lower_known_warning_or_failure(self):
        cfg = validate({"devices": [{"id": "d", "role": "MM", "host": "192.0.2.1"}]})
        for cpu, expected in ((0, "unknown"), (50, "warn"), (70, "crit")):
            outputs = dict(GOOD_COMMON, version="Switch uptime is " + LONG + " days",
                           cpu=f"user {cpu}% system 0% idle {100 - cpu}%")
            dc = DeviceCollection("d", True, results={key: command(key, value) for key, value in outputs.items()})
            with self.subTest(cpu=cpu):
                result, _ = evaluate_run(cfg, {"d": dc}, {}, {}, {}, now=NOW)
                self.assertEqual(result["devices"]["d"]["status"], expected)
                self.assertEqual(result["summary"]["overall"], expected)
                json.dumps(result, allow_nan=False)

    def test_invalid_vrrp_numbers_do_not_replace_baselines_or_hide_other_checks(self):
        base = {"vrrp": {"Vlan20/1": "Master"}, "intf_up": ["XGE1/0/1"]}
        before = copy.deepcopy(base)
        dc = DeviceCollection("d", True, results={
            "vrrp": command("vrrp", "Total number of virtual routers : " + LONG),
            "interface": command("interface", "XGE1/0/1 UP 1G F A"),
        })
        checks, metrics = [], {}
        after = eval_backbone(dc, base, checks, metrics)
        by_key = {item["key"]: item for item in checks}
        self.assertEqual(by_key["vrrp"]["level"], "unknown")
        self.assertEqual(by_key["interface"]["level"], "ok")
        self.assertEqual(metrics["intf_up"], 1)
        self.assertNotIn("vrrp", metrics)
        self.assertEqual(base, before)
        self.assertEqual(after, before)


class NumericRunPersistence(unittest.TestCase):
    def test_demo_saves_all_devices_and_raw_then_recovers_after_bad_uptime(self):
        cfg = validate({**copy.deepcopy(DEMO_CONFIG), "ssh": {"parallel": 1, "retries": 0},
                        "schedule": {"enabled": False, "background": False},
                        "report": {"excel_auto": False, "notify": False}})
        now = time.time()
        with tempfile.TemporaryDirectory() as folder:
            engines = []

            def make(name, corrupt):
                store = Store(Path(folder) / (name + ".sqlite3"))
                credentials = CredentialStore(persistent=False)
                credentials.set("shared", Credential("synthetic", "test-only"), False)
                world = DemoWorld(speed=0)
                world.devices_provider = lambda: cfg["devices"]
                original = world.output

                def output(device, cmd):
                    text = original(device, cmd)
                    if corrupt and device["id"] == "bb1" and cmd == "display version":
                        return re.sub(r"(uptime\s+is\s+)[^\n]+", lambda m: m.group(1) + LONG + " days",
                                      text, count=1, flags=re.I)
                    return text

                world.output = output
                engine = Engine(SimpleNamespace(get=lambda: copy.deepcopy(cfg)), store, credentials, world, demo=True)
                engine.demo_quiet = True
                engines.append(engine)
                return engine, world, original

            try:
                control, _, _ = make("control", False)
                faulty, world, original = make("faulty", True)
                with patch("socket.create_connection", side_effect=AssertionError("Demo must not connect")):
                    control_id = control.run_blocking("test", now=now)
                    faulty_id = faulty.run_blocking("test", now=now)
                self.assertIsNotNone(control_id, control.last_error)
                self.assertIsNotNone(faulty_id, faulty.last_error)
                normal = control.store.get_run(control_id)
                actual = faulty.store.get_run(faulty_id)
                self.assertEqual(len(actual["devices"]), 14)
                self.assertEqual(faulty.store._db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
                self.assertFalse(faulty.running)
                self.assertEqual(faulty.last_error, "")
                for device_id, expected in normal["devices"].items():
                    got = actual["devices"][device_id]
                    self.assertTrue(got["connected"])
                    if device_id == "bb1":
                        before = dict(expected["metrics"])
                        before["uptime"] = None
                        self.assertEqual(got["metrics"], before)
                        self.assertEqual(next(c for c in got["checks"] if c["key"] == "uptime")["level"], "unknown")
                        self.assertEqual([c for c in got["checks"] if c["key"] != "uptime"],
                                         [c for c in expected["checks"] if c["key"] != "uptime"])
                    else:
                        self.assertEqual(got["metrics"], expected["metrics"])
                        self.assertEqual(got["checks"], expected["checks"])
                        self.assertEqual(got["status"], expected["status"])
                self.assertEqual(faulty.store.baselines(), control.store.baselines())
                raw = faulty.store.get_raw(faulty_id, "bb1", "version")
                self.assertTrue(raw["ok"])
                self.assertIn(LONG + " days", raw["output"])
                self.assertEqual(raw["command"], "display version")
                json.dumps(actual, ensure_ascii=False, allow_nan=False)
                preserved = copy.deepcopy(actual)

                world.output = original
                with patch("socket.create_connection", side_effect=AssertionError("Demo must not connect")):
                    recovered_id = faulty.run_blocking("test", now=now + 3600)
                self.assertIsNotNone(recovered_id, faulty.last_error)
                self.assertNotEqual(recovered_id, faulty_id)
                recovered = faulty.store.get_run(recovered_id)
                uptime = next(c for c in recovered["devices"]["bb1"]["checks"] if c["key"] == "uptime")
                self.assertEqual(uptime["level"], "ok")
                self.assertIsNotNone(recovered["devices"]["bb1"]["metrics"]["uptime"])
                self.assertEqual(len(recovered["devices"]), 14)
                self.assertEqual(faulty.store.get_run(faulty_id), preserved)
                self.assertEqual(faulty.store._db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 2)
                json.dumps(recovered, ensure_ascii=False, allow_nan=False)
            finally:
                for engine in engines:
                    engine.stop()
                    for worker in engine._device_workers:
                        for thread in (worker.thread, worker.abort_thread):
                            if thread:
                                thread.join(2)
                                self.assertFalse(thread.is_alive(), "Demo cleanup left a worker alive")
                    engine.store._db.close()


if __name__ == "__main__":
    unittest.main()
