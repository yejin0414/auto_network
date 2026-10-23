"""실제 netmiko 접속 경로 → 파서 → 판단 → 저장까지 가짜 SSH 장비로 검증."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from nc.collector import NetmikoDriver
from nc.config import ConfigStore
from nc.credentials import Credential, CredentialStore
from nc.engine import Engine
from nc.store import Store
from tests.mock_ssh import MockDevice

FX = Path(__file__).parent / "fixtures"
r = lambda f: (FX / f).read_text(encoding="utf-8")
strip_prompt = lambda t: "\n".join(l for l in t.splitlines() if not l.strip().startswith(("<BB-3>", "(WLC-01)", "(ArubaMM)")))


def comware(state):
    def resp(cmd):
        table = {
            "screen-length disable": "Info: Screen-length is disabled.",
            "display version": r("comware_version.txt"),
            "show cpu summary": r("comware_cpu_summary.txt"),
            "show memory summary": r("comware_mem_summary.txt"),
            "show logbuffer reverse": r("comware_logbuffer_reverse.txt"),
            "display cpu-usage": r("comware_cpu.txt"),
            "display memory": r("comware_memory.txt"),
            "display device": r("comware_device.txt"),
            "display power": r("comware_power.txt").replace("Fault", "Normal") if not state.get("psu_fault") else r("comware_power.txt"),
            "display fan": r("comware_fan.txt"),
            "display interface brief": r("comware_interface_brief.txt") if not state.get("link_down")
                else r("comware_interface_brief.txt").replace("XGE1/0/1             UP   10G(a)  F(a)", "XGE1/0/1             DOWN auto    A   "),
            "display link-aggregation summary": r("comware_lagg.txt"),
            "display ospf peer": r("comware_ospf.txt").replace("Init/DROther", "Full/DROther"),
            "display vrrp": "              ^\n % Unrecognized command found at '^' position.",
            "show vrrp": r("comware_vrrp.txt"),
        }
        table.update(state.get("command_outputs", {}))
        return strip_prompt(table.get(cmd, "              ^\n % Unrecognized command found at '^' position."))
    return resp


def aruba(kind):
    def resp(cmd):
        table = {
            "no paging": "", "show version": r("aos8_version.txt"), "show cpuload": r("aos8_cpuload.txt"),
            "show memory": r("aos8_memory.txt"),
            "show cpu": r("aos8_show_cpu.txt"),
        }
        if kind == "mm":
            table["show switches"] = r("aos8_show_switches.txt")
        if kind == "wlc":
            table["show lc-cluster group-membership"] = r("group_membership_7240xm.txt")
            table["show lc-cluster load distribution client"] = r("aos8_load_distribution.txt")
        return strip_prompt(table.get(cmd, "% Invalid input detected at '^' marker."))
    return resp


class EndToEnd(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.state = {}
        self.bb = MockDevice("<BB-3>", comware(self.state))
        self.mm = MockDevice("(ArubaMM) [mynode] #", aruba("mm"))
        self.wlc = MockDevice("(WLC-01) #", aruba("wlc"))
        cfg = {
            "devices": [
                {"id": "bb3", "name": "BB-3", "role": "BB", "host": "127.0.0.1", "port": self.bb.port},
                {"id": "mm", "name": "MM", "role": "MM", "host": "127.0.0.1", "port": self.mm.port},
                {"id": "wlc1", "name": "WLC-01", "role": "WLC", "host": "127.0.0.1", "port": self.wlc.port, "cluster_primary": True},
                {"id": "dead", "name": "DEAD", "role": "WLC", "host": "127.0.0.1", "port": 1},
            ],
            "ssh": {"connect_timeout": 5, "command_timeout": 10, "retries": 0},
            "report": {"notify": False},
        }
        (self.tmp / "config.json").write_text(json.dumps(cfg))
        self.creds = CredentialStore(persistent=False)
        self.creds.set("backbone", Credential("op", "pw"), False)
        self.creds.set("aruba", Credential("op", "pw"), False)
        self.store = Store(self.tmp / "db.sqlite")
        self.engine = Engine(ConfigStore(self.tmp / "config.json"), self.store, self.creds, NetmikoDriver())
        self.engine.reports_dir = self.tmp / "reports"

    def tearDown(self):
        for d in (self.bb, self.mm, self.wlc):
            d.close()
        self.store._db.close()

    def test_full_run(self):
        t = time.time()
        rid = self.engine.run_blocking("manual")
        run = self.store.get_run(rid)
        devs = run["devices"]
        took = time.time() - t
        checks = lambda d: {c["key"]: c for c in devs[d]["checks"]}

        bb = checks("bb3")
        self.assertEqual(devs["bb3"]["metrics"]["cpu"], 11.0)
        self.assertEqual(devs["bb3"]["metrics"]["mem"], 68.6)        # show memory summary: 2번 슬롯 FreeRatio 31.4%
        self.assertEqual(devs["bb3"]["metrics"]["cpu_detail"]["5s"], 12.0)
        self.assertEqual(devs["bb3"]["metrics"]["mem_detail"]["free_kb"], 2514828)
        self.assertEqual(len(devs["bb3"]["metrics"]["log"]), 4)
        self.assertEqual({c["cmd_id"]: c["command"] for c in devs["bb3"]["commands"]}["cpu"], "show cpu summary")
        self.assertEqual(devs["wlc1"]["metrics"]["cpu_detail"]["user"], 7.2)
        self.assertEqual(devs["wlc1"]["metrics"]["mem_detail"]["used_kb"], 1872100)
        self.assertEqual(bb["memory"]["level"], "warn")
        self.assertEqual(bb["vrrp"]["level"], "ok")            # display vrrp 거부 → show vrrp 대체 실행
        self.assertEqual(bb["vrrp"]["command"], "show vrrp")
        self.assertEqual(bb["lagg"]["level"], "warn")           # BAGG20 Unselected 1
        self.assertEqual(bb["interface"]["level"], "ok")        # 첫 회차는 기준 저장
        self.assertNotIn("screen-length disable", [c["command"] for c in devs["bb3"]["commands"]])

        self.assertEqual(devs["wlc1"]["metrics"]["cpu"], 16.3)
        self.assertEqual(checks("mm")["switches"]["summary"], "Up 2 / 전체 3")
        self.assertEqual(checks("wlc1")["mm_status"]["level"], "warn")   # 127.0.0.1은 MM 목록에 없음
        self.assertEqual(devs["dead"]["status"], "unknown")              # 접속 실패 = 확인 불가(장애 아님)
        self.assertIsNotNone(run["summary"]["total_active"])

        raw = self.store.get_raw(rid, "bb3", "cpu")
        self.assertIn("Last 1 min", raw["output"])
        self.assertNotIn("<BB-3>", raw["output"])
        print(f"\n  1회 점검 {took:.1f}초, 종합={run['overall']}, 수신 명령(BB)={self.bb.received}")

        # 2회차: 기준 대비 링크 Down + 전원 Fault → 장애
        self.state.update(link_down=True, psu_fault=True)
        run2 = self.store.get_run(self.engine.run_blocking("manual"))
        bb2 = {c["key"]: c for c in run2["devices"]["bb3"]["checks"]}
        self.assertEqual(bb2["interface"]["level"], "crit")
        self.assertIn("XGE1/0/1", bb2["interface"]["summary"])
        self.assertEqual(bb2["power"]["level"], "crit")
        self.assertEqual(run2["devices"]["bb3"]["status"], "crit")
        ev = [e["text"] for e in self.store.list_events()]
        self.assertTrue(any("인터페이스" in e for e in ev))

        # 직접 확인: 허용/차단
        ok = self.engine.console("bb3", "display  interface brief")
        self.assertTrue(ok["ok"], ok)
        blocked = self.engine.console("bb3", "reset saved-configuration")
        self.assertFalse(blocked["ok"])
        sent = set(self.bb.received + self.mm.received + self.wlc.received)
        bad = [c for c in sent if not c.startswith(("show", "display", "screen-length", "no paging", "quit", "exit", "logout"))]
        self.assertEqual(bad, [], f"조회 외 명령 전송: {bad}")

    def test_7506_extended_formats_through_ssh_and_storage(self):
        from tests.test_7506_hardware import OLD_DEVICE

        # Synthetic compatibility case, not a claim that S7500E's plain
        # command returns its documented verbose response on real hardware.
        detail = r("comware_7506_ospf_extended_detail.txt")
        detail = "\n".join(line for line in detail.splitlines() if "display ospf" not in line)
        outputs = {"display device": OLD_DEVICE, "display ospf peer": detail}
        self.state["command_outputs"] = outputs
        run_id = self.engine.run_blocking("manual")
        device = self.store.get_run(run_id)["devices"]["bb3"]
        checks = {c["key"]: c for c in device["checks"]}
        for key, command in (("device", "display device"), ("ospf", "display ospf peer")):
            self.assertEqual(checks[key]["level"], "ok")
            self.assertEqual(checks[key]["command"], command)
            self.assertEqual(self.store.get_raw(run_id, "bb3", key)["output"].strip(), outputs[command].strip())
        self.assertEqual(self.store.baselines()["bb3"]["slots"], ["1", "2"])
        self.assertEqual(self.store.baselines()["bb3"]["ospf"], ["203.0.113.11", "203.0.113.12"])

    def test_wrong_password_not_retried(self):
        self.creds.set("backbone", Credential("op", "WRONG"), False)
        run = self.store.get_run(self.engine.run_blocking("manual"))
        c = run["devices"]["bb3"]["checks"][0]
        self.assertEqual(c["level"], "unknown")
        self.assertIn("로그인 실패", c["summary"])

    def test_7506_documented_outputs_collect_evaluate_and_preserve_raw(self):
        from tests.test_7506_hardware import DEVICE, POWER

        def fixture(name):
            return "\n".join(r(name).splitlines()[1:])

        outputs = {"display device": DEVICE, "display power": POWER,
                   "display ospf peer": fixture("comware_7506_ospf.txt")}
        self.state["command_outputs"] = outputs
        run_id = self.engine.run_blocking("manual")
        first = self.store.get_run(run_id)
        checks = {c["key"]: c for c in first["devices"]["bb3"]["checks"]}
        for key, cmd in (("device", "display device"), ("power", "display power"), ("ospf", "display ospf peer")):
            self.assertEqual(checks[key]["level"], "ok")
            self.assertEqual(checks[key]["command"], cmd)
            self.assertIn(cmd, self.bb.received)
            self.assertEqual(self.store.get_raw(run_id, "bb3", key)["output"].strip(), outputs[cmd].strip())
        baseline = self.store.baselines()["bb3"]
        self.assertEqual(baseline["slots"], ["0", "1"])
        self.assertEqual(set(baseline["power_states"]), {"1/1", "1/2", "2/1", "2/2"})
        self.assertEqual(baseline["ospf"], ["203.0.113.11", "203.0.113.12"])

        # The original S7500 default uses a detailed response to this SAME
        # command. Truncated hardware must not reset established baselines.
        outputs["display ospf peer"] = fixture("comware_7506_ospf_detail.txt")
        outputs["display device"] += "\n3 SYNTHETIC-LPU"
        outputs["display power"] += "\nChassis 3:"
        second_id = self.engine.run_blocking("manual")
        second = self.store.get_run(second_id)
        checks = {c["key"]: c for c in second["devices"]["bb3"]["checks"]}
        self.assertEqual(checks["ospf"]["level"], "ok")
        self.assertEqual(checks["device"]["level"], "unknown")
        self.assertEqual(checks["power"]["level"], "unknown")
        self.assertEqual(self.store.baselines()["bb3"], baseline)


if __name__ == "__main__":
    unittest.main()
