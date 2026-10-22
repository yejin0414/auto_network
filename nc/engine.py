"""점검 실행·자동 주기 스케줄러."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import parsers as P
from .collector import CmdResult, DeviceCollection, collect_device, run_spec, safe_error
from .commands import CLUSTER_COMMANDS, check_console_command, commands_for
from .config import ConfigStore, ssh_for
from .credentials import CredentialStore
from .evaluate import evaluate_run
from .store import Store

log = logging.getLogger("netcheck")


def next_slot(now: float, interval_min: int, align: bool, last_start: float | None) -> float:
    if align:
        dt = datetime.fromtimestamp(now)
        midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed = (dt - midnight).total_seconds()
        step = interval_min * 60
        k = int(elapsed // step) + 1
        return (midnight + timedelta(seconds=k * step)).timestamp()
    if last_start is None:
        return now + 5
    return last_start + interval_min * 60


def device_time_limit(device: dict, ssh: dict) -> float:
    """장비 한 대 점검 제한 시간(초). 접속 대기×(재시도+1) + 명령 대기×3, 최소 5분.
    ssh.device_limit_minutes 를 넣으면 그 값을 씁니다."""
    s = ssh_for(device, ssh)
    fixed = float(ssh.get("device_limit_minutes") or 0)
    if fixed > 0:
        return fixed * 60
    return max(300.0, s["connect_timeout"] * (int(s.get("retries", 1)) + 1) + s["command_timeout"] * 3)


def _abort_session(holder: dict) -> None:
    sess = holder.get("session")
    if sess is None:
        return
    fn = getattr(sess, "abort", None) or getattr(sess, "close", None)
    if fn:
        threading.Thread(target=fn, name="netcheck-abort", daemon=True).start()


class _Abandoned(Exception):
    """중단 처리된(너무 오래 걸린) 점검이 뒤늦게 끝남"""


class Engine:
    def __init__(self, cfg: ConfigStore, store: Store, creds: CredentialStore, driver: Any, demo: bool = False) -> None:
        self.cfg = cfg
        self.store = store
        self.creds = creds
        self.driver = driver
        self.demo = demo
        self._lock = threading.Lock()
        self.running = False
        self.progress: dict[str, str] = {}
        self.run_started: float | None = None
        self.run_trigger = ""
        self.last_error = ""
        self.next_run: float | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._last_auto_start: float | None = None
        self.schedule_paused_reason = ""
        self._gen = 0                 # 점검 회차 번호(멈춘 점검을 버릴 때 사용)
        self.max_run_seconds = 40 * 60  # 이보다 오래 걸리는 점검은 멈춘 것으로 보고 다음 점검을 막지 않음
        self.device_grace = 45.0        # 장비 제한 시간 뒤 이만큼 더 기다렸다가 강제 중단
        self.cluster_fallback_seconds = 300.0  # 모든 클러스터 대체 수집을 합친 시간 예산

    # ------------------------------------------------------------- 상태
    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "run_started": self.run_started,
            "run_trigger": self.run_trigger,
            "progress": dict(self.progress),
            "next_run": self.next_run,
            "last_error": self.last_error,
            "demo": self.demo,
            "now": time.time(),
        }

    # ------------------------------------------------------------- 점검
    def start_check(self, trigger: str = "manual") -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.run_started = time.time()
            self.run_trigger = trigger
            self.progress = {}
            self._gen += 1
            gen = self._gen
        threading.Thread(target=self._run_safe, args=(trigger, None, gen), name="netcheck-run", daemon=True).start()
        return True

    def run_blocking(self, trigger: str = "manual", now: float | None = None) -> int | None:
        with self._lock:
            if self.running:
                return None
            self.running = True
            self.run_started = now or time.time()
            self.run_trigger = trigger
            self.progress = {}
            self._gen += 1
            gen = self._gen
        return self._run_safe(trigger, now, gen)

    def _run_safe(self, trigger: str, now: float | None = None, gen: int = 0) -> int | None:
        try:
            return self._run(trigger, now, gen)
        except _Abandoned:
            log.warning("너무 오래 걸려 중단 처리한 점검이 뒤늦게 끝났습니다(결과는 버림)")
            return None
        except Exception as exc:  # pragma: no cover - 방어
            log.exception("점검 실패")
            if gen == self._gen:
                self.last_error = f"점검 중 오류: {type(exc).__name__}: {exc}"
            return None
        finally:
            with self._lock:
                if gen == self._gen:
                    self.running = False
            self._wake.set()

    def abandon_stuck_run(self) -> bool:
        """점검이 max_run_seconds 넘게 끝나지 않으면 멈춘 것으로 보고 다음 점검을 할 수 있게 합니다."""
        with self._lock:
            if not self.running or self.run_started is None:
                return False
            if time.time() - self.run_started < self.max_run_seconds:
                return False
            mins = int((time.time() - self.run_started) // 60)
            self._gen += 1
            self.running = False
        self.last_error = f"이전 점검이 {mins}분 넘게 끝나지 않아 중단 처리했습니다. 응답 없는 장비가 있는지 확인하세요."
        log.warning(self.last_error)
        return True

    def _run_cancelled(self, gen: int) -> bool:
        return self._stop.is_set() or bool(gen and gen != self._gen)

    def _set_progress(self, gen: int, device_id: str, message: str) -> None:
        with self._lock:
            if not self._run_cancelled(gen):
                self.progress[device_id] = message

    @staticmethod
    def _cluster_result_usable(key: str, result: CmdResult | None) -> bool:
        if result is None or not result.ok:
            return False
        if key == "membership":
            # Missing peers and explicit failed states are real observations,
            # not reasons to replace this snapshot with a healthier peer view.
            # If no status was readable at all, try another collector.
            return any(row["state"] for row in P.parse_membership(result.output))
        return bool(P.parse_load_distribution(result.output)["rows"])

    def _cluster_attempt(self, device: dict, specs: list, ssh: dict, deadline: float, gen: int) -> dict[str, CmdResult]:
        """daemon 작업을 감독해 open/run/close가 멈춰도 전체 예산 안에 반환합니다.

        worker는 지역 상태에만 기록합니다. 제한 시각 전에 완료된 명령만 복사하고
        취소 뒤 늦게 반환한 세션/결과는 현재 회차나 다음 회차에 반영하지 않습니다.
        """
        done, cancel = threading.Event(), threading.Event()
        lock = threading.Lock()
        holder: dict = {}
        state: dict = {"results": {}, "error": ""}
        started = time.time()

        def cancelled() -> bool:
            return cancel.is_set() or self._run_cancelled(gen) or time.monotonic() >= deadline

        def receive(result: CmdResult) -> None:
            with lock:
                if not cancelled():
                    state["results"][result.id] = result

        def work() -> None:
            try:
                collection = collect_device(
                    self.driver, device, specs, self.creds.get(device["credential"]), ssh,
                    deadline=time.time() + max(0.0, deadline - time.monotonic()), holder=holder,
                    cancelled=cancelled, on_result=receive,
                )
                with lock:
                    if not cancelled():
                        state["error"] = collection.error
            except Exception as exc:
                with lock:
                    if not cancelled():
                        state["error"] = f"대체 수집 실패: {type(exc).__name__} {safe_error(exc)}"
            finally:
                done.set()

        threading.Thread(target=work, name="netcheck-cluster", daemon=True).start()
        try:
            while not done.is_set() and not cancelled():
                done.wait(min(0.05, max(0.0, deadline - time.monotonic())))
            with lock:
                cancel.set()
                results = dict(state["results"])
                error = state["error"]
        finally:
            cancel.set()
            if not done.is_set():
                _abort_session(holder)
        if self._run_cancelled(gen):
            raise _Abandoned()
        reason = error or ("클러스터 대체 수집 시간 예산 초과" if time.monotonic() >= deadline else "클러스터 명령을 수집하지 못했습니다.")
        for spec in specs:
            if spec.id not in results:
                results[spec.id] = CmdResult(spec.id, spec.label, spec.commands[0], "", False, reason,
                                             round(time.time() - started, 2), spec.optional)
        return results

    def _collect_clusters(self, groups: dict, primaries: dict, collections: dict,
                          ssh: dict, gen: int) -> dict[str, dict]:
        deadline = time.monotonic() + max(0.0, self.cluster_fallback_seconds)
        clusters: dict[str, dict] = {}
        for name, members in groups.items():
            cluster: dict = {"sources": {}}

            def merge(device: dict, results: dict) -> None:
                for spec in CLUSTER_COMMANDS:
                    if self._cluster_result_usable(spec.id, cluster.get(spec.id)):
                        continue
                    result = results.get(spec.id)
                    if result is not None:
                        cluster[spec.id] = result
                        cluster["sources"][spec.id] = {"id": device["id"], "name": device["name"]}

            primary = primaries[name]
            order = [primary] + [w for w in members if w["id"] != primary["id"]]
            # Preserve every usable result already collected before opening a fallback session.
            for w in order:
                dc = collections.get(w["id"])
                if dc and dc.connected:
                    merge(w, dc.results)
            for w in order[1:]:
                if self._run_cancelled(gen):
                    raise _Abandoned()
                missing = [spec for spec in CLUSTER_COMMANDS if not self._cluster_result_usable(spec.id, cluster.get(spec.id))]
                if not missing or time.monotonic() >= deadline:
                    break
                dc = collections.get(w["id"])
                if not dc or not dc.connected:
                    continue
                results = self._cluster_attempt(w, missing, ssh, deadline, gen)
                with self._lock:
                    if self._run_cancelled(gen):
                        raise _Abandoned()
                    dc.results.update(results)
                    merge(w, results)
            if self._run_cancelled(gen):
                raise _Abandoned()
            for spec in CLUSTER_COMMANDS:
                if spec.id not in cluster:
                    cluster[spec.id] = CmdResult(spec.id, spec.label, spec.commands[0], "", False,
                                                "클러스터 대체 수집 시간 예산 초과" if time.monotonic() >= deadline
                                                else "접속 가능한 클러스터 수집 장비가 없습니다.")
            sources = cluster["sources"]
            ids = {s["id"] for s in sources.values()}
            if len(ids) == 1:
                source = next(iter(sources.values()))
                cluster.update(source=source["name"], source_id=source["id"])
            else:
                labels = {"membership": "멤버십", "load": "Client 분배"}
                cluster["source"] = " · ".join(f"{labels[key]} {sources[key]['name']}" for key in labels if key in sources) or None
                cluster["source_id"] = None
            clusters[name] = cluster
        return clusters

    def _run(self, trigger: str, now: float | None, gen: int = 0) -> int:
        cfg = self.cfg.get()
        started = now or time.time()
        hook = getattr(self.driver, "begin_run", None)
        if hook:
            hook(started)
        ssh = cfg["ssh"]
        devices = [d for d in cfg["devices"] if d["enabled"]]
        wlcs = [d for d in devices if d["role"] == "WLC"]
        # 클러스터(IN/OUT 등)별 대표 WLC
        groups: dict[str, list[dict]] = {}
        for w in wlcs:
            groups.setdefault(w.get("cluster", ""), []).append(w)
        primaries = {name: next((w for w in ws if w.get("cluster_primary")), ws[0]) for name, ws in groups.items()}
        primary_ids = {p["id"] for p in primaries.values()}
        with self._lock:
            if self._run_cancelled(gen):
                raise _Abandoned()
            self.progress = {d["id"]: "대기" for d in devices}
        limits = {d["id"]: device_time_limit(d, ssh) for d in devices}
        started_at: dict[str, float] = {}
        holders: dict[str, dict] = {d["id"]: {} for d in devices}

        def job(d: dict) -> DeviceCollection:
            if self._run_cancelled(gen):
                raise _Abandoned()
            started_at[d["id"]] = time.time()
            specs = commands_for(d["role"], cfg["extra_commands"].get(d["role"]))
            if d["id"] in primary_ids:
                specs += list(CLUSTER_COMMANDS)
            self._set_progress(gen, d["id"], "접속 중")

            def prog(msg: str, did=d["id"], name=d["name"]) -> None:
                self._set_progress(gen, did, msg[len(name):].strip() if msg.startswith(name) else msg)

            dc = collect_device(self.driver, d, specs, self.creds.get(d["credential"]), ssh, prog,
                                deadline=started_at[d["id"]] + limits[d["id"]], holder=holders[d["id"]],
                                cancelled=lambda: self._run_cancelled(gen))
            self._set_progress(gen, d["id"], "완료" if dc.connected else "실패")
            return dc

        got: dict[str, DeviceCollection] = {}
        if devices:
            # 장비마다 제한 시간을 두고, 넘기면 세션을 끊고 '응답 없음'으로 처리해 점검이 반드시 끝나게 함
            pool = ThreadPoolExecutor(max_workers=max(1, int(ssh.get("parallel", 6))), thread_name_prefix="netcheck-dev")
            futs = {pool.submit(job, d): d for d in devices}
            pending = set(futs)
            try:
                while pending:
                    if self._run_cancelled(gen):
                        raise _Abandoned()
                    done, pending = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                    if self._run_cancelled(gen):
                        raise _Abandoned()
                    for f in done:
                        d = futs[f]
                        try:
                            got[d["id"]] = f.result()
                        except Exception as exc:  # pragma: no cover - 방어
                            log.exception("%s 점검 오류", d["name"])
                            got[d["id"]] = DeviceCollection(device_id=d["id"], connected=False, started=time.time(),
                                                            error=f"점검 중 오류: {type(exc).__name__} {exc}",
                                                            error_kind="error", finished=time.time())
                    now_t = time.time()
                    for f in list(pending):
                        d = futs[f]
                        st = started_at.get(d["id"])
                        if st and now_t - st > limits[d["id"]] + self.device_grace:
                            pending.discard(f)
                            _abort_session(holders[d["id"]])
                            mins = max(1, round((now_t - st) / 60))
                            log.warning("%s: %d분 넘게 응답이 없어 이 장비 점검을 중단합니다", d["name"], mins)
                            self._set_progress(gen, d["id"], "응답 없음")
                            got[d["id"]] = DeviceCollection(
                                device_id=d["id"], connected=False, started=st, finished=now_t, error_kind="timeout",
                                error=(f"응답 없음: {mins}분 넘게 점검이 끝나지 않아 이 장비는 중단했습니다. "
                                       "장비 부하·회선 상태를 확인하거나 설정 → 접속 대기 시간을 조정하세요."))
                    if self._run_cancelled(gen):
                        raise _Abandoned()
            finally:
                if self._run_cancelled(gen):
                    for holder in holders.values():
                        _abort_session(holder)
                pool.shutdown(wait=False, cancel_futures=True)
        collections: dict[str, DeviceCollection] = {d["id"]: got[d["id"]] for d in devices if d["id"] in got}

        clusters = self._collect_clusters(groups, primaries, collections, ssh, gen)

        if self._run_cancelled(gen):
            raise _Abandoned()
        prev_run = self.store.get_run()
        evaluation, new_base = evaluate_run(cfg, collections, clusters, self.store.baselines(),
                                            self.store.previous_metrics(), now=started)
        finished = time.time() if now is None else started + 40
        run_id = self.store.save_run(started, finished, trigger, evaluation, collections, clusters,
                                     report_config=cfg)
        self.store.save_baselines(new_base)
        self.store.add_events(self._diff_events(prev_run, evaluation, run_id, started))
        try:
            self.store.add_vrrp(self._vrrp_rows(prev_run, evaluation, run_id, started))
        except Exception:  # pragma: no cover - 이력 기록 실패가 점검을 막지 않도록
            log.exception("VRRP 이력 기록 실패")
        self.store.prune(cfg["retention_days"])
        self.last_error = ""
        self._after_run(cfg, run_id)
        return run_id

    # ------------------------------------------------------------- 점검 후: 엑셀 저장, 알림
    reports_dir: Path | None = None   # app.py가 지정(기본: 프로그램 폴더\보고서)
    last_report: str = ""

    def report_folder(self, cfg: dict | None = None) -> Path:
        cfg = cfg or self.cfg.get()
        folder = cfg["report"].get("folder")
        return Path(folder) if folder else (self.reports_dir or Path("보고서"))

    def _after_run(self, cfg: dict, run_id: int) -> None:
        if self.demo_quiet:
            return
        run = self.store.get_run(run_id)
        if run is None:
            return
        rep = cfg["report"]
        saved = ""
        if rep.get("excel_auto"):
            try:
                from .excel import save_report

                path = save_report(run, cfg.get("site_name", ""), cfg["thresholds"],
                                   lambda dev, cmd: self.store.get_raw(run_id, dev, cmd),
                                   self.report_folder(cfg), cfg["retention_days"])
                saved = str(path)
                self.last_report = saved
            except Exception as exc:
                log.warning("엑셀 보고서 저장 실패: %s", exc)
                self.last_error = f"엑셀 보고서를 저장하지 못했습니다: {type(exc).__name__} {exc}"
        if rep.get("notify"):
            try:
                from .notify import completion_message, show_toast

                title, lines = completion_message(run)
                show_toast(title, lines)
            except Exception as exc:  # pragma: no cover
                log.warning("알림 실패: %s", exc)

    demo_quiet = False   # 데모 이력 채우는 동안에는 알림을 띄우지 않음

    @staticmethod
    def _vrrp_rows(prev: dict | None, cur: dict, run_id: int, ts: float) -> list[dict]:
        """VRRP 변경 이력: (1) 직전 점검과 역할이 달라진 그룹, (2) 장비 로그(logbuffer)의 VRRP 상태 변경.
        같은 그룹·전환의 유일한 로그가 관측 구간 안에 있을 때만 둘을 합칩니다.
        개별 명령의 관측 시각은 없으므로 직전 완료~이번 시작 사이를 보수적으로 사용합니다.
        모호하거나 시각이 불명확한 로그는 별도 기록으로 보존합니다."""
        import math

        from .parsers import vrrp_group_key

        def timestamp(value):
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                return value
            return None

        def norm(key):
            return vrrp_group_key(*key.rsplit("/", 1)) if "/" in key else key.casefold()

        rows: list[dict] = []
        prev_devs = (prev or {}).get("devices", {})
        prev_ts = (prev or {}).get("started")
        lower = timestamp((prev or {}).get("finished"))
        if lower is None:
            lower = timestamp(prev_ts)
        upper = timestamp(ts)
        bounded = lower is not None and upper is not None and lower < upper
        for dev_id, res in cur["devices"].items():
            m = res.get("metrics") or {}
            logs = []
            seen = set()
            for raw in m.get("vrrp_logs") or []:
                x = dict(raw)
                x["group"] = norm(x.get("group") or vrrp_group_key(x.get("interface", ""), x.get("vrid", "")))
                x["old"], x["new"] = x.get("old", "").capitalize(), x.get("new", "").capitalize()
                x["ts"] = timestamp(x.get("ts"))
                identity = tuple(x.get(k) for k in ("group", "old", "new", "time", "ts", "text"))
                if identity not in seen:
                    seen.add(identity)
                    logs.append(x)
            used: set[int] = set()
            old = ((prev_devs.get(dev_id) or {}).get("metrics") or {}).get("vrrp") or {}
            old_n = {norm(k): v.capitalize() for k, v in old.items()}
            for k, v in (m.get("vrrp") or {}).items():
                g, v = norm(k), v.capitalize()
                if g not in old_n or old_n[g] == v:
                    continue
                row = {"device_id": dev_id, "device_name": res["name"], "grp": g, "old": old_n[g], "new": v,
                       "detected": ts, "prev_check": prev_ts, "run_id": run_id, "source": "check"}
                if bounded and "/" in g and all(g.rsplit("/", 1)):
                    # Multiple transitions in this group cannot establish which one
                    # produced the observed role, even when one old/new pair matches.
                    candidates = [(i, x) for i, x in enumerate(logs) if x["group"] == g and
                                  (x["ts"] is None or lower < x["ts"] <= upper)]
                    if len(candidates) == 1:
                        i, x = candidates[0]
                    else:
                        i, x = -1, {}
                    if (i not in used and x.get("ts") is not None and x.get("old") == old_n[g]
                            and x.get("new") == v):
                        used.add(i)
                        row.update(log_time=x["time"], log_ts=x["ts"], text=x["text"], source="check+log")
                rows.append(row)
            for i, x in enumerate(logs):
                if i in used:
                    continue
                rows.append({"device_id": dev_id, "device_name": res["name"], "grp": x["group"], "old": x["old"],
                             "new": x["new"], "log_time": x["time"], "log_ts": x["ts"], "detected": ts,
                             "prev_check": prev_ts, "run_id": run_id, "source": "log", "text": x["text"]})
        return rows

    @staticmethod
    def _diff_events(prev: dict | None, cur: dict, run_id: int, ts: float) -> list[tuple]:
        events = []
        prev_devs = (prev or {}).get("devices", {})
        for dev_id, res in cur["devices"].items():
            # 계정 미입력은 장비 상태 변화가 아니므로 기록하지 않음(화면 상단 안내로 대신)
            bad = lambda c: c["level"] in ("warn", "crit", "unknown") and c.get("source") != "credential"
            before = {(c["key"]): c for c in prev_devs.get(dev_id, {}).get("checks", []) if bad(c)}
            now_bad = {(c["key"]): c for c in res["checks"] if bad(c)}
            for key, c in now_bad.items():
                old = before.get(key)
                if old is None or old["level"] != c["level"]:
                    events.append((ts, run_id, dev_id, c["level"], "new", f"{res['name']} · {c['label']}: {c['summary']}"))
            for key, c in before.items():
                if key not in now_bad and prev is not None:
                    events.append((ts, run_id, dev_id, "ok", "recovered", f"{res['name']} · {c['label']} 정상 복귀"))
        return events

    # ------------------------------------------------------------- 직접 확인
    def console(self, device_id: str, command: str) -> dict[str, Any]:
        reason = check_console_command(command)
        if reason:
            return {"ok": False, "error": reason}
        cfg = self.cfg.get()
        dev = next((d for d in cfg["devices"] if d["id"] == device_id), None)
        if dev is None:
            return {"ok": False, "error": "장비를 찾을 수 없습니다."}
        cred = self.creds.get(dev["credential"])
        if cred is None:
            return {"ok": False, "error": "이 장비의 접속 계정을 먼저 입력하세요."}
        from .collector import ConnectFailure
        from .commands import CommandSpec
        t0 = time.time()
        try:
            from .config import ssh_for

            dssh = ssh_for(dev, cfg["ssh"])
            session = self.driver.open(dev, cred, dssh)
        except ConnectFailure as exc:
            return {"ok": False, "error": str(exc)}
        try:
            r = run_spec(session, CommandSpec("console", command, (" ".join(command.split()),), timeout=60), dssh)
        finally:
            session.close()
        return {"ok": r.ok, "error": r.error, "output": r.output, "command": r.command, "duration": round(time.time() - t0, 1)}

    # ------------------------------------------------------------- 스케줄러
    def start_scheduler(self) -> None:
        threading.Thread(target=self._scheduler_loop, name="netcheck-scheduler", daemon=True).start()

    def reschedule(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _scheduler_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._scheduler_step()
            except Exception:  # pragma: no cover - 방어: 스케줄러가 죽지 않도록
                log.exception("자동 점검 예약 처리 오류")
                self._stop.wait(30)

    def _scheduler_step(self) -> None:
        refresh = self._wake.is_set()
        self._wake.clear()
        cfg = self.cfg.get()
        sched = cfg["schedule"]
        now = time.time()
        active = any(d.get("enabled", True) for d in cfg["devices"])
        signature = (sched["enabled"], sched["interval_minutes"], sched["align_to_clock"], active)
        refresh = refresh or signature != getattr(self, "_schedule_signature", None)
        self._schedule_signature = signature
        if not sched["enabled"] or not active:
            self.next_run = None
            self._wake.wait(30)
            return
        if self.next_run is None or refresh:
            self.next_run = next_slot(now, sched["interval_minutes"], sched["align_to_clock"], self._last_auto_start)
        wait = self.next_run - now
        if wait > 0:
            self._wake.wait(min(wait, 30))
            # Read fresh settings on the next step. Computing with this step's
            # snapshot here would consume the wake and retain the old interval.
            return
        if self._wake.is_set() or self._stop.is_set():
            # A change arrived after the snapshot; reconsider before starting.
            return
        self._last_auto_start = time.time()
        self.next_run = None
        self.abandon_stuck_run()
        if not self.start_check("auto"):
            log.info("이전 점검이 진행 중이라 이번 자동 점검은 건너뜁니다")
        time.sleep(1)
