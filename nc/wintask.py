"""창을 닫아도 자동 점검: Windows 작업 스케줄러에 '점검 1회 실행' 작업을 등록합니다.

- 프로그램 창이 켜져 있으면 프로그램 안의 스케줄러가 점검하고, 작업 스케줄러가 깨운 실행은 바로 끝납니다.
- 창이 닫혀 있으면 작업 스케줄러가 정해진 시간마다 NetcheckCenter.exe --auto-check 를 실행해
  점검 → 엑셀 보고서 저장 → 완료 알림 후 종료합니다(창은 뜨지 않음).
- 관리자 권한이 필요 없고, 로그인한 사용자 계정으로 실행됩니다(저장한 접속 계정을 그대로 사용).
- PC가 절전 중이었으면 깨어난 뒤 바로 놓친 점검을 실행합니다.
"""

from __future__ import annotations

import logging
import csv
import io
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

log = logging.getLogger("netcheck")
TASK_NAME = "AutoNetwork NetcheckCenter AutoCheck"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def launch_command() -> tuple[str, str, str]:
    """(실행 파일, 인수, 작업 폴더)"""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return str(exe), "--auto-check", str(exe.parent)
    app = Path(__file__).resolve().parent.parent / "app.py"
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    return str(pyw if pyw.exists() else py), f'"{app}" --auto-check', str(app.parent)


def build_xml(interval_minutes: int, align: bool, command: str, arguments: str, workdir: str,
              now: datetime | None = None) -> str:
    now = now or datetime.now()
    if align:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = (now + timedelta(minutes=interval_minutes)).replace(microsecond=0)
    limit = max(10, min(interval_minutes - 1, 55))
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>무선망 통합 점검: 프로그램 창을 닫아도 정해진 시간마다 BB·MM·WLC 점검 (프로그램 설정 → 자동 점검에서 끄기)</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT{int(interval_minutes)}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{start.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT{limit}M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(workdir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _schtasks(*args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, timeout=timeout, creationflags=NO_WINDOW)


def _out(r: subprocess.CompletedProcess) -> str:
    raw = (r.stdout or b"") + (r.stderr or b"")
    for enc in ("utf-8", "cp949", "mbcs"):
        try:
            return raw.decode(enc).strip()
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace").strip()


def sync(schedule: dict, *, timeout: float = 30) -> dict:
    """설정에 맞게 작업을 등록/갱신/삭제합니다. 결과: {ok, registered, message}"""
    if sys.platform != "win32":
        return {"ok": True, "registered": False, "supported": False, "message": ""}
    deadline = time.monotonic() + timeout

    def run(*args: str) -> subprocess.CompletedProcess:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Windows 작업 동기화 제한 시간을 초과했습니다.")
        return _schtasks(*args, timeout=remaining)

    want = bool(schedule.get("enabled")) and bool(schedule.get("background", False))
    try:
        if not want:
            query = run("/Query", "/TN", TASK_NAME)
            if query.returncode == 0:
                removed = run("/Delete", "/TN", TASK_NAME, "/F")
                if removed.returncode != 0:
                    return {"ok": False, "registered": True, "supported": True,
                            "message": f"Windows 자동 점검 작업을 해제하지 못했습니다: {_out(removed)}"}
                log.info("창을 닫았을 때 자동 점검(작업 스케줄러)을 해제했습니다")
            else:
                # A failed query may mean access denied or a temporary error,
                # not necessarily an absent task. Confirm absence via a full
                # successful listing before reporting that deletion is done.
                listing = run("/Query", "/FO", "CSV", "/NH")
                if listing.returncode != 0:
                    return {"ok": False, "registered": None, "supported": True,
                            "message": f"Windows 자동 점검 작업 상태를 확인하지 못했습니다: {_out(query)} {_out(listing)}"}
                rows = list(csv.reader(io.StringIO(_out(listing))))
                if any(len(row) < 3 for row in rows):
                    return {"ok": False, "registered": None, "supported": True,
                            "message": "Windows 작업 목록을 해석하지 못해 자동 점검 작업의 해제를 확인할 수 없습니다."}
                if any(row[0].lstrip("\\").casefold() == TASK_NAME.casefold() for row in rows):
                    return {"ok": False, "registered": True, "supported": True,
                            "message": f"Windows 자동 점검 작업이 남아 있으나 상태를 읽지 못했습니다: {_out(query)}"}
            return {"ok": True, "registered": False, "supported": True, "message": ""}
        cmd, argv, wd = launch_command()
        xml = build_xml(int(schedule.get("interval_minutes", 60)), bool(schedule.get("align_to_clock", True)), cmd, argv, wd)
        fd, tmp = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        try:
            Path(tmp).write_text(xml, encoding="utf-16")
            r = run("/Create", "/TN", TASK_NAME, "/XML", tmp, "/F")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        if r.returncode != 0:
            msg = _out(r)
            log.warning("작업 스케줄러 등록 실패: %s", msg)
            return {"ok": False, "registered": None, "supported": True,
                    "message": f"Windows 작업 스케줄러에 등록하지 못했습니다: {msg}"}
        log.info("작업 스케줄러 등록: %s %s (%s분마다)", cmd, argv, schedule.get("interval_minutes"))
        return {"ok": True, "registered": True, "supported": True, "message": ""}
    except Exception as exc:  # pragma: no cover - 방어
        log.warning("작업 스케줄러 처리 실패: %s", exc)
        return {"ok": False, "registered": None, "supported": True, "message": f"작업 스케줄러 처리 실패: {exc}"}


def query_xml() -> str:
    if sys.platform != "win32":
        return ""
    r = _schtasks("/Query", "/TN", TASK_NAME, "/XML")
    return _out(r) if r.returncode == 0 else ""
