"""접속 진단의 단계·결과를 유지하면서 부분 생성 자원을 정리하는지 검증합니다.

모든 소켓과 SSH 라이브러리를 대체하므로 실제 장비나 설치된 SSH 패키지가
필요하지 않습니다. 가짜 Transport도 정상 종료 시 자신의 소켓을 닫습니다.
"""

import logging
import sys
import unittest
from contextlib import ExitStack
from copy import deepcopy
from types import ModuleType
from unittest.mock import Mock, call, patch

from nc.collector import ConnectFailure
from nc.credentials import Credential
from nc.diagnose import diagnose


class AuthenticationException(Exception):
    pass


class BadAuthenticationType(AuthenticationException):
    def __init__(self, allowed_types):
        super().__init__("allowed authentication types")
        self.allowed_types = allowed_types


SSH_STEPS = [
    "설정", "TCP 연결", "SSH 배너", "암호 방식", "인증 방식", "로그인",
    "로그인 직후 화면", "프로그램 접속·명령",
]
COMMAND_OUTPUT = "Mock version\n\nBuild 1\nUptime 2\nReady\nOMITTED\n"
SCREEN = "\r\nWelcome\r\n\n<MOCK>\r\n"


class ProbeFixture:
    def __init__(self, role="BB", protocol="ssh"):
        self.device = {
            "id": "mock-device", "name": "Mock device", "role": role,
            "host": "192.0.2.40", "port": 2222, "protocol": protocol,
        }
        self.cred = Credential("operator", "S05-test-value")
        self.ssh = {
            "connect_timeout": 99, "command_timeout": 88,
            "bb_connect_timeout": 7, "bb_command_timeout": 11,
            "ctrl_connect_timeout": 9, "ctrl_command_timeout": 13,
        }
        self.sockets = [Mock(name=f"socket_{i}") for i in range(3)]
        self.transports = [Mock(name=f"transport_{i}") for i in range(2)]
        self.channel = Mock(name="channel")
        self.session = Mock(name="netmiko_session")
        self.driver = Mock(name="netmiko_driver")
        self.driver.open.return_value = self.session
        self.session.run.side_effect = self._command
        self.created_sockets = []
        self.created_transports = []
        self.bound_sockets = {}
        self.constructor_fail_at = None
        self.constructor_error = OSError("original-constructor-failure")

        for i, tr in enumerate(self.transports):
            tr.is_authenticated.return_value = True
            tr.open_session.return_value = self.channel
            # Match real Transport ownership on normal close. Extra raw-socket
            # scopes are required only when construction/close itself fails.
            tr.close.side_effect = lambda i=i: self.bound_sockets[i].close()
        self.transports[0].auth_none.side_effect = BadAuthenticationType(
            ["password", "keyboard-interactive"]
        )

        self.connect = Mock(name="create_connection", side_effect=self._connect)
        self.transport = Mock(name="Transport", side_effect=self._transport)
        self.transport._preferred_kex = ("curve25519-sha256",)
        self.transport._preferred_keys = ("ssh-ed25519",)
        self.transport._preferred_ciphers = ("aes128-ctr",)
        self.transport._preferred_macs = ("hmac-sha2-256",)
        self.algorithms = {
            "kex": ["curve25519-sha256"], "hostkey": ["ssh-ed25519"],
            "enc_c2s": ["aes128-ctr"], "enc_s2c": ["aes128-ctr"],
            "mac_c2s": ["hmac-sha2-256"], "mac_s2c": ["hmac-sha2-256"],
        }
        self.banner = Mock(return_value=("SSH-2.0-Mock", [], self.algorithms))
        self.read = Mock(return_value=SCREEN)

        self.paramiko = ModuleType("paramiko")
        self.paramiko.__version__ = "mock-paramiko"
        self.paramiko.Transport = self.transport
        self.paramiko.AuthenticationException = AuthenticationException
        self.paramiko.BadAuthenticationType = BadAuthenticationType
        self.netmiko = ModuleType("netmiko")
        self.netmiko.__version__ = "mock-netmiko"

    def _connect(self, *args, **kwargs):
        sock = self.sockets[len(self.created_sockets)]
        self.created_sockets.append(sock)
        return sock

    def _transport(self, sock):
        index = self.transport.call_count - 1
        if index == self.constructor_fail_at:
            raise self.constructor_error
        tr = self.transports[index]
        self.bound_sockets[index] = sock
        self.created_transports.append(tr)
        return tr

    def _command(self, *args, **kwargs):
        logging.getLogger("paramiko").debug("Mock connected to 192.0.2.40")
        logging.getLogger("netmiko").debug("PASSWORD omitted by report")
        return COMMAND_OUTPUT

    def __enter__(self):
        self.stack = ExitStack()
        self.stack.enter_context(patch.dict(sys.modules, {
            "paramiko": self.paramiko, "netmiko": self.netmiko,
        }))
        self.stack.enter_context(patch("nc.diagnose.socket.create_connection", self.connect))
        self.stack.enter_context(patch("nc.diagnose.read_server_kexinit", self.banner))
        self.stack.enter_context(patch("nc.diagnose._read", self.read))
        self.stack.enter_context(patch("nc.diagnose.NetmikoDriver", return_value=self.driver))
        self.stack.enter_context(patch("nc.diagnose.time.time", return_value=100.0))
        for name in ("paramiko", "netmiko"):
            # Keep synthetic logs inside the diagnostic report, not the CI log.
            self.stack.enter_context(patch.object(logging.getLogger(name), "propagate", False))
        return self

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)


