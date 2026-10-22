"""백본 접속 방식별 검증: 오래된 SSH(SHA-1), Telnet, 접속 실패 원인 안내."""
import socket
import unittest

import paramiko

from nc.collector import ConnectFailure, NetmikoDriver, probe_connection, run_spec
from nc.commands import BB_COMMANDS
from nc.config import ConfigError, normalize_device
from nc.credentials import Credential
from tests.mock_ssh import MockDevice
from tests.mock_telnet import MockTelnetDevice
from tests.test_e2e_ssh import comware

SSH = {"connect_timeout": 8, "command_timeout": 15}
CPU = next(c for c in BB_COMMANDS if c.id == "cpu")


def bb(port, protocol="ssh"):
    return {"id": "bb3", "name": "BB-3", "role": "BB", "host": "127.0.0.1", "port": port, "protocol": protocol}


class BackboneAccess(unittest.TestCase):
    @unittest.skipIf(int(paramiko.__version__.split(".")[0]) >= 4, "배포판은 paramiko 3.x를 사용(requirements.txt)")
    def test_legacy_sha1_ssh_backbone(self):
        d = MockDevice("<BB-3>", comware({}), legacy=True)
        try:
            s = NetmikoDriver().open(bb(d.port), Credential("op", "pw"), SSH)
            r = run_spec(s, CPU, SSH)
            s.close()
            self.assertTrue(r.ok, r.error)
            self.assertIn("Last 1 min", r.output)
        finally:
            d.close()

    def test_telnet_backbone(self):
        d = MockTelnetDevice("<BB-3>", comware({}))
        try:
            s = NetmikoDriver().open(bb(d.port, "telnet"), Credential("op", "pw"), SSH)
            r = run_spec(s, CPU, SSH)
            s.close()
            self.assertTrue(r.ok, r.error)
            self.assertIn("Last 1 min", r.output)
            self.assertIn("show cpu summary", d.received)
        finally:
            d.close()

    def test_telnet_wrong_password(self):
        d = MockTelnetDevice("<BB-3>", comware({}))
        try:
            with self.assertRaises(ConnectFailure) as cm:
                NetmikoDriver().open(bb(d.port, "telnet"), Credential("op", "bad"), SSH)
            self.assertEqual(cm.exception.kind, "auth")
        finally:
            d.close()

    def test_refused_port_is_explained(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        with self.assertRaises(ConnectFailure) as cm:
            NetmikoDriver().open(bb(port), Credential("op", "pw"), SSH)
        self.assertEqual(cm.exception.kind, "refused")
        self.assertIn("Telnet", str(cm.exception))

    def test_non_ssh_port_is_explained(self):
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1); port = srv.getsockname()[1]

        def serve():
            c, _ = srv.accept(); c.sendall(b"Username:"); c.close()
        import threading
        threading.Thread(target=serve, daemon=True).start()
        kind, msg = probe_connection("127.0.0.1", port, "ssh", 3)
        srv.close()
        self.assertIn(kind, ("ssh_banner", "ssh"))
        self.assertTrue(msg)

    def test_config_protocol(self):
        d = normalize_device({"role": "BB", "host": "192.0.2.101", "protocol": "telnet"}, 0)
        self.assertEqual((d["protocol"], d["port"]), ("telnet", 23))
        self.assertEqual(normalize_device({"role": "BB", "host": "192.0.2.101"}, 0)["protocol"], "ssh")
        with self.assertRaises(ConfigError):
            normalize_device({"role": "WLC", "host": "192.0.2.101", "protocol": "telnet"}, 0)


if __name__ == "__main__":
    unittest.main()
