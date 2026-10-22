"""Windows EXE: 프로그램 창(Edge 앱 모드)이 열리고, 창을 닫으면 프로그램이 완전히 종료되는지.
점검 후 엑셀 자동 저장, 엑셀 내려받기, 완료 알림(가능한 경우)도 확인합니다.

    python tests/windows_window_check.py dist\\NetcheckCenter\\NetcheckCenter.exe
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from windows_test_support import require_disposable_windows

require_disposable_windows()

EXE = Path(sys.argv[1]).resolve()
PORT = 8876  # 독립 프로젝트 데모 기본 포트(8875 + 1)
BASE = f"http://127.0.0.1:{PORT}"
ENV = dict(os.environ, NC_NO_DIALOG="1", NC_ASSUME_YES="1")


def get(path, token=""):
    req = urllib.request.Request(BASE + path, headers={"X-NC-Token": token})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def post(path, token, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(),
                                 headers={"X-NC-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def ps(cmd):
    return subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60).stdout


def edge_pids(profile):
    out = ps("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
             "Where-Object { $_.CommandLine -like '*" + str(profile).replace("'", "''") + "*' } | "
             "ForEach-Object { $_.ProcessId }")
    return [int(x) for x in out.split() if x.strip().isdigit()]


profile = EXE.parent / "data-demo" / "window"
app = subprocess.Popen([str(EXE), "--demo"], cwd=EXE.parent, env=ENV)
try:
    win = False
    for _ in range(120):
        try:
            v = json.loads(get("/api/version"))
            if v.get("window"):
                win = True
                break
        except Exception:
            pass
        time.sleep(1)
    print("Edge 앱 창 프로세스:", edge_pids(profile))
    assert win, "프로그램 창이 열리지 않았거나 화면 신호가 없습니다"
    print("1) 프로그램 창(Edge 앱 모드) 열림 OK")

    token = re.search(rb'NC_TOKEN = "([^"]+)"', get("/")).group(1).decode()
    post("/api/check", token)
    for _ in range(180):
        time.sleep(1)
        if not json.loads(get("/api/state", token))["engine"]["running"]:
            break
    st = json.loads(get("/api/state", token))
    files = list((EXE.parent / "보고서-demo").glob("무선망점검_*.xlsx"))
    print("엑셀 자동 저장:", [f.name for f in files], "| last_report:", st.get("last_report"))
    assert files, "점검 후 엑셀 보고서가 저장되지 않았습니다"
    data = get("/report.xlsx?t=" + token)
    assert data[:2] == b"PK" and len(data) > 5000, "엑셀 내려받기 실패"
    print("2) 엑셀 자동 저장·내려받기 OK")

    n = post("/api/test_notify", token)
    print("3) 완료 알림(토스트):", "표시 요청 성공" if n.get("ok") else f"INCONCLUSIVE: {n.get('error')}")
    print("NOT_RUN: 사용자 화면에 토스트가 실제 표시되었는지 수동 확인")

    pids = edge_pids(profile)
    assert pids, "앱 창 Edge 프로세스를 찾지 못했습니다"
    ps("Stop-Process -Id " + ",".join(map(str, pids)) + " -Force")  # 사용자가 창을 닫은 것과 같은 상황
    try:
        code = app.wait(60)
    except subprocess.TimeoutExpired:
        raise AssertionError("창을 닫았는데 프로그램이 종료되지 않았습니다")
    time.sleep(2)
    left = ps("Get-Process NetcheckCenter -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }").split()
    assert not left, f"NetcheckCenter 프로세스가 남아 있습니다: {left}"
    assert not edge_pids(profile), "앱 창 Edge 프로세스가 남아 있습니다"
    print(f"4) 창을 닫자 프로그램 완전 종료 OK (종료 코드 {code}, 남은 프로세스 없음)")
finally:
    if app.poll() is None:
        app.kill()
    for p in edge_pids(profile):
        ps(f"Stop-Process -Id {p} -Force")
print("Windows 프로그램 창·종료·엑셀 확인 완료")
