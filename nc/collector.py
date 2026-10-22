"""SSH 수집기. 장비에는 조회(show/display) 명령만 보냅니다."""

from __future__ import annotations

import re
import socket
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Protocol

from .commands import ROLE_DEVICE_TYPE, CommandSpec, check_console_command
from .credentials import Credential
from .parsers import clean, looks_like_error

SECRET_RE = re.compile(r"(?i)(password|passwd|secret|community)\s*[:=]?\s*\S+")


def safe_error(text: str) -> str:
    text = SECRET_RE.sub(r"\1 ****", str(text))
    text = " ".join(text.split())
    return text[:300]


@dataclass
class CmdResult:
    id: str
    label: str
    command: str
    output: str
    ok: bool
    error: str = ""
    duration: float = 0.0
    optional: bool = False


@dataclass
class DeviceCollection:
    device_id: str
    connected: bool
    error: str = ""
    error_kind: str = ""          # credential / auth / timeout / connection
    results: dict[str, CmdResult] = field(default_factory=dict)
    started: float = 0.0
    finished: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


class Session(Protocol):
    def run(self, command: str, timeout: int) -> str: ...
    def close(self) -> None: ...


class Driver(Protocol):
    def open(self, device: dict, cred: Credential, ssh: dict) -> Session: ...


