"""빌드된 Windows EXE를 실제로 띄워 계정 저장 → SSH 점검 → 재시작 후 계정 유지까지 확인.

    python tests/windows_exe_check.py dist\\NetcheckCenter\\NetcheckCenter.exe
GitHub Actions(Windows)에서 실행합니다.
"""
import json
import hashlib
import os
import re
import sqlite3
import subprocess
import sys
import time
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from windows_test_support import require_disposable_windows

require_disposable_windows()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.mock_ssh import MockDevice  # noqa: E402
from tests.test_e2e_ssh import aruba, comware  # noqa: E402
from nc.store import validate_database, _wal_safe_version  # noqa: E402

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


def rejected_settings(token, body, status):
    try:
        req("/api/settings", body, token)
    except urllib.error.HTTPError as exc:
        assert exc.code == status, f"예상한 저장 오류 {status}, 실제 {exc.code}"
        payload = json.loads(exc.read().decode("utf-8"))
        assert payload.get("error"), "실패 응답에 오류 설명 없음"
        assert body["credentials"][0]["password"] not in json.dumps(payload), "오류 응답에 비밀번호 포함"
    else:
        raise AssertionError("실패해야 할 설정·계정 저장이 성공함")


def verify_failed_combined_save(token, config_path):
    """Exercise validation and native keyring rollback inside the disposable runner."""
    before = json.loads(req("/api/state", token=token))
    disk = config_path.read_bytes()
    changed = json.loads(json.dumps(before["config"]))
    changed["site_name"] = "Uncommitted synthetic site"
    credential = {"profile": "shared", "username": "uncommitted", "password": "WRONG-SYNTHETIC",
                  "remember": True}
    invalid = json.loads(json.dumps(changed))
    invalid["thresholds"].update(cpu_warn=95, cpu_crit=50)
    rejected_settings(token, {"config": invalid, "credentials": [credential]}, 400)
    state = json.loads(req("/api/state", token=token))
    assert state["config"] == before["config"], "설정 검증 실패 후 설정 변경됨"
    assert state["credentials"] == before["credentials"], "설정 검증 실패 후 계정 변경됨"
    assert config_path.read_bytes() == disk, "설정 검증 실패 후 디스크 내용 변경됨"

    # Stage a valid config, but prevent its final atomic file replacement. This
    # exercises compensation after a native Windows credential write succeeds.
    backup = config_path.with_name("transaction-check-backup.json")
    config_path.replace(backup)
    config_path.mkdir()
    try:
        rejected_settings(token, {"config": changed, "credentials": [credential]}, 500)
        state = json.loads(req("/api/state", token=token))
        assert state["config"] == before["config"], "설정 쓰기 실패 후 메모리 설정 변경됨"
        assert state["credentials"] == before["credentials"], "설정 쓰기 실패 후 계정 변경됨"
    finally:
        config_path.rmdir()
        backup.replace(config_path)
    assert config_path.read_bytes() == disk
    print("설정 검증/파일 교체 실패 시 설정·계정 보존 확인")


