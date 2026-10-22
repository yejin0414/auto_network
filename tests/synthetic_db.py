"""Bounded, deterministic SQLite fixtures for the opt-in scale benchmark.

No device, network listener, credential backend, or scheduler is used. Raw
payloads are explicitly synthetic random-like UTF-8 text, compressed exactly
as application output is compressed; no sparse padding enlarges the database.
"""
from __future__ import annotations

import hashlib
import json
import random
import string
import time
import zlib

from nc.config import validate
from nc.report_context import capture_context

BASE = 1700000000
INTERVAL = 300
BATCH_ROWS = 1000
POOL_SIZE = 128


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def configuration(devices):
    cfg = validate({
        "site_name": "Synthetic scale verification", "retention_days": 30,
        "report": {"excel_auto": False, "notify": False},
        "devices": [{"id": f"d{i:04}", "name": f"Synthetic device {i:04}",
                     "role": "BB" if i % 3 == 0 else "WLC",
                     "host": f"device-{i:04}.example.invalid"} for i in range(devices)],
    })
    cfg["_baseline_epochs"] = {d["id"]: hashlib.sha256(d["id"].encode()).hexdigest()[:32]
                               for d in cfg["devices"]}
    return cfg


def payload_pool(raw_bytes):
    rng = random.Random(0x4E435343414C45)
    alphabet = string.ascii_letters + string.digits + "_-"
    outputs = []
    for number in range(POOL_SIZE):
        prefix = f"SYNTHETIC diagnostic payload {number:03}\n"
        text = prefix + "".join(rng.choices(alphabet, k=raw_bytes - len(prefix)))
        require(len(text.encode()) == raw_bytes, "Unexpected synthetic payload size")
        outputs.append(text)
    compressed = [zlib.compress(text.encode(), 6) for text in outputs]
    return outputs, compressed


def device_result(cfg, device_index, run_id):
    device = cfg["devices"][device_index]
    uptime = None if run_id % 17 == 0 and device_index % 3 == 0 else run_id * INTERVAL + device_index
    return {"id": device["id"], "name": device["name"], "host": device["host"], "role": device["role"],
            "group": "synthetic", "connected": True, "status": "ok", "issues": 0,
            "metrics": {"uptime": uptime, "cpu": 10 + (run_id + device_index) % 30,
                        "mem": 20 + device_index % 25},
            "checks": [{"key": "cpu", "label": "CPU", "level": "ok", "summary": "Synthetic normal load",
                        "evidence": [], "cmd_id": "synthetic", "command": "display synthetic"}],
            "baseline_epoch": cfg["_baseline_epochs"][device["id"]]}


def evaluation(cfg, run_id):
    return {"summary": {"overall": "ok", "counts": {"ok": len(cfg["devices"])},
                        "total_devices": len(cfg["devices"])},
            "devices": {d["id"]: device_result(cfg, i, run_id) for i, d in enumerate(cfg["devices"])}}


