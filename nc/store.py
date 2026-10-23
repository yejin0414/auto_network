"""SQLite 이력 저장소: 점검 회차, 장비별 결과, 원본 출력(압축), 기준값, 이벤트."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import tempfile
import threading
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .report_context import capture_context, normalize_context
from .file_publish import publish_new_file

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started REAL NOT NULL, finished REAL, trigger TEXT, overall TEXT, summary TEXT, report_context TEXT
);
CREATE INDEX IF NOT EXISTS ix_runs_started ON runs(started);
CREATE TABLE IF NOT EXISTS device_results (
  run_id INTEGER NOT NULL, device_id TEXT NOT NULL, status TEXT, cpu REAL, mem REAL, data TEXT,
  PRIMARY KEY (run_id, device_id)
);
CREATE INDEX IF NOT EXISTS ix_dr_device ON device_results(device_id, run_id);
CREATE INDEX IF NOT EXISTS ix_dr_uptime ON device_results(device_id, run_id DESC)
  WHERE json_extract(data,'$.metrics.uptime') IS NOT NULL;
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
CREATE INDEX IF NOT EXISTS ix_vrrp_order ON vrrp_history(COALESCE(log_ts, detected) DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_vrrp_text ON vrrp_history(device_id, text);
CREATE INDEX IF NOT EXISTS ix_vrrp_unacked ON vrrp_history(acked, device_id) WHERE acked IS NULL;
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, run_id INTEGER, device_id TEXT,
  level TEXT, kind TEXT, text TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS inventory_state (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL, devices TEXT
);
"""

_INIT_TIMEOUT = 30.0
_INIT_RETRY_DELAY = 0.05
_REQUIRED_COLUMNS = {
    "runs": {"id", "started", "finished", "trigger", "overall", "summary"},
    "device_results": {"run_id", "device_id", "status", "cpu", "mem", "data"},
    "raw_outputs": {"run_id", "device_id", "cmd_id", "label", "command", "ok", "error", "duration", "output"},
    "baselines": {"device_id", "data", "updated"},
    "events": {"id", "ts", "run_id", "device_id", "level", "kind", "text"},
    "vrrp_history": {"id", "device_id", "device_name", "grp", "old", "new", "log_time", "log_ts", "detected",
                     "prev_check", "run_id", "source", "text", "acked"},
}
log = logging.getLogger("netcheck")


def _wal_safe_version(version: tuple[int, ...]) -> bool:
    """SQLite releases containing the WAL-reset corruption fix or its backport.

    https://www.sqlite.org/wal.html#the_wal_reset_bug
    Unknown/unpatched older branches use the rollback journal instead.
    """
    return (version >= (3, 51, 3)
            or version[:2] == (3, 50) and version >= (3, 50, 7)
            or version[:2] == (3, 44) and version >= (3, 44, 6))


def _deadline(timeout: float) -> float:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("백업 제한 시간은 양수여야 합니다.")
    return time.monotonic() + timeout


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("SQLite 백업/검증 제한 시간을 초과했습니다.")
    return remaining


