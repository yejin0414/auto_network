"""Opt-in synthetic scale/portable-recovery check, never an equipment check.

Run directly (not unittest discovery):
  python tests/db_scale_check.py --output scale.json --min-db-bytes 1073741824
Use --runs 100 --devices 20 for a small development smoke check. Every database
is temporary; only the requested JSON evidence survives. No network, scheduler,
credential backend, GUI, USB drive or NAS is exercised.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nc.backup_transfer import export_backup, restore_backup, verify_backup_package
from nc.collector import CmdResult, DeviceCollection
from nc.credentials import CredentialStore
from nc.report import render
from nc.report_context import capture_context
from nc.server import App
from nc.store import Store
from tests.synthetic_db import BASE, INTERVAL, POOL_SIZE, configuration, evaluation, fingerprint, require, seed_database

GIB = 1024 ** 3
CHUNK = 1024 ** 2
QUERY_BUDGET = 45.0


def peak_rss_bytes():
    """Process lifetime peak resident memory; unavailable is null, never zero."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            return int(counters.PeakWorkingSetSize)
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)
    except (ImportError, OSError, AttributeError):
        return None


def hash_file(path, timeout):
    digest, size, deadline = hashlib.sha256(), 0, time.monotonic() + timeout
    with Path(path).open("rb") as source:
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("File hashing exceeded its phase deadline")
            chunk = source.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "bytes": size}


def transfer_file(source, destination, timeout):
    """A real bounded byte copy to an isolated directory, not a link/clone."""
    digest, size, deadline = hashlib.sha256(), 0, time.monotonic() + timeout
    destination.parent.mkdir(parents=True)
    with source.open("rb") as input_file, destination.open("xb") as output:
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("Isolated external-copy simulation exceeded its phase deadline")
            chunk = input_file.read(CHUNK)
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        output.flush()
        os.fsync(output.fileno())
    require(not os.path.samefile(source, destination), "External copy must have independent file identity")
    return {"sha256": digest.hexdigest(), "bytes": size}


class Evidence:
    def __init__(self, args):
        self.args = args
        self.data = {"status": "RUNNING", "runtime": {"python": platform.python_version(),
                     "sqlite": sqlite3.sqlite_version, "platform": platform.platform()},
                     "profile": {"runs": args.runs, "devices": args.devices, "raw_bytes": args.raw_bytes,
                                 "minimum_database_bytes": args.min_db_bytes, "phase_timeout_seconds": args.timeout},
                     "phases": [], "limitations": ["Synthetic data; no actual network equipment or credentials",
                     "External transfer is a byte copy between isolated local directories, not USB/NAS/cloud",
                     "API handlers and HTML output are checked without a browser or HTTP listener",
                     "Peak RSS is process lifetime residency, not a proof of memory bounds on every input",
                     "SHA-256 detects transfer changes; it does not authenticate a backup publisher"]}

    def phase(self, name, operation, *, budget=None, db=None):
        budget = self.args.timeout if budget is None else min(budget, self.args.timeout)
        print(f"SCALE phase={name} start", flush=True)
        entry = {"name": name, "budget_seconds": budget, "status": "RUNNING"}
        self.data["phases"].append(entry)
        started = time.monotonic()
        if db is not None:
            db.set_progress_handler(lambda: int(time.monotonic() - started >= budget), 10000)
        try:
            value = operation()
            require(time.monotonic() - started <= budget, f"Phase {name} exceeded {budget:g}s budget")
            entry["status"] = "PASS"
            return value
        except Exception:
            entry["status"] = "FAIL"
            raise
        finally:
            if db is not None:
                db.set_progress_handler(None, 0)
            entry["elapsed_seconds"] = time.monotonic() - started
            entry["peak_rss_bytes"] = peak_rss_bytes()
            print(f"SCALE phase={name} status={entry['status']} seconds={entry['elapsed_seconds']:.3f}", flush=True)


