"""장비 접속 진단과 기존 백본 도구 설정 가져오기.

SecureCRT는 되는데 프로그램만 안 될 때, 접속 과정을 단계별로 직접 시험해 어디서 막히는지 보여 줍니다.
비밀번호는 결과에 포함하지 않습니다.
"""

from __future__ import annotations

import io
import logging
import re
import socket
import time
from typing import Any

from .collector import ConnectFailure, NetmikoDriver, safe_error
from .credentials import Credential

KEXINIT_NAMES = ("kex", "hostkey", "enc_c2s", "enc_s2c", "mac_c2s", "mac_s2c")
LABEL = {"kex": "키 교환", "hostkey": "호스트 키", "enc_c2s": "암호화", "mac_c2s": "무결성(MAC)"}


def read_server_kexinit(host: str, port: int, timeout: float) -> tuple[str, list[str], dict[str, list[str]]]:
    """SSH 서버의 버전 문자열과 지원 암호 방식 목록(KEXINIT)을 읽습니다."""
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(timeout)
    try:
        s.sendall(b"SSH-2.0-NetcheckProbe_1.0\r\n")
        buf, pre, banner = b"", [], ""
        while not banner:
            chunk = s.recv(4096)
            if not chunk:
                raise ConnectionError("서버가 SSH 배너를 보내기 전에 연결을 끊었습니다")
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.rstrip(b"\r").decode("utf-8", "replace")
                if text.startswith("SSH-"):
                    banner = text
                    break
                pre.append(text)
            if len(buf) > 65536:
                raise ConnectionError("SSH 배너가 아닌 데이터가 너무 깁니다")
        while len(buf) < 5:
            chunk = s.recv(4096)
            if not chunk:
                raise ConnectionError("KEXINIT 헤더를 받기 전에 연결이 끊겼습니다")
            buf += chunk
        plen = int.from_bytes(buf[:4], "big")
        if plen < 6 or plen > 65536:
            raise ConnectionError("KEXINIT 길이가 비정상입니다")
        while len(buf) < 4 + plen:
            chunk = s.recv(4096)
            if not chunk:
                raise ConnectionError("KEXINIT 패킷을 모두 받기 전에 연결이 끊겼습니다")
            buf += chunk
        pad = buf[4]
        if pad < 4 or pad >= plen - 1:
            raise ConnectionError("KEXINIT 패딩 길이가 비정상입니다")
        payload = buf[5:4 + plen - pad]
        if len(payload) < 17 or payload[0] != 20:
            raise ConnectionError("KEXINIT 메시지를 받지 못했습니다")
        i, lists = 17, {}
        for name in KEXINIT_NAMES:
            if i + 4 > len(payload):
                raise ConnectionError("KEXINIT 알고리즘 목록이 잘렸습니다")
            n = int.from_bytes(payload[i:i + 4], "big")
            i += 4
            if i + n > len(payload):
                raise ConnectionError("KEXINIT 알고리즘 이름이 잘렸습니다")
            lists[name] = payload[i:i + n].decode("ascii", "replace").split(",") if n else []
            i += n
        return banner, pre, lists
    finally:
        s.close()


def client_algorithms() -> dict[str, list[str]]:
    import paramiko

    T = paramiko.Transport
    return {"kex": list(T._preferred_kex), "hostkey": list(T._preferred_keys),
            "enc_c2s": list(T._preferred_ciphers), "mac_c2s": list(T._preferred_macs)}


def mask_ips(text: str) -> str:
    return re.sub(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b",
                  lambda m: m.group(0) if m.group(1) == "127" else f"{m.group(1)}.x.x.{m.group(4)}", text)