class DiagnoseResources(unittest.TestCase):
    def run_probe(self, fixture, *, with_credentials=True):
        loggers = [logging.getLogger(name) for name in ("paramiko", "netmiko")]
        before = [(list(lg.handlers), lg.level) for lg in loggers]
        try:
            return diagnose(fixture.device, fixture.cred if with_credentials else None, fixture.ssh)
        finally:
            self.assertEqual([(list(lg.handlers), lg.level) for lg in loggers], before)

    def assert_report(self, result, names, summary):
        self.assertEqual(set(result), {"ok", "summary", "steps", "log", "copy_text"})
        self.assertEqual([s["name"] for s in result["steps"]], names)
        for step in result["steps"]:
            self.assertEqual(set(step), {"name", "ok", "detail"})
        self.assertEqual(result["summary"], summary)
        self.assertEqual(result["ok"], summary == "모든 단계 통과")
        self.assertTrue(result["copy_text"].startswith(summary + "\n[정보] 설정: "))
        self.assertIn("\n--- 상세 로그 ---\n", result["copy_text"])
        self.assertNotIn("S05-test-value", str(result))

    def assert_closed(self, fixture, *, channel=False, session=True):
        for sock in fixture.created_sockets:
            sock.close.assert_called()
        for tr in fixture.created_transports:
            tr.close.assert_called_once()
        if channel:
            fixture.channel.close.assert_called_once()
        else:
            fixture.channel.close.assert_not_called()
        if session:
            fixture.session.close.assert_called_once()
        else:
            fixture.session.close.assert_not_called()

    def assert_ssh_error(self, result, marker):
        failures = [s for s in result["steps"] if s["name"] == "SSH 협상/로그인"]
        self.assertEqual(len(failures), 1)
        self.assertIs(failures[0]["ok"], False)
        self.assertIn(marker, failures[0]["detail"])
        self.assertNotIn("secondary-cleanup", failures[0]["detail"])
        self.assertEqual(result["steps"][-1]["name"], "프로그램 접속·명령")
        self.assertIs(result["steps"][-1]["ok"], True)

    def test_normal_ssh_preserves_order_commands_timeouts_and_report(self):
        for role in ("BB", "MM", "WLC"):
            for blank_first_screen in (False, True):
                with self.subTest(role=role, blank_first_screen=blank_first_screen):
                    with ProbeFixture(role) as f:
                        if blank_first_screen:
                            f.read.side_effect = ["\r\n", SCREEN]
                        original_device, original_ssh = deepcopy(f.device), deepcopy(f.ssh)
                        result = self.run_probe(f)
                        self.assert_report(result, SSH_STEPS, "모든 단계 통과")
                        self.assertEqual([s["ok"] for s in result["steps"]], [None] + [True] * 7)
                        timeout = 7 if role == "BB" else 9
                        command_timeout = 11 if role == "BB" else 13
                        dtype = "hp_comware" if role == "BB" else "aruba_os"
                        command = "display version" if role == "BB" else "show version"
                        self.assertEqual(f.connect.call_args_list, [
                            call(("192.0.2.40", 2222), timeout=10),
                            call(("192.0.2.40", 2222), timeout=timeout),
                            call(("192.0.2.40", 2222), timeout=timeout),
                        ])
                        f.banner.assert_called_once_with("192.0.2.40", 2222, timeout)
                        self.assertEqual(f.transport.call_args_list, [call(f.sockets[1]), call(f.sockets[2])])
                        for tr in f.transports:
                            self.assertEqual(tr.banner_timeout, timeout)
                            tr.start_client.assert_called_once_with(timeout=timeout)
                        f.transports[0].auth_none.assert_called_once_with("operator")
                        f.transports[1].auth_password.assert_called_once_with(
                            "operator", f.cred.password, fallback=True,
                        )
                        f.transports[1].open_session.assert_called_once_with(timeout=timeout)
                        f.channel.get_pty.assert_called_once_with(term="vt100", width=200, height=50)
                        f.channel.invoke_shell.assert_called_once_with()
                        self.assertEqual(f.read.call_args_list,
                                         [call(f.channel, 6)] + ([call(f.channel, 4)] if blank_first_screen else []))
                        if blank_first_screen:
                            f.channel.send.assert_called_once_with("\r\n")
                        else:
                            f.channel.send.assert_not_called()
                        f.driver.open.assert_called_once_with(
                            dict(original_device, device_type=dtype), f.cred,
                            dict(original_ssh, connect_timeout=timeout, command_timeout=command_timeout),
                        )
                        f.session.run.assert_called_once_with(command, 30)
                        self.assertEqual(result["steps"][6]["detail"], "Welcome\n<MOCK>")
                        self.assertEqual(result["steps"][7]["detail"],
                                         f"0.0초, '{command}' 응답:\nMock version\nBuild 1\nUptime 2\nReady")
                        self.assertEqual(result["log"], "Mock connected to 192.0.2.40")
                        self.assertIn("192.x.x.40", result["copy_text"])
                        self.assertNotIn("192.0.2.40", result["copy_text"])
                        self.assertEqual(f.device, original_device)
                        self.assertEqual(f.ssh, original_ssh)
                        self.assert_closed(f, channel=True)

    def test_telnet_and_missing_credentials_keep_short_paths(self):
        for dtype in (None, "hp_comware_telnet"):
            with self.subTest(telnet_device_type=dtype):
                with ProbeFixture(protocol="telnet") as f:
                    del f.device["port"]
                    if dtype:
                        f.device["device_type"] = dtype
                    result = self.run_probe(f)
                    self.assert_report(result, ["설정", "TCP 연결", "프로그램 접속·명령"], "모든 단계 통과")
                    f.connect.assert_called_once_with(("192.0.2.40", 23), timeout=10)
                    f.transport.assert_not_called()
                    f.banner.assert_not_called()
                    f.read.assert_not_called()
                    self.assertEqual(f.driver.open.call_args.args[0]["device_type"], "hp_comware_telnet")
                    f.session.run.assert_called_once_with("display version", 30)
                    self.assert_closed(f)
        for protocol in ("ssh", "telnet"):
            with self.subTest(missing_credentials=protocol):
                with ProbeFixture(protocol=protocol) as f:
                    result = self.run_probe(f, with_credentials=False)
                    self.assert_report(result, ["설정", "계정"], "계정 단계에서 막혔습니다.")
                    self.assertIs(result["steps"][-1]["ok"], False)
                    f.connect.assert_not_called()
                    f.transport.assert_not_called()
                    f.banner.assert_not_called()
                    f.driver.open.assert_not_called()
                    self.assert_closed(f, session=False)

    def test_constructor_failure_closes_new_socket_and_keeps_original_error(self):
        for index in (0, 1):
            for cleanup_fails in (False, True):
                with self.subTest(transport=index, cleanup_fails=cleanup_fails):
                    with ProbeFixture() as f:
                        f.constructor_fail_at = index
                        if cleanup_fails:
                            f.sockets[index + 1].close.side_effect = RuntimeError("secondary-cleanup-socket")
                        result = self.run_probe(f)
                        names = SSH_STEPS[:4 + index] + ["SSH 협상/로그인", "프로그램 접속·명령"]
                        self.assert_report(result, names, "SSH 협상/로그인 단계에서 막혔습니다.")
                        self.assert_ssh_error(result, "original-constructor-failure")
                        self.assertEqual(len(f.created_sockets), index + 2)
                        self.assertEqual(len(f.created_transports), index)
                        self.assert_closed(f)

    def test_negotiation_and_auth_errors_close_all_acquired_resources(self):
        cases = ((0, "start_client"), (1, "start_client"),
                 (1, "auth_password"), (1, "is_authenticated"))
        for index, method in cases:
            for cleanup_fails in (False, True):
                with self.subTest(transport=index, method=method, cleanup_fails=cleanup_fails):
                    with ProbeFixture() as f:
                        getattr(f.transports[index], method).side_effect = OSError("original-operation-failure")
                        if cleanup_fails:
                            f.transports[index].close.side_effect = RuntimeError("secondary-cleanup-transport")
                            f.sockets[index + 1].close.side_effect = RuntimeError("secondary-cleanup-socket")
                        result = self.run_probe(f)
                        names = SSH_STEPS[:4 + index] + ["SSH 협상/로그인", "프로그램 접속·명령"]
                        self.assert_report(result, names, "SSH 협상/로그인 단계에서 막혔습니다.")
                        self.assert_ssh_error(result, "original-operation-failure")
                        self.assertEqual(len(f.created_transports), index + 1)
                        f.transports[1].open_session.assert_not_called()
                        self.assert_closed(f)

    def test_channel_failures_close_channel_transport_and_socket(self):
        stages = ("open_session", "get_pty", "invoke_shell", "read", "send", "read_retry")
        for stage in stages:
            for cleanup_fails in (False, True):
                with self.subTest(stage=stage, cleanup_fails=cleanup_fails):
                    with ProbeFixture() as f:
                        error = OSError("original-channel-failure")
                        if stage == "open_session":
                            f.transports[1].open_session.side_effect = error
                        elif stage == "read":
                            f.read.side_effect = error
                        elif stage == "read_retry":
                            f.read.side_effect = ["", error]
                        else:
                            getattr(f.channel, stage).side_effect = error
                            if stage == "send":
                                f.read.return_value = ""
                        if cleanup_fails:
                            f.channel.close.side_effect = RuntimeError("secondary-cleanup-channel")
                            f.transports[1].close.side_effect = RuntimeError("secondary-cleanup-transport")
                            f.sockets[2].close.side_effect = RuntimeError("secondary-cleanup-socket")
                        result = self.run_probe(f)
                        names = SSH_STEPS[:6] + ["SSH 협상/로그인", "프로그램 접속·명령"]
                        self.assert_report(result, names, "SSH 협상/로그인 단계에서 막혔습니다.")
                        self.assert_ssh_error(result, "original-channel-failure")
                        if stage in ("send", "read_retry"):
                            f.channel.send.assert_called_once_with("\r\n")
                        self.assert_closed(f, channel=stage != "open_session")

    def test_authentication_rejection_stops_after_cleanup_even_when_close_fails(self):
        for cleanup_fails in (False, True):
            with self.subTest(cleanup_fails=cleanup_fails):
                with ProbeFixture() as f:
                    f.transports[1].auth_password.side_effect = AuthenticationException("original-auth-rejection")
                    if cleanup_fails:
                        f.transports[1].close.side_effect = RuntimeError("secondary-cleanup-transport")
                        f.sockets[2].close.side_effect = RuntimeError("secondary-cleanup-socket")
                    result = self.run_probe(f)
                    self.assert_report(result, SSH_STEPS[:6], "로그인 단계에서 막혔습니다.")
                    self.assertIs(result["steps"][-1]["ok"], False)
                    self.assertIn("original-auth-rejection", result["steps"][-1]["detail"])
                    self.assertNotIn("secondary-cleanup", str(result))
                    f.transports[1].open_session.assert_not_called()
                    f.driver.open.assert_not_called()
                    f.session.run.assert_not_called()
                    self.assert_closed(f, session=False)

    def test_close_failure_after_success_keeps_existing_failure_reporting(self):
        for resource in ("first_transport", "channel", "second_transport"):
            with self.subTest(resource=resource):
                with ProbeFixture() as f:
                    error = RuntimeError("original-close-failure")
                    if resource == "first_transport":
                        f.transports[0].close.side_effect = error
                        f.sockets[1].close.side_effect = RuntimeError("secondary-cleanup-socket")
                        prefix, channel = SSH_STEPS[:5], False
                    elif resource == "channel":
                        f.channel.close.side_effect = error
                        f.transports[1].close.side_effect = RuntimeError("secondary-cleanup-transport")
                        f.sockets[2].close.side_effect = RuntimeError("secondary-cleanup-socket")
                        prefix, channel = SSH_STEPS[:6], True
                    else:
                        f.transports[1].close.side_effect = error
                        f.sockets[2].close.side_effect = RuntimeError("secondary-cleanup-socket")
                        prefix, channel = SSH_STEPS[:7], True
                    result = self.run_probe(f)
                    self.assert_report(result, prefix + ["SSH 협상/로그인", "프로그램 접속·명령"],
                                       "SSH 협상/로그인 단계에서 막혔습니다.")
                    self.assert_ssh_error(result, "original-close-failure")
                    self.assert_closed(f, channel=channel)

    def test_existing_probe_and_auth_information_branches_are_preserved(self):
        cases = ("tcp", "banner", "algorithms", "auth_none_error", "auth_none_allowed", "additional_auth")
        for stage in cases:
            with self.subTest(stage=stage):
                with ProbeFixture() as f:
                    names, summary, channel = list(SSH_STEPS), "모든 단계 통과", True
                    if stage == "tcp":
                        f.connect.side_effect = OSError("mock TCP unavailable")
                        names, summary, channel = SSH_STEPS[:2], "TCP 연결 단계에서 막혔습니다.", False
                    elif stage == "banner":
                        f.banner.side_effect = OSError("mock banner unavailable")
                        names.remove("암호 방식")
                        summary = "SSH 배너 단계에서 막혔습니다."
                    elif stage == "algorithms":
                        f.algorithms["kex"] = ["different-mock-kex"]
                        summary = "암호 방식 단계에서 막혔습니다."
                    elif stage == "auth_none_error":
                        f.transports[0].auth_none.side_effect = OSError("mock auth lookup unavailable")
                    elif stage == "auth_none_allowed":
                        f.transports[0].auth_none.side_effect = None
                    else:
                        f.transports[1].is_authenticated.return_value = False
                        names.remove("로그인 직후 화면")
                        summary, channel = "로그인 단계에서 막혔습니다.", False
                    result = self.run_probe(f)
                    self.assert_report(result, names, summary)
                    if stage == "tcp":
                        f.banner.assert_not_called()
                        f.transport.assert_not_called()
                        f.driver.open.assert_not_called()
                    else:
                        self.assertIs(result["steps"][-1]["ok"], True)
                        f.session.run.assert_called_once_with("display version", 30)
                    if stage == "auth_none_error":
                        auth = next(s for s in result["steps"] if s["name"] == "인증 방식")
                        self.assertIsNone(auth["ok"])
                        self.assertEqual(auth["detail"], "확인 못함: OSError")
                    elif stage == "auth_none_allowed":
                        self.assertIn("인증 없이 로그인 허용", result["steps"][4]["detail"])
                    elif stage == "additional_auth":
                        self.assertEqual(result["steps"][5]["detail"], "추가 인증 필요(2단계 인증 등)")
                        f.transports[1].open_session.assert_not_called()
                    self.assert_closed(f, channel=channel, session=stage != "tcp")

    def test_netmiko_errors_preserve_report_and_existing_session_cleanup(self):
        for stage in ("open_connection", "open_other", "command"):
            with self.subTest(stage=stage):
                with ProbeFixture() as f:
                    if stage == "open_connection":
                        f.driver.open.side_effect = ConnectFailure("connection", "original-netmiko-failure")
                    elif stage == "open_other":
                        f.driver.open.side_effect = OSError("original-netmiko-failure")
                    else:
                        f.session.run.side_effect = OSError("original-netmiko-failure")
                    result = self.run_probe(f)
                    self.assert_report(result, SSH_STEPS, "프로그램 접속·명령 단계에서 막혔습니다.")
                    self.assertIs(result["steps"][-1]["ok"], False)
                    self.assertIn("original-netmiko-failure", result["steps"][-1]["detail"])
                    if stage == "open_connection":
                        self.assertTrue(result["steps"][-1]["detail"].startswith("[connection] "))
                    if stage != "command":
                        f.session.run.assert_not_called()
                    self.assert_closed(f, channel=True, session=stage == "command")


if __name__ == "__main__":
    unittest.main()
