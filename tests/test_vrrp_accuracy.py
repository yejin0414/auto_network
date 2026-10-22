"""VRRP 전환 연결과 그룹 소실 판정: 순수 함수만 사용하고 장비에는 접속하지 않음."""

import copy
import unittest
from datetime import datetime

from nc.collector import CmdResult, DeviceCollection
from nc.engine import Engine
from nc.evaluate import eval_backbone
from nc.parsers import log_time_ts, parse_vrrp_logs, parse_vrrp_snapshot, vrrp_group_key


def event(group="Vlan20/1", old="Master", new="Backup", ts=1500.0, text="transition"):
    interface, vrid = group.rsplit("/", 1)
    return {"group": group, "interface": interface, "vrid": vrid, "old": old, "new": new,
            "ts": ts, "time": "device time", "text": text}


def history(logs, *, old=None, current=None, previous_times=None):
    old = old if old is not None else {"Vlan20/1": "Master"}
    current = current if current is not None else {"Vlan20/1": "Backup"}
    previous_times = previous_times if previous_times is not None else {"started": 1000.0, "finished": 1040.0}
    prev = {**previous_times, "devices": {"b": {"metrics": {"vrrp": old}}}}
    cur = {"devices": {"b": {"name": "Demo backbone", "metrics": {"vrrp": current, "vrrp_logs": logs}}}}
    return Engine._vrrp_rows(prev, cur, 2, 2000.0)


def evaluate_vrrp(output, baseline=None, ok=True):
    base = copy.deepcopy(baseline if baseline is not None else {"vrrp": {"Vlan10/1": "Master", "Vlan20/1": "Backup"}})
    before = copy.deepcopy(base)
    command = CmdResult("vrrp", "VRRP", "display vrrp", output, ok, "" if ok else "mock read failure")
    dc = DeviceCollection("b", True, results={"vrrp": command})
    checks, metrics = [], {}
    new_base = eval_backbone(dc, base, checks, metrics)
    if base != before:
        raise AssertionError("evaluation mutated the supplied baseline")
    return checks[0], metrics, new_base