def diagnose(device: dict, cred: Credential | None, ssh_cfg: dict) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    log_buf = io.StringIO()
    handler = logging.StreamHandler(log_buf)
    handler.setLevel(logging.DEBUG)
    plog = logging.getLogger("paramiko")
    nlog = logging.getLogger("netmiko")
    old = (plog.level, nlog.level)
    for lg in (plog, nlog):
        lg.addHandler(handler)
        lg.setLevel(logging.DEBUG)

    def step(name: str, ok: bool | None, detail: str) -> None:
        steps.append({"name": name, "ok": ok, "detail": detail})

    host = device["host"]
    protocol = device.get("protocol", "ssh")
    port = int(device.get("port", 23 if protocol == "telnet" else 22))
    from .config import ssh_for

    ssh_cfg = ssh_for(device, ssh_cfg)
    timeout = int(ssh_cfg["connect_timeout"])
    try:
        import netmiko
        import paramiko

        dtype = device.get("device_type") or ("hp_comware" if device["role"] == "BB" else "aruba_os")
        if protocol == "telnet" and not dtype.endswith("_telnet"):
            dtype += "_telnet"
        step("설정", None, f"{host}:{port} / {protocol.upper()} / 장비 종류 {dtype} / "
                          f"계정 {'(' + cred.username + ')' if cred else '없음'} / "
                          f"netmiko {netmiko.__version__}, paramiko {paramiko.__version__}")
        if cred is None:
            step("계정", False, "이 장비의 접속 계정이 입력되지 않았습니다. 설정 → 접속 계정에서 입력하세요.")
            return _finish(steps, log_buf)

        t0 = time.time()
        try:
            socket.create_connection((host, port), timeout=10).close()
            step("TCP 연결", True, f"{port}번 포트 열림 ({(time.time() - t0) * 1000:.0f}ms)")
        except Exception as exc:
            step("TCP 연결", False, f"{port}번 포트에 연결하지 못했습니다: {type(exc).__name__} {safe_error(exc)}. "
                                  "SecureCRT와 같은 PC인지, 포트·접속 방식이 같은지 확인하세요.")
            return _finish(steps, log_buf)

        if protocol == "ssh":
            try:
                t0 = time.time()
                banner, pre, server = read_server_kexinit(host, port, timeout)
                step("SSH 배너", True, f"{banner} ({(time.time() - t0):.1f}초)" + (f" / 배너 앞 문구: {' | '.join(pre)[:200]}" if pre else ""))
                mine = client_algorithms()
                bad = []
                for key in ("kex", "hostkey", "enc_c2s", "mac_c2s"):
                    common = [a for a in mine[key] if a in server[key]]
                    if not common:
                        bad.append(f"{LABEL[key]}: 장비 {', '.join(server[key])}")
                detail = " / ".join(f"{LABEL[k]} {', '.join(server[k][:6])}" for k in ("kex", "hostkey", "enc_c2s", "mac_c2s"))
                if bad:
                    step("암호 방식", False, "맞는 방식이 없습니다 → " + " ; ".join(bad))
                else:
                    step("암호 방식", True, "공통 방식 있음 (" + detail + ")")
            except Exception as exc:
                step("SSH 배너", False, f"{type(exc).__name__}: {safe_error(exc)}")

            try:
                tr = paramiko.Transport(socket.create_connection((host, port), timeout=timeout))
                tr.banner_timeout = timeout
                tr.start_client(timeout=timeout)
                try:
                    tr.auth_none(cred.username)
                    step("인증 방식", True, "인증 없이 로그인 허용(장비 안에서 다시 아이디/비밀번호를 물을 수 있음)")
                except paramiko.BadAuthenticationType as exc:
                    step("인증 방식", True, "장비가 허용: " + ", ".join(exc.allowed_types))
                except Exception as exc:
                    step("인증 방식", None, f"확인 못함: {type(exc).__name__}")
                tr.close()
                tr = paramiko.Transport(socket.create_connection((host, port), timeout=timeout))
                tr.banner_timeout = timeout
                tr.start_client(timeout=timeout)
                try:
                    tr.auth_password(cred.username, cred.password, fallback=True)
                    ok = tr.is_authenticated()
                    step("로그인", ok, "성공" if ok else "추가 인증 필요(2단계 인증 등)")
                except paramiko.AuthenticationException as exc:
                    step("로그인", False, f"계정/비밀번호 거부: {safe_error(exc)}. SecureCRT에 저장된 계정과 같은지 확인하세요.")
                    tr.close()
                    return _finish(steps, log_buf)
                if tr.is_authenticated():
                    ch = tr.open_session(timeout=timeout)
                    ch.get_pty(term="vt100", width=200, height=50)
                    ch.invoke_shell()
                    screen = _read(ch, 6)
                    if not screen.strip():
                        ch.send("\r\n")
                        screen += _read(ch, 4)
                    ch.close()
                    lines = [l for l in screen.replace("\r", "").split("\n") if l.strip()]
                    step("로그인 직후 화면", True, "\n".join(lines[-15:])[-1500:] or "(아무것도 출력되지 않음)")
                tr.close()
            except Exception as exc:
                step("SSH 협상/로그인", False, f"{type(exc).__name__}: {safe_error(exc)}")

        t0 = time.time()
        try:
            dev = dict(device, device_type=dtype)
            session = NetmikoDriver().open(dev, cred, ssh_cfg)
            try:
                cmd = "display version" if device["role"] == "BB" else "show version"
                out = session.run(cmd, 30)
                first = "\n".join([l for l in out.split("\n") if l.strip()][:4])
                step("프로그램 접속·명령", True, f"{time.time() - t0:.1f}초, '{cmd}' 응답:\n{first}")
            finally:
                session.close()
        except ConnectFailure as exc:
            step("프로그램 접속·명령", False, f"[{exc.kind}] {exc}")
        except Exception as exc:
            step("프로그램 접속·명령", False, f"{type(exc).__name__}: {safe_error(exc)}")
    finally:
        for lg in (plog, nlog):
            lg.removeHandler(handler)
        plog.setLevel(old[0])
        nlog.setLevel(old[1])
    return _finish(steps, log_buf)


