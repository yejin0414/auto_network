"""이전 검토에서 발견한 수집/판정 회귀: 실제 네트워크와 스케줄러를 사용하지 않음."""

import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nc.collector import CmdResult, ConnectFailure, DeviceCollection, collect_device, run_spec
from nc.commands import CommandSpec, check_console_command, commands_for
from nc.config import validate
from nc.credentials import Credential
from nc.diagnose import read_server_kexinit
from nc.engine import Engine
from nc.evaluate import eval_backbone, evaluate_run
from nc.parsers import parse_mem_comware


def command_result(key, output="", ok=True):
    return CmdResult(key, key, "show " + key, output, ok, "" if ok else "mock command failure")


def healthy_wlc():
    return DeviceCollection("w", True, results={
        "version": command_result("version", "uptime is 2 days"),
        "cpu": command_result("cpu", "user 1% system 2% idle 97%"),
        "memory": command_result("memory", "total: 1000, used: 200, free: 800"),
    })


class CommandSafetyRegressions(unittest.TestCase):
    def test_extra_commands_cannot_bypass_console_policy(self):
        for command in ("reboot", "display x\nreset saved-configuration", "show x\x1breboot",
                        "show x\x08reboot", "show x\vreset", "show x | redirect flash:/x",
                        "show x > flash:/x", "show x & reboot", "show x\u2028reboot"):
            with self.subTest(command=repr(command)):
                self.assertIsNotNone(check_console_command(command))
                with self.assertRaises(ValueError):
                    commands_for("BB", [command])

    def test_execution_checks_even_manually_constructed_specs(self):
        session = Mock()
        result = run_spec(session, CommandSpec("extra1", "unsafe", ("reboot",)), {})
        self.assertFalse(result.ok)
        session.run.assert_not_called()

    def test_read_only_filter_is_preserved(self):
        self.assertIsNone(check_console_command("display current-configuration | include vlan"))
        self.assertIsNone(check_console_command("display interface brief | count"))
        specs = commands_for("BB", ["display interface brief"])
        self.assertEqual(specs[-1].commands, ("display interface brief",))

    def test_authentication_failure_is_never_retried(self):
        driver = Mock()
        driver.open.side_effect = ConnectFailure("auth", "mock login denied")
        result = collect_device(driver, {"id": "b", "name": "BB", "role": "BB", "host": "192.0.2.1"},
                                [], Credential("demo", "demo-only"), {"retries": 3})
        self.assertEqual(result.error_kind, "auth")
        self.assertFalse(result.connected)
        driver.open.assert_called_once()


class ParserAndEvaluationRegressions(unittest.TestCase):
    def test_invalid_memory_rows_do_not_crash_or_produce_metrics(self):
        for output in ("Slot Total Free\n1 0 0", "Slot Total Free\n1 100 200",
                       "Slot Total Free FreeRatio\n1 100 20 120%", "FreeRatio 120%",
                       "Total 100 Used 200", "Slot Total Free\n1 " + "9" * 400 + " 0"):
            with self.subTest(output=output[:80]):
                self.assertIsNone(parse_mem_comware(output))

    def test_valid_memory_slot_survives_invalid_slot(self):
        parsed = parse_mem_comware("Slot Total Free\n1 0 0\n2 100 40")
        self.assertEqual(parsed["used_pct"], 60)
        self.assertEqual([slot["slot"] for slot in parsed["slots"]], ["2"])

    def test_zero_memory_is_unknown_in_run(self):
        cfg = validate({"devices": [{"id": "b", "role": "BB", "host": "192.0.2.1"}]})
        dc = DeviceCollection("b", True, results={"memory": command_result("memory", "Slot Total Free\n1 0 0")})
        evaluation, _ = evaluate_run(cfg, {"b": dc}, {}, {}, {})
        self.assertEqual(evaluation["devices"]["b"]["status"], "unknown")
        self.assertNotIn("mem", evaluation["devices"]["b"]["metrics"])

    def test_unclassified_power_state_is_not_reported_as_absent(self):
        checks = []
        dc = DeviceCollection("b", True, results={"power": command_result("power", "1 Off\n2 NotSupply")})
        eval_backbone(dc, {}, checks, {})
        self.assertEqual(checks[0]["level"], "unknown")
        self.assertNotIn("미장착", checks[0]["summary"])
        self.assertEqual(checks[0]["evidence"], ["1 Off", "2 NotSupply"])

    def test_failed_missing_and_unparsed_cluster_data_are_unknown(self):
        cfg = validate({"devices": [{"id": "w", "role": "WLC", "host": "192.0.2.1"}]})
        for clusters in ({}, {"": {"membership": command_result("membership", ok=False),
                                  "load": command_result("load", ok=False)}},
                         {"": {"membership": command_result("membership", "unrecognized format"),
                                "load": command_result("load", "unrecognized format")}}):
            with self.subTest(clusters=clusters):
                evaluation, _ = evaluate_run(cfg, {"w": healthy_wlc()}, clusters, {}, {})
                device = evaluation["devices"]["w"]
                checks = {check["key"]: check for check in device["checks"]}
                self.assertEqual(device["status"], "unknown")
                self.assertEqual(checks["cluster"]["level"], "unknown")
                self.assertEqual(checks["clients"]["level"], "unknown")

    def test_valid_cluster_data_preserves_healthy_status(self):
        cfg = validate({"devices": [{"id": "w", "role": "WLC", "host": "192.0.2.1"}]})
        membership = ("Type IPv4 Address    Priority Connection-Type STATUS\n"
                      "---- --------------- -------- --------------- ------\n"
                      "self 192.0.2.1            128    L2-Connected CONNECTED (Leader)")
        clusters = {"": {"membership": command_result("membership", membership),
                         "load": command_result("load", "192.0.2.1 100 100\nTotal: Active Clients 100")}}
        evaluation, _ = evaluate_run(cfg, {"w": healthy_wlc()}, clusters, {}, {})
        self.assertEqual(evaluation["devices"]["w"]["status"], "ok")