def seed_database(store, cfg, runs, raw_bytes, timeout):
    """Stream rows into one fixture transaction; batch storage stays bounded."""
    started = time.monotonic()
    outputs, compressed = payload_pool(raw_bytes)
    db = store._db
    store.sync_inventory(cfg)
    context = json.dumps(capture_context(cfg), separators=(",", ":"), sort_keys=True)
    summary = json.dumps(evaluation(cfg, 1)["summary"], separators=(",", ":"))
    devices = len(cfg["devices"])
    result_rows, raw_rows, event_rows, vrrp_rows = [], [], [], []
    log_count = 0

    def flush():
        if time.monotonic() - started > timeout:
            raise TimeoutError("Synthetic database generation exceeded its phase deadline")
        db.executemany("INSERT INTO device_results VALUES (?,?,?,?,?,?)", result_rows)
        db.executemany("INSERT INTO raw_outputs VALUES (?,?,?,?,?,?,?,?,?)", raw_rows)
        db.executemany("INSERT INTO events(id,ts,run_id,device_id,level,kind,text) VALUES (?,?,?,?,?,?,?)", event_rows)
        db.executemany("INSERT INTO vrrp_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", vrrp_rows)
        result_rows.clear(); raw_rows.clear(); event_rows.clear(); vrrp_rows.clear()

    with db:
        for run_id in range(1, runs + 1):
            ts = BASE + run_id * INTERVAL
            db.execute("INSERT INTO runs(id,started,finished,trigger,overall,summary,report_context) VALUES (?,?,?,?,?,?,?)",
                       (run_id, ts, ts + 40, "synthetic", "ok", summary, context))
            for i, device in enumerate(cfg["devices"]):
                ordinal = (run_id - 1) * devices + i
                result = device_result(cfg, i, run_id)
                result_rows.append((run_id, device["id"], "ok", result["metrics"]["cpu"], result["metrics"]["mem"],
                                    json.dumps(result, separators=(",", ":"), sort_keys=True)))
                raw_rows.append((run_id, device["id"], "synthetic", "Synthetic output", "display synthetic", 1, "", 0.01,
                                 compressed[ordinal % POOL_SIZE]))
                if (ordinal + 1) % 10 == 0:
                    log_count += 1
                    text = f"Synthetic transition {log_count}"
                    event_rows.append((log_count, ts, run_id, device["id"], "warn", "new", text))
                    vrrp_rows.append((log_count, device["id"], device["name"], "Vlan1/1", "Master", "Backup", "",
                                      None if log_count % 3 == 0 else ts, ts, ts - INTERVAL, run_id,
                                      "synthetic", text, ts + 1 if log_count % 2 == 0 else None))
                if len(result_rows) >= BATCH_ROWS:
                    flush()
        flush()
        db.executemany("INSERT INTO baselines VALUES (?,?,?)",
                       ((d["id"], '{"slots":["1"]}', BASE) for d in cfg["devices"]))
    # A completed fixture must occupy real main-file pages rather than only WAL.
    if db.execute("PRAGMA journal_mode").fetchone()[0] == "wal":
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    return {"runs": runs, "device_results": runs * devices, "raw_outputs": runs * devices,
            "events": log_count, "vrrp_history": log_count, "baselines": devices,
            "raw_uncompressed_bytes_each": raw_bytes,
            "raw_compressed_bytes_min": min(map(len, compressed)),
            "raw_compressed_bytes_max": max(map(len, compressed)),
            "raw_compressed_bytes_mean": sum(map(len, compressed)) / len(compressed),
            "payload_pool_size": POOL_SIZE, "batch_rows": BATCH_ROWS,
            "simulated_interval_seconds": INTERVAL, "elapsed_seconds": time.monotonic() - started}, outputs


def fingerprint(db, *, timeout=300.0):
    """Hash every value of every table in row order, with bounded fetch batches."""
    deadline = time.monotonic() + timeout
    table_names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    tables = {}
    for name in table_names:
        digest, count = hashlib.sha256(), 0
        quoted = '"' + name.replace('"', '""') + '"'
        cursor = db.execute(f"SELECT * FROM {quoted} ORDER BY rowid")
        try:
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Logical database fingerprint exceeded its phase deadline")
                batch = cursor.fetchmany(256)
                if not batch:
                    break
                for row in batch:
                    for value in row:
                        if value is None:
                            kind, encoded = b"N", b""
                        elif isinstance(value, bytes):
                            kind, encoded = b"B", value
                        elif isinstance(value, str):
                            kind, encoded = b"S", value.encode("utf-8")
                        else:
                            kind, encoded = b"J", json.dumps(value, allow_nan=False).encode()
                        digest.update(kind + len(encoded).to_bytes(8, "big"))
                        digest.update(encoded)
                    digest.update(b"\xff")
                    count += 1
        finally:
            cursor.close()
        tables[name] = {"rows": count, "sha256": digest.hexdigest()}
    schema = [tuple(r) for r in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
    schema_sha = hashlib.sha256(json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    aggregate = hashlib.sha256(json.dumps(tables, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"sha256": aggregate, "schema_sha256": schema_sha, "tables": tables}
