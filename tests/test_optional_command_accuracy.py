"""Optional status completeness, with local synthetic text only.

The explicit-empty messages/totals below are synthetic parser-contract cases,
not captures proving a firmware's wording. Existing complete fixtures remain
covered, while unknown variants must stay unknown until verified separately.
"""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

from nc import parsers as P
from nc.collector import CmdResult, DeviceCollection
from nc.commands import BB_COMMANDS
from nc.config import validate
from nc.evaluate import eval_backbone, evaluate_run


FX = Path(__file__).parent / "fixtures"
SPECS = {spec.id: spec for spec in BB_COMMANDS}
PARSERS = {"device": P.parse_device_slots_snapshot, "lagg": P.parse_lagg_snapshot,
           "power": P.parse_power_snapshot, "fan": P.parse_fan_snapshot, "ospf": P.parse_ospf_snapshot}
GOOD = {
    "device": "1 SyntheticSwitch Master\n2 SyntheticSwitch Standby",
    "lagg": "BAGG10 Selected 2/2\nBAGG20 Selected 1/1",
    "power": "Slot 1:\n1 Normal\n2 Normal",
    "fan": "Slot 1:\nFan Frame 1 State: Normal\nFan Frame 2 State: Normal",
    "ospf": "Peer 203.0.113.1 State Full\nPeer 203.0.113.2 State 2-Way",
}
PARTIAL = {
    "device": "3 SyntheticSwitch Mystery",
    "lagg": "BAGG30 D 0x8000, 0200-0000-0030",
    "power": "3 Mystery",
    "fan": "Fan Frame 3 State: Mystery",
    "ospf": "203.0.113.3 192.0.2.3 1 37 Mystery Vlan103",
}
HEADER = {
    "device": "Slot Type State Subslot Soft Ver Patch Ver",
    "lagg": "AGG AGG Partner ID Selected Unselected Individual Share\nInterface Mode Ports Ports Ports Type",
    "power": "PowerID State Mode Current(A)",
    "fan": "Slot 1:",
    "ospf": "OSPF Process 1 with Router ID 203.0.113.1\nNeighbor Brief Information\nRouter ID Address Pri Dead-Time State Interface",
}
EMPTY = {"device": "No slots configured.", "lagg": "No aggregation groups configured.",
         "power": "No power supplies installed.", "fan": "No fans installed.", "ospf": "No OSPF peers configured."}
TOTAL_NOUN = {"device": "slots", "lagg": "aggregation groups", "power": "power supplies", "fan": "fans", "ospf": "OSPF peers"}
BASE = {"slots": ["1", "2"], "lagg": {"BAGG10": 2, "BAGG20": 1},
        "power_states": {"1/1": "Normal", "1/2": "Normal"}, "fan_states": {"1/1": "Normal", "1/2": "Normal"},
        "ospf": ["203.0.113.1", "203.0.113.2"], "vrrp": {"Vlan10/1": "Master"}}
FAULT = {"device": "1 SyntheticSwitch Fault", "lagg": "BAGG10 Selected 1/1",
         "power": "Slot 1:\n1 Fault", "fan": "Slot 1:\nFan Frame 1 State: Fault", "ospf": "Peer 203.0.113.1 State Down"}


def command(key, output, ok=True):
    spec = SPECS[key]
    return CmdResult(key, spec.label, spec.commands[0], output, ok,
                     "" if ok else "synthetic command failure", optional=spec.optional)


def evaluate(key, output, base=None, ok=True):
    before = copy.deepcopy(BASE if base is None else base)
    baseline = copy.deepcopy(before)
    checks, metrics = [], {}
    actual = eval_backbone(DeviceCollection("b", True, results={key: command(key, output, ok)}), baseline, checks, metrics)
    if baseline != before:
        raise AssertionError("input baseline was mutated")
    if len(checks) != 1:
        raise AssertionError(f"expected a visible check for {key}, received {checks}")
    return checks[0], actual