class VrrpHistoryAccuracy(unittest.TestCase):
    def test_same_vrid_on_another_vlan_does_not_supply_exact_time(self):
        rows = history([event("Vlan30/1")])
        self.assertEqual([r["source"] for r in rows], ["check", "log"])
        self.assertNotIn("log_ts", rows[0])
        self.assertEqual(rows[1]["grp"], "Vlan30/1")

    def test_normalized_interface_and_vrid_match(self):
        for alias in ("Vlan-interface020/01", "Vlanif20/1", "vlan20/1"):
            with self.subTest(alias=alias):
                rows = history([event(alias)], old={"Vlan-interface20/1": "Master"})
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["source"], "check+log")
                self.assertEqual(rows[0]["grp"], "Vlan20/1")
                self.assertEqual(rows[0]["log_ts"], 1500)

    def test_both_old_and_new_states_must_match(self):
        for log in (event(old="Initialize"), event(new="Master")):
            with self.subTest(log=log):
                rows = history([log])
                self.assertEqual(rows[0]["source"], "check")
                self.assertEqual(rows[1]["source"], "log")

    def test_missing_interface_is_not_an_exact_group_match(self):
        for current_group in ("Vlan20/1", "/1"):
            with self.subTest(current_group=current_group):
                rows = history([event("/1")], old={current_group: "Master"}, current={current_group: "Backup"})
                self.assertEqual(rows[0]["source"], "check")
                self.assertNotIn("log_ts", rows[0])

    def test_old_future_or_unknown_times_stay_separate(self):
        for ts in (999, 1001, 1040, 2000.1, None, float("nan"), float("inf")):
            with self.subTest(ts=ts):
                rows = history([event(ts=ts)])
                self.assertEqual([r["source"] for r in rows], ["check", "log"])
                self.assertNotIn("log_ts", rows[0])

    def test_current_boundary_is_allowed_and_legacy_started_is_used(self):
        self.assertEqual(history([event(ts=2000)])[0]["source"], "check+log")
        self.assertEqual(history([event(ts=1001)], previous_times={"started": 1000})[0]["source"], "check+log")
        self.assertEqual(history([event(ts=1000)], previous_times={"started": 1000})[0]["source"], "check")

    def test_missing_or_reversed_observation_interval_cannot_match(self):
        for times in ({}, {"started": 2100, "finished": 2140}, {"started": float("nan")}):
            with self.subTest(times=times):
                self.assertEqual(history([event()], previous_times=times)[0]["source"], "check")

    def test_multiple_transitions_are_ambiguous_in_either_log_order(self):
        logs = [event(ts=1200, text="first"), event(ts=1800, text="second")]
        for ordered in (logs, list(reversed(logs))):
            rows = history(ordered)
            self.assertEqual([r["source"] for r in rows], ["check", "log", "log"])
            self.assertNotIn("log_ts", rows[0])

    def test_intermediate_transitions_prevent_an_incorrect_direct_match(self):
        logs = [event(ts=1200), event(old="Backup", new="Initialize", ts=1300, text="second"),
                event(old="Initialize", new="Backup", ts=1400, text="third")]
        rows = history(logs)
        self.assertEqual(rows[0]["source"], "check")
        self.assertEqual(len(rows), 4)

    def test_unknown_time_in_same_group_keeps_matching_ambiguous(self):
        rows = history([event(), event(ts=None, text="undated")])
        self.assertEqual(rows[0]["source"], "check")
        self.assertEqual(len(rows), 3)

    def test_exact_duplicate_log_is_consumed_once(self):
        log = event()
        rows = history([log, dict(log)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "check+log")

    def test_each_vlan_transition_uses_only_its_own_event(self):
        rows = history([event("Vlan30/1", ts=1700, text="vlan30"), event("Vlan20/1", ts=1500, text="vlan20")],
                       old={"Vlan20/1": "Master", "Vlan30/1": "Master"},
                       current={"Vlan20/1": "Backup", "Vlan30/1": "Backup"})
        self.assertEqual({r["grp"]: r["log_ts"] for r in rows}, {"Vlan20/1": 1500, "Vlan30/1": 1700})
        self.assertTrue(all(r["source"] == "check+log" for r in rows))


class VrrpSnapshotAccuracy(unittest.TestCase):
    def test_missing_one_group_is_critical_and_preserves_baseline(self):
        check, metrics, base = evaluate_vrrp("Total number of virtual routers : 1\nVlan10 1 Master 120")
        self.assertEqual(check["level"], "crit")
        self.assertIn("Vlan20/1: 그룹 사라짐", check["evidence"])
        self.assertEqual(metrics["vrrp"], {"Vlan10/1": "Master"})
        self.assertEqual(base["vrrp"], {"Vlan10/1": "Master", "Vlan20/1": "Backup"})

    def test_explicit_empty_is_loss_when_baseline_exists(self):
        for output in ("Total number of virtual routers : 0", "No VRRP groups configured."):
            with self.subTest(output=output):
                check, metrics, base = evaluate_vrrp(output)
                self.assertEqual(check["level"], "crit")
                self.assertEqual(metrics["vrrp"], {})
                self.assertEqual(len(base["vrrp"]), 2)

    def test_unparseable_partial_and_failed_commands_are_unknown(self):
        for output, ok in (("", True), ("unknown output format", True), ("", False),
                           ("Total number of virtual routers : 2\nVlan10 1 Master 120", True),
                           ("Total number of virtual routers : 0\nVlan10 1 Master 120", True)):
            with self.subTest(output=output, ok=ok):
                check, metrics, base = evaluate_vrrp(output, ok=ok)
                self.assertEqual(check["level"], "unknown")
                self.assertNotIn("vrrp", metrics)
                self.assertEqual(len(base["vrrp"]), 2)

    def test_fresh_empty_or_abnormal_state_does_not_create_baseline(self):
        for output, level in (("Total number of virtual routers : 0", "ok"), ("Vlan10 1 Initialize 100", "crit")):
            with self.subTest(output=output):
                check, _, base = evaluate_vrrp(output, baseline={})
                self.assertEqual(check["level"], level)
                self.assertNotIn("vrrp", base)

    def test_acknowledged_baseline_can_be_recreated_from_healthy_snapshot(self):
        check, _, base = evaluate_vrrp("Vlan-interface10 1 Backup 100", baseline={"ospf": ["192.0.2.1"]})
        self.assertEqual(check["level"], "ok")
        self.assertEqual(base, {"ospf": ["192.0.2.1"], "vrrp": {"Vlan10/1": "Backup"}})

    def test_interface_alias_change_is_not_loss_or_role_change(self):
        baseline = {"vrrp": {"Vlan-interface020/01": "Master"}}
        check, _, base = evaluate_vrrp("Vlanif20 1 Master 100", baseline=baseline)
        self.assertEqual(check["level"], "ok")
        self.assertEqual(base, baseline)

    def test_duplicate_group_and_unknown_state_are_not_complete_snapshots(self):
        for output in ("Vlan20 1 Master 120\nVlanif20 1 Backup 100", "VRID 1 State Mystery"):
            self.assertIsNone(parse_vrrp_snapshot(output))

    def test_unparsed_table_rows_cannot_imply_missing_or_empty_configuration(self):
        for output in ("Vlan10 1 Master\nVlan20 1 UnknownState", "Vlan10 1 Master\nVlan20 1",
                       "Total number of virtual routers : 0\nVlan20 1 UnknownState"):
            with self.subTest(output=output):
                check, metrics, base = evaluate_vrrp(output)
                self.assertEqual(check["level"], "unknown")
                self.assertNotIn("vrrp", metrics)
                self.assertEqual(len(base["vrrp"]), 2)

    def test_verbose_group_header_without_state_is_unknown_even_without_total(self):
        # Synthetic incomplete variants; documented Comware verbose output puts
        # Interface, VRID and Admin Status/State on separate lines.
        for header in ("Vlan-interface20 | Virtual Router ID : 1", "Interface Vlan-interface20\n  VRID : 1",
                       "Interface Vlan-interface20", "Vlan-interface20"):
            with self.subTest(header=header):
                check, metrics, base = evaluate_vrrp("Vlan10 1 Master\n" + header)
                self.assertEqual(check["level"], "unknown")
                self.assertNotIn("vrrp", metrics)
                self.assertEqual(len(base["vrrp"]), 2)


class VrrpLogTimeAccuracy(unittest.TestCase):
    def test_milliseconds_are_preserved(self):
        expected = datetime(2026, 10, 22, 10, 15, 32, 123000).timestamp()
        self.assertAlmostEqual(log_time_ts("Oct 22 10:15:32:123 2026"), expected, places=5)

    def test_yearless_log_uses_observed_run_year_not_wall_clock(self):
        now = datetime(2025, 1, 1, 1).timestamp()
        text = ("%Dec 31 23:59:59:999 Demo VRRP/6/STATE_CHANGE: Interface Vlan-interface20, "
                "VRID 1, state from Master to Backup.")
        logs = parse_vrrp_logs(text, now=now)
        self.assertAlmostEqual(logs[0]["ts"], datetime(2024, 12, 31, 23, 59, 59, 999000).timestamp(), places=5)

    def test_invalid_leap_day_rollover_returns_unknown(self):
        self.assertIsNone(log_time_ts("Feb 29 00:00:00", now=datetime(2024, 1, 1).timestamp()))

    def test_normalization_keeps_distinct_vlan_groups(self):
        self.assertEqual(vrrp_group_key(" VLAN-interface 020 ", "01"), "Vlan20/1")
        self.assertNotEqual(vrrp_group_key("Vlan20", "1"), vrrp_group_key("Vlan30", "1"))


if __name__ == "__main__":
    unittest.main()
