"""Windows EXE: 창을 닫아도 자동 점검(작업 스케줄러) 확인.

1) 프로그램을 켜면 작업 스케줄러에 'AutoNetwork NetcheckCenter AutoCheck'가 이 EXE로 등록되는지
2) 프로그램이 켜져 있을 때 작업 스케줄러 실행(--auto-check)은 점검하지 않고 바로 끝나는지
3) 설정에서 주기를 바꾸면 작업도 바뀌는지
4) 프로그램(창)이 꺼져 있을 때 --auto-check 가 창 없이 점검 → 기록 저장 → 엑셀 저장까지 하는지
5) 설정에서 '창을 닫아도 자동 점검'을 끄면 작업이 지워지는지

    python tests/windows_task_check.py dist\\NetcheckCenter\\NetcheckCenter.exe
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from windows_test_support import require_disposable_windows

require_disposable_windows()

SRC = Path(sys.argv[1]).resolve().parent
TASK = "AutoNetwork NetcheckCenter AutoCheck"
PORT = 8875
BASE = f"http://127.0.0.1:{PORT}"
ENV = dict(os.environ, NC_NO_DIALOG="1", NC_ASSUME_YES="1")

work = Path(tempfile.mkdtemp(prefix="nc_task_")).resolve() / "NetcheckCenter"
shutil.copytree(SRC, work, ignore=shutil.ignore_patterns("data", "data-demo", "보고서", "보고서-demo"))
EXE = work / "NetcheckCenter.exe"
(work / "config").mkdir(exist_ok=True)
(work / "config" / "config.json").write_text(json.dumps({
    "site_name": "작업 스케줄러 확인",
    "devices": [{"id": "bb1", "role": "BB", "name": "BB-TEST", "host": "127.0.0.1", "port": 1}],
    "schedule": {"enabled": True, "interval_minutes": 60, "align_to_clock": True, "background": True},
}, ensure_ascii=False), encoding="utf-8")
DB = work / "data" / "netcheck.sqlite3"
LOG = work / "data" / "netcheck.log"


def runs():
    if not DB.exists():
        return []
    con = sqlite3.connect(str(DB))
    try:
        return con.execute("SELECT id, trigger FROM runs ORDER BY id").fetchall()
    finally:
        con.close()


def task_xml():
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK, "/XML"], capture_output=True)
    if r.returncode != 0:
        return ""
    raw = r.stdout
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-8", "cp949", "mbcs"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass
    return raw.decode("utf-8", "replace")


def token():
    p = Path(os.environ["LOCALAPPDATA"]) / "AutoNetwork.NetcheckCenter" / "instance.json"
    return json.loads(p.read_text(encoding="utf-8"))["token"]


def call(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers={"X-NC-Token": token(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def start_gui():
    p = subprocess.Popen([str(EXE), "--no-browser"], cwd=work, env=ENV)
    for _ in range(90):
        try:
            urllib.request.urlopen(BASE + "/api/version", timeout=2)
            return p
        except Exception:
            time.sleep(1)
    raise AssertionError("프로그램이 시작되지 않았습니다")


def stop_gui(p):
    try:
        call("/api/quit", {})
    except Exception:
        pass
    try:
        p.wait(30)
    except subprocess.TimeoutExpired:
        p.kill()


def wait_xml(pred, what, secs=40):
    for _ in range(secs):
        x = task_xml()
        if pred(x):
            return x
        time.sleep(1)
    raise AssertionError(f"{what}: {task_xml()[:1500]}")


def auto_check():
    r = subprocess.run([str(EXE), "--auto-check"], cwd=work, env=ENV, timeout=600)
    return r.returncode


subprocess.run(["schtasks", "/Delete", "/TN", TASK, "/F"], capture_output=True)
try:
    gui = start_gui()
    try:
        x = wait_xml(lambda x: "--auto-check" in x, "작업이 등록되지 않음")
        # 임시 폴더가 짧은 이름(RUNNER~1)일 수 있어 폴더 이름과 실행 파일 이름으로 비교
        assert work.parent.name.lower() in x.lower() and "netcheckcenter.exe" in x.lower(), x
        assert "PT60M" in x or "PT1H<" in x, x   # Windows가 60분을 PT1H로 바꿔 저장
        print("1) 작업 스케줄러 등록 OK (이 EXE, 60분마다)")

        n = len(runs())
        assert auto_check() == 0
        assert len(runs()) == n, "프로그램이 켜져 있는데 작업 스케줄러 실행이 점검을 했습니다"
        assert "그쪽 자동 점검에 맡깁니다" in LOG.read_text(encoding="utf-8")
        print("2) 프로그램이 켜져 있으면 작업 스케줄러 실행은 바로 끝남 OK")

        cfg = call("/api/state")["config"]
        cfg["schedule"]["interval_minutes"] = 30
        call("/api/config", cfg)
        wait_xml(lambda x: "PT30M" in x, "주기 변경이 작업에 반영되지 않음")
        st = call("/api/state")
        print("3) 주기 변경 반영 OK (30분), 화면 상태:", st.get("background"))
        assert st["background"].get("registered"), st.get("background")
    finally:
        stop_gui(gui)
    time.sleep(2)

    n = len(runs())
    code = auto_check()
    rs = runs()
    print("   --auto-check 종료 코드:", code, "기록:", rs[-3:])
    assert len(rs) == n + 1 and rs[-1][1] == "auto", "창이 닫혀 있을 때 점검하지 않았습니다"
    reports = list((work / "보고서").glob("*.xlsx"))
    assert reports, "엑셀 보고서가 저장되지 않았습니다"
    print("4) 창이 닫혀 있으면 창 없이 점검 + 엑셀 저장 OK:", reports[-1].name)

    # 실제 작업 스케줄러로 실행(로그인 세션이 없는 빌드 서버에서는 실행되지 않을 수 있어 참고용)
    n = len(runs())
    r = subprocess.run(["schtasks", "/Run", "/TN", TASK], capture_output=True)
    ok = False
    for _ in range(60):
        if len(runs()) > n:
            ok = True
            break
        time.sleep(1)
    print("   (참고) schtasks /Run 으로 실행:", "점검됨" if ok else "INCONCLUSIVE: 이 빌드 서버에서는 실행 안 됨(로그인 세션 없음)")

    gui = start_gui()
    try:
        cfg = call("/api/state")["config"]
        cfg["schedule"]["background"] = False
        call("/api/config", cfg)
        wait_xml(lambda x: x == "", "끄기를 했는데 작업이 남아 있음")
        print("5) '창을 닫아도 자동 점검' 끄면 작업 삭제 OK")
    finally:
        stop_gui(gui)
    print("작업 등록/변경/해제 및 직접 --auto-check 실행 검증 통과; 실제 예약 실행은 위 별도 결과 참조")
finally:
    subprocess.run(["schtasks", "/Delete", "/TN", TASK, "/F"], capture_output=True)
