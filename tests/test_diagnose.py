"""접속 진단, 기존 백본 도구 설정 가져오기, 시간 기준 명령 출력 정리."""
import socket
import unittest
from pathlib import Path

from nc.collector import strip_echo_and_prompt
from nc.credentials import Credential
from nc.diagnose import diagnose, mask_ips, parse_old_devices_yaml
from tests.mock_ssh import MockDevice
from tests.test_e2e_ssh import comware

OLD_EXAMPLE = """devices:
  - name: backbone3
    host: 192.0.2.3
    port: 22
    device_type: hp_comware
    enabled: true
  - name: backbone4
    host: 192.0.2.4
    port: 23
    device_type: hp_comware_telnet
    enabled: false
"""


def dev(port):
    return {"id": "bb", "name": "BB", "role": "BB", "host": "127.0.0.1", "port": port}


class Diagnose(unittest.TestCase):
    def test_all_steps_pass_and_show_login_screen(self):
        d = MockDevice("<BB-3>", comware({}), login_question="\r\nChange the password now? [Y/N]:")
        try:
            r = diagnose(dev(d.port), Credential("op", "pw"), {"connect_timeout": 8})
        finally:
            d.close()
        self.assertTrue(r["ok"], r)
        names = [s["name"] for s in r["steps"]]
        for n in ("TCP 연결", "SSH 배너", "암호 방식", "인증 방식", "로그인", "로그인 직후 화면", "프로그램 접속·명령"):
            self.assertIn(n, names)
        screen = next(s for s in r["steps"] if s["name"] == "로그인 직후 화면")["detail"]
        self.assertIn("[Y/N]", screen)
        self.assertNotIn("pw", r["copy_text"].replace("paramiko", ""))

    def test_wrong_password_stops_at_login(self):
        d = MockDevice("<BB-3>", comware({}))
        try:
            r = diagnose(dev(d.port), Credential("op", "bad"), {"connect_timeout": 8})
        finally:
            d.close()
        self.assertFalse(r["ok"])
        self.assertEqual(r["steps"][-1]["name"], "로그인")

    def test_closed_port_and_no_credential(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        r = diagnose(dev(port), Credential("op", "pw"), {})
        self.assertEqual(r["summary"], "TCP 연결 단계에서 막혔습니다.")
        self.assertIn("입력되지", diagnose(dev(port), None, {})["steps"][-1]["detail"])

    def test_mask_ips(self):
        self.assertEqual(mask_ips("203.0.113.40 127.0.0.1"), "203.x.x.40 127.0.0.1")


class ImportOldTool(unittest.TestCase):
    def test_parse(self):
        devs = parse_old_devices_yaml(OLD_EXAMPLE)
        self.assertEqual([(d["host"], d["port"], d["protocol"], d["enabled"]) for d in devs],
                         [("192.0.2.3", 22, "ssh", True), ("192.0.2.4", 23, "telnet", False)])
        self.assertEqual(devs[1]["device_type"], "hp_comware_telnet")
        self.assertEqual(parse_old_devices_yaml("devices: []"), [])


class TimingOutput(unittest.TestCase):
    def test_strip(self):
        raw = "display cpu-usage\r\nSlot 1 CPU 0 CPU usage:\r\n   6% in last 5 seconds\r\n<BB-3>"
        self.assertEqual(strip_echo_and_prompt(raw, "display cpu-usage"), "Slot 1 CPU 0 CPU usage:\n   6% in last 5 seconds")
        self.assertEqual(strip_echo_and_prompt("x\n[BB-3]\n", "display x"), "x")


if __name__ == "__main__":
    unittest.main()
