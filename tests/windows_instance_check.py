"""Windows EXE 단일 실행·이전 버전 교체 확인 (GitHub Actions Windows에서 실행).

    python tests/windows_instance_check.py dist\\NetcheckCenter\\NetcheckCenter.exe
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from windows_test_support import require_disposable_windows

require_disposable_windows()

EXE = Path(sys.argv[1]).resolve()
PORT = 8877
ENV = dict(os.environ, NC_ASSUME_YES="1", NC_NO_DIALOG="1")


def version():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/version", timeout=3) as r:
            return json.loads(r.read())["version"]
    except Exception:
        return None


PROCS = []


def _cleanup():
    for p in PROCS:
        if p.poll() is None:
            p.kill()


import atexit  # noqa: E402

atexit.register(_cleanup)


def start(ver=None):
    env = dict(ENV)
    if ver:
        env["NC_VERSION_OVERRIDE"] = ver
    p = subprocess.Popen([str(EXE), "--demo", "--browser", "--no-browser", "--port", str(PORT)], cwd=EXE.parent, env=env)
    PROCS.append(p)
    return p


def wait_version(expect, seconds=60):
    end = time.time() + seconds
    while time.time() < end:
        v = version()
        if v == expect:
            return True
        time.sleep(0.5)
    return False


def kill(*ps):
    for p in ps:
        if p and p.poll() is None:
            p.kill()
            p.wait()


inst = Path(os.environ["LOCALAPPDATA"]) / "AutoNetwork.NetcheckCenter" / "demo-instance.json"

# 1) 같은 버전을 두 번 실행 → 두 번째는 바로 끝나고 첫 번째가 계속 응답
a = start()
cur = None
for _ in range(120):
    cur = version()
    if cur:
        break
    time.sleep(0.5)
assert cur, "첫 실행이 응답하지 않습니다"
b = start()
assert b.wait(60) == 0, "같은 버전 두 번째 실행이 정상 종료되지 않았습니다"
assert a.poll() is None and version() == cur, "첫 실행이 영향을 받았습니다"
print(f"1) 같은 버전 중복 실행 → 기존 창 사용 OK (v{cur})")
kill(a)
time.sleep(2)

# 2) 이전 버전 실행 중 → 새 버전이 종료 요청으로 교체
old = start("1.0.0")
assert wait_version("1.0.0"), "이전 버전 역할 실행 실패"
new = start()
assert wait_version(cur), "새 버전으로 교체되지 않았습니다(종료 요청)"
old.wait(20)
print("2) 이전 버전 → 새 버전 교체(종료 요청) OK")
kill(new)
time.sleep(2)

# 3) 인증 토큰 파일이 없으면 기존 프로세스를 종료하지 않고 충돌로 반환
old = start("1.0.0")
assert wait_version("1.0.0")
inst.unlink(missing_ok=True)
new = start()
assert new.wait(60) == 2, "인증 정보가 없는 프로세스 교체를 허용하면 안 됩니다"
assert old.poll() is None and version() == "1.0.0", "인증 정보가 없는 기존 프로세스를 종료했습니다"
print("3) 인증 정보 없는 기존 프로세스 유지 OK")
kill(old)
time.sleep(2)

# 4) Windows에서 다른 프로그램이 SO_REUSEADDR 로 포트를 잡고 있으면 같이 열지 않고 실패해야 함
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", PORT))
srv.listen(5)


def fake():
    while True:
        try:
            c, _ = srv.accept()
        except OSError:
            return
        c.recv(4096)
        c.sendall(b"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nhello")
        c.close()


threading.Thread(target=fake, daemon=True).start()
p = start()
code = p.wait(60)
srv.close()
assert code == 2, f"다른 프로그램이 쓰는 포트에서 실행되면 안 됩니다(exit={code})"
print("4) 포트 독점 확인 OK (다른 프로그램과 같은 포트 동시 사용 안 함)")
print("Windows 단일 실행·버전 교체 확인 완료")
