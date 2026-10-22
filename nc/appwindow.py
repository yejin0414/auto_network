"""프로그램 창: Windows에 기본으로 있는 Microsoft Edge의 '앱 모드'로 엽니다.

- 주소창·탭이 없는 독립 창으로 열리며 별도 설치(WebView2 런타임, .NET 등)가 필요 없습니다.
- 이 프로그램 전용 Edge 프로필(데이터 폴더 안)을 써서 평소 쓰는 Edge와 섞이지 않습니다.
- 창이 닫히면(Edge 종료 또는 화면의 종료 신호) 프로그램 전체를 종료합니다.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger("netcheck")
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
WINDOW_TITLE_MARK = "AutoNetwork · 무선망 통합 점검"


def find_browser() -> str | None:
    """Edge(우선) 또는 Chrome 실행 파일 경로. NC_BROWSER 환경 변수로 직접 지정할 수 있습니다."""
    forced = os.environ.get("NC_BROWSER")
    if forced and Path(forced).exists():
        return forced
    if sys.platform == "win32":
        roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        rels = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"]
        for rel in rels:
            for root in roots:
                if root:
                    p = Path(root) / rel
                    if p.exists():
                        return str(p)
        try:
            import winreg

            for name in ("msedge.exe", "chrome.exe"):
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}") as k:
                            v = winreg.QueryValue(k, None)
                            if v and Path(v).exists():
                                return v
                    except OSError:
                        pass
        except ImportError:  # pragma: no cover
            pass
        return None
    for name in ("microsoft-edge", "microsoft-edge-stable", "google-chrome", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    return None


def launch(browser: str, url: str, profile: Path) -> subprocess.Popen:
    profile.mkdir(parents=True, exist_ok=True)
    args = [
        browser,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-background-mode",
        # 창을 최소화하거나 다른 창에 가려져도 화면 신호(heartbeat)가 늦어지지 않게(종료 오판 방지)
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-features=msEdgeStartupBoost,msImplicitSignin,msEdgeSidebarV2,Translate,"
        "IntensiveWakeUpThrottling,CalculateNativeWinOcclusion",
        "--window-size=1480,940",
    ]
    if sys.platform != "win32" and os.geteuid() == 0:  # pragma: no cover - 리눅스 테스트 환경
        args.append("--no-sandbox")
    return subprocess.Popen(args, creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_tree(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15,
                           creationflags=NO_WINDOW)
        else:
            proc.terminate()
            proc.wait(5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ------------------------------------------------------------------ Windows 창 조작(최소화·앞으로)

def _find_windows() -> list[int]:
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if WINDOW_TITLE_MARK in buf.value:
                    found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def minimize_when_shown(timeout: float = 60) -> None:
    def run() -> None:
        end = time.time() + timeout
        while time.time() < end:
            hw = _find_windows()
            if hw:
                import ctypes

                for h in hw:
                    ctypes.windll.user32.ShowWindow(h, 6)  # SW_MINIMIZE
                return
            time.sleep(0.5)

    if sys.platform == "win32":
        threading.Thread(target=run, daemon=True).start()


def bring_to_front() -> bool:
    hw = _find_windows()
    if not hw:
        return False
    import ctypes

    u = ctypes.windll.user32
    for h in hw:
        u.ShowWindow(h, 9)  # SW_RESTORE
        u.SetForegroundWindow(h)
    return True


# ------------------------------------------------------------------ 창 수명 감시

class WindowWatch:
    """창이 닫혔는지 판단합니다.

    - 화면이 5초마다 보내는 신호(heartbeat)와 창을 닫을 때 보내는 종료 신호(bye)
    - 우리가 띄운 Edge 프로세스가 끝났는지
    둘 중 확실한 쪽으로 '닫힘'을 판단해 on_closed를 부릅니다.
    """

    def __init__(self, proc: subprocess.Popen | None, on_closed: Callable[[], None]) -> None:
        self.proc = proc
        self.on_closed = on_closed
        self.started = time.time()
        self.last_seen: float | None = None
        self.bye_at: float | None = None
        self._stop = threading.Event()

    def heartbeat(self) -> None:
        self.last_seen = time.time()
        self.bye_at = None

    def bye(self) -> None:
        self.bye_at = time.time()

    @property
    def window_open(self) -> bool:
        return self.last_seen is not None and time.time() - self.last_seen < 20

    def stop(self) -> None:
        self._stop.set()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="netcheck-window-watch", daemon=True).start()

    def _closed(self) -> bool:
        now = time.time()
        seen = self.last_seen
        # 창을 닫을 때 보낸 신호: 새로고침이면 곧바로 다시 신호가 오므로 4초 기다림
        if self.bye_at and now - self.bye_at > 4 and (seen is None or seen <= self.bye_at):
            return True
        if self.proc is not None and self.proc.poll() is not None:
            # 우리가 띄운 Edge가 끝남(창 닫힘). 혹시 다른 Edge로 넘어갔으면 신호가 계속 오므로 확인
            if seen is None:
                return now - self.started > 20
            return now - seen > 30
        if self.proc is None:
            # 일반 브라우저로 연 경우: 백그라운드 탭은 신호가 1분까지 늦을 수 있어 넉넉히
            if seen is None:
                return now - self.started > 300
            return now - seen > 180
        return False

    def _loop(self) -> None:
        while not self._stop.wait(1):
            if self._closed():
                log.info("프로그램 창이 닫혀 종료합니다")
                self.on_closed()
                return
