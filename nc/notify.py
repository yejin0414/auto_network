"""Windows 알림(화면 오른쪽 아래 토스트). 추가 설치 없이 Windows 기본 PowerShell로 띄웁니다."""

from __future__ import annotations

import base64
import logging
import subprocess
import sys
import threading

log = logging.getLogger("netcheck")
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
# Windows PowerShell의 앱 ID: 별도 등록 없이 알림 센터에 표시됩니다.
APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&apos;"))


def build_script(title: str, lines: list[str]) -> str:
    texts = "".join(f"<text>{_xml_escape(t)}</text>" for t in [title] + lines[:2])
    xml = (f'<toast duration="long"><visual><binding template="ToastGeneric">{texts}'
           '</binding></visual><audio src="ms-winsoundevent:Notification.Default"/></toast>')
    return (
        "$ErrorActionPreference='Stop';"
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null;"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('{xml.replace(chr(39), chr(39) * 2)}');"
        "$t = New-Object Windows.UI.Notifications.ToastNotification $x;"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_ID}').Show($t);"
    )


def show_toast(title: str, lines: list[str], wait: bool = False) -> bool:
    """알림을 띄웁니다. Windows가 아니면 아무것도 하지 않습니다."""
    if sys.platform != "win32":
        return False
    script = build_script(title, lines)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-WindowStyle", "Hidden", "-EncodedCommand", encoded]

    def run() -> bool:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=NO_WINDOW)
            if r.returncode != 0:
                log.warning("알림 표시 실패: %s", r.stderr.decode("utf-8", "replace")[:300])
            return r.returncode == 0
        except Exception as exc:  # pragma: no cover
            log.warning("알림 표시 실패: %s", exc)
            return False

    if wait:
        return run()
    threading.Thread(target=run, daemon=True).start()
    return True


def completion_message(run: dict) -> tuple[str, list[str]]:
    s = run["summary"]
    c = s.get("counts", {})
    head = {"ok": "점검 완료: 모두 정상", "warn": "점검 완료: 주의 필요", "crit": "점검 완료: 장애 발생",
            "unknown": "점검 완료: 일부 확인 불가"}[s["overall"]]
    line1 = f"장애 {c.get('crit', 0)} · 주의 {c.get('warn', 0)} · 확인 불가 {c.get('unknown', 0)} · 정상 {c.get('ok', 0)}"
    bad = []
    for d in run["devices"].values():
        for ch in d["checks"]:
            if ch["level"] in ("crit", "warn"):
                bad.append((0 if ch["level"] == "crit" else 1, f"{d['name']} {ch['label']}: {ch['summary']}"))
    bad.sort()
    line2 = bad[0][1] if bad else "모든 장비가 기준 안에 있습니다."
    if len(bad) > 1:
        line2 += f" 외 {len(bad) - 1}건"
    return head, [line1, line2[:120]]