def _read(ch, seconds: float) -> str:
    out, end = "", time.time() + seconds
    while time.time() < end:
        if ch.recv_ready():
            out += ch.recv(65535).decode("utf-8", "replace")
        else:
            time.sleep(0.2)
    return out


def _finish(steps: list[dict], log_buf: io.StringIO) -> dict[str, Any]:
    failed = [s for s in steps if s["ok"] is False]
    log_lines = [l for l in log_buf.getvalue().splitlines() if "password" not in l.lower()][-60:]
    summary = f"{failed[0]['name']} 단계에서 막혔습니다." if failed else "모든 단계 통과"
    report = "\n".join(f"[{'OK' if s['ok'] else ('실패' if s['ok'] is False else '정보')}] {s['name']}: {s['detail']}" for s in steps)
    return {"ok": not failed, "summary": summary, "steps": steps,
            "log": "\n".join(log_lines),
            "copy_text": mask_ips(f"{summary}\n{report}\n--- 상세 로그 ---\n" + "\n".join(log_lines))}


def parse_old_devices_yaml(text: str) -> list[dict[str, Any]]:
    """기존 백본 상태 추적기의 config/devices.yaml → 장비 목록."""
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        items = data.get("devices", []) if isinstance(data, dict) else []
    except ImportError:  # pragma: no cover - 간이 해석
        items, cur = [], None
        for line in text.splitlines():
            m = re.match(r"^\s*(-\s*)?(\w+)\s*:\s*(.*?)\s*$", line)
            if not m:
                continue
            if m.group(1):
                cur = {}
                items.append(cur)
            if cur is not None:
                cur[m.group(2)] = m.group(3).strip("'\"")
    out = []
    for it in items:
        if not isinstance(it, dict) or not it.get("host"):
            continue
        dtype = str(it.get("device_type") or "hp_comware").strip()
        out.append({
            "name": str(it.get("name") or it["host"]).strip(),
            "host": str(it["host"]).strip(),
            "port": int(it.get("port") or (23 if dtype.endswith("_telnet") else 22)),
            "device_type": dtype,
            "protocol": "telnet" if dtype.endswith("_telnet") else "ssh",
            "enabled": str(it.get("enabled", True)).lower() not in ("false", "0", "no"),
            "role": "BB",
        })
    return out
