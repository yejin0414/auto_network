"""Synthetic S7500E-family grammar regressions, not real 7506 captures.

Headers and state meanings are documented by H3C; board names, versions,
readings and combinations below are synthetic test data.
https://www.h3c.com/cn/d_201106/716357_30005_0.htm
https://www.h3c.com/en/Support/Resource_Center/EN/Switches/Catalog/S7500E/S7500E/Technical_Documents/Reference_Guides/Command_References/H3C_CR-22188/01/202409/2275338_294551_0.htm
https://www.h3c.com/cn/Service/Document_Software/Document_Center/Switches/Catalog/S7500E/S7500E-XS/Maintenance/Troubleshooting/H3C_S7500E-XS_TG-R7178-6W100/?CHID=211761
"""
import unittest
from pathlib import Path

from nc import parsers as P
from tests.test_optional_command_accuracy import evaluate


DEVICE_HEADER = "Slot No. Brd Type Brd Status Subslot Num Sft Ver Patch Ver"
IRF_HEADER = "Chassis Slot Type State Subslot Soft Ver Patch Ver"
POWER_HEADER = "PowerID State Mode Current(A) Voltage(V) Power(W)"
DEVICE = DEVICE_HEADER + "\n0 SYNTHETIC-MPU Slave 0 TEST-0000 None\n1 SYNTHETIC-MPU Master 0 TEST-0000 None\n2 NONE Absent 0 NONE None"
IRF = IRF_HEADER + "\n1 0 SYNTHETIC-MPU Master 0 TEST-0000 None\n2 0 SYNTHETIC-MPU Slave 0 TEST-0000 None"
POWER = "Chassis 1:\nPower 1 State: Normal\nPower 2 State: Absent\nChassis 2:\nPower 1 State: Normal\nPower 2 State: Normal"


