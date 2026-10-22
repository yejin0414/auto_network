"""SQLite 이력 저장소: 점검 회차, 장비별 결과, 원본 출력(압축), 기준값, 이벤트."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import zlib
from pathlib import Path
from typing import Any

from .report_context import capture_context, normalize_context

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started REAL NOT NULL, finished REAL, trigger TEXT, overall TEXT, summary TEXT, report_context TEXT
);
CREATE TABLE IF NOT EXISTS device_results (
  run_id INTEGER NOT NULL, device_id TEXT NOT NULL, status TEXT, cpu REAL, mem REAL, data TEXT,
  PRIMARY KEY (run_id, device_id)
);
CREATE INDEX IF NOT EXISTS ix_dr_device ON device_results(device_id, run_id);
CREATE TABLE IF NOT EXISTS raw_outputs (
  run_id INTEGER NOT NULL, device_id TEXT NOT NULL, cmd_id TEXT NOT NULL,
  label TEXT, command TEXT, ok INTEGER, error TEXT, duration REAL, output BLOB,
  PRIMARY KEY (run_id, device_id, cmd_id)
);
CREATE TABLE IF NOT EXISTS baselines (device_id TEXT PRIMARY KEY, data TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS vrrp_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, device_name TEXT, grp TEXT,
  old TEXT, new TEXT, log_time TEXT, log_ts REAL, detected REAL, prev_check REAL, run_id INTEGER,
  source TEXT, text TEXT, acked REAL
);
CREATE INDEX IF NOT EXISTS vrrp_history_dev ON vrrp_history(device_id, acked);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, run_id INTEGER, device_id TEXT,
  level TEXT, kind TEXT, text TEXT
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            # Serialize the schema check and ALTER across independent processes.
            # SQLite commits the migration atomically; retrying an interrupted
            # startup or opening an already migrated database is safe.
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                columns = {row["name"] for row in self._db.execute("PRAGMA table_info(runs)")}
                if "report_context" not in columns:
                    self._db.execute("ALTER TABLE runs ADD COLUMN report_context TEXT")

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # ------------------------------------------------------------- 회차
    def save_run(self, started: float, finished: float, trigger: str, evaluation: dict,
                 collections: dict, clusters: dict | None, *, report_config: dict | None = None) -> int:
        summary = evaluation["summary"]
        context = (json.dumps(capture_context(report_config), ensure_ascii=False, allow_nan=False)
                   if report_config is not None else None)
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO runs(started, finished, trigger, overall, summary, report_context) VALUES (?,?,?,?,?,?)",
                (started, finished, trigger, summary["overall"], json.dumps(summary, ensure_ascii=False), context),
            )
            run_id = int(cur.lastrowid)
            for dev_id, res in evaluation["devices"].items():
                m = res.get("metrics", {})
                self._db.execute(
                    "INSERT INTO device_results VALUES (?,?,?,?,?,?)",
                    (run_id, dev_id, res["status"], m.get("cpu"), m.get("mem"), json.dumps(res, ensure_ascii=False)),
                )
            rows = []
            for dev_id, dc in collections.items():
                for r in dc.results.values():
                    rows.append((run_id, dev_id, r.id, r.label, r.command, int(r.ok), r.error, r.duration,
                                 zlib.compress(r.output.encode("utf-8"), 6)))
            if clusters and "membership" in clusters:  # 예전 형식(클러스터 1개)
                clusters = {"": clusters}
            for cluster in (clusters or {}).values():
                for key in ("membership", "load"):
                    src = (((cluster.get("sources") or {}).get(key) or {}).get("id")
                           if "sources" in cluster else cluster.get("source_id"))
                    r = cluster.get(key)
                    if r is not None and src:
                        rows.append((run_id, src, r.id, r.label, r.command, int(r.ok), r.error, r.duration,
                                     zlib.compress(r.output.encode("utf-8"), 6)))
            self._db.executemany("INSERT OR REPLACE INTO raw_outputs VALUES (?,?,?,?,?,?,?,?,?)", rows)
        return run_id

    def list_runs(self, limit: int = 50) -> list[dict]:
        rows = self._q("SELECT id, started, finished, trigger, overall, summary FROM runs ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            s = json.loads(r["summary"] or "{}")
            out.append({"id": r["id"], "started": r["started"], "finished": r["finished"], "trigger": r["trigger"],
                        "overall": r["overall"], "counts": s.get("counts", {}), "total_active": s.get("total_active")})
        return out

    def get_run(self, run_id: int | None = None) -> dict | None:
        rows = (self._q("SELECT * FROM runs WHERE id=?", (run_id,)) if run_id
                else self._q("SELECT * FROM runs ORDER BY id DESC LIMIT 1"))
        if not rows:
            return None
        r = rows[0]
        devs = self._q("SELECT device_id, data FROM device_results WHERE run_id=?", (r["id"],))
        raw = self._q("SELECT device_id, cmd_id, label, command, ok, error, duration FROM raw_outputs WHERE run_id=? ORDER BY rowid", (r["id"],))
        cmds: dict[str, list] = {}
        for x in raw:
            cmds.setdefault(x["device_id"], []).append({
                "cmd_id": x["cmd_id"], "label": x["label"], "command": x["command"],
                "ok": bool(x["ok"]), "error": x["error"], "duration": x["duration"],
            })
        devices = {}
        for d in devs:
            data = json.loads(d["data"])
            data["commands"] = cmds.get(d["device_id"], [])
            devices[d["device_id"]] = data
        try:
            context = normalize_context(json.loads(r["report_context"] or "null"))
        except (TypeError, ValueError):
            context = None
        return {"id": r["id"], "started": r["started"], "finished": r["finished"], "trigger": r["trigger"],
                "overall": r["overall"], "summary": json.loads(r["summary"] or "{}"), "devices": devices,
                "report_context": context}

    def get_raw(self, run_id: int, device_id: str, cmd_id: str) -> dict | None:
        rows = self._q("SELECT * FROM raw_outputs WHERE run_id=? AND device_id=? AND cmd_id=?", (run_id, device_id, cmd_id))
        if not rows:
            return None
        r = rows[0]
        return {"command": r["command"], "label": r["label"], "ok": bool(r["ok"]), "error": r["error"],
                "duration": r["duration"], "output": zlib.decompress(r["output"]).decode("utf-8", "replace")}

    def previous_metrics(self) -> dict[str, dict]:
        """장비별 가장 최근 회차의 지표(재부팅 감지용)."""
        rows = self._q(
            "SELECT dr.device_id, dr.data, r.started FROM device_results dr JOIN runs r ON r.id=dr.run_id "
            "WHERE dr.run_id=(SELECT MAX(run_id) FROM device_results x WHERE x.device_id=dr.device_id "
            "AND json_extract(x.data,'$.metrics.uptime') IS NOT NULL)"
        )
        out = {}
        for r in rows:
            m = json.loads(r["data"]).get("metrics", {})
            out[r["device_id"]] = {"uptime": m.get("uptime"), "ts": r["started"]}
        return out

    def trend(self, device_id: str, since: float) -> list[dict]:
        rows = self._q(
            "SELECT r.started, dr.status, dr.cpu, dr.mem FROM device_results dr JOIN runs r ON r.id=dr.run_id "
            "WHERE dr.device_id=? AND r.started>=? ORDER BY r.id", (device_id, since))
        return [{"t": r["started"], "status": r["status"], "cpu": r["cpu"], "mem": r["mem"]} for r in rows]

    def trends_all(self, since: float) -> dict[str, list]:
        rows = self._q(
            "SELECT dr.device_id, r.id, r.started, dr.status, dr.cpu, dr.mem FROM device_results dr "
            "JOIN runs r ON r.id=dr.run_id WHERE r.started>=? ORDER BY r.id", (since,))
        out: dict[str, list] = {}
        for r in rows:
            out.setdefault(r["device_id"], []).append({"run": r["id"], "t": r["started"], "status": r["status"], "cpu": r["cpu"], "mem": r["mem"]})
        return out

    # ------------------------------------------------------------- 기준값
    def baselines(self) -> dict[str, dict]:
        return {r["device_id"]: json.loads(r["data"]) for r in self._q("SELECT device_id, data FROM baselines")}

    def baseline_times(self) -> dict[str, float]:
        return {r["device_id"]: r["updated"] for r in self._q("SELECT device_id, updated FROM baselines")}

    def save_baselines(self, updates: dict[str, dict]) -> None:
        if not updates:
            return
        now = time.time()
        with self._lock, self._db:
            for dev, data in updates.items():
                self._db.execute(
                    "INSERT INTO baselines VALUES (?,?,?) ON CONFLICT(device_id) DO UPDATE SET data=excluded.data",
                    (dev, json.dumps(data, ensure_ascii=False), now),
                )

    def reset_baseline(self, device_id: str | None) -> None:
        with self._lock, self._db:
            if device_id:
                self._db.execute("DELETE FROM baselines WHERE device_id=?", (device_id,))
            else:
                self._db.execute("DELETE FROM baselines")

    # ------------------------------------------------------------- 이벤트
    def add_events(self, events: list[tuple]) -> None:
        if not events:
            return
        with self._lock, self._db:
            self._db.executemany("INSERT INTO events(ts, run_id, device_id, level, kind, text) VALUES (?,?,?,?,?,?)", events)

    def list_events(self, limit: int = 100) -> list[dict]:
        rows = self._q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    # ------------------------------------------------------------- VRRP 변경 이력
    def add_vrrp(self, rows: list[dict]) -> int:
        """rows: device_id, device_name, grp, old, new, log_time, log_ts, detected, prev_check, run_id, source, text.
        같은 장비 로그(text)가 이미 있으면 다시 넣지 않습니다."""
        n = 0
        with self._lock, self._db:
            for r in rows:
                if r.get("text"):
                    dup = self._db.execute("SELECT 1 FROM vrrp_history WHERE device_id=? AND text=? LIMIT 1",
                                           (r["device_id"], r["text"])).fetchone()
                    if dup:
                        continue
                self._db.execute(
                    "INSERT INTO vrrp_history(device_id, device_name, grp, old, new, log_time, log_ts, detected, prev_check,"
                    " run_id, source, text, acked) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                    (r["device_id"], r.get("device_name", ""), r.get("grp", ""), r.get("old", ""), r.get("new", ""),
                     r.get("log_time", ""), r.get("log_ts"), r.get("detected"), r.get("prev_check"), r.get("run_id"),
                     r.get("source", ""), r.get("text", "")))
                n += 1
        return n

    def list_vrrp(self, limit: int = 300) -> list[dict]:
        rows = self._q("SELECT * FROM vrrp_history ORDER BY COALESCE(log_ts, detected) DESC, id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def vrrp_unacked(self) -> int:
        return int(self._q("SELECT COUNT(*) AS n FROM vrrp_history WHERE acked IS NULL")[0]["n"])

    def ack_vrrp(self, device_id: str | None = None) -> list[str]:
        """미확인 VRRP 변경을 확인 처리하고, 해당 백본의 VRRP 기준값만 지웁니다
        (다음 점검 때 그때의 역할이 새 기준이 되어 '역할 변화' 표시가 사라짐). 처리한 장비 id 목록."""
        now = time.time()
        with self._lock, self._db:
            if device_id:
                devs = [device_id]
            else:
                devs = [r[0] for r in self._db.execute("SELECT DISTINCT device_id FROM vrrp_history WHERE acked IS NULL")]
                devs += [r[0] for r in self._db.execute("SELECT device_id FROM baselines")]
            devs = sorted(set(devs))
            for dev in devs:
                self._db.execute("UPDATE vrrp_history SET acked=? WHERE device_id=? AND acked IS NULL", (now, dev))
                row = self._db.execute("SELECT data FROM baselines WHERE device_id=?", (dev,)).fetchone()
                if row:
                    data = json.loads(row[0])
                    if "vrrp" in data:
                        data.pop("vrrp")
                        self._db.execute("UPDATE baselines SET data=?, updated=? WHERE device_id=?",
                                         (json.dumps(data, ensure_ascii=False), now, dev))
        return devs

    # ------------------------------------------------------------- 보관 기간
    def prune(self, days: int) -> None:
        cutoff = time.time() - days * 86400
        with self._lock, self._db:
            old = [r[0] for r in self._db.execute("SELECT id FROM runs WHERE started<?", (cutoff,)).fetchall()]
            for rid in old:
                for t in ("raw_outputs", "device_results"):
                    self._db.execute(f"DELETE FROM {t} WHERE run_id=?", (rid,))
                self._db.execute("DELETE FROM runs WHERE id=?", (rid,))
            self._db.execute("DELETE FROM events WHERE ts<?", (cutoff,))
            self._db.execute("DELETE FROM vrrp_history WHERE COALESCE(log_ts, detected)<? AND acked IS NOT NULL", (cutoff,))
