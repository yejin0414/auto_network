"""Synthetic S7500E brief output, not a capture from a production 7506.

Column order is documented in H3C S7500E Release 6100, IPv4 routing:
https://wwwsg.h3c.com/cn/d_200912/658550_30005_0.htm
All addresses and device names below are synthetic.
Original S7500 default detailed output is documented in section 3.1.20:
https://www.h3c.com/en/d_200707/207783_294551_0.htm
"""
import unittest
from pathlib import Path

from nc import parsers as P
from tests.test_optional_command_accuracy import evaluate


OUTPUT = (Path(__file__).parent / "fixtures" / "comware_7506_ospf.txt").read_text(encoding="utf-8")
BASE = {"ospf": ["203.0.113.11", "203.0.113.12"]}
DETAIL = (Path(__file__).parent / "fixtures" / "comware_7506_ospf_detail.txt").read_text(encoding="utf-8")


class S7506Ospf(unittest.TestCase):
    def test_interface_before_state_is_supported(self):
        rows = P.parse_ospf_snapshot(OUTPUT)
        self.assertIsNotNone(rows)
        self.assertEqual([(r["router_id"], r["interface"], r["state"]) for r in rows],
                         [("203.0.113.11", "Vlan100", "Full/BDR"),
                          ("203.0.113.12", "Vlan101", "Full/DR")])
        self.assertTrue(all(r["area"] == "0.0.0.0" for r in rows))
        check, after = evaluate("ospf", OUTPUT, base={})
        self.assertEqual(check["level"], "ok")
        self.assertEqual(after, BASE)

    def test_both_orders_whitespace_and_presentation(self):
        flipped = OUTPUT.replace("Interface       State", "State           Interface")
        flipped = flipped.replace("Vlan100         Full/BDR", "Full/BDR        Vlan100")
        flipped = flipped.replace("Vlan101         Full/DR", "Full/DR         Vlan101")
        tabbed = "\n".join(line if "display ospf peer" in line else line.replace(" ", "\t")
                           for line in OUTPUT.splitlines())
        for text in (OUTPUT, flipped, tabbed,
                     "\x1b[32m" + OUTPUT.replace("\n", "\r\n") + "\x1b[0m\n<BB-SYNTHETIC>"):
            with self.subTest(output=text):
                check, after = evaluate("ospf", text, base=BASE)
                self.assertEqual(check["level"], "ok")
                self.assertEqual(after, BASE)

    def test_every_documented_neighbor_state(self):
        for state in ("Full", "2-Way", "Init", "Down", "ExStart", "Exchange", "Loading", "Attempt"):
            with self.subTest(state=state):
                text = OUTPUT.replace("Full/DR", state)
                check, after = evaluate("ospf", text, base=BASE)
                self.assertEqual(check["level"], "ok" if state in ("Full", "2-Way") else "crit")
                self.assertEqual(after, BASE)

    def test_truncated_unknown_or_contradictory_rows_preserve_baseline(self):
        first, second = OUTPUT.strip().rsplit("\n", 1)
        for tail in ("203.0.113.12 192.0.2.12 1 35 Vlan101",
                     "203.0.113.12 192.0.2.12 1 35 Full/DR",
                     "203.0.113.12 192.0.2.12 1 35 Vlan101 Mystery",
                     "203.0.113.12 192.0.2.12 1 35 Vlan101 Full/DR trailing",
                     "999.0.0.12 192.0.2.12 1 35 Vlan101 Full/DR",
                     "203.0.113.12 999.0.0.12 1 35 Vlan101 Full/DR",
                     "203.0.113.12 192.0.2.12 1 35 101 Full/DR",
                     "203.0.113.12 192.0.2.12 1 35 Full/DR Full/BDR",
                     second + "\n" + second.replace("Full/DR", "Down"),
                     second + "\nTotal OSPF peers: 3",
                     second + "\nNo OSPF peers configured.",
                     second + "\n---- More ----", second + "\n% Invalid input"):
            with self.subTest(tail=tail):
                text = first + "\n" + tail
                self.assertIsNone(P.parse_ospf_snapshot(text))
                check, after = evaluate("ospf", text, base=BASE)
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(after, BASE)
                self.assertEqual(evaluate("ospf", text, base={})[1], {})

    def test_known_bad_neighbor_in_partial_output_remains_visible(self):
        for state in ("Down", "Init", "ExStart"):
            text = OUTPUT.replace("Full/BDR", state) + "\n203.0.113.13 192.0.2.13 1 35 Vlan103 Mystery"
            with self.subTest(state=state):
                self.assertIsNone(P.parse_ospf_snapshot(text))
                check, after = evaluate("ospf", text, base=BASE)
                self.assertEqual(check["level"], "crit")
                self.assertIn("일부 해석 불가", check["summary"])
                self.assertEqual(after, BASE)

    def test_complete_missing_neighbor_still_alerts(self):
        text = OUTPUT.strip().rsplit("\n", 1)[0]
        check, after = evaluate("ospf", text, base=BASE)
        self.assertEqual(check["level"], "crit")
        self.assertIn("203.0.113.12: 인접 사라짐", check["evidence"])
        self.assertEqual(after, BASE)

    def test_original_7500_default_detailed_output(self):
        rows = P.parse_ospf_snapshot(DETAIL)
        self.assertIsNotNone(rows)
        self.assertEqual([r["router_id"] for r in rows], BASE["ospf"])
        self.assertEqual({r["interface"] for r in rows}, {"Vlan-interface100"})
        check, after = evaluate("ospf", DETAIL, base={})
        self.assertEqual(check["level"], "ok")
        self.assertEqual(after, BASE)

    def test_detail_fault_and_two_way_states(self):
        for state in ("2-Way", "Down", "Init", "ExStart", "Exchange", "Loading", "Attempt"):
            text = DETAIL.replace("State: Full Mode: Nbr is Slave", f"State: {state} Mode: None")
            with self.subTest(state=state):
                check, after = evaluate("ospf", text, base=BASE)
                self.assertEqual(check["level"], "ok" if state == "2-Way" else "crit")
                self.assertEqual(after, BASE)

    def test_detail_missing_or_unknown_fields_do_not_create_or_replace_baseline(self):
        lines = DETAIL.splitlines()
        for text in (["\n".join(lines[:i]) for i in range(1, len(lines)) if i not in (9, 10)] +
                     [DETAIL.replace("State: Full", "State: Mystery"),
                      DETAIL.replace("Address: 192.0.2.12", "Address:"),
                      DETAIL.replace("Vlan-interface100", "100"),
                      DETAIL.replace("31s", "unknown"),
                      DETAIL.replace("RouterID: 203.0.113.12", "RouterID: 999.0.0.12"),
                      DETAIL + "\nChassis unsupported", DETAIL + "\n---- More ----",
                      DETAIL + "\nNo OSPF peers configured."]):
            with self.subTest(text=text):
                self.assertIsNone(P.parse_ospf_snapshot(text))
                check, after = evaluate("ospf", text, base=BASE)
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(after, BASE)
                self.assertEqual(evaluate("ospf", text, base={})[1], {})

    def test_detail_conflicting_identity_cannot_create_fault(self):
        duplicate = DETAIL + "\nRouterID: 203.0.113.11 Address: 192.0.2.11\nState: Down Mode: None Priority: 1"
        for text in (duplicate, DETAIL + "\nState: Down Mode: None Priority: 1"):
            check, after = evaluate("ospf", text, base=BASE)
            self.assertEqual(check["level"], "unknown")
            self.assertEqual(after, BASE)

    def test_completed_detail_fault_survives_partial_next_record(self):
        text = DETAIL.replace("State: Full Mode: Nbr is Master", "State: Down Mode: None").rsplit("\n", 3)[0]
        check, after = evaluate("ospf", text, base=BASE)
        self.assertEqual(check["level"], "crit")
        self.assertIn("일부 해석 불가", check["summary"])
        self.assertEqual(after, BASE)

    def test_detail_interface_sections_keep_identity_and_reject_empty_tail(self):
        second = "Area 0.0.0.1 interface 192.0.2.20(Vlan-interface200)'s neighbor(s)\n"
        text = DETAIL.replace("RouterID: 203.0.113.12", second + "RouterID: 203.0.113.12")
        rows = P.parse_ospf_snapshot(text)
        self.assertEqual([(r["area"], r["interface"]) for r in rows],
                         [("0.0.0.0", "Vlan-interface100"), ("0.0.0.1", "Vlan-interface200")])
        self.assertIsNone(P.parse_ospf_snapshot(text + "\n" + second))

    def test_empty_detailed_process_cannot_prove_neighbors_missing(self):
        header = "OSPF Process 2 with Router ID 203.0.113.20"
        baseline = {"ospf": BASE["ospf"] + ["203.0.113.99"]}
        for text in (DETAIL + "\n" + header, DETAIL + "\n" + header + "\nNeighbors",
                     header + "\nNeighbors\n" + DETAIL.split("\n", 1)[1]):
            with self.subTest(text=text):
                self.assertIsNone(P.parse_ospf_snapshot(text))
                check, after = evaluate("ospf", text, base=baseline)
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(after, baseline)


if __name__ == "__main__":
    unittest.main()
