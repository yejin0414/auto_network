import unittest
from pathlib import Path
from nc import parsers as P
from nc.commands import check_console_command

FX = Path(__file__).parent / "fixtures"
r = lambda f: (FX / f).read_text(encoding="utf-8")


class ArubaParsers(unittest.TestCase):
    def test_show_switches_aos8(self):
        rows = P.parse_show_switches(r("aos8_show_switches.txt"))
        self.assertEqual([x["status"] for x in rows], ["Up", "Up", "Down"])
        self.assertEqual(rows[2]["config_state"], "UPDATE REQUIRED")
        self.assertEqual(rows[1]["model"], "Aruba7240XM")

    def test_show_switches_variants(self):
        rows = P.parse_show_switches(r("mm_show_switches_status_variants.txt"))
        self.assertEqual(rows[-1]["status"], "Down")
        self.assertEqual(len(P.parse_show_switches(r("mm_show_switches_normal.txt"))), 4)

    def test_membership_7240xm(self):
        rows = P.parse_membership(r("group_membership_7240xm.txt"))
        self.assertEqual(len(rows), 4)
        self.assertTrue(rows[0]["self"])
        self.assertEqual(rows[0]["role"], "Leader")
        self.assertEqual(rows[1]["conn"], "L2-Connected")
        self.assertTrue(all(x["state"] == "CONNECTED" for x in rows))

    def test_membership_legacy(self):
        rows = P.parse_membership(r("group_membership_initial.txt"))
        self.assertEqual({x["conn"] for x in rows}, {"Type-A"})

    def test_load_distribution(self):
        d = P.parse_load_distribution(r("aos8_load_distribution.txt"))
        self.assertEqual(d["rows"]["192.0.2.13"]["active"], 12)
        self.assertEqual(d["total_active"], 813)
        self.assertEqual(P.parse_load_distribution(r("cluster_load_normal.txt"))["total_active"], 1015)

    def test_cpu_mem_uptime(self):
        self.assertEqual(P.parse_cpu_aruba(r("aos8_cpuload.txt"))["1m"], 16.3)
        self.assertEqual(P.parse_mem_aruba(r("aos8_memory.txt"))["used_pct"], 47.4)
        self.assertEqual(P.parse_uptime(r("aos8_version.txt")), 25 * 86400 + 3 * 3600 + 31 * 60 + 16)
        self.assertIsNone(P.parse_cpu_aruba("garbage"))


class ComwareParsers(unittest.TestCase):
    def test_cpu_takes_max_slot(self):
        p = P.parse_cpu_comware(r("comware_cpu.txt"))
        self.assertEqual((p["5s"], p["1m"], p["5m"]), (12.0, 11.0, 9.0))
        self.assertEqual(len(p["slots"]), 2)

    def test_memory_takes_tightest_slot(self):
        self.assertEqual(P.parse_mem_comware(r("comware_memory.txt"))["used_pct"], 64.3)
        self.assertEqual(P.parse_mem_comware("Total 1000 Used 280 FreeRatio 72%")["used_pct"], 28.0)

    def test_interfaces(self):
        i = P.parse_interfaces(r("comware_interface_brief.txt"))
        self.assertEqual(i["XGE1/0/2"], "DOWN")
        self.assertEqual(i["XGE1/0/3"], "ADM")
        self.assertEqual(i["BAGG10"], "UP")
        self.assertNotIn("Interface", i)

    def test_lagg_ospf_vrrp(self):
        self.assertEqual(P.parse_lagg(r("comware_lagg.txt"))["BAGG20"], {"selected": 1, "unselected": 1})
        peers = P.parse_ospf(r("comware_ospf.txt"))
        self.assertEqual([p["state"] for p in peers], ["Full/BDR", "Full/DR", "Init/DROther"])
        self.assertEqual(peers[0]["interface"], "Vlan100")
        v = P.parse_vrrp(r("comware_vrrp.txt"))
        self.assertEqual([(g["vrid"], g["state"]) for g in v], [("10", "Master"), ("20", "Backup")])
        self.assertEqual(P.parse_vrrp("VRID 10 State Master Priority 120")[0]["state"], "Master")

    def test_hw(self):
        self.assertEqual([p["state"] for p in P.parse_power(r("comware_power.txt"))], ["Normal", "Fault"])
        self.assertEqual(len(P.parse_fan(r("comware_fan.txt"))), 2)
        self.assertEqual([s["state"] for s in P.parse_device_slots(r("comware_device.txt"))], ["Master", "Standby"])
        self.assertEqual(P.parse_uptime(r("comware_version.txt")), 12 * 86400 + 3 * 3600 + 41 * 60)

    def test_error_detection(self):
        self.assertTrue(P.looks_like_error("show vrrp\n      ^\n % Unrecognized command found at '^' position."))
        self.assertTrue(P.looks_like_error("% Invalid input detected at '^' marker."))
        self.assertFalse(P.looks_like_error(r("comware_vrrp.txt")))


class ConsoleSafety(unittest.TestCase):
    def test_allowed(self):
        for c in ["display interface brief", "show switches", "show log system 50", "display current-configuration | include vlan"]:
            self.assertIsNone(check_console_command(c), c)

    def test_blocked(self):
        for c in ["reload", "system-view", "show running-config; reload", "display x\nreboot", "show tech-support",
                  "clear arp", "show ver | debug", "write", "undo shutdown", ""]:
            self.assertIsNotNone(check_console_command(c), c)


if __name__ == "__main__":
    unittest.main()
