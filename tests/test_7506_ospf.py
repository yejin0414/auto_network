"""Synthetic S7500E brief output, not a capture from a production 7506.

Column order is documented in H3C S7500E Release 6100, IPv4 routing:
https://wwwsg.h3c.com/cn/d_200912/658550_30005_0.htm
All addresses and device names below are synthetic.
Original S7500 default detailed output is documented in section 3.1.20:
https://www.h3c.com/en/d_200707/207783_294551_0.htm

Extended detailed fields are documented for S7500E *verbose* output. Their
synthetic response-body fixture verifies parser compatibility, not that these
releases return detailed output for the collected default command:
https://www.h3c.com/cn/d_200911/654940_30005_0.htm
https://www.h3c.com/cn/d_200911/654971_30005_0.htm
https://www.h3c.com/en/d_201601/913471_294551_0.htm
"""
import unittest
from pathlib import Path

from nc import parsers as P
from tests.test_optional_command_accuracy import evaluate


OUTPUT = (Path(__file__).parent / "fixtures" / "comware_7506_ospf.txt").read_text(encoding="utf-8")
BASE = {"ospf": ["203.0.113.11", "203.0.113.12"]}
DETAIL = (Path(__file__).parent / "fixtures" / "comware_7506_ospf_detail.txt").read_text(encoding="utf-8")
EXTENDED = (Path(__file__).parent / "fixtures" / "comware_7506_ospf_extended_detail.txt").read_text(encoding="utf-8")


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

    def test_brief_empty_sections_cannot_seed_or_prove_disappearance(self):
        headings = ("OSPF Process 2 with Router ID 203.0.113.20",
                    "Neighbor Brief Information", "Neighbors", "Area: 0.0.0.2",
                    "Router ID Address Pri Dead-Time State Interface")
        complete = OUTPUT.split("\n", 1)[1]
        extra_baseline = {"ospf": BASE["ospf"] + ["203.0.113.99"]}
        for heading in headings:
            for text in (OUTPUT + "\n" + heading, OUTPUT + "\n" + heading + "\n" + complete):
                with self.subTest(heading=heading, text=text):
                    self.assertIsNone(P.parse_ospf_snapshot(text))
                    for baseline in ({}, BASE, extra_baseline):
                        check, after = evaluate("ospf", text, base=baseline)
                        self.assertEqual(check["level"], "unknown")
                        self.assertEqual(after, baseline)
                        self.assertNotIn("인접 사라짐", check["evidence"])

    def test_brief_multiple_complete_sections_and_processes(self):
        table = "Router ID Address Pri Dead-Time State Interface\n"
        row = "203.0.113.13 192.0.2.13 1 35 Full/DR Vlan102\n"
        section = "Area: 0.0.0.2\n" + table + row
        for extra in (section, "Neighbor Brief Information\n" + section,
                      "OSPF Process 2 with Router ID 203.0.113.20\nNeighbor Brief Information\n" + section):
            with self.subTest(extra=extra):
                rows = P.parse_ospf_snapshot(OUTPUT + extra)
                self.assertIsNotNone(rows)
                self.assertEqual(len(rows), 3)
                self.assertEqual(rows[-1]["area"], "0.0.0.2")
                check, after = evaluate("ospf", OUTPUT + extra, base={})
                self.assertEqual(check["level"], "ok")
                self.assertEqual(after, {"ospf": BASE["ospf"] + ["203.0.113.13"]})
        # The same router/interface identity can belong to distinct processes.
        second = OUTPUT.split("\n", 1)[1].replace("OSPF Process 1", "OSPF Process 2")
        self.assertEqual(len(P.parse_ospf_snapshot(OUTPUT + second)), 4)

    def test_brief_legacy_peer_rows_and_explicit_empty_contract(self):
        legacy = "Peer 203.0.113.11 State Full\nPeer 203.0.113.12 State 2-Way"
        self.assertEqual(len(P.parse_ospf_snapshot(legacy)), 2)
        self.assertEqual(evaluate("ospf", legacy, base={})[1], BASE)
        header = ("OSPF Process 1 with Router ID 203.0.113.10\nNeighbor Brief Information\n"
                  "Area: 0.0.0.0\nRouter ID Address Pri Dead-Time State Interface\n")
        for empty in ("No OSPF peers configured.", "Total number of OSPF peers: 0"):
            for text in (empty, header + empty):
                with self.subTest(text=text):
                    self.assertEqual(P.parse_ospf_snapshot(text), [])
                    check, after = evaluate("ospf", text, base={})
                    self.assertEqual(check["level"], "info")
                    self.assertEqual(after, {})
                    check, after = evaluate("ospf", text, base=BASE)
                    self.assertEqual(check["level"], "crit")
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

    def test_extended_detailed_fields_keep_neighbor_identity(self):
        rows = P.parse_ospf_snapshot(EXTENDED)
        self.assertIsNotNone(rows)
        self.assertEqual([(r["router_id"], r["area"], r["interface"], r["state"].lower()) for r in rows],
                         [("203.0.113.11", "0.0.0.0", "Vlan-interface100", "full"),
                          ("203.0.113.12", "0.0.0.1", "Vlan-interface200", "full")])
        check, after = evaluate("ospf", EXTENDED, base={})
        self.assertEqual(check["level"], "ok")
        self.assertEqual(after, BASE)

    def test_detailed_variants_are_optional_and_independent(self):
        variants = [
            DETAIL.replace("Address: 192.0.2.11", "Address: 192.0.2.11 GR State: Helper"),
            DETAIL.replace("BDR: 192.0.2.10", "BDR: 192.0.2.10 MTU: 1500"),
            DETAIL.replace("DR: 192.0.2.11 BDR: 192.0.2.10", "DR: None BDR: None"),
            DETAIL.replace("Dead timer expires in 31s", "Options is 0x02 (-|-|-|-|-|-|E|-)\nDead timer expires in 31s"),
            DETAIL.replace("Dead timer expires in 31s", "Dead timer due in 31 sec"),
            DETAIL.replace("Neighbor has been up for", "Neighbor is up for"),
            DETAIL.replace("Mode: Nbr is Master", "Mode: Null"),
            DETAIL.replace("Mode: Nbr is Master", "Mode: Hold"),
            DETAIL + "Authentication Sequence: [ 0 ]\n",
            DETAIL + "Neighbor state change count: 6\n",
            DETAIL + "BFD status: Enabled (Control mode)\n",
            DETAIL + "BFD status: Enabled (Echo mode)\n",
            DETAIL.replace("192.0.2.10(Vlan-interface100)", "192.0.2.10 ( Vlan-interface100 )"),
        ]
        for text in variants:
            with self.subTest(text=text):
                self.assertEqual(len(P.parse_ospf_snapshot(text)), 2)
                check, after = evaluate("ospf", text, base={})
                self.assertEqual(check["level"], "ok")
                self.assertEqual(after, BASE)

    def test_repeated_neighbors_heading_requires_next_complete_area(self):
        header = "Neighbors\nArea 0.0.0.1 interface 192.0.2.20(Vlan-interface200)'s neighbor(s)\n"
        text = DETAIL.replace("RouterID: 203.0.113.12", header + "RouterID: 203.0.113.12")
        rows = P.parse_ospf_snapshot(text)
        self.assertIsNotNone(rows)
        self.assertEqual([r["area"] for r in rows], ["0.0.0.0", "0.0.0.1"])
        for tail in ("Neighbors", header, "Neighbors\nNeighbors",
                     "Neighbors\nOSPF Process 2 with Router ID 203.0.113.20",
                     "Neighbors\nRouterID: 203.0.113.13 Address: 192.0.2.13"):
            with self.subTest(tail=tail):
                broken = text + "\n" + tail
                self.assertIsNone(P.parse_ospf_snapshot(broken))
                check, after = evaluate("ospf", broken, base=BASE)
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(after, BASE)

    def test_extended_metadata_cannot_complete_missing_or_invalid_core_fields(self):
        mutations = [
            EXTENDED.replace("State: Full Mode: Nbr is master Priority: 1\n", ""),
            EXTENDED.replace("DR: None BDR: None MTU: 1500\n", ""),
            EXTENDED.replace("Dead timer due in 38 sec\n", ""),
            EXTENDED.replace("Neighbor is up for 00:02:44\n", ""),
            EXTENDED.replace("GR state: Normal", "GR state: Unknown"),
            EXTENDED.replace("DR: None", "DR: invalid"),
            EXTENDED.replace("MTU: 1500", "MTU: unknown"),
            EXTENDED.replace("Options is 0x02", "Options is unknown"),
            EXTENDED.replace("Dead timer due in 38 sec", "Dead timer due in unknown sec"),
            EXTENDED.replace("Neighbor is up for 00:02:44", "Neighbor is up for unknown"),
            EXTENDED.replace("Authentication Sequence: [ 0 ]", "Authentication Sequence:"),
            EXTENDED.replace("BFD status: Disabled", "BFD status: Unknown"),
            EXTENDED + "Future metadata: unrecognized\n",
        ]
        for text in mutations:
            with self.subTest(text=text):
                self.assertIsNone(P.parse_ospf_snapshot(text))
                check, after = evaluate("ospf", text, base=BASE)
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(after, BASE)
                self.assertEqual(evaluate("ospf", text, base={})[1], {})

    def test_extended_duplicate_fields_and_history_are_not_current_neighbors(self):
        history = ("Last Neighbor Down Event:\nRouter ID: 203.0.113.99\n"
                   "Local Address: 192.0.2.10\nRemote Address: 192.0.2.99\n"
                   "Time: Apr 9 03:18:19 2014\nReason: Ospf_ifachange\n")
        for text in (EXTENDED.replace("BFD status: Disabled", "BFD status: Disabled\nBFD status: Disabled"),
                     EXTENDED + "Neighbor state change count: 5\n", EXTENDED + history):
            with self.subTest(text=text):
                self.assertIsNone(P.parse_ospf_snapshot(text))
                check, after = evaluate("ospf", text, base=BASE)
                self.assertEqual(check["level"], "unknown")
                self.assertEqual(after, BASE)
                self.assertEqual(evaluate("ospf", text, base={})[1], {})

    def test_extended_complete_fault_survives_partial_next_record(self):
        text = EXTENDED.replace("State: Full Mode: Nbr is master", "State: Down Mode: None")
        text = text.replace("Neighbor is up for 00:02:44\n", "")
        check, after = evaluate("ospf", text, base=BASE)
        self.assertEqual(check["level"], "crit")
        self.assertIn("일부 해석 불가", check["summary"])
        self.assertEqual(after, BASE)


if __name__ == "__main__":
    unittest.main()
