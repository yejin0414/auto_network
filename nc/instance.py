"""한 PC에서 하나만 실행 + 새 버전 실행 시 이전 버전 교체.

같은 포트를 이미 쓰는 프로그램이 있으면:
- 같은 버전이면 그 창을 앞으로 띄우고 이번 실행은 끝냅니다.
- 이전 버전이면 종료할지 물어보고, 예를 누르면 이전 버전을 끄고 새 버전으로 실행합니다.
  (같은 AutoNetwork 앱의 인증된 종료 요청만 사용하며 다른 앱을 강제 종료하지 않습니다.)
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
APP_ID = "auto_network"


def instance_file(demo: bool = False) -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "AutoNetwork.NetcheckCenter" / ("demo-instance.json" if demo else "instance.json")


def write_instance(port: int, token: str, version: str, demo: bool = False) -> None:
    try:
        p = instance_file(demo)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"app": APP_ID, "demo": demo, "pid": os.getpid(), "port": port,
                                   "token": token, "version": version}), encoding="utf-8")
        if sys.platform != "win32":
            tmp.chmod(0o600)
        tmp.replace(p)
    except OSError:
        pass


def clear_instance(demo: bool = False) -> None:
    try:
        p = instance_file(demo)
        if p.exists() and json.loads(p.read_text(encoding="utf-8")).get("pid") == os.getpid():
            p.unlink()
    except (OSError, ValueError):
        pass


def _read_instance(demo: bool = False) -> dict:
    try:
        value = json.loads(instance_file(demo).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _http(port: int, path: str, token: str = "", body: dict | None = None, timeout: float = 3) -> dict | None:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 headers={"X-NC-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            value = json.loads(r.read().decode("utf-8"))
            return value if isinstance(value, dict) else None
    except Exception:
        return None


def running_instance(demo: bool = False) -> dict | None:
    """프로그램 창(화면 서버)이 지금 실행 중이면 그 정보를, 아니면 None."""
    info = _read_instance(demo)
    port = info.get("port")
    if not port:
        return None
    try:
        v = _http(int(port), "/api/version", timeout=3)
    except (TypeError, ValueError):
        return None
    return {**info, **v} if v and v.get("app") == APP_ID and bool(v.get("demo")) == demo else None


def port_free(port: int) -> bool:
    s = socket.socket()
    if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # 방금 닫힌 연결(TIME_WAIT)은 무시
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def wait_port_free(port: int, seconds: float = 15) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if port_free(port):
            return True
        time.sleep(0.3)
    return False


def listener_pid(port: int) -> int | None:
    """Windows netstat으로 127.0.0.1:port 를 듣고 있는 프로세스 번호."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                             timeout=10, creationflags=NO_WINDOW).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].endswith(f":{port}") and "LISTEN" in parts[3].upper():
            try:
                return int(parts[4])
            except ValueError:
                pass
    return None


def image_name(pid: int) -> str:
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, timeout=10, creationflags=NO_WINDOW).stdout
        m = re.match(r'\s*"([^"]+)"', out)
        return m.group(1) if m else ""
    except Exception:
        return ""


def _looks_like_netcheck(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
            return "NC_TOKEN" in r.read(4096).decode("utf-8", "replace")
    except Exception:
        return False


def take_over(port: int, my_version: str, ask: Callable[[str], bool], say: Callable[[str], None],
              demo: bool = False) -> str:
    """포트가 사용 중일 때 처리. 반환: 'ready'(이어서 실행) / 'focused'(기존 창 사용, 종료) / 'busy'(실행 불가)."""
    running = _http(port, "/api/version")
    # Do not recognize the original project by its page or executable filename.
    # An independent copy must never focus, terminate, or take over that app.
    if not running or running.get("app") != APP_ID or bool(running.get("demo")) != demo:
        say(f"{port}번 포트를 다른 프로그램이 사용 중이라 실행할 수 없습니다.\n"
            "설정 파일(config\\config.json)의 server.port를 바꾸세요.")
        return "busy"
    inst = _read_instance(demo)
    token = inst.get("token", "") if inst.get("port") == port else ""

    if running.get("version") == my_version:
        if token and _http(port, "/api/focus", token, {}) is not None:
            return "focused"
        say("무선망 통합 점검이 이미 실행 중입니다.\n작업 표시줄에서 열려 있는 창을 확인하세요.")
        return "focused"

    old_ver = (running or {}).get("version") or "이전 버전"
    if not token:
        say("기존 AutoNetwork 실행본의 인증 정보를 확인하지 못했습니다. 기존 프로그램을 직접 종료하세요.")
        return "busy"

    if not ask(f"무선망 통합 점검 {('v' + old_ver) if old_ver[0].isdigit() else old_ver}이(가) 이미 실행 중입니다.\n\n"
               f"그 프로그램을 종료하고 새 버전(v{my_version})으로 실행할까요?"):
        return "busy"

    if token:
        _http(port, "/api/quit", token, {})
        if wait_port_free(port, 10):
            return "ready"
    say("이전 버전을 종료하지 못했습니다.\n작업 표시줄이나 작업 관리자에서 'NetcheckCenter'를 종료한 뒤 다시 실행하세요.")
    return "busy"