def _validate_connection(db: sqlite3.Connection, deadline: float) -> None:
    def query(sql):
        # SQLite's busy timeout is per statement. Recompute the remaining
        # allowance so several schema reads share one validation deadline.
        db.execute(f"PRAGMA busy_timeout={int(_remaining(deadline) * 1000)}")
        return db.execute(sql).fetchall()

    db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    try:
        checks = query("PRAGMA quick_check")
        if len(checks) != 1 or checks[0][0] != "ok":
            raise sqlite3.DatabaseError("SQLite 무결성 검사를 통과하지 못했습니다.")
        tables = {r[0] for r in query("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, required in _REQUIRED_COLUMNS.items():
            _remaining(deadline)
            columns = {r[1] for r in query(f"PRAGMA table_info({table})")}
            if table not in tables or not required.issubset(columns):
                raise sqlite3.DatabaseError(f"Netcheck 데이터베이스 필수 스키마가 없습니다: {table}")
        _remaining(deadline)
    except sqlite3.OperationalError:
        _remaining(deadline)
        raise
    finally:
        db.set_progress_handler(None, 0)


def validate_database(path: Path, *, timeout: float = 30.0) -> None:
    """Read-only quick_check plus core application schema, including legacy DBs."""
    deadline = _deadline(timeout)
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=_remaining(deadline))
    try:
        db.execute("PRAGMA query_only=ON")
        _validate_connection(db, deadline)
    finally:
        db.close()


class Store:
    def __init__(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path.resolve()
        self._lock = threading.Lock()
        self._backup_lock = threading.Lock()
        # Startup retries have one deadline, rather than a fresh SQLite timeout
        # for every statement. Normal operations regain their 30-second timeout.
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=0)
        try:
            self._db.row_factory = sqlite3.Row
            self._initialize()
            self._db.execute("PRAGMA busy_timeout=30000")
        except BaseException:
            # close() also rolls back any unfinished migration. Failed startup
            # must not leave a Windows file handle alive in the traceback.
            self._db.close()
            raise

    def _initialize(self) -> None:
        deadline = time.monotonic() + _INIT_TIMEOUT
        journal_mode = "WAL" if _wal_safe_version(sqlite3.sqlite_version_info) else "DELETE"
        while True:
            try:
                # Change modes before any transaction or schema writes. A busy
                # WAL-to-DELETE transition must fail startup, never leave this
                # runtime operating in the affected WAL mode.
                selected = self._db.execute(f"PRAGMA journal_mode={journal_mode}").fetchone()
                effective = self._db.execute("PRAGMA journal_mode").fetchone()
                if (not selected or str(selected[0]).upper() != journal_mode
                        or not effective or str(effective[0]).upper() != journal_mode):
                    raise sqlite3.OperationalError(f"SQLite 저널 모드 {journal_mode} 전환을 확인하지 못했습니다.")
                self._db.execute("BEGIN IMMEDIATE")
                # executescript() would implicitly commit BEGIN IMMEDIATE.
                # Keep all DDL, the schema check and ALTER in one transaction.
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        self._db.execute(statement)
                columns = {row["name"] for row in self._db.execute("PRAGMA table_info(runs)")}
                if "report_context" not in columns:
                    self._db.execute("ALTER TABLE runs ADD COLUMN report_context TEXT")
                self._db.commit()
                return
            except sqlite3.OperationalError as exc:
                self._db.rollback()
                code = getattr(exc, "sqlite_errorcode", 0) & 0xff
                remaining = deadline - time.monotonic()
                if code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or remaining <= 0:
                    raise
                time.sleep(min(_INIT_RETRY_DELAY, remaining))

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # ------------------------------------------------------------- 회차
    def save_run(self, started: float, finished: float, trigger: str, evaluation: dict,
                 collections: dict, clusters: dict | None, *, report_config: dict | None = None) -> int:
        with self._lock, self._db:
            return self._save_run(started, finished, trigger, evaluation, collections, clusters, report_config=report_config)

    def commit_run(self, started: float, finished: float, trigger: str, evaluation: dict,
                   collections: dict, clusters: dict | None, *, report_config: dict | None = None,
                   baseline_updates: dict | None = None, events_factory=None, vrrp_factory=None,
                   expected_revision: int | None = None) -> int:
        """Persist a complete run atomically; factories must not re-enter Store.

        Inventory/reset changes do not erase a valid historical observation, but
        an older run must not recreate baselines after those changes.
        """
        with self._lock, self._db:
            run_id = self._save_run(started, finished, trigger, evaluation, collections, clusters, report_config=report_config)
            if expected_revision is None or expected_revision == self._revision():
                self._save_baselines(baseline_updates or {})
            if events_factory is not None:
                self._add_events(events_factory(run_id))
            if vrrp_factory is not None:
                self._add_vrrp(vrrp_factory(run_id))
        return run_id

    def _save_run(self, started: float, finished: float, trigger: str, evaluation: dict,
                 collections: dict, clusters: dict | None, *, report_config: dict | None = None) -> int:
        summary = evaluation["summary"]
        context = (json.dumps(capture_context(report_config), ensure_ascii=False, allow_nan=False)
                   if report_config is not None else None)
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
        run, _ = self._read_run_snapshot(run_id, include_output=False)
        return run

    def get_report_snapshot(self, run_id: int | None = None) -> tuple[dict | None, Callable[[str, str], dict | None]]:
        run, rows = self._read_run_snapshot(run_id, include_output=True)
        raw = {(r["device_id"], r["cmd_id"]): r for r in rows}

        def lookup(device_id: str, cmd_id: str) -> dict | None:
            row = raw.get((device_id, cmd_id))
            return self._decode_raw(row) if row is not None else None

        return run, lookup

    def _read_run_snapshot(self, run_id: int | None, *, include_output: bool) -> tuple[dict | None, list[sqlite3.Row]]:
        # Capture only one run. JSON conversion, decompression and report writing
        # happen after releasing both the SQLite snapshot and the shared lock.
        with self._lock:
            outer_transaction = self._db.in_transaction
            self._db.execute("SAVEPOINT nc_run_snapshot")
            try:
                rows = (self._db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchall() if run_id
                        else self._db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchall())
                devs, raw = [], []
                if rows:
                    rid = rows[0]["id"]
                    devs = self._db.execute("SELECT device_id, data FROM device_results WHERE run_id=?", (rid,)).fetchall()
                    columns = "device_id, cmd_id, label, command, ok, error, duration"
                    if include_output:
                        columns += ", output"
                    raw = self._db.execute(f"SELECT {columns} FROM raw_outputs WHERE run_id=? ORDER BY rowid", (rid,)).fetchall()
                self._db.execute("RELEASE nc_run_snapshot")
            except BaseException:
                # SQLite may already have rolled back on an I/O/interrupt error.
                # Preserve that error and never roll back a caller's transaction.
                try:
                    self._db.execute("RELEASE nc_run_snapshot")
                except sqlite3.Error:
                    if not outer_transaction:
                        try:
                            self._db.rollback()
                        except sqlite3.Error:
                            pass
                raise
        if not rows:
            return None, []
        r = rows[0]
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
                "report_context": context}, raw

    def get_raw(self, run_id: int, device_id: str, cmd_id: str) -> dict | None:
        rows = self._q("SELECT * FROM raw_outputs WHERE run_id=? AND device_id=? AND cmd_id=?", (run_id, device_id, cmd_id))
        if not rows:
            return None
        return self._decode_raw(rows[0])

    @staticmethod
    def _decode_raw(r: sqlite3.Row) -> dict:
        return {"command": r["command"], "label": r["label"], "ok": bool(r["ok"]), "error": r["error"],
                "duration": r["duration"], "output": zlib.decompress(r["output"]).decode("utf-8", "replace")}

    def previous_metrics(self) -> dict[str, dict]:
        """장비별 가장 최근 회차의 지표(재부팅 감지용)."""
        rows = self._q(
            # Iterate devices with an uptime sample once, then seek their newest
            # non-null sample. The partial index excludes failed/empty samples.
            "SELECT dr.device_id, dr.data, r.started FROM "
            "(SELECT DISTINCT device_id FROM device_results "
            "WHERE json_extract(data,'$.metrics.uptime') IS NOT NULL) d "
            "JOIN device_results dr ON dr.device_id=d.device_id AND dr.run_id="
            "(SELECT MAX(x.run_id) FROM device_results x WHERE x.device_id=d.device_id "
            "AND json_extract(x.data,'$.metrics.uptime') IS NOT NULL) "
            "JOIN runs r ON r.id=dr.run_id"
        )
        out = {}
        for r in rows:
            data = json.loads(r["data"])
            m = data.get("metrics", {})
            out[r["device_id"]] = {"uptime": m.get("uptime"), "ts": r["started"],
                                    "baseline_epoch": data.get("baseline_epoch")}
        return out

    def trend(self, device_id: str, since: float) -> list[dict]:
        rows = self._q(
            # Select the requested time window before reading device history.
            "SELECT r.started, dr.status, dr.cpu, dr.mem FROM runs r INDEXED BY ix_runs_started "
            "JOIN device_results dr ON r.id=dr.run_id "
            "WHERE dr.device_id=? AND r.started>=? ORDER BY r.id", (device_id, since))
        return [{"t": r["started"], "status": r["status"], "cpu": r["cpu"], "mem": r["mem"]} for r in rows]

    def trends_all(self, since: float) -> dict[str, list]:
        rows = self._q(
            "SELECT dr.device_id, r.id, r.started, dr.status, dr.cpu, dr.mem "
            "FROM runs r INDEXED BY ix_runs_started JOIN device_results dr ON r.id=dr.run_id "
            "WHERE r.started>=? ORDER BY r.id", (since,))
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
        with self._lock, self._db:
            self._save_baselines(updates)

    def _save_baselines(self, updates: dict[str, dict]) -> None:
        now = time.time()
        for dev, data in updates.items():
            self._db.execute(
                "INSERT INTO baselines VALUES (?,?,?) ON CONFLICT(device_id) DO UPDATE SET data=excluded.data",
                (dev, json.dumps(data, ensure_ascii=False), now),
            )

    def _revision(self) -> int:
        row = self._db.execute("SELECT revision FROM inventory_state WHERE singleton=1").fetchone()
        return int(row[0]) if row else 0

    def inventory_revision(self) -> int:
        with self._lock:
            return self._revision()

    def _bump_revision(self) -> int:
        self._db.execute("INSERT INTO inventory_state(singleton,revision,devices) VALUES(1,1,NULL) "
                         "ON CONFLICT(singleton) DO UPDATE SET revision=inventory_state.revision+1")
        return self._revision()

    @staticmethod
    def _inventory(cfg: dict) -> dict:
        from .config import device_identities

        epochs = cfg.get("_baseline_epochs") or {}
        keys = ("host", "role", "port", "protocol", "device_type", "cluster")
        return {did: {**dict(zip(keys, identity)), "epoch": epochs.get(did)}
                for did, identity in device_identities(cfg).items()}

    def sync_inventory(self, cfg: dict) -> int:
        """Reconcile only baseline metadata; historical observations are retained."""
        current = self._inventory(cfg)
        with self._lock, self._db:
            # Serialize the read/compare/write across independent app processes.
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute("SELECT revision,devices FROM inventory_state WHERE singleton=1").fetchone()
            previous = json.loads(row["devices"]) if row and row["devices"] is not None else None
            revision = int(row["revision"]) if row else 0
            changed = set()
            if previous is not None:
                for did, old in previous.items():
                    new = current.get(did)
                    # A first legacy-to-epoch migration is not evidence that a
                    # still-present device was replaced. Later epoch changes are.
                    if new is None or any(old.get(key) != new.get(key) for key in old if key != "epoch") or (
                            old.get("epoch") is not None and old.get("epoch") != new.get("epoch")):
                        changed.add(did)
            existing = {r[0] for r in self._db.execute("SELECT device_id FROM baselines")}
            remove = (existing - set(current) - {"__cluster__"}) | changed
            baseline_changed = bool(remove)
            for did in remove:
                self._db.execute("DELETE FROM baselines WHERE device_id=?", (did,))

            cluster = self._db.execute("SELECT data FROM baselines WHERE device_id='__cluster__'").fetchone()
            if cluster:
                data = json.loads(cluster[0])
                hosts = {d["host"] for did, d in current.items() if d["role"] == "WLC" and did not in changed}
                # A changed/deleted device must not leave its IP-keyed state
                # behind, even if another inventory entry now reuses that IP.
                invalid_hosts = {d["host"] for did, d in (previous or {}).items() if did in changed and d["role"] == "WLC"}
                kept = {host: state for host, state in data.get("conn_type", {}).items() if host in hosts - invalid_hosts}
                if kept:
                    if kept != data.get("conn_type", {}):
                        baseline_changed = True
                        data["conn_type"] = kept
                        self._db.execute("UPDATE baselines SET data=? WHERE device_id='__cluster__'", (json.dumps(data, ensure_ascii=False),))
                else:
                    baseline_changed = True
                    self._db.execute("DELETE FROM baselines WHERE device_id='__cluster__'")
            if previous != current or baseline_changed:
                revision += 1
            self._db.execute("INSERT INTO inventory_state VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE "
                             "SET revision=excluded.revision,devices=excluded.devices",
                             (revision, json.dumps(current, ensure_ascii=False, sort_keys=True)))
        return revision

    def reset_baseline(self, device_id: str | None) -> None:
        with self._lock, self._db:
            if device_id:
                self._db.execute("DELETE FROM baselines WHERE device_id=?", (device_id,))
            else:
                self._db.execute("DELETE FROM baselines")
            self._bump_revision()

    # ------------------------------------------------------------- 이벤트
    def add_events(self, events: list[tuple]) -> None:
        if not events:
            return
        with self._lock, self._db:
            self._add_events(events)

    def _add_events(self, events: list[tuple]) -> None:
        self._db.executemany("INSERT INTO events(ts, run_id, device_id, level, kind, text) VALUES (?,?,?,?,?,?)", events)

    def list_events(self, limit: int = 100) -> list[dict]:
        rows = self._q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    # ------------------------------------------------------------- VRRP 변경 이력
    def add_vrrp(self, rows: list[dict]) -> int:
        with self._lock, self._db:
            return self._add_vrrp(rows)

    def _add_vrrp(self, rows: list[dict]) -> int:
        """rows: device_id, device_name, grp, old, new, log_time, log_ts, detected, prev_check, run_id, source, text.
        같은 장비 로그(text)가 이미 있으면 다시 넣지 않습니다."""
        n = 0
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
            self._bump_revision()
        return devs

    # ------------------------------------------------------------- 온라인 백업
    @property
    def backup_directory(self) -> Path:
        return self.path.parent / "backups"

    def _managed_backups(self) -> list[Path]:
        pattern = re.compile(re.escape(self.path.stem) + r"-backup-\d{8}T\d{12}Z-[0-9a-f]{32}\.sqlite3$")
        if not self.backup_directory.exists():
            return []
        return sorted((p for p in self.backup_directory.iterdir()
                       if not p.is_symlink() and p.is_file() and pattern.fullmatch(p.name)),
                      key=lambda p: p.name, reverse=True)

    def backup(self, destination: Path | None = None, *, timeout: float = 30.0, keep: int = 7) -> Path:
        """Publish a verified online backup without overwriting any target."""
        deadline = _deadline(timeout)
        if not self._backup_lock.acquire(timeout=_remaining(deadline)):
            raise TimeoutError("SQLite 백업 작업 대기 시간을 초과했습니다.")
        try:
            return self._backup(destination, deadline, keep)
        finally:
            self._backup_lock.release()

    def backup_if_due(self, *, timeout: float = 30.0, keep: int = 7) -> Path:
        """Reuse a verified managed backup from the last 24h, or create one."""
        deadline = _deadline(timeout)
        if not self._backup_lock.acquire(timeout=_remaining(deadline)):
            raise TimeoutError("SQLite 백업 작업 대기 시간을 초과했습니다.")
        try:
            now = time.time()
            for path in self._managed_backups():
                _remaining(deadline)
                if not 0 <= now - path.stat().st_mtime < 86400:
                    continue
                try:
                    validate_database(path, timeout=_remaining(deadline))
                except (sqlite3.Error, OSError):
                    continue
                return path
            return self._backup(None, deadline, keep)
        finally:
            self._backup_lock.release()

    def _backup(self, destination: Path | None, deadline: float, keep: int) -> Path:
        if isinstance(keep, bool) or not isinstance(keep, int) or keep < 1:
            raise ValueError("관리 백업 보관 개수는 1 이상이어야 합니다.")
        managed = destination is None
        if managed:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            destination = self.backup_directory / f"{self.path.stem}-backup-{stamp}-{uuid4().hex}.sqlite3"
        destination = Path(destination).absolute()
        forbidden = {self.path, *(Path(str(self.path) + suffix) for suffix in ("-wal", "-shm", "-journal"))}
        if destination.resolve() in forbidden or str(destination).lower().endswith(("-wal", "-shm", "-journal")) or any(
                os.path.lexists(str(destination) + suffix) for suffix in ("", "-wal", "-shm", "-journal")):
            raise FileExistsError("기존 파일이나 사용 중인 데이터베이스에 백업을 덮어쓸 수 없습니다.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        _remaining(deadline)
        fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        os.close(fd)
        temporary = Path(name)
        source = target = None
        try:
            if not self._lock.acquire(timeout=_remaining(deadline)):
                raise TimeoutError("SQLite 저장 작업 대기 시간을 초과했습니다.")
            try:
                if self._db.in_transaction:
                    raise ValueError("완료되지 않은 SQLite 트랜잭션 중에는 백업할 수 없습니다.")
            finally:
                self._lock.release()
            # A separate read-only connection lets SQLite's online backup API
            # release source locks between steps. Do not monopolize the shared
            # application connection during copying or destination validation.
            source = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=0)
            source.execute("PRAGMA query_only=ON")
            target = sqlite3.connect(str(temporary), timeout=0)

            def progress(_status, _remaining_pages, _total_pages):
                _remaining(deadline)

            source.backup(target, pages=128, progress=progress, sleep=0.05)
            source.close()
            source = None
            _remaining(deadline)
            target.execute("PRAGMA journal_mode=DELETE").fetchall()
            _validate_connection(target, deadline)
            target.close()
            target = None
            with temporary.open("r+b") as handle:
                os.fsync(handle.fileno())
            _remaining(deadline)
            if any(os.path.lexists(str(destination) + suffix) for suffix in ("-wal", "-shm", "-journal")):
                raise FileExistsError("백업 대상에 SQLite 보조 파일이 생겨 확정하지 않았습니다.")
            publish_new_file(temporary, destination)
        finally:
            if source is not None:
                try:
                    source.close()
                except sqlite3.Error as exc:
                    log.warning("백업 원본 읽기 연결 정리 실패: %s", exc)
            if target is not None:
                try:
                    target.close()
                except sqlite3.Error as exc:
                    log.warning("임시 백업 연결 정리 실패: %s", exc)
            for suffix in ("", "-wal", "-shm", "-journal"):
                try:
                    Path(str(temporary) + suffix).unlink(missing_ok=True)
                except OSError as exc:
                    log.warning("임시 백업 파일 정리 실패(%s): %s", temporary.name + suffix, exc)
        if managed:
            # The just-published backup survives even if the wall clock moved
            # backwards relative to older filenames.
            older = [p for p in self._managed_backups() if p != destination]
            for old in older[keep - 1:]:
                try:
                    old.unlink()
                except OSError as exc:
                    log.warning("이전 관리 백업 정리 실패(%s): %s", old.name, exc)
        return destination

    # ------------------------------------------------------------- 보관 기간
    def prune(self, days: int) -> None:
        cutoff = time.time() - days * 86400
        with self._lock, self._db:
            # Keep one transaction and a fixed number of statements regardless
            # of the number of expired runs; retain runs until both child deletes.
            for table in ("raw_outputs", "device_results"):
                self._db.execute(f"DELETE FROM {table} WHERE run_id IN (SELECT id FROM runs WHERE started<?)", (cutoff,))
            self._db.execute("DELETE FROM runs WHERE started<?", (cutoff,))
            self._db.execute("DELETE FROM events WHERE ts<?", (cutoff,))
            self._db.execute("DELETE FROM vrrp_history WHERE COALESCE(log_ts, detected)<? AND acked IS NOT NULL", (cutoff,))