class S7506Hardware(unittest.TestCase):
    def test_standalone_documented_header_and_slave_role(self):
        rows = P.parse_device_slots_snapshot("<Synthetic>display device\n" + DEVICE + "\n<Synthetic>")
        self.assertEqual([(r["slot"], r["state"]) for r in rows],
                         [("0", "Slave"), ("1", "Master"), ("2", "Absent")])
        check, base = evaluate("device", DEVICE, base={})
        self.assertEqual(check["level"], "ok")
        self.assertEqual(base, {"slots": ["0", "1"]})
        without_patch = "\n".join(line.rsplit(" ", 1)[0] for line in DEVICE.splitlines()[1:])
        self.assertIsNotNone(P.parse_device_slots_snapshot(DEVICE_HEADER.replace(" Patch Ver", "") + "\n" + without_patch))

    def test_irf_keeps_chassis_and_slot_identity(self):
        rows = P.parse_device_slots_snapshot(IRF)
        self.assertEqual([r["slot"] for r in rows], ["1/0", "2/0"])
        self.assertEqual([r["slot"] for r in P.parse_device_slots(IRF)], ["1/0", "2/0"])
        check, base = evaluate("device", IRF, base={})
        self.assertEqual(check["level"], "ok")
        self.assertEqual(base, {"slots": ["1/0", "2/0"]})

    def test_irf_fault_absence_and_disappearance_keep_previous_baseline(self):
        before = {"slots": ["1/0", "2/0"]}
        for output in (IRF.replace("Slave", "Fault"), IRF.replace("Slave", "Absent"),
                       "\n".join(IRF.splitlines()[:2])):
            with self.subTest(output=output):
                check, after = evaluate("device", output, base=before)
                self.assertEqual(check["level"], "crit")
                self.assertEqual(after, before)

    def test_device_unknown_state_truncation_and_metadata_do_not_seed(self):
        partials = [DEVICE.replace("Slave", "Mystery"), DEVICE_HEADER, DEVICE + "\n" + DEVICE_HEADER,
                    DEVICE_HEADER + "\n0 SYNTHETIC-MPU Slave", IRF_HEADER + "\n1 0 SYNTHETIC-MPU Fault",
                    IRF_HEADER + "\n1 0 SYNTHETIC-MPU Master 0", IRF + "\nunknown metadata",
                    IRF + "\n2 1 SYNTHETIC-LPU Normal", IRF.replace("Master 0", "Master unknown"),
                    IRF.replace("Master 0", "Master " + "9" * 100),
                    IRF.replace(IRF_HEADER, "Slot Type State Subslot Soft Ver Patch Ver").replace("Slave", "Fault")]
        for output in partials:
            with self.subTest(output=output):
                self.assertIsNone(P.parse_device_slots_snapshot(output))
                check, after = evaluate("device", output, base={})
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(after, {})

    def test_device_duplicate_and_conflicting_counts_do_not_prove_fault(self):
        outputs = [IRF + "\n2 0 SYNTHETIC-MPU Fault 0 TEST-0000 None",
                   IRF.replace("Slave", "Fault") + "\nTotal number of slots: 0",
                   IRF + "\nTotal number of slots: 3",
                   IRF + "\nTotal number of slots: 2\nTotal number of slots: 3"]
        before = {"slots": ["1/0", "2/0"]}
        for output in outputs:
            with self.subTest(output=output):
                self.assertIsNone(P.parse_device_slots_snapshot(output))
                check, after = evaluate("device", output, base=before)
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(after, before)

    def test_complete_irf_fault_survives_partial_healthy_other_member(self):
        output = IRF_HEADER + "\n1 0 SYNTHETIC-MPU Fault 0 TEST-0000 None\n2 0 SYNTHETIC-MPU Normal"
        before = {"slots": ["1/0", "2/0"]}
        check, after = evaluate("device", output, base=before)
        self.assertEqual(check["level"], "crit")
        self.assertIn("일부 해석 불가", check["summary"])
        self.assertIn("1 0 SYNTHETIC-MPU Fault", check["evidence"][0])
        self.assertEqual(after, before)

    def test_power_standalone_and_irf_state_lines(self):
        standalone = "Power 1 State: Normal\nPower 2 State: Absent"
        check, base = evaluate("power", standalone, base={})
        self.assertEqual(check["level"], "ok")
        self.assertEqual(base, {"power_states": {"/1": "Normal", "/2": "Absent"}})
        rows = P.parse_power_snapshot(POWER)
        self.assertEqual([(r["slot"], r["id"]) for r in rows], [("1", "1"), ("1", "2"), ("2", "1"), ("2", "2")])
        self.assertEqual(P.parse_power(POWER), rows)
        check, base = evaluate("power", POWER, base={})
        self.assertEqual(check["level"], "ok")
        self.assertEqual(base["power_states"], {"1/1": "Normal", "1/2": "Absent", "2/1": "Normal", "2/2": "Normal"})

    def test_power_input_reading_and_documented_table_variants(self):
        for preamble, header, suffix, slot in (("Input Power: 321.0 W", POWER_HEADER + " FanDirection", " --", ""),
                                                ("Slot 1\nInput Power: 267(W)", POWER_HEADER, "", "1")):
            output = preamble + "\n" + header + "\n1 Normal AC -- -- --" + suffix + "\n2 Absent -- -- -- --" + suffix
            with self.subTest(preamble=preamble):
                rows = P.parse_power_snapshot(output)
                self.assertEqual([(r["slot"], r["id"], r["state"]) for r in rows], [(slot, "1", "Normal"), (slot, "2", "Absent")])
                check, base = evaluate("power", output, base={})
                self.assertEqual(check["level"], "ok")
                self.assertTrue(base)
                faulty, updated = evaluate("power", output.replace("Normal", "Faulty"), base={})
                self.assertEqual(faulty["level"], "crit")
                self.assertEqual(updated, {})

    def test_power_new_format_absent_or_missing_normal_is_critical(self):
        before = {"power_states": {"1/1": "Normal", "2/1": "Normal", "2/2": "Normal"}}
        for output in (POWER.replace("Power 2 State: Normal", "Power 2 State: Absent"),
                       POWER.rsplit("\n", 1)[0]):
            with self.subTest(output=output):
                check, after = evaluate("power", output, base=before)
                self.assertEqual(check["level"], "crit")
                self.assertEqual(after, before)

    def test_power_partial_duplicate_and_mixed_sections_remain_unknown(self):
        outputs = [POWER + "\nChassis 3:", "Chassis 1:\nChassis 2:\nPower 1 State: Normal",
                   POWER + "\nPower 2 State: Fault", POWER.replace("Chassis 2:", "Slot 2:"),
                   "Input Power: 321.0 W", "Input Power: 321.0 W\n" + POWER_HEADER,
                   "Input Power: missing\n1 Normal", "Input Power: 321.0 W\nInput Power: 322.0 W\n1 Normal",
                   POWER + "\nChassis 2:\nPower 3 State: Normal",
                   POWER + "\nTotal number of power supplies: 0",
                   POWER + "\nTotal number of power supplies: 5"]
        before = {"power_states": {"1/1": "Normal", "2/1": "Normal", "2/2": "Normal"}}
        for output in outputs:
            with self.subTest(output=output):
                self.assertIsNone(P.parse_power_snapshot(output))
                check, after = evaluate("power", output, base=before)
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(after, before)

    def test_power_table_truncation_is_not_independent_fault_evidence(self):
        output = "Input Power: 321.0 W\n" + POWER_HEADER + "\n1 Normal AC -- -- --\n2 Faulty"
        check, after = evaluate("power", output, base={})
        self.assertEqual(check["level"], "unknown")
        self.assertEqual(after, {})
        output = output.replace("1 Normal", "1 Faulty").replace("2 Faulty", "2 Normal")
        check, after = evaluate("power", output, base={})
        self.assertEqual(check["level"], "crit")
        self.assertIn("일부 해석 불가", check["summary"])
        self.assertEqual(after, {})

    def test_power_partial_fault_has_correct_chassis_and_does_not_seed(self):
        output = POWER.replace("Chassis 2:\nPower 1 State: Normal", "Chassis 2:\nPower 1 State: Faulty") + "\nunknown metadata"
        rows = P.optional_partial_rows(output, "power")
        self.assertEqual([(r["slot"], r["id"]) for r in rows if r["state"] == "Faulty"], [("2", "1")])
        check, after = evaluate("power", output, base={})
        self.assertEqual(check["level"], "crit")
        self.assertIn("일부 해석 불가", check["summary"])
        self.assertEqual(after, {})

    def test_power_unknown_state_and_truncated_command_never_seed(self):
        for output in (POWER.replace("Normal", "Mystery"), POWER + "\n---- More ----",
                       POWER + "\n% Invalid input", POWER + "\nPermission denied"):
            with self.subTest(output=output):
                check, after = evaluate("power", output, base={})
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(after, {})

    def test_state_prefixes_never_become_healthy_or_fault_tokens(self):
        outputs = [("device", DEVICE.replace("Slave", "Slave-Unknown")),
                   ("device", IRF.replace("Master", "Master-Unknown")),
                   ("device", "Slot 1 State Normal-Unknown"),
                   ("device", "Slot 1 State Fault-Unknown"),
                   ("power", "1 Normal-Unknown"),
                   ("power", "Power 1 State: Normal-Unknown"),
                   ("power", "Power 1 State: Faulty-Unknown"),
                   ("power", "Chassis 1:\nPower 1 State: Absent-Unknown")]
        for key, output in outputs:
            before = {"slots": ["1", "0"], "power_states": {"1/1": "Normal", "/1": "Normal"}}
            for baseline in ({}, before):
                with self.subTest(key=key, output=output, baseline=baseline):
                    check, after = evaluate(key, output, base=baseline)
                    self.assertEqual(check["level"], "unknown")
                    self.assertEqual(after, baseline)

    def test_malformed_power_section_cannot_reuse_previous_chassis(self):
        before = {"power_states": {"1/1": "Normal", "1/2": "Normal"}}
        for bad_section in ("Chassis X:", "Chassis -2:", "Chassis 2: truncated", "Slot X:"):
            for state in ("Absent", "Faulty", "Normal"):
                output = "Chassis 1:\nPower 1 State: Normal\n" + bad_section + "\nPower 2 State: " + state
                with self.subTest(section=bad_section, state=state):
                    self.assertIsNone(P.parse_power_snapshot(output))
                    self.assertEqual(P.optional_partial_rows(output, "power"), [])
                    check, after = evaluate("power", output, base=before)
                    self.assertEqual(check["level"], "unknown")
                    self.assertEqual(after, before)

    def test_unheaded_device_rows_cannot_change_identity_format(self):
        for output in ("1 SyntheticSwitch Master\n" + IRF,
                       "1 SyntheticSwitch Fault\n" + IRF,
                       "1 SyntheticSwitch Master\n" + "\n".join(IRF.splitlines()[1:]),
                       "\n".join(IRF.splitlines()[1:]) + "\n1 SyntheticSwitch Master",
                       "1 SyntheticSwitch Master\n" + DEVICE):
            for baseline in ({}, {"slots": ["1", "2"]}):
                with self.subTest(output=output, baseline=baseline):
                    self.assertIsNone(P.parse_device_slots_snapshot(output))
                    check, after = evaluate("device", output, base=baseline)
                    self.assertEqual(check["level"], "unknown")
                    self.assertEqual(after, baseline)

    def test_power_reading_with_zero_total_is_not_empty_configuration(self):
        before = {"power_states": {"/1": "Normal"}}
        for reading in ("Input Power: 321.0 W", "Input Power: 0(W)"):
            for empty in ("Total number of power supplies: 0", "No power supplies installed."):
                output = reading + "\n" + empty
                with self.subTest(output=output):
                    self.assertIsNone(P.parse_power_snapshot(output))
                    check, after = evaluate("power", output, base=before)
                    self.assertEqual(check["level"], "unknown")
                    self.assertEqual(after, before)

    def test_power_table_header_at_end_does_not_prove_missing_supply(self):
        before = {"power_states": {"/1": "Normal", "/2": "Normal"}}
        for trailing in (POWER_HEADER, "PowerID State"):
            output = POWER_HEADER + "\n1 Normal AC -- -- --\n" + trailing
            with self.subTest(trailing=trailing):
                self.assertIsNone(P.parse_power_snapshot(output))
                check, after = evaluate("power", output, base=before)
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(after, before)

    def test_legacy_hardware_fixtures_and_fan_contract_are_unchanged(self):
        folder = Path(__file__).parent / "fixtures"
        device = P.parse_device_slots_snapshot((folder / "comware_device.txt").read_text())
        power = P.parse_power_snapshot((folder / "comware_power.txt").read_text())
        fan = P.parse_fan_snapshot((folder / "comware_fan.txt").read_text())
        self.assertEqual([r["slot"] for r in device], ["1", "2"])
        self.assertEqual([(r["slot"], r["id"]) for r in power], [("1", "1"), ("1", "2")])
        self.assertEqual([(r["slot"], r["id"]) for r in fan], [("1", "1"), ("1", "2")])
        self.assertIsNone(P.parse_fan_snapshot("Chassis 1:\nFan 1 State: Normal"))
        self.assertIsNone(P.parse_fan_snapshot("Input Power: 321.0 W\nFan 1 State: Normal"))


if __name__ == "__main__":
    unittest.main()
