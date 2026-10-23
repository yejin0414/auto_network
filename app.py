"""무선망 통합 점검 센터 — 실행 진입점.

    python app.py              프로그램 창으로 실행 (실장비, config/config.json)
    python app.py --demo       장비 없이 데모 데이터로 실행
    python app.py --browser    프로그램 창(Edge 앱 모드) 대신 기본 웹 브라우저로 열기
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import mimetypes
import os
import sqlite3
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from nc.collector import NetmikoDriver
from nc.config import CREDENTIAL_PROFILES, ConfigStore
from nc.credentials import Credential, CredentialStore
from nc.engine import Engine
from nc.server import App, serve
from nc.store import Store

VERSION = "1.5.2"
# 자동 검사(CI)에서 '이전 버전' 역할을 흉내 낼 때만 사용
if __import__("os").environ.get("NC_VERSION_OVERRIDE"):
    VERSION = __import__("os").environ["NC_VERSION_OVERRIDE"]


def base_dirs() -> tuple[Path, Path]:
    """(리소스 폴더, 실행 폴더). PyInstaller EXE에서도 동작."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)), Path(sys.executable).parent
    here = Path(__file__).resolve().parent
    return here, here


def main() -> int:
    ap = argparse.ArgumentParser(description="BB · MM · WLC 통합 자동 점검")
    ap.add_argument("--demo", action="store_true", help="장비 없이 데모 데이터로 실행")
    ap.add_argument("--port", type=int, default=0, help="내부 화면 포트(기본 8875, 데모 8876)")
    ap.add_argument("--browser", action="store_true", help="프로그램 창 대신 기본 웹 브라우저로 열기")
    ap.add_argument("--web", action="store_true",
                    help="웹 버전: 평소 쓰는 웹 브라우저로 열고, 브라우저를 닫아도 계속 실행(화면의 ‘프로그램 끄기’로 종료)")
    ap.add_argument("--minimized", action="store_true", help="창을 최소화한 상태로 시작(자동 시작용)")
    ap.add_argument("--no-browser", action="store_true", help="창을 열지 않고 화면 서버만 실행(테스트·원격용)")
    ap.add_argument("--check-once", action="store_true", help="한 번 점검하고 결과만 출력한 뒤 종료")
    ap.add_argument("--auto-check", action="store_true",
                    help="(Windows 작업 스케줄러용) 창 없이 1회 점검 → 엑셀 저장 → 알림. 프로그램 창이 켜져 있으면 그쪽이 점검하므로 바로 종료")
    maintenance = ap.add_mutually_exclusive_group()
    maintenance.add_argument("--restore-db", type=Path, help="백업 DB를 검증해 새 파일로 복원(장비 접속 없음)")
    maintenance.add_argument("--verify-db", type=Path, help="DB 무결성과 Netcheck 스키마만 검증(장비 접속 없음)")
    maintenance.add_argument("--export-backup", type=Path, help="DB를 SHA-256 검증 정보가 포함된 외부 보관 패키지로 내보내기")
    maintenance.add_argument("--verify-backup", type=Path, help="외부 보관 패키지의 내용·SHA-256·DB 무결성 검증")
    maintenance.add_argument("--restore-backup", type=Path, help="외부 보관 패키지를 검증해 새 DB로 복원")
    ap.add_argument("--restore-to", type=Path, help="복원할 새 DB 경로(기존 파일 덮어쓰기 금지)")
    ap.add_argument("--export-to", type=Path, help="내보낼 새 .ncbak 파일 경로(기존 파일 덮어쓰기 금지)")
    ap.add_argument("--db-timeout", type=float, default=300.0, help="DB 검증·복원·내보내기 전체 제한 시간(초, 기본 300)")
    args = ap.parse_args()
    if sys.stdout is None:  # pythonw / 창 없는 실행
        sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")

    restoring = args.restore_db or args.restore_backup
    if not math.isfinite(args.db_timeout) or args.db_timeout <= 0:
        ap.error("--db-timeout은 유한한 양수여야 합니다.")
    if args.restore_to and not restoring:
        ap.error("--restore-to는 --restore-db 또는 --restore-backup과 함께 사용하세요.")
    if restoring and not args.restore_to:
        ap.error("복원에는 새 경로 --restore-to가 필요합니다.")
    if bool(args.export_to) != bool(args.export_backup):
        ap.error("--export-backup과 새 경로 --export-to를 함께 사용하세요.")
    if restoring or args.verify_db or args.export_backup or args.verify_backup:
        # Maintenance exits before config, credentials, driver or scheduler setup.
        from nc.db_maintenance import restore_database
        from nc.backup_transfer import export_backup, restore_backup, verify_backup_package
        from nc.store import validate_database
        try:
            if args.restore_db:
                path = restore_database(args.restore_db, args.restore_to, timeout=args.db_timeout)
                message = f"DB 복원 완료: {path} (기존 DB는 변경하지 않았습니다)"
            elif args.restore_backup:
                path = restore_backup(args.restore_backup, args.restore_to, timeout=args.db_timeout)
                message = f"외부 백업 복원 완료: {path} (기존 DB는 변경하지 않았습니다)"
            elif args.export_backup:
                path = export_backup(args.export_backup, args.export_to, timeout=args.db_timeout)
                message = f"외부 보관 패키지 생성 완료: {path}"
            elif args.verify_backup:
                metadata = verify_backup_package(args.verify_backup, timeout=args.db_timeout)
                message = f"외부 백업 SHA-256 및 DB 무결성 검증 완료: {metadata['sha256']}"
            else:
                validate_database(args.verify_db, timeout=args.db_timeout)
                message = "DB 무결성 및 Netcheck 스키마 검증 완료"
        except (OSError, ValueError, sqlite3.Error):
            message = "DB 백업/검증/복원 실패: 무결성, 새 대상 경로, 디스크 공간·권한·잠금 및 제한 시간을 확인하세요."
            print(message, file=sys.stderr)
            message_box(message)
            return 1
        print(message)
        if getattr(sys, "frozen", False):
            message_box(message)
        return 0

    res_dir, run_dir = base_dirs()
    data_dir = run_dir / ("data-demo" if args.demo else "data")
    data_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(data_dir / "netcheck.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()],
                        format="%(asctime)s %(levelname)s %(message)s")
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

    creds = CredentialStore(persistent=not args.demo)
    if args.demo:
        from nc.demo import DEMO_CONFIG, DemoWorld, seed_history

        cfg_path = data_dir / "config.json"
        if not cfg_path.exists():
            cfg_path.write_text(json.dumps(DEMO_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        cfg = ConfigStore(cfg_path)
        for p in CREDENTIAL_PROFILES:
            creds.set(p, Credential("demo", "demo"), remember=False)
        driver = DemoWorld(speed=1.0)
        driver.devices_provider = lambda: cfg.get()["devices"]
    else:
        cfg_dir = run_dir / "config"
        cfg_dir.mkdir(exist_ok=True)
        example = res_dir / "config" / "config.example.json"
        if not (cfg_dir / "config.example.json").exists() and example.exists():
            (cfg_dir / "config.example.json").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        cfg = ConfigStore(cfg_dir / "config.json")
        creds.load_saved(list(CREDENTIAL_PROFILES))
        driver = NetmikoDriver()

    store = Store(data_dir / "netcheck.sqlite3")
    engine = Engine(cfg, store, creds, driver, demo=args.demo)
    engine.reports_dir = run_dir / ("보고서-demo" if args.demo else "보고서")

    if args.demo and not store.list_runs(1):
        logging.info("데모 이력(지난 24시간)을 만드는 중…")
        seed_history(engine, driver)

    if args.auto_check:
        from nc.instance import running_instance

        sched = cfg.get()["schedule"]
        if not sched["enabled"] or not sched["background"]:
            logging.info("[작업 스케줄러] 자동 점검이 꺼져 있어 점검하지 않습니다")
            return 0
        if not [d for d in cfg.get()["devices"] if d.get("enabled", True)]:
            logging.info("[작업 스케줄러] 점검할 장비가 없어 점검하지 않습니다")
            return 0
        other = running_instance(demo=args.demo)
        if other:
            logging.info("[작업 스케줄러] 프로그램 창(v%s)이 켜져 있어 그쪽 자동 점검에 맡깁니다", other.get("version", "?"))
            return 0
        logging.info("[작업 스케줄러] 창이 닫혀 있어 백그라운드로 점검합니다")
        rid = engine.run_blocking("auto")
        logging.info("[작업 스케줄러] 점검 %s (%s)", "완료" if rid else "실패", engine.last_report or engine.last_error)
        logging.shutdown()
        return 0 if rid else 1

    if args.check_once:
        rid = engine.run_blocking("manual")
        run = store.get_run(rid) if rid else None
        print(json.dumps(run["summary"], ensure_ascii=False, indent=2) if run else "점검 실패")
        return 0 if rid else 1

    conf = cfg.get()
    host = "127.0.0.1"
    port = args.port or (int(conf["server"].get("port", 8875)) + (1 if args.demo else 0))
    from nc.appwindow import WindowWatch, bring_to_front, find_browser, kill_tree, launch, minimize_when_shown

    app = App(engine, res_dir / "web", desktop=False, version=VERSION)
    app.web_mode = bool(args.web)
    from nc.instance import clear_instance, take_over, write_instance

    try:
        httpd = serve(app, host, port)
    except OSError:
        result = take_over(port, VERSION, ask=ask_yes_no, say=lambda m: (print("[알림] " + m), message_box(m)), demo=args.demo)
        if result != "ready":
            return 0 if result == "focused" else 2
        httpd = serve(app, host, port)
    write_instance(port, app.token, VERSION, demo=args.demo)
    engine.start_scheduler()

    # 창을 닫아도 자동 점검: Windows 작업 스케줄러 등록/갱신(설정 저장 때마다 다시 맞춤)
    background_sync = None
    if not args.demo:
        from nc import wintask
        from nc.schedule_sync import ScheduleSynchronizer

        background_sync = ScheduleSynchronizer(lambda: cfg.get()["schedule"], wintask.sync, app.publish_background)
        app.on_config_saved = background_sync.request
        background_sync.request()
    url = f"http://{host}:{port}/"
    logging.info("무선망 통합 점검 센터 v%s%s 시작 (%s)", VERSION, " 데모" if args.demo else "", url)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.5}, name="netcheck-http", daemon=True).start()

    exit_evt = threading.Event()
    app.on_quit = exit_evt.set
    proc = None
    watch = None
    if args.web:
        # 웹 버전: 브라우저 탭을 닫아도 계속 실행하며 자동 점검. 다시 실행하면 브라우저만 새로 엶.
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        logging.info("웹 버전으로 실행합니다 (%s). 끄려면 화면의 ‘프로그램 끄기’", url)
    elif not args.no_browser:
        browser = None if args.browser else find_browser()
        if browser:
            # 프로그램 창(Edge 앱 모드): 설치 필요 없음, 창을 닫으면 프로그램 전체 종료
            proc = launch(browser, url, data_dir / "window")
            if args.minimized:
                minimize_when_shown()
            logging.info("프로그램 창을 열었습니다 (%s)", Path(browser).name)
        else:
            if not args.browser:
                message_box("이 PC에서 Microsoft Edge를 찾지 못해 기본 웹 브라우저로 엽니다.")
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        watch = WindowWatch(proc, exit_evt.set)
        app.watch = watch
        watch.start()
    app.on_focus = (lambda: webbrowser.open(url)) if args.web else (lambda: bring_to_front() or (proc is None and webbrowser.open(url)))

    print(f"무선망 통합 점검 센터 v{VERSION}{' (데모)' if args.demo else ''}")
    print(f"화면 주소: {url}")
    print("창을 닫거나 이 창에서 Ctrl+C 를 누르면 종료합니다.")
    try:
        while not exit_evt.wait(1):
            pass
    except KeyboardInterrupt:
        pass
    # 정리 후 프로세스를 확실히 끝냄(점검 중인 작업이 있어도 남지 않도록)
    logging.info("종료합니다")
    exit_code = 0
    try:
        if watch:
            watch.stop()
        engine.stop()
        app.begin_shutdown()
        httpd.shutdown()
        if background_sync is not None:
            if not background_sync.close():
                exit_code = 1
        # Keep the port reserved until task updates finish, so a replacement
        # process cannot race the old process while registering its own path.
        httpd.server_close()
        kill_tree(proc)
        clear_instance(demo=args.demo)
        logging.shutdown()
    finally:
        os._exit(exit_code)


def ask_yes_no(text: str) -> bool:
    """Windows 예/아니요 질문. 콘솔에서 실행 중이면(Windows 외) 그대로 진행."""
    import os

    if os.environ.get("NC_ASSUME_YES") or sys.platform != "win32":
        return True
    try:
        import ctypes

        return ctypes.windll.user32.MessageBoxW(None, text, "무선망 통합 점검", 0x04 | 0x20) == 6
    except Exception:
        return True


def message_box(text: str) -> None:
    """콘솔 없는 EXE에서도 보이도록 Windows 메시지 상자를 띄웁니다."""
    import os

    if sys.platform != "win32" or os.environ.get("NC_NO_DIALOG"):
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "무선망 통합 점검", 0x40)
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())