class OptionalSnapshots(unittest.TestCase):
    def test_existing_complete_fixtures_remain_usable(self):
        names = {"device": "comware_device.txt", "lagg": "comware_lagg.txt", "power": "comware_power.txt",
                 "fan": "comware_fan.txt", "ospf": "comware_ospf.txt"}
        for key, name in names.items():
            with self.subTest(key=key):
                rows = PARSERS[key]((FX / name).read_text(encoding="utf-8"))
                self.assertIsNotNone(rows)
                self.assertTrue(rows)

    def test_partial_fixtures_are_unknown_and_preserve_all_baselines(self):
        for key, name in (("device", "optional_slots_partial.txt"), ("lagg", "optional_lagg_partial.txt")):
            with self.subTest(key=key):
                output = (FX / name).read_text(encoding="utf-8")
                self.assertIsNone(PARSERS[key](output))
                check, actual = evaluate(key, output)
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(actual, BASE)

    def test_blank_headers_and_unrecognized_formats_are_never_empty_configuration(self):
        for key, parser in PARSERS.items():
            for output in ("", "<synthetic>", SPECS[key].commands[0], HEADER[key], "synthetic unrecognized format"):
                with self.subTest(key=key, output=output):
                    self.assertIsNone(parser(output))
                    check, actual = evaluate(key, output)
                    self.assertEqual(check["level"], "unknown")
                    self.assertEqual(actual, BASE)
                    self.assertEqual(check["cmd_id"], key)

    def test_every_partial_healthy_snapshot_is_unknown_without_seeding_baselines(self):
        for key in PARSERS:
            for baseline in (BASE, {}):
                with self.subTest(key=key, existing=bool(baseline)):
                    check, actual = evaluate(key, GOOD[key] + "\n" + PARTIAL[key], base=baseline)
                    self.assertEqual(check["level"], "unknown")
                    self.assertEqual(actual, baseline)
                    self.assertTrue(check["evidence"])

    def test_command_failure_and_unsupported_output_are_unknown(self):
        for key in PARSERS:
            for output, ok in ((GOOD[key], False), ("% Unrecognized command", True),
                               (GOOD[key] + "\n" + "\n".join(["metadata"] * 7) + "\n% Invalid input", True)):
                with self.subTest(key=key, ok=ok):
                    check, actual = evaluate(key, output, ok=ok)
                    self.assertEqual(check["level"], "unknown")
                    self.assertEqual(actual, BASE)
                    if not ok:
                        self.assertEqual(check["summary"], "synthetic command failure")

    def test_explicit_empty_has_info_without_baseline_but_disappearance_with_baseline(self):
        for key in ("lagg", "power", "fan", "ospf"):
            for output in (EMPTY[key], f"Total number of {TOTAL_NOUN[key]} : 0"):
                with self.subTest(key=key, output=output):
                    parsed = PARSERS[key](output)
                    self.assertIsNotNone(parsed)
                    self.assertFalse(parsed)
                    check, actual = evaluate(key, output, base={})
                    self.assertEqual(check["level"], "info")
                    self.assertEqual(actual, {})
                    check, actual = evaluate(key, output)
                    self.assertEqual(check["level"], "crit")
                    self.assertEqual(actual, BASE)

    def test_physical_device_zero_slots_is_unknown(self):
        for output in (EMPTY["device"], "Total number of slots : 0", "1 SyntheticSwitch Absent"):
            with self.subTest(output=output):
                check, actual = evaluate("device", output, base={})
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(actual, {})

    def test_declared_empty_and_partial_or_real_rows_is_a_contradiction(self):
        for key, parser in PARSERS.items():
            for suffix in (GOOD[key], FAULT[key], PARTIAL[key]):
                with self.subTest(key=key, suffix=suffix):
                    output = f"Total number of {TOTAL_NOUN[key]} : 0\n{suffix}"
                    self.assertIsNone(parser(output))
                    check, actual = evaluate(key, output)
                    self.assertEqual(check["level"], "unknown")
                    self.assertEqual(actual, BASE)

    def test_conflicting_and_incomplete_totals_are_unknown(self):
        for key in PARSERS:
            for total_lines in (f"Total number of {TOTAL_NOUN[key]} : 1",
                                f"Total number of {TOTAL_NOUN[key]} : 3",
                                f"Total number of {TOTAL_NOUN[key]} : 2\nTotal number of {TOTAL_NOUN[key]} : 0"):
                with self.subTest(key=key, total=total_lines):
                    check, actual = evaluate(key, GOOD[key] + "\n" + total_lines)
                    self.assertEqual(check["level"], "unknown")
                    self.assertEqual(actual, BASE)

    def test_duplicate_id_with_conflicting_state_cannot_establish_a_fault_or_baseline(self):
        for key in PARSERS:
            output = GOOD[key] + "\n" + FAULT[key]
            with self.subTest(key=key):
                self.assertIsNone(PARSERS[key](output))
                check, actual = evaluate(key, output)
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(actual, BASE)

    def test_empty_new_hardware_section_is_partial(self):
        for key in ("power", "fan"):
            check, actual = evaluate(key, GOOD[key] + "\nSlot 2:")
            self.assertEqual(check["level"], "unknown")
            self.assertEqual(actual, BASE)

    def test_missing_state_or_interface_in_ospf_table_is_partial(self):
        for row in ("203.0.113.3 192.0.2.3", "203.0.113.3 192.0.2.3 1 37 Full"):
            check, actual = evaluate("ospf", GOOD["ospf"] + "\n" + row)
            self.assertEqual(check["level"], "unknown")
            self.assertEqual(actual, BASE)

    def test_invalid_lagg_counts_are_not_shifted_into_valid_columns(self):
        for row in ("BAGG10 Selected 3/2", "BAGG10 Selected -1/2", "BAGG10 Selected 1.5/2",
                    "BAGG10 D None -1 0 0 Shar", "BAGG10 D None 2 unknown 0 Shar",
                    "BAGG10 D None 2 0 -1 Shar", "BAGG10 Selected " + "9" * 100 + "/2"):
            with self.subTest(row=row):
                self.assertEqual(P.parse_lagg(row), {})
                check, actual = evaluate("lagg", row)
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(actual, BASE)

    def test_zero_valid_lagg_counts_and_static_missing_partner_remain_supported(self):
        for row in ("BAGG10 Selected 0/0", "BAGG10 S None 0 0 0 Shar", "BAGG10 S 0 0 0 NonS", "BAGG10 0 0"):
            with self.subTest(row=row):
                self.assertEqual(P.parse_lagg_snapshot(row), {"BAGG10": {"selected": 0, "unselected": 0}})

    def test_unrecognized_slot_state_is_not_a_normal_baseline(self):
        for row in ("Slot 1 State Mystery", "1 SyntheticSwitch Mystery"):
            check, actual = evaluate("device", row, base={})
            self.assertEqual(check["level"], "unknown")
            self.assertEqual(actual, {})

    def test_unclassified_power_state_cannot_seed_baseline(self):
        check, actual = evaluate("power", "1 Off\n2 NotSupply", base={})
        self.assertEqual(check["level"], "unknown")
        self.assertEqual(actual, {})

    def test_unclassified_power_state_cannot_prove_other_items_missing(self):
        check, actual = evaluate("power", "Slot 1:\nPower 1 State Mystery")
        self.assertEqual(check["level"], "unknown")
        self.assertEqual(actual, BASE)

    def test_complete_smaller_snapshot_can_prove_disappearance(self):
        one = {"device": "1 SyntheticSwitch Master", "lagg": "BAGG10 Selected 2/2",
               "power": "Slot 1:\n1 Normal", "fan": "Slot 1:\nFan Frame 1 State: Normal", "ospf": "Peer 203.0.113.1 State Full"}
        for key, output in one.items():
            with self.subTest(key=key):
                check, actual = evaluate(key, output)
                self.assertEqual(check["level"], "crit")
                self.assertEqual(actual, BASE)


