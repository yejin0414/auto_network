"""빌드된 Windows EXE를 실제로 띄워 계정 저장 → SSH 점검 → 재시작 후 계정 유지까지 확인.

    python tests/windows_exe_check.py dist\\NetcheckCenter\\NetcheckCenter.exe
GitHub Actions(Windows)에서 실행합니다.
"""
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from windows_test_support import require_disposable_windows

require_disposable_windows()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.mock_ssh import MockDevice  # noqa: E402
from tests.test_e2e_ssh import aruba, comware  # noqa: E402

EXE = Path(sys.argv[1]).resolve()
PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"


def req(path, body=None, token=""):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers={"X-NC-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return resp.read().decode("utf-8")


def start():
    p = subprocess.Popen([str(EXE), "--browser", "--no-browser", "--port", str(PORT)], cwd=EXE.parent)
    for _ in range(60):
        try:
            page = req("/")
            return p, re.search(r'NC_TOKEN = "([^"]+)"', page).group(1)
        except Exception:
            time.sleep(1)
    p.kill()
    raise SystemExit("EXE 화면 서버가 뜨지 않았습니다")


def check(token):
    req("/api/check", {}, token)
    for _ in range(120):
        time.sleep(1)
        if not json.loads(req("/api/state", token=token))["engine"]["running"]:
            break
    return json.loads(req("/api/run", token=token))


def main():
    bb = MockDevice("<BB-3>", comware({}), legacy=True)  # 오래된 Comware처럼 SHA-1 SSH만 제공
    wlc = MockDevice("(WLC-01) #", aruba("wlc"))
    cfg_dir = EXE.parent / "config"
    cfg_dir.mkdir(exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps({
        "devices": [
            {"id": "bb3", "name": "BB-3", "role": "BB", "host": "127.0.0.1", "port": bb.port},
            {"id": "wlc1", "name": "WLC-01", "role": "WLC", "host": "127.0.0.1", "port": wlc.port, "cluster_primary": True},
        ],
        "schedule": {"enabled": False},
        "ssh": {"bb_connect_timeout": 30, "bb_command_timeout": 30, "ctrl_connect_timeout": 30, "ctrl_command_timeout": 30, "retries": 0},
    }), encoding="utf-8")

    p, tok = start()
    try:
        req("/api/credentials", {"profile": "shared", "username": "op", "password": "pw", "remember": True}, tok)
        state = json.loads(req("/api/state", token=tok))
        print("계정 상태:", state["credentials"], "keyring:", state["keyring"])
        run = check(tok)
        for d, v in run["devices"].items():
            print(d, v["connected"], v["status"], v.get("error"))
            assert v["connected"], f"{d} SSH 접속 실패: {v.get('error')}"
        assert run["devices"]["bb3"]["metrics"]["cpu"] is not None, "CPU 값 없음"
    finally:
        p.kill(); p.wait()

    # 재시작: Windows 자격 증명 관리자에서 계정을 다시 읽는지
    p, tok = start()
    try:
        state = json.loads(req("/api/state", token=tok))
        print("재시작 후 계정 상태:", state["credentials"])
        assert set(state["credentials"]) == {"shared"}, "재시작 후 계정이 유지되지 않았습니다"
        run = check(tok)
        assert all(v["connected"] for v in run["devices"].values()), "재시작 후 SSH 접속 실패"
        req("/api/credentials", {"profile": "shared", "clear": True}, tok)
    finally:
        p.kill(); p.wait()
        (cfg_dir / "config.json").unlink(missing_ok=True)
        for d in ("data",):
            import shutil
            shutil.rmtree(EXE.parent / d, ignore_errors=True)
    print("Windows EXE 계정·SSH 점검 확인 완료")


if __name__ == "__main__":
    main()
