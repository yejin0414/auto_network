"""로컬 전용 웹 서버(127.0.0.1). 화면과 API를 제공합니다."""

from __future__ import annotations

import json
import logging
import mimetypes
import secrets
import socket
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import CREDENTIAL_PROFILES, ConfigError, validate
from .credentials import CredentialError
from .engine import Engine
from .instance import APP_ID
from .report import render

log = logging.getLogger("netcheck")
MAX_BODY = 256 * 1024


class App:
    def __init__(self, engine: Engine, web_dir: Path, desktop: bool = False, version: str = "") -> None:
        self.engine = engine
        self.desktop = desktop
        self.version = version
        self.on_quit = None   # 새 버전이 실행될 때 이 프로그램을 끄는 함수
        self.watch = None     # 프로그램 창 감시(창이 닫히면 종료)
        self.on_focus = None  # 같은 버전을 또 실행했을 때 창을 앞으로
        self.on_config_saved = None  # 설정 저장 후(작업 스케줄러 갱신)
        self.background: dict = {}   # 창을 닫아도 자동 점검(작업 스케줄러) 등록 상태
        self._config_lock = threading.RLock()
        self._closing = False
        self.web_mode = False        # 웹 버전(브라우저를 닫아도 계속 실행)
        self.web_dir = web_dir
        self.token = secrets.token_urlsafe(24)

    # ------------------------------------------------------------- GET
    def state(self) -> dict[str, Any]:
        with self._config_lock:
            cfg = self.engine.cfg.get()
            background = dict(self.background)
            credentials = self.engine.creds.status()
            storage_uncertain = self.engine.creds.storage_uncertain
        return {
            "config": cfg,
            "version": self.version,
            "report_folder": str(self.engine.report_folder(cfg).resolve()),
            "last_report": self.engine.last_report,
            "windows": sys.platform == "win32",
            "background": background,
            "web_mode": self.web_mode,
            "engine": self.engine.status(),
            "credentials": credentials,
            "credential_storage_uncertain": storage_uncertain,
            "credential_profiles": CREDENTIAL_PROFILES,
            "keyring": self.engine.creds.keyring_available,
            "baseline_times": self.engine.store.baseline_times(),
            "vrrp_unacked": self.engine.store.vrrp_unacked(),
            "latest_run_id": (self.engine.store.list_runs(1) or [{}])[0].get("id"),
        }

    def publish_background(self, result: dict, schedule: dict) -> bool:
        """Publish only a result matching the currently saved schedule."""
        with self._config_lock:
            if self.engine.cfg.get()["schedule"] != schedule:
                return False
            self.background = dict(result)
            return True

    def begin_shutdown(self) -> None:
        # Wait for any accepted save and its wakeup before draining the worker.
        with self._config_lock:
            self._closing = True

    def handle_get(self, path: str, q: dict[str, str]) -> tuple[int, Any]:
        st = self.engine.store
        if path == "/api/state":
            return 200, self.state()
        if path == "/api/run":
            rid = int(q["id"]) if q.get("id") else None
            run = st.get_run(rid)
            return (200, run) if run else (404, {"error": "점검 기록이 없습니다."})
        if path == "/api/runs":
            return 200, st.list_runs(int(q.get("limit", 72)))
        if path == "/api/raw":
            raw = st.get_raw(int(q["run"]), q["device"], q["cmd"])
            return (200, raw) if raw else (404, {"error": "원본 출력이 없습니다."})
        if path == "/api/trends":
            hours = float(q.get("hours", 24))
            return 200, st.trends_all(time.time() - hours * 3600)
        if path == "/api/events":
            return 200, st.list_events(int(q.get("limit", 60)))
        if path == "/api/vrrp":
            return 200, {"items": st.list_vrrp(int(q.get("limit", 300))), "unacked": st.vrrp_unacked()}
        return 404, {"error": "없는 경로입니다."}

    # ------------------------------------------------------------- POST
    def handle_post(self, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        eng = self.engine
        if path == "/api/heartbeat":
            if self.watch:
                self.watch.heartbeat()
            return 200, {"ok": True}
        if path == "/api/quit":
            if self.on_quit:
                import threading
                threading.Timer(0.3, self.on_quit).start()
            return 200, {"ok": True}
        if path == "/api/focus":
            if self.on_focus:
                self.on_focus()
            return 200, {"ok": True}
        if path in ("/api/excel_open", "/api/excel_save"):
            from .excel import save_report
            cfg = eng.cfg.get()
            run = eng.store.get_run(int(body["id"]) if body.get("id") else None)
            if not run:
                return 404, {"error": "점검 기록이 없습니다."}
            try:
                p = save_report(run, cfg.get("site_name", ""), cfg["thresholds"],
                                lambda dev, cmd, rid=run["id"]: eng.store.get_raw(rid, dev, cmd),
                                eng.report_folder(cfg), cfg["retention_days"])
            except PermissionError:
                return 409, {"error": "같은 이름의 엑셀 파일이 열려 있어 저장하지 못했습니다. 엑셀에서 닫고 다시 누르세요."}
            except OSError as exc:
                return 500, {"error": f"보고서 폴더에 저장하지 못했습니다: {exc}"}
            if path == "/api/excel_open":
                _open_path(p)
            return 200, {"ok": True, "path": str(p)}
        if path == "/api/open_reports":
            folder = eng.report_folder()
            folder.mkdir(parents=True, exist_ok=True)
            _open_path(folder)
            return 200, {"ok": True, "path": str(folder.resolve())}
        if path == "/api/test_notify":
            from .notify import show_toast
            ok = show_toast("무선망 통합 점검 알림 테스트", ["점검이 끝나면 이렇게 화면 오른쪽 아래에 알려 드립니다."], wait=True)
            return 200, {"ok": ok, "error": "" if ok else "Windows 알림을 띄우지 못했습니다(알림 설정이나 집중 모드를 확인하세요)."}
        if path == "/api/check":
            started = eng.start_check("manual")
            return (202, {"started": True}) if started else (409, {"error": "이미 점검이 진행 중입니다."})
        if path in ("/api/config", "/api/credentials", "/api/settings"):
            with self._config_lock:
                if self._closing:
                    return 503, {"error": "프로그램을 종료 중이므로 설정을 저장할 수 없습니다."}
                has_config = path != "/api/credentials"
                try:
                    cfg = validate(body if path == "/api/config" else body.get("config")) if has_config else None
                    changes = body.get("credentials", []) if path == "/api/settings" else [body]
                    if path == "/api/config":
                        cfg = eng.cfg.save(cfg)
                    else:
                        cfg = eng.creds.apply(changes, (lambda: eng.cfg.save(cfg)) if has_config else None)
                except CredentialError as exc:
                    return 503, {"error": str(exc), "rollback_failed": exc.rollback_failed}
                except ConfigError as exc:
                    return 400, {"error": str(exc)}
                except (TypeError, ValueError):
                    return 400, {"error": "설정 또는 계정 입력 형식이 올바르지 않습니다. 입력 값을 확인하세요."}
                except OSError:
                    return 500, {"error": "설정 파일을 저장하지 못했습니다. 기존 설정과 계정을 유지했습니다."}
                if has_config:
                    try:
                        eng.reschedule()
                        if self.on_config_saved:
                            self.on_config_saved(cfg)
                    except Exception:  # pragma: no cover
                        log.exception("설정 저장 후 처리 실패")
                payload = {"ok": True, "config": cfg} if has_config else {"ok": True, "note": None}
                if path != "/api/config":
                    payload["credentials"] = eng.creds.status()
                return 200, payload
        if path == "/api/vrrp/ack":
            # 확인 · 초기화: 미확인 VRRP 변경을 확인 처리하고 그 백본의 VRRP 기준값만 지움 → 다음 점검부터 '역할 변화' 표시 없음
            devs = eng.store.ack_vrrp(body.get("device") or None)
            started = bool(body.get("recheck")) and eng.start_check("manual")
            return 200, {"ok": True, "devices": devs, "recheck": started, "running": eng.running}
        if path == "/api/baseline/reset":
            eng.store.reset_baseline(body.get("device") or None)
            return 200, {"ok": True}
        if path == "/api/diagnose":
            from .diagnose import diagnose
            cfg = eng.cfg.get()
            dev = next((d for d in cfg["devices"] if d["id"] == body.get("device")), None)
            if dev is None:
                return 404, {"error": "장비를 찾을 수 없습니다."}
            if eng.demo:
                return 200, {"ok": True, "summary": "데모 모드에서는 실제 장비 진단을 하지 않습니다.", "steps": [], "log": "", "copy_text": ""}
            return 200, diagnose(dev, eng.creds.get(dev["credential"]), cfg["ssh"])
        if path == "/api/import_backbone":
            from .diagnose import parse_old_devices_yaml
            try:
                devices = parse_old_devices_yaml(str(body.get("text", "")))
            except Exception as exc:
                return 400, {"error": f"파일을 읽지 못했습니다: {type(exc).__name__}"}
            if not devices:
                return 400, {"error": "devices.yaml에서 장비를 찾지 못했습니다. 기존 백본 도구 폴더의 config\\devices.yaml 파일을 고르세요."}
            return 200, {"devices": devices}
        if path == "/api/console":
            return 200, eng.console(str(body.get("device", "")), str(body.get("command", "")))
        return 404, {"error": "없는 경로입니다."}


def _open_path(p) -> None:
    """파일·폴더를 Windows 기본 프로그램(엑셀, 탐색기)으로 엽니다."""
    import os
    import subprocess
    try:
        if sys.platform == "win32":
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":  # pragma: no cover
            subprocess.Popen(["open", str(p)])
        else:  # pragma: no cover
            subprocess.Popen(["xdg-open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        log.warning("열기 실패: %s", p)


def make_handler(app: App):
    allowed_hosts = None

    class Handler(BaseHTTPRequestHandler):
        server_version = "AutoNetwork.NetcheckCenter"

        def log_message(self, fmt: str, *args) -> None:  # 조용히
            log.debug("%s %s", self.address_string(), fmt % args)

        def _host_ok(self) -> bool:
            try:
                host = urlparse("//" + (self.headers.get("Host") or "")).hostname
            except ValueError:
                return False
            return host in ("127.0.0.1", "localhost", "::1")

        def _send(self, code: int, payload: Any, ctype: str = "application/json; charset=utf-8", extra: dict | None = None) -> None:
            data = payload if isinstance(payload, bytes) else (
                payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _token_ok(self) -> bool:
            return secrets.compare_digest(self.headers.get("X-NC-Token", ""), app.token)

        def do_GET(self) -> None:
            if not self._host_ok():
                return self._send(403, {"error": "로컬에서만 접속할 수 있습니다."})
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/api/version":  # 토큰 없이: 새로 실행한 프로그램이 이전 실행본의 버전을 확인
                return self._send(200, {"app": APP_ID, "demo": app.engine.demo, "version": app.version,
                                        "window": bool(app.watch and app.watch.window_open)})
            if url.path in ("/", "/index.html"):
                page = (app.web_dir / "index.html").read_text(encoding="utf-8").replace("__NC_TOKEN__", app.token).replace("__NC_DESKTOP__", "true" if app.desktop else "false")
                return self._send(200, page, "text/html; charset=utf-8")
            if url.path.startswith("/static/"):
                rel = url.path[len("/static/"):]
                target = (app.web_dir / rel).resolve()
                if app.web_dir.resolve() not in target.parents or not target.is_file():
                    return self._send(404, {"error": "없음"})
                ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                return self._send(200, target.read_bytes(), ctype)
            if url.path == "/report.xlsx":
                if not secrets.compare_digest(q.get("t", ""), app.token):
                    return self._send(403, {"error": "권한 없음"})
                from urllib.parse import quote
                from .excel import build_workbook, report_filename
                run = app.engine.store.get_run(int(q["id"]) if q.get("id") else None)
                if not run:
                    return self._send(404, {"error": "점검 기록이 없습니다."})
                cfg = app.engine.cfg.get()
                data = build_workbook(run, cfg.get("site_name", ""), cfg["thresholds"],
                                      lambda dev, cmd: app.engine.store.get_raw(run["id"], dev, cmd))
                name = report_filename(run)
                return self._send(200, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  {"Content-Disposition": f"attachment; filename=\"netcheck.xlsx\"; filename*=UTF-8''{quote(name)}"})
            if url.path == "/report":
                if not secrets.compare_digest(q.get("t", ""), app.token):
                    return self._send(403, {"error": "권한 없음"})
                run = app.engine.store.get_run(int(q["id"]) if q.get("id") else None)
                if not run:
                    return self._send(404, {"error": "점검 기록이 없습니다."})
                site = app.engine.cfg.get().get("site_name", "")
                name = time.strftime("netcheck_report_%Y%m%d_%H%M.html", time.localtime(run["started"]))
                disp = {"Content-Disposition": f'attachment; filename="{name}"'} if q.get("download") else {}
                return self._send(200, render(run, site), "text/html; charset=utf-8", disp)
            if url.path.startswith("/api/"):
                if not self._token_ok():
                    return self._send(403, {"error": "화면을 새로고침하세요(세션 만료)."})
                try:
                    code, payload = app.handle_get(url.path, q)
                except (KeyError, ValueError) as exc:
                    code, payload = 400, {"error": f"요청 값 오류: {exc}"}
                return self._send(code, payload)
            self._send(404, {"error": "없는 경로입니다."})

        def do_POST(self) -> None:
            url0 = urlparse(self.path)
            if url0.path == "/api/bye":  # 창을 닫을 때 화면이 보내는 신호(sendBeacon은 헤더를 못 붙여 주소에 토큰)
                q0 = {k: v[0] for k, v in parse_qs(url0.query).items()}
                if self._host_ok() and secrets.compare_digest(q0.get("t", ""), app.token) and app.watch:
                    app.watch.bye()
                return self._send(204, b"", "text/plain")
            if not self._host_ok() or not self._token_ok():
                return self._send(403, {"error": "화면을 새로고침하세요(세션 만료)."})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length < 0:
                    raise ValueError
            except ValueError:
                return self._send(400, {"error": "Content-Length는 0 이상의 정수여야 합니다."})
            if length > MAX_BODY:
                return self._send(413, {"error": "요청이 너무 큽니다."})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._send(400, {"error": "JSON 형식이 아닙니다."})
            url = urlparse(self.path)
            try:
                code, payload = app.handle_post(url.path, body)
            except Exception as exc:  # pragma: no cover
                log.exception("POST 처리 실패")
                code, payload = 500, {"error": f"처리 중 오류: {type(exc).__name__}"}
            self._send(code, payload)

    return Handler


class _Server(ThreadingHTTPServer):
    """Windows에서는 포트를 독점(SO_EXCLUSIVEADDRUSE)으로 엽니다.
    기본값(SO_REUSEADDR)은 Windows에서 같은 포트를 두 프로그램이 동시에 열 수 있게 해,
    새 버전을 실행해도 이전 버전 화면이 보이는 문제가 생깁니다."""

    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve(app: App, host: str, port: int) -> ThreadingHTTPServer:
    httpd = _Server((host, port), make_handler(app))
    httpd.daemon_threads = True
    return httpd
