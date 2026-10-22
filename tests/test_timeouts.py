"""백본과 컨트롤러(MM·WLC) 접속 대기 시간이 따로 적용되는지."""
import unittest

from nc.collector import collect_device
from nc.commands import CommandSpec
from nc.config import validate
from nc.credentials import Credential


class FakeSession:
    def __init__(self, log, ssh):
        self.log, self.ssh = log, ssh

    def run(self, command, timeout):
        self.log.append(("run", timeout))
        return "ok"

    def close(self):
        pass


class FakeDriver:
    def __init__(self):
        self.log = []

    def open(self, device, cred, ssh):
        self.log.append(("open", device["role"], ssh["connect_timeout"]))
        return FakeSession(self.log, ssh)


class Timeouts(unittest.TestCase):
    def test_bb_and_controller_use_their_own_values(self):
        cfg = validate({"ssh": {"bb_connect_timeout": 300, "bb_command_timeout": 240,
                                "ctrl_connect_timeout": 45, "ctrl_command_timeout": 50}})
        spec = [CommandSpec("x", "x", ("display x",))]
        for role, conn, cmd in (("BB", 300, 240), ("WLC", 45, 50), ("MM", 45, 50)):
            drv = FakeDriver()
            collect_device(drv, {"id": role, "name": role, "role": role, "host": "h"}, spec, Credential("u", "p"), cfg["ssh"])
            self.assertEqual(drv.log[0], ("open", role, conn))
            self.assertEqual(drv.log[1], ("run", cmd))

    def test_migration_from_shared_values(self):
        s = validate({"ssh": {"connect_timeout": 15, "command_timeout": 30}})["ssh"]
        self.assertEqual((s["bb_connect_timeout"], s["ctrl_connect_timeout"]), (120, 60))
        s = validate({"ssh": {"connect_timeout": 180, "command_timeout": 60}})["ssh"]
        self.assertEqual((s["bb_connect_timeout"], s["ctrl_connect_timeout"]), (180, 180))
        self.assertNotIn("connect_timeout", s)

    def test_range(self):
        from nc.config import ConfigError
        with self.assertRaises(ConfigError):
            validate({"ssh": {"bb_connect_timeout": 5}})


if __name__ == "__main__":
    unittest.main()
