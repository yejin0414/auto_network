"""Serialize Windows task updates and converge on the latest saved schedule."""

from __future__ import annotations

import copy
import logging
import threading
import time
from typing import Callable

log = logging.getLogger("netcheck")


class ScheduleSynchronizer:
    """One worker owns OS updates; callbacks are wakeups, never settings snapshots.

    ``publish`` must ignore a result if its schedule no longer matches the
    configuration. It is called without the worker lock to avoid lock inversion
    with configuration saves. Failed OS updates retry until shutdown; shutdown
    drains the latest saved value once and has a bounded wait.
    """

    def __init__(self, read_schedule: Callable[[], dict], apply: Callable[[dict], dict],
                 publish: Callable[[dict, dict], object], *, retry_delay: float = 5,
                 max_retry_delay: float = 60) -> None:
        self._read = read_schedule
        self._apply = apply
        self._publish_callback = publish
        self._retry_delay = retry_delay
        self._max_retry_delay = max_retry_delay
        self._condition = threading.Condition()
        self._requested = False
        self._closing = False
        self._aborted = False
        self._thread: threading.Thread | None = None
        self._last_success: dict | None = None
        self._last_result: dict | None = None
        self._retry_at: float | None = None
        self._failed_schedule: dict | None = None
        self._failures = 0
        self._drained = False

    def _publish(self, result: dict, schedule: dict) -> None:
        with self._condition:
            if self._aborted:
                return
        try:
            self._publish_callback(dict(result), copy.deepcopy(schedule))
        except Exception:
            # A UI callback must not kill the worker or strand newer settings.
            log.exception("자동 점검 작업 동기화 상태 표시 실패")

    def request(self, _saved_config: dict | None = None) -> bool:
        """Wake for the authoritative current config; ignore an old callback payload."""
        with self._condition:
            if self._closing:
                return False
        schedule = copy.deepcopy(self._read())
        # Publish before waking the worker, so a fast success cannot be replaced
        # afterwards by this request's pending status.
        self._publish({"ok": None, "registered": False, "pending": True, "retrying": False,
                       "message": "최신 자동 점검 설정을 Windows 작업에 반영하는 중입니다."}, schedule)
        with self._condition:
            if self._closing:
                return False
            self._requested = True
            self._retry_at = None
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="netcheck-wintask", daemon=True)
                self._thread.start()
            self._condition.notify_all()
        return True

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._requested and not self._aborted:
                    if self._closing:
                        self._drained = bool(self._last_result and self._last_result.get("ok"))
                        return
                    wait = None if self._retry_at is None else max(0, self._retry_at - time.monotonic())
                    if wait == 0:
                        break
                    self._condition.wait(wait)
                if self._aborted:
                    return
                self._requested = False
                self._retry_at = None
            schedule = copy.deepcopy(self._read())
            if schedule == self._last_success:
                result = dict(self._last_result or {})
            else:
                try:
                    result = dict(self._apply(copy.deepcopy(schedule)))
                except Exception as exc:
                    log.exception("자동 점검 작업 동기화 실패")
                    result = {"ok": False, "registered": None, "supported": True,
                              "message": f"Windows 작업 동기화 실패: {type(exc).__name__}: {exc}"}
            result.update(pending=False, retrying=False)
            if result.get("ok"):
                self._last_success = copy.deepcopy(schedule)
                self._failed_schedule = None
                self._failures = 0
            else:
                # A failed mutation may have changed the OS task partially.
                self._last_success = None
            self._last_result = dict(result)
            latest = self._read()
            with self._condition:
                if self._aborted:
                    return
                if latest != schedule:
                    self._requested = True
                    continue
                if not result.get("ok") and not self._closing:
                    self._failures = self._failures + 1 if self._failed_schedule == schedule else 1
                    self._failed_schedule = copy.deepcopy(schedule)
                    delay = min(self._max_retry_delay, self._retry_delay * 2 ** min(self._failures - 1, 10))
                    self._retry_at = time.monotonic() + delay
                    result.update(retrying=True, retry_in_seconds=delay)
            self._publish(result, schedule)

    def close(self, timeout: float = 65) -> bool:
        """Stop accepting callbacks and drain the last saved settings, without retries.

        The caller must first stop configuration writes. False means the final OS
        state could not be confirmed (failure or timeout), never successful drain.
        """
        with self._condition:
            if self._closing and self._thread is not None and not self._thread.is_alive():
                return self._drained
            self._closing = True
            self._requested = True
            self._retry_at = None
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="netcheck-wintask", daemon=True)
                self._thread.start()
            self._condition.notify_all()
            worker = self._thread
        worker.join(timeout=max(0, timeout))
        if worker.is_alive():
            with self._condition:
                self._aborted = True
                self._condition.notify_all()
            log.warning("자동 점검 작업 종료 동기화 제한 시간을 초과했습니다. 다음 실행에서 다시 반영합니다.")
            return False
        if not self._drained:
            log.warning("마지막 자동 점검 설정의 Windows 작업 반영을 확인하지 못했습니다.")
        return self._drained