def probe(store, cfg, runs, outputs, evidence, prefix, *, atomic_added=False):
    """Exercise public query/report/API paths and check known synthetic values."""
    devices = cfg["devices"]
    latest_ts = BASE + runs * INTERVAL
    expected_logs = ((runs - int(atomic_added)) * len(devices)) // 10 + int(atomic_added)
    expected_unacked = (((runs - int(atomic_added)) * len(devices) // 10 + 1) // 2 + int(atomic_added))

    def query(name, operation):
        return evidence.phase(prefix + "." + name, operation, budget=QUERY_BUDGET, db=store._db)

    def latest():
        result = store.get_run()
        require(result["id"] == runs and len(result["devices"]) == len(devices), "Latest run/device count differs")
        require(result["report_context"] == capture_context(cfg), "Saved report context differs")
        listed = store.list_runs(72)
        require([x["id"] for x in listed] == list(range(runs, max(0, runs - 72), -1)), "Run order/limit differs")
        return result

    run = query("latest_run", latest)

    def previous():
        result = store.previous_metrics()
        require(set(result) == {d["id"] for d in devices}, "Previous metrics lost devices")
        for i, device in enumerate(devices):
            rid = runs - int(runs % 17 == 0 and i % 3 == 0)
            require(result[device["id"]] == {"uptime": rid * INTERVAL + i, "ts": BASE + rid * INTERVAL,
                    "baseline_epoch": cfg["_baseline_epochs"][device["id"]]}, "Previous metrics value/epoch differs")

    query("previous_metrics", previous)

    for days in (1, 7):
        def trends(days=days):
            result = store.trends_all(latest_ts - days * 86400)
            count = min(runs, days * 86400 // INTERVAL + 1)
            require(set(result) == {d["id"] for d in devices}, "Trend devices differ")
            for i, device in enumerate(devices):
                rows = result[device["id"]]
                require(len(rows) == count, "Trend window count differs")
                require(rows[-1]["run"] == runs and rows[0]["run"] == runs - count + 1, "Trend ordering differs")
                require(rows[-1]["cpu"] == 10 + (runs + i) % 30, "Trend CPU differs")
            one = store.trend(devices[0]["id"], latest_ts - days * 86400)
            require(len(one) == count and one[-1]["t"] == latest_ts, "Single-device trend differs")
        query(f"trends_{days}d", trends)

    def vrrp():
        rows = store.list_vrrp(300)
        require(len(rows) == min(300, expected_logs), "VRRP list count differs")
        require(store.vrrp_unacked() == expected_unacked, "VRRP unacknowledged count differs")
        require([r["id"] for r in rows] == sorted([r["id"] for r in rows], reverse=True), "VRRP order differs")
        if rows:
            require(store.add_vrrp([rows[0]]) == 0, "VRRP duplicate was inserted")
        require(len(store.list_events(60)) == min(60, expected_logs), "Event count/limit differs")
    query("vrrp_events_dedup", vrrp)

    def samples():
        for rid in sorted({1, max(1, runs // 2), runs}):
            for i in sorted({0, len(devices) // 2, len(devices) - 1}):
                raw = store.get_raw(rid, devices[i]["id"], "synthetic")
                expected = outputs[((rid - 1) * len(devices) + i) % POOL_SIZE]
                require(raw is not None and raw["ok"] and raw["output"] == expected, "Raw-output sample differs")
        html = render(run, "Current configuration must not replace historical site")
        require(cfg["site_name"] in html and "Current configuration must not" not in html,
                "Historical HTML report context differs")
    query("raw_samples_report", samples)

    def api():
        engine = SimpleNamespace(cfg=SimpleNamespace(get=lambda: copy.deepcopy(cfg)), store=store,
                                 creds=CredentialStore(persistent=False), persistence_lock=threading.RLock(),
                                 report_folder=lambda _cfg: store.path.parent, last_report="", last_error="",
                                 status=lambda: {"running": False, "demo": True})
        app = App(engine, Path(__file__).resolve().parents[1] / "web")
        code, state = app.handle_get("/api/state", {})
        require(code == 200 and not state["storage_error"] and state["latest_run_id"] == runs,
                "State API returned inconsistent storage state")
        require(state["vrrp_unacked"] == expected_unacked, "State API unacknowledged count differs")
        code, result = app.handle_get("/api/run", {})
        require(code == 200 and result["report_context"] == capture_context(cfg), "Run API lost report context")
        with patch("nc.server.time.time", return_value=latest_ts):
            code, result = app.handle_get("/api/trends", {"hours": "24"})
        require(code == 200 and len(result[devices[0]["id"]]) == min(runs, 289), "Trend API differs")
        code, result = app.handle_get("/api/vrrp", {})
        require(code == 200 and result["unacked"] == expected_unacked, "VRRP API differs")
    query("ui_api_handlers", api)


def atomic_write(store, cfg, runs, outputs):
    run_id, ts, devices = runs + 1, BASE + (runs + 1) * INTERVAL, cfg["devices"]
    collections = {d["id"]: DeviceCollection(d["id"], True, results={"synthetic": CmdResult(
        "synthetic", "Synthetic output", "display synthetic", outputs[(runs * len(devices) + i) % POOL_SIZE], True)})
        for i, d in enumerate(devices)}
    result = store.commit_run(ts, ts + 40, "synthetic-atomic", evaluation(cfg, run_id), collections, {},
                             report_config=cfg, baseline_updates={d["id"]: {"slots": ["1"]} for d in devices},
                             expected_revision=store.inventory_revision(),
                             events_factory=lambda rid: [(ts, rid, devices[0]["id"], "warn", "new", "Atomic synthetic event")],
                             vrrp_factory=lambda rid: [{"device_id": devices[0]["id"], "device_name": devices[0]["name"],
                                 "log_ts": ts, "detected": ts, "run_id": rid, "source": "synthetic",
                                 "text": "Atomic synthetic VRRP event"}])
    require(result == run_id, "Atomic run ID differs")
    require(store._db.execute("SELECT count(*) FROM events WHERE run_id=?", (result,)).fetchone()[0] == 1,
            "Atomic event was not committed")
    require(store._db.execute("SELECT count(*) FROM raw_outputs WHERE run_id=?", (result,)).fetchone()[0] == len(devices),
            "Atomic raw outputs were not committed")
    return result


def readonly_fingerprint(path, timeout):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        return fingerprint(db, timeout=timeout)


def unacked_fingerprint(db):
    digest, count = hashlib.sha256(), 0
    cursor = db.execute("SELECT * FROM vrrp_history WHERE acked IS NULL ORDER BY id")
    try:
        for row in cursor:
            digest.update(json.dumps(tuple(row), separators=(",", ":"), ensure_ascii=False).encode())
            digest.update(b"\n")
            count += 1
    finally:
        cursor.close()
    return {"rows": count, "sha256": digest.hexdigest()}


def prune_check(store, runs, devices):
    now, days = BASE + runs * INTERVAL, 30
    cutoff = now - days * 86400
    db = store._db
    old_runs = db.execute("SELECT count(*) FROM runs WHERE started<?", (cutoff,)).fetchone()[0]
    unacked = unacked_fingerprint(db)
    with patch("nc.store.time.time", return_value=now):
        store.prune(days)
    remaining = db.execute("SELECT count(*) FROM runs").fetchone()[0]
    require(remaining == runs - old_runs, "Prune removed an incorrect number of runs")
    for table in ("device_results", "raw_outputs"):
        require(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == remaining * devices,
                f"Prune orphan/count mismatch: {table}")
    require(db.execute("SELECT count(*) FROM events WHERE ts<?", (cutoff,)).fetchone()[0] == 0, "Expired events survived")
    require(db.execute("SELECT count(*) FROM vrrp_history WHERE COALESCE(log_ts,detected)<? AND acked IS NOT NULL",
                       (cutoff,)).fetchone()[0] == 0, "Expired acknowledged VRRP survived")
    require(unacked_fingerprint(db) == unacked, "Prune changed unacknowledged VRRP records")
    require(db.execute("SELECT count(*) FROM baselines").fetchone()[0] == devices, "Prune changed baselines")
    return {"retention_days": days, "deleted_runs": old_runs, "remaining_runs": remaining,
            "unacknowledged_preserved": unacked, "freelist_pages_after": db.execute("PRAGMA freelist_count").fetchone()[0],
            "note": "SQLite reuses freed pages; pruning does not promise a smaller filesystem file"}


def execute(args, evidence):
    with tempfile.TemporaryDirectory(prefix="netcheck-scale-") as temporary:
        root = Path(temporary)
        free = shutil.disk_usage(root).free
        require(free >= 10 * GIB, "Scale check requires at least 10 GiB of temporary free space")
        evidence.data["disk_free_bytes_before"] = free
        source_dir = root / "source-app"
        source_path = source_dir / "data" / "history.sqlite3"
        source_path.parent.mkdir(parents=True)
        cfg, source, restored = configuration(args.devices), None, None
        try:
            source = Store(source_path)
            evidence.data["journal_mode"] = source._db.execute("PRAGMA journal_mode").fetchone()[0]
            fixture, outputs = evidence.phase("seed", lambda: seed_database(source, cfg, args.runs, args.raw_bytes, args.timeout))
            evidence.data["fixture"] = fixture
            for table in ("runs", "device_results", "raw_outputs", "events", "vrrp_history", "baselines"):
                actual = source._db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                require(actual == fixture[table], f"Seed row count differs: {table}")
            page_count = source._db.execute("PRAGMA page_count").fetchone()[0]
            page_size = source._db.execute("PRAGMA page_size").fetchone()[0]
            freelist = source._db.execute("PRAGMA freelist_count").fetchone()[0]
            evidence.data["fixture_storage"] = {"file_bytes": source_path.stat().st_size, "page_count": page_count,
                "page_size": page_size, "freelist_pages": freelist, "used_page_bytes": (page_count - freelist) * page_size}
            require(source_path.stat().st_size >= args.min_db_bytes and (page_count - freelist) * page_size >= args.min_db_bytes,
                    "Actual file/used-page bytes fall below the requested minimum")
            probe(source, cfg, args.runs, outputs, evidence, "source")
            final_runs = evidence.phase("atomic_run_write", lambda: atomic_write(source, cfg, args.runs, outputs),
                                        budget=QUERY_BUDGET, db=source._db)
            expected = evidence.phase("source_logical_fingerprint", lambda: fingerprint(source._db, timeout=args.timeout), db=source._db)
            evidence.data["logical_before"] = expected
            # Export temporarily holds snapshot, package and verification copies.
            require(shutil.disk_usage(root).free >= 4 * source_path.stat().st_size + 256 * CHUNK,
                    "Insufficient temporary space for bounded backup/export working copies")
            backup = evidence.phase("managed_online_backup", lambda: source.backup(timeout=min(args.timeout, 180)), budget=180)
            backup_digest = evidence.phase("backup_logical_fingerprint", lambda: readonly_fingerprint(backup, args.timeout))
            require(backup_digest == expected, "Managed online backup differs from the committed source")
            package = evidence.phase("export_package", lambda: export_backup(backup, source_dir / "export" / "history.ncbak",
                                                                               timeout=args.timeout))
            package_hash = evidence.phase("package_sha256", lambda: hash_file(package, args.timeout))
            evidence.data["package"] = package_hash
            external = root / "isolated-external" / "history.ncbak"
            copied = evidence.phase("external_byte_transfer", lambda: transfer_file(package, external, args.timeout))
            require(copied == package_hash, "External byte transfer changed the package")
            evidence.data["external_copy"] = evidence.phase("external_copy_sha256", lambda: hash_file(external, args.timeout))
            require(evidence.data["external_copy"] == package_hash, "Re-read external copy differs")
            evidence.data["manifest"] = evidence.phase("verify_external_package", lambda: verify_backup_package(external, timeout=args.timeout))
            source._db.close()
            source = None
            before_hash = evidence.phase("source_closed_sha256", lambda: hash_file(source_path, args.timeout))
            hidden_dir = root / "source-unavailable"
            source_dir.rename(hidden_dir)
            require(not source_path.exists() and not package.exists() and not backup.exists(),
                    "Original source/backup/package paths are still available")
            evidence.data["original_paths_unavailable_during_restore"] = True
            restored_path = evidence.phase("restore_external_package", lambda: restore_backup(external, root / "restored-app" / "history.sqlite3",
                                                                                                timeout=args.timeout))
            actual = evidence.phase("restored_logical_fingerprint", lambda: readonly_fingerprint(restored_path, args.timeout))
            require(actual == expected, "Restored tables/schema differ from the committed source")
            evidence.data["logical_restored"] = actual
            restored = Store(restored_path)
            probe(restored, cfg, final_runs, outputs, evidence, "restored", atomic_added=True)
            evidence.data["prune"] = evidence.phase("prune_restored", lambda: prune_check(restored, final_runs, args.devices),
                                                    budget=180, db=restored._db)
            after_hash = evidence.phase("preserved_source_sha256", lambda: hash_file(hidden_dir / "data" / "history.sqlite3", args.timeout))
            require(after_hash == before_hash, "Recovery/prune modified the preserved original database")
            evidence.data["preserved_source"] = {**after_hash, "unchanged": True}
            evidence.data["disk_free_bytes_after_checks"] = shutil.disk_usage(root).free
        finally:
            for store in (restored, source):
                if store is not None:
                    store._db.close()
    evidence.data["temporary_databases_removed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10000)
    parser.add_argument("--devices", type=int, default=100)
    parser.add_argument("--raw-bytes", type=int, default=1536)
    parser.add_argument("--min-db-bytes", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=300.0, help="Per-phase deadline in seconds")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.runs < 1 or args.devices < 1 or not 128 <= args.raw_bytes <= 65536 or args.min_db_bytes < 0
            or not math.isfinite(args.timeout) or args.timeout <= 0):
        parser.error("Positive run/device counts, 128..65536 raw bytes, nonnegative minimum size and positive timeout required")
    evidence, started = Evidence(args), time.monotonic()
    try:
        execute(args, evidence)
        evidence.data["status"] = "PASS"
    except Exception as exc:
        evidence.data["status"] = "FAIL"
        evidence.data["error"] = {"type": type(exc).__name__, "message": str(exc)}
        import traceback
        traceback.print_exc()
    finally:
        evidence.data["elapsed_seconds"] = time.monotonic() - started
        evidence.data["peak_rss_bytes"] = peak_rss_bytes()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SCALE {evidence.data['status']} evidence={args.output}", flush=True)
    return 0 if evidence.data["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