class ConnectFailure(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


# ------------------------------------------------------------------ Netmiko (실장비)

TRAILING_PROMPT_RE = re.compile(r"^\s*(?:<[^<>\r\n]{1,80}>|\[[^\[\]\r\n]{1,80}\])\s*$")


class NetmikoSession:
    """timing=True: 기존 백본 상태 추적기와 같은 방식(send_command_timing).
    프롬프트 모양에 의존하지 않아 배너·프롬프트가 특이한 장비에서도 동작합니다."""

    def __init__(self, conn: Any, timing: bool = False) -> None:
        self.conn = conn
        self.timing = timing

    def run(self, command: str, timeout: int) -> str:
        if self.timing:
            raw = self.conn.send_command_timing(
                command_string=command,
                strip_prompt=False,
                strip_command=False,
                cmd_verify=False,
                read_timeout=timeout,
            )
            return strip_echo_and_prompt(raw, command)
        try:
            return self.conn.send_command(command, read_timeout=timeout, strip_prompt=True, strip_command=True)
        except Exception as exc:
            if "ReadTimeout" not in type(exc).__name__ and "pattern" not in str(exc).lower():
                raise
            # 프롬프트를 못 찾으면 시간 기준 방식으로 한 번 더
            raw = self.conn.send_command_timing(command_string=command, strip_prompt=False, strip_command=False,
                                                cmd_verify=False, read_timeout=timeout)
            return strip_echo_and_prompt(raw, command)

    def close(self) -> None:
        try:
            self.conn.disconnect()
        except Exception:
            pass

    def abort(self) -> None:
        """응답 없이 멈춘 세션을 강제로 끊어 기다리던 명령이 바로 끝나게 합니다."""
        for name in ("remote_conn", "remote_conn_pre"):
            obj = getattr(self.conn, name, None)
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass


def strip_echo_and_prompt(raw: str, command: str) -> str:
    lines = (raw or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and command.strip() and command.strip() in lines[0]:
        lines.pop(0)
    while lines and (not lines[-1].strip() or TRAILING_PROMPT_RE.match(lines[-1])):
        lines.pop()
    return "\n".join(lines)


def _aruba_class():
    from netmiko.aruba.aruba_os import ArubaOsSSH

    class SafeArubaOsSSH(ArubaOsSSH):
        """enable 비밀번호가 없을 때 enable을 강제로 시도하지 않는 Aruba 세션."""

        def session_preparation(self) -> None:
            self.ansi_escape_codes = True
            self._test_channel_read(pattern=r"[>#]")
            self.set_base_prompt()
            if not self.check_enable_mode() and self.secret:
                self.enable()
            try:
                self.disable_paging(command="no paging")
            except Exception:
                pass

    return SafeArubaOsSSH


def probe_connection(host: str, port: int, protocol: str, timeout: float = 8.0) -> tuple[str, str]:
    """접속 실패 시 원인을 좁힙니다: 포트 열림 → SSH 배너 → 암호 방식 협상.

    반환 (kind, 사람이 읽을 메시지). 원인을 특정하지 못하면 ("", "").
    """
    proto = "Telnet" if protocol == "telnet" else "SSH"
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except socket.timeout:
        return "timeout", (f"{host}:{port} 응답 없음({int(timeout)}초): 관리망 경로, 방화벽/ACL, "
                           f"장비의 {proto} 허용 대상(접속 PC IP)을 확인하세요.")
    except ConnectionRefusedError:
        other = "Telnet(23)" if proto == "SSH" else "SSH(22)"
        return "refused", (f"{host}:{port} 연결 거부: 장비에서 {proto}가 꺼져 있거나 포트가 다릅니다. "
                           f"설정에서 접속 방식을 {other}로 바꿔 보세요.")
    except OSError as exc:
        return "connection", f"{host}:{port} 접속 실패: {safe_error(exc)}"
    if protocol == "telnet":
        sock.close()
        return "", ""
    try:
        import paramiko

        t = paramiko.Transport(sock)
        t.banner_timeout = timeout
        try:
            t.start_client(timeout=timeout)
        except paramiko.SSHException as exc:
            text = str(exc)
            remote = getattr(t, "remote_version", "") or ""
            if any(k in text.lower() for k in ("incompatible", "no acceptable", "no matching", "kex")):
                return "ssh_algo", (f"SSH 암호 방식이 맞지 않습니다(장비: {remote or '알 수 없음'}). "
                                    "오래된 장비가 쓰는 SHA-1 방식을 지원하는 최신 버전으로 업데이트하거나, "
                                    "설정에서 접속 방식을 Telnet으로 바꿔 보세요. "
                                    f"상세: {safe_error(text)}")
            if "banner" in text.lower() or "eof" in text.lower():
                return "ssh_banner", (f"{host}:{port}에서 SSH 응답이 없습니다. 이 포트가 SSH가 아니거나 "
                                      "장비가 접속 PC를 차단했을 수 있습니다. 상세: " + safe_error(text))
            return "ssh", f"SSH 협상 실패: {safe_error(text)}"
        finally:
            t.close()
    except Exception as exc:  # pragma: no cover - 방어
        return "", f"진단 중 오류: {type(exc).__name__}"
    return "", ""


class NetmikoDriver:
    def open(self, device: dict, cred: Credential, ssh: dict) -> Session:
        try:
            from netmiko import ConnectHandler
            from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException
        except ImportError as exc:  # pragma: no cover
            raise ConnectFailure("connection", "netmiko가 설치되어 있지 않습니다. requirements.txt를 설치하세요.") from exc
        # 접속 대기 시간(설정 → 접속 대기 시간, 기본 60초)
        timeout = int(ssh.get("connect_timeout", 60))
        protocol = device.get("protocol", "ssh")
        device_type = (device.get("device_type") or "").strip() or ROLE_DEVICE_TYPE[device["role"]]
        if protocol == "telnet" and not device_type.endswith("_telnet"):
            device_type += "_telnet"
        port = int(device.get("port", 23 if protocol == "telnet" else 22))
        params = dict(
            device_type=device_type,
            host=device["host"],
            port=port,
            username=cred.username,
            password=cred.password,
            conn_timeout=timeout,
            auth_timeout=timeout,
            banner_timeout=timeout,
            timeout=timeout,
            fast_cli=False,
        )
        if cred.secret:
            params["secret"] = cred.secret
        try:
            if device["role"] in ("MM", "WLC") and protocol != "telnet" and device_type == "aruba_os":
                conn = _aruba_class()(**params)
            else:
                conn = ConnectHandler(**params)
        except NetmikoAuthenticationException as exc:
            raise ConnectFailure("auth", "로그인 실패: 계정 또는 비밀번호를 확인하세요. "
                                 "(백본·MM·WLC 모두 설정 → 접속 계정 하나를 씁니다)") from exc
        except Exception as exc:
            kind, msg = probe_connection(device["host"], port, protocol, min(timeout, 10))
            if kind:
                raise ConnectFailure(kind, msg) from exc
            if isinstance(exc, NetmikoTimeoutException):
                raise ConnectFailure("timeout", f"접속 시간 초과({timeout}초): {safe_error(exc)}") from exc
            raise ConnectFailure("connection", f"접속 실패: {type(exc).__name__} {safe_error(exc)}") from exc
        # 백본은 기존 백본 상태 추적기와 동일하게 시간 기준 명령 실행
        return NetmikoSession(conn, timing=device["role"] == "BB")


# ------------------------------------------------------------------ 수집

def collect_device(
    driver: Driver,
    device: dict,
    specs: list[CommandSpec],
    cred: Credential | None,
    ssh: dict,
    progress: Callable[[str], None] | None = None,
    deadline: float | None = None,
    holder: dict | None = None,
) -> DeviceCollection:
    """deadline(시각)을 넘기면 남은 명령은 실행하지 않고 '시간 초과로 생략'으로 남깁니다.
    holder가 있으면 열린 세션을 holder["session"]에 넣어 밖에서 강제 종료할 수 있게 합니다."""
    progress = progress or (lambda _m: None)
    from .config import ssh_for

    ssh = ssh_for(device, ssh)  # 백본 / 컨트롤러 대기 시간 분리
    dc = DeviceCollection(device_id=device["id"], connected=False, started=time.time())
    if cred is None:
        dc.error = "접속 계정이 입력되지 않았습니다. 설정 → 접속 계정에서 입력하세요."
        dc.error_kind = "credential"
        dc.finished = time.time()
        return dc
    retries = int(ssh.get("retries", 1))
    session = None
    last: ConnectFailure | None = None
    for attempt in range(retries + 1):
        try:
            progress(f"{device['name']} 접속 중")
            session = driver.open(device, cred, ssh)
            if holder is not None:
                holder["session"] = session
            break
        except ConnectFailure as exc:
            last = exc
            if exc.kind == "auth":
                break  # 계정 잠금 방지: 인증 실패는 재시도하지 않음
            if deadline and time.time() > deadline:
                break
            time.sleep(min(2.0, 0.5 * (attempt + 1)))
    if session is None:
        dc.error = str(last) if last else "접속 실패"
        dc.error_kind = last.kind if last else "connection"
        dc.finished = time.time()
        return dc
    dc.connected = True
    try:
        for spec in specs:
            if deadline and time.time() > deadline:
                dc.results[spec.id] = CmdResult(spec.id, spec.label, spec.commands[0], "", False,
                                                "시간 초과로 생략(장비 응답이 너무 느려 이 장비 점검 제한 시간을 넘김)",
                                                0.0, spec.optional)
                continue
            dc.results[spec.id] = run_spec(session, spec, ssh)
            progress(f"{device['name']} {spec.label}")
    finally:
        session.close()
    dc.finished = time.time()
    return dc


def run_spec(session: Session, spec: CommandSpec, ssh: dict) -> CmdResult:
    """대체 명령을 차례로 시도. 거부되거나(expect가 있을 때) 기대한 값이 없으면 다음 명령."""
    timeout = max(spec.timeout or 0, int(ssh.get("command_timeout", 60)))
    started = time.time()
    first_ok: tuple[str, str] | None = None
    output, error, used = "", "", spec.commands[0]
    for cmd in spec.commands:
        used = cmd
        reason = check_console_command(cmd)
        if reason:
            return CmdResult(spec.id, spec.label, cmd, "", False, reason,
                             round(time.time() - started, 2), spec.optional)
        try:
            output = clean(session.run(cmd, timeout))
        except Exception as exc:
            output, error = "", f"명령 실패: {type(exc).__name__} {safe_error(exc)}"
            continue
        if looks_like_error(output):
            error = "장비가 명령을 지원하지 않거나 권한이 없습니다."
            continue
        if not output.strip():
            error = "빈 출력"
            continue
        if spec.expect and not re.search(spec.expect, output):
            first_ok = first_ok or (cmd, output)
            error = "기대한 값이 출력에 없습니다."
            continue
        error = ""
        break
    else:
        if first_ok:  # 해석 가능한 출력은 없지만 응답은 있었음 → 원본 확인용으로 남김
            used, output = first_ok
            error = ""
    ok = not error and bool(output.strip())
    return CmdResult(spec.id, spec.label, used, output, ok, error, round(time.time() - started, 2), spec.optional)