class SSHBannerRegressions(unittest.TestCase):
    @staticmethod
    def packet(payload):
        padding = b"\x00" * 4
        return struct.pack(">I", 1 + len(payload) + len(padding)) + bytes([len(padding)]) + payload + padding

    def test_eof_after_banner_or_partial_packet_raises_and_closes(self):
        for initial in (b"SSH-2.0-Mock\r\n", b"SSH-2.0-Mock\r\n\x00\x00\x00\x64\x04"):
            with self.subTest(initial=initial):
                sock = Mock()
                # A third recv is a test failure, preventing an old-code infinite loop.
                sock.recv.side_effect = [initial, b""]
                with patch("nc.diagnose.socket.create_connection", return_value=sock):
                    with self.assertRaises(ConnectionError):
                        read_server_kexinit("mock.invalid", 22, 1)
                self.assertEqual(sock.recv.call_count, 2)
                sock.close.assert_called_once()

    def test_truncated_algorithm_list_is_rejected(self):
        payload = b"\x14" + b"\x00" * 16 + struct.pack(">I", 100) + b"short"
        sock = Mock()
        sock.recv.return_value = b"SSH-2.0-Mock\r\n" + self.packet(payload)
        with patch("nc.diagnose.socket.create_connection", return_value=sock):
            with self.assertRaises(ConnectionError):
                read_server_kexinit("mock.invalid", 22, 1)
        sock.close.assert_called_once()

    def test_complete_algorithm_lists_still_parse(self):
        algorithms = (b"curve25519-sha256", b"ssh-ed25519", b"aes128-ctr", b"aes128-ctr",
                      b"hmac-sha2-256", b"hmac-sha2-256")
        payload = b"\x14" + b"\x00" * 16 + b"".join(struct.pack(">I", len(a)) + a for a in algorithms)
        sock = Mock()
        sock.recv.return_value = b"SSH-2.0-Mock\r\n" + self.packet(payload)
        with patch("nc.diagnose.socket.create_connection", return_value=sock):
            banner, _, lists = read_server_kexinit("mock.invalid", 22, 1)
        self.assertEqual(banner, "SSH-2.0-Mock")
        self.assertEqual(lists["kex"], ["curve25519-sha256"])


class ReportErrorRegressions(unittest.TestCase):
    def test_report_save_error_remains_visible_after_collection(self):
        cfg = validate({"report": {"notify": False}})
        store = Mock()
        store.get_run.side_effect = [None, {"id": 1}]
        store.get_report_snapshot.return_value = ({"id": 1}, lambda *_: None)
        store.baselines.return_value = {}
        store.previous_metrics.return_value = {}
        store.commit_run.return_value = 1
        engine = Engine(SimpleNamespace(get=lambda: cfg), store, None, SimpleNamespace())
        with patch("nc.excel.save_report", side_effect=OSError("mock report write failure")):
            self.assertEqual(engine._run("test", None), 1)
        self.assertIn("mock report write failure", engine.last_error)


if __name__ == "__main__":
    unittest.main()