class PartialKnownEvidence(unittest.TestCase):
    def test_known_power_fault_and_unclassified_state_both_remain_visible(self):
        check, actual = evaluate("power", "Slot 1:\nPower 1 State Fault\nPower 2 State Mystery")
        self.assertEqual(check["level"], "crit")
        self.assertIn("일부 해석 불가", check["summary"])
        self.assertEqual(check["evidence"], ["Power 1 State Fault", "Power 2 State Mystery"])
        self.assertEqual(actual, BASE)

    def test_individually_valid_faults_survive_without_any_baseline_update(self):
        for key in PARSERS:
            with self.subTest(key=key):
                check, actual = evaluate(key, FAULT[key] + "\n" + PARTIAL[key])
                self.assertEqual(check["level"], "crit")
                self.assertIn("일부 해석 불가", check["summary"])
                self.assertTrue(check["evidence"])
                self.assertEqual(actual, BASE)

    def test_unselected_warning_survives_partial_output(self):
        check, actual = evaluate("lagg", "BAGG10 Selected 2/3\n" + PARTIAL["lagg"])
        self.assertEqual(check["level"], "warn")
        self.assertIn("일부 해석 불가", check["summary"])
        self.assertEqual(actual, BASE)

    def test_explicit_absent_retains_prior_normal_failure(self):
        rows = {"device": "1 SyntheticSwitch Absent", "power": "Slot 1:\n1 Absent",
                "fan": "Slot 1:\nFan Frame 1 State: Absent"}
        for key, output in rows.items():
            with self.subTest(key=key):
                check, actual = evaluate(key, output + "\n" + PARTIAL[key])
                self.assertEqual(check["level"], "crit")
                self.assertEqual(actual, BASE)

    def test_complete_healthy_first_run_can_establish_its_baseline(self):
        for key, output in GOOD.items():
            with self.subTest(key=key):
                check, actual = evaluate(key, output, base={})
                self.assertEqual(check["level"], "ok")
                self.assertTrue(actual)


class WholeRunStatus(unittest.TestCase):
    def setUp(self):
        self.cfg = validate({"devices": [{"id": "b", "name": "Synthetic BB", "host": "192.0.2.1", "role": "BB"}]})

    def test_optional_parse_failure_is_visible_in_device_and_run_status(self):
        for key in PARSERS:
            with self.subTest(key=key):
                dc = DeviceCollection("b", True, results={key: command(key, "unrecognized synthetic output")})
                run, new = evaluate_run(self.cfg, {"b": dc}, {}, {"b": copy.deepcopy(BASE)}, {})
                self.assertEqual(run["devices"]["b"]["status"], "unknown")
                self.assertEqual(run["summary"]["overall"], "unknown")
                self.assertEqual(new, {})

    def test_log_and_extra_keep_their_existing_reference_only_contract(self):
        for log_ok in (True, False):
            dc = DeviceCollection("b", True, results={"log": command("log", "synthetic unparsed log", log_ok),
                                                      "extra1": CmdResult("extra1", "extra", "display extra", "raw text", True)})
            run, _ = evaluate_run(self.cfg, {"b": dc}, {}, {}, {})
            levels = {c["key"]: c["level"] for c in run["devices"]["b"]["checks"]}
            self.assertEqual(levels, {"log": "info", "extra1": "info"})


if __name__ == "__main__":
    unittest.main()