def verify_database_backup_and_cleanup(token, config, run):
    live_path = (EXE.parent / "data" / "netcheck.sqlite3").resolve()
    live = sqlite3.connect(live_path.as_uri() + "?mode=ro", uri=True)
    try:
        actual_mode = live.execute("PRAGMA journal_mode").fetchone()[0].lower()
        expected_mode = "wal" if _wal_safe_version(sqlite3.sqlite_version_info) else "delete"
        assert actual_mode == expected_mode, f"EXE DB 저널 모드: {actual_mode}, 예상: {expected_mode}"
        print("Windows EXE DB journal mode:", actual_mode, "SQLite:", sqlite3.sqlite_version)
    finally:
        live.close()
    result = json.loads(req("/api/backup", {}, token))
    backup = Path(result["path"])
    assert backup.parent.resolve() == (EXE.parent / "data" / "backups").resolve()
    validate_database(backup)
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="netcheck-exe-restore-") as directory:
        restored = Path(directory) / "restored.sqlite3"
        env = {**os.environ, "NC_NO_DIALOG": "1"}
        for arguments in (["--verify-db", str(backup)],
                          ["--restore-db", str(backup), "--restore-to", str(restored)]):
            completed = subprocess.run([str(EXE), *arguments], cwd=EXE.parent, env=env, timeout=45)
            assert completed.returncode == 0, "EXE DB 검증/새 파일 복원 실패"
        validate_database(restored)
        db = sqlite3.connect(restored)
        try:
            assert db.execute("SELECT COUNT(*) FROM runs WHERE id=?", (run["id"],)).fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM raw_outputs WHERE run_id=?", (run["id"],)).fetchone()[0] > 0
            assert db.execute("SELECT COUNT(*) FROM baselines WHERE device_id='bb3'").fetchone()[0] == 1
            print("Windows 복원 DB SQLite:", sqlite3.sqlite_version)
        finally:
            db.close()
        before = hashlib.sha256(restored.read_bytes()).hexdigest()
        rejected = subprocess.run([str(EXE), "--restore-db", str(backup), "--restore-to", str(restored)],
                                  cwd=EXE.parent, env=env, timeout=45)
        assert rejected.returncode == 1, "기존 DB 덮어쓰기를 거부하지 않음"
        assert hashlib.sha256(restored.read_bytes()).hexdigest() == before
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == digest
    removed = json.loads(json.dumps(config))
    removed["devices"] = [d for d in removed["devices"] if d["id"] != "bb3"]
    req("/api/settings", {"config": removed, "credentials": []}, token)
    state = json.loads(req("/api/state", token=token))
    assert "bb3" not in state["baseline_times"], "삭제한 장비 기준값이 남음"
    history = json.loads(req(f"/api/run?id={run['id']}", token=token))
    assert "bb3" in history["devices"], "장비 삭제가 과거 회차를 지움"
    assert json.loads(req(f"/api/raw?run={run['id']}&device=bb3&cmd=cpu", token=token))["output"]
    req("/api/settings", {"config": config, "credentials": []}, token)
    print("Windows EXE 백업·새 파일 복원·덮어쓰기 거부·장비 삭제 기준값 정리/과거 이력 보존 확인")


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
        cfg = json.loads(req("/api/state", token=tok))["config"]
        cfg["site_name"] = "Synthetic combined save"
        req("/api/settings", {"config": cfg, "credentials": [
            {"profile": "shared", "username": "op", "password": "pw", "remember": True}]}, tok)
        state = json.loads(req("/api/state", token=tok))
        print("계정 상태:", state["credentials"], "keyring:", state["keyring"])
        assert state["config"]["site_name"] == cfg["site_name"]
        assert state["credentials"]["shared"]["remembered"] is True
        # Older clients can still update the shared credential separately;
        # an empty password for the same user must retain the current secret.
        req("/api/credentials", {"profile": "shared", "username": "op", "password": "",
                                 "remember": True}, tok)
        verify_failed_combined_save(tok, cfg_dir / "config.json")
        run = check(tok)
        for d, v in run["devices"].items():
            print(d, v["connected"], v["status"], v.get("error"))
            assert v["connected"], f"{d} SSH 접속 실패: {v.get('error')}"
        assert run["devices"]["bb3"]["metrics"]["cpu"] is not None, "CPU 값 없음"
        verify_database_backup_and_cleanup(tok, cfg, run)
    finally:
        p.kill(); p.wait()

    # 재시작: Windows 자격 증명 관리자에서 계정을 다시 읽는지
    p, tok = start()
    try:
        state = json.loads(req("/api/state", token=tok))
        print("재시작 후 계정 상태:", state["credentials"])
        assert set(state["credentials"]) == {"shared"}, "재시작 후 계정이 유지되지 않았습니다"
        assert state["credentials"]["shared"]["username"] == "op", "복구된 계정이 재시작 후 유지되지 않음"
        assert state["config"]["site_name"] == "Synthetic combined save", "실패한 설정이 재시작 후 반영됨"
        run = check(tok)
        assert all(v["connected"] for v in run["devices"].values()), "재시작 후 SSH 접속 실패"
        print("설정 저장 실패 후 재시작: 기존 Windows 저장 계정으로 Mock SSH 점검 성공")
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
