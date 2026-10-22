"""수집 결과 → 장비별 점검 항목과 종합 상태.

상태 단계: ok(정상) < unknown(확인 불가) < warn(주의) < crit(장애)
접속·명령·해석 실패는 장비 장애로 단정하지 않고 '확인 불가'로 분리합니다.
"""

from __future__ import annotations

import statistics
import time
from typing import Any

from . import parsers as P
from .collector import CmdResult, DeviceCollection

RANK = {"ok": 0, "info": 0, "unknown": 1, "warn": 2, "crit": 3}
LEVEL_LABEL = {"ok": "정상", "info": "정상", "unknown": "확인 불가", "warn": "주의", "crit": "장애"}


def worst(levels) -> str:
    best = "ok"
    for lv in levels:
        if RANK.get(lv, 0) > RANK[best]:
            best = lv
    return best


def check(key: str, label: str, level: str, summary: str, evidence: list[str] | None = None,
          cmd: CmdResult | None = None, source: str = "") -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "level": level,
        "summary": summary,
        "evidence": [e for e in (evidence or []) if e][:12],
        "cmd_id": cmd.id if cmd else "",
        "command": cmd.command if cmd else "",
        "source": source,
    }


def fmt_uptime(sec: int | None) -> str:
    if sec is None:
        return "-"
    d, rem = divmod(int(sec), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}일 {h}시간"
    if h:
        return f"{h}시간 {m}분"
    return f"{m}분"


def _failed(key: str, label: str, r: CmdResult) -> dict[str, Any]:
    return check(key, label, "unknown", r.error or "출력을 해석하지 못했습니다.", [r.output[:300]] if r.output else [], r)


# ------------------------------------------------------------------ 공통 지표

def eval_common(dc: DeviceCollection, role: str, th: dict, prev: dict | None, metrics: dict, checks: list, now: float) -> None:
    r = dc.results.get("version")
    if r:
        if r.ok:
            info = P.parse_version(r.output)
            up = P.parse_uptime(r.output)
            metrics.update({k: v for k, v in info.items()})
            metrics["uptime"] = up
            level, summary, ev = "ok", f"가동 {fmt_uptime(up)}", []
            prev_up = (prev or {}).get("uptime")
            prev_ts = (prev or {}).get("ts")
            if up is not None and prev_up is not None and prev_ts:
                expected = prev_up + (now - prev_ts)
                if up + 600 < expected and up < prev_up:
                    level, summary = "warn", f"재부팅 감지: 이전 점검 이후 다시 시작됨(가동 {fmt_uptime(up)})"
            elif up is not None and up < 3600:
                level, summary = "warn", f"최근 재부팅: 가동 {fmt_uptime(up)}"
            ev = [l for l in r.output.split("\n") if "uptime" in l.lower() or "reboot" in l.lower()][:3]
            checks.append(check("uptime", "가동시간", level, summary, ev, r))
        else:
            checks.append(_failed("uptime", "가동시간", r))

    r = dc.results.get("cpu")
    if r:
        parsed = (P.parse_cpu_comware if role == "BB" else P.parse_cpu_aruba)(r.output) if r.ok else None
        if parsed:
            val = parsed.get("1m", parsed.get("5m", parsed.get("5s")))
            metrics["cpu"] = val
            metrics["cpu_detail"] = parsed
            level = "crit" if val >= th["cpu_crit"] else "warn" if val >= th["cpu_warn"] else "ok"
            if "user" in parsed:
                detail = f"user {parsed['user']}% · system {parsed['system']}% · idle {parsed['idle']}%"
            else:
                names = {"5s": "Last 5 sec", "1m": "Last 1 min", "5m": "Last 5 min"}
                detail = " · ".join(f"{names[k]} {parsed[k]:g}%" for k in ("5s", "1m", "5m") if k in parsed)
                if len(parsed.get("slots", [])) > 1:
                    detail += " (슬롯 중 최대)"
            summary = f"{val:g}% (1분 평균)" if level == "ok" and "user" not in parsed else f"{val:g}%" + (f" (기준 {th['cpu_warn']:g}%/{th['cpu_crit']:g}%)" if level != "ok" else "")
            checks.append(check("cpu", "CPU", level, summary, [detail], r))
        else:
            checks.append(_failed("cpu", "CPU", r))

    r = dc.results.get("memory")
    if r:
        parsed = (P.parse_mem_comware if role == "BB" else P.parse_mem_aruba)(r.output) if r.ok else None
        if parsed:
            val = parsed["used_pct"]
            metrics["mem"] = val
            metrics["mem_detail"] = parsed
            level = "crit" if val >= th["mem_crit"] else "warn" if val >= th["mem_warn"] else "ok"
            if role == "BB" and "free_kb" in parsed:
                detail = f"Free {parsed['free_kb'] // 1024:,}MB (FreeRatio {parsed['free_ratio']:g}%) / Total {parsed['total_kb'] // 1024:,}MB"
            elif "total_kb" in parsed:
                detail = f"Used {parsed['used_kb'] // 1024:,}MB / Total {parsed['total_kb'] // 1024:,}MB"
            else:
                detail = f"FreeRatio {parsed['free_ratio']:g}%"
            summary = f"{val:g}% 사용" + (f" (기준 {th['mem_warn']:g}%/{th['mem_crit']:g}%)" if level != "ok" else "")
            checks.append(check("memory", "메모리", level, summary, [detail], r))
        else:
            checks.append(_failed("memory", "메모리", r))


# ------------------------------------------------------------------ 백본

def eval_backbone(dc: DeviceCollection, base: dict, checks: list, metrics: dict) -> dict:
    """base를 갱신한 사본을 돌려줍니다."""
    nb = dict(base)

    r = dc.results.get("device")
    if r:
        slots = P.parse_device_slots(r.output) if r.ok else []
        if slots:
            bad = [s for s in slots if s["state"].lower() in ("fault", "faulty", "abnormal", "offline")]
            now_ids = {s["slot"] for s in slots if s["state"].lower() not in ("absent",)}
            missing = sorted(set(base.get("slots", [])) - now_ids)
            if bad:
                checks.append(check("device", "슬롯/IRF", "crit", f"비정상 슬롯 {len(bad)}개", [s["line"] for s in bad], r))
            elif missing:
                checks.append(check("device", "슬롯/IRF", "crit", f"기준 대비 사라진 슬롯: {', '.join(missing)}", [], r))
            else:
                roles = ", ".join(f"{s['slot']}:{s['state']}" for s in slots)
                checks.append(check("device", "슬롯/IRF", "ok", f"{len(slots)}개 정상 ({roles})", [], r))
            if "slots" not in base:
                nb["slots"] = sorted(now_ids)
        elif not r.ok:
            checks.append(_failed("device", "슬롯/IRF", r))

    for key, label, parser in (("power", "전원", P.parse_power), ("fan", "팬", P.parse_fan)):
        r = dc.results.get(key)
        if not r:
            continue
        items = parser(r.output) if r.ok else []
        if not items:
            if not r.ok:
                checks.append(_failed(key, label, r))
            continue
        bkey = f"{key}_states"
        prev = base.get(bkey, {})
        cur = {f"{i['slot']}/{i['id']}": i["state"] for i in items}
        bad = [i for i in items if i["state"].lower() in P.BAD_HW]
        lost = [i for i in items if i["state"].lower() == "absent" and prev.get(f"{i['slot']}/{i['id']}", "").lower() == "normal"]
        unclassified = [i for i in items if i["state"].lower() not in (*P.BAD_HW, "normal", "absent")]
        normal = sum(1 for i in items if i["state"].lower() == "normal")
        if bad or lost:
            checks.append(check(key, label, "crit", f"이상 {len(bad) + len(lost)}개 / 전체 {len(items)}개", [i["line"] for i in bad + lost], r))
        elif unclassified:
            checks.append(check(key, label, "unknown", f"정상 여부를 확인할 상태 {len(unclassified)}개",
                                [i["line"] for i in unclassified], r))
        else:
            absent = len(items) - normal
            checks.append(check(key, label, "ok", f"Normal {normal}개" + (f" · 미장착 {absent}개" if absent else ""), [], r))
        if bkey not in base:
            nb[bkey] = cur

    r = dc.results.get("interface")
    if r:
        intfs = P.parse_interfaces(r.output) if r.ok else {}
        if intfs:
            phys = {k: v for k, v in intfs.items() if P.is_physical_or_agg(k)}
            ups = {k for k, v in phys.items() if v == "UP"}
            metrics["intf_up"] = len(ups)
            metrics["intf_total"] = len(phys)
            if "intf_up" not in base:
                nb["intf_up"] = sorted(ups)
                checks.append(check("interface", "인터페이스", "ok", f"UP {len(ups)}개 기준 저장", [], r))
            else:
                was = set(base["intf_up"])
                down = sorted(was - ups)
                new = sorted(ups - was)
                nb["intf_up"] = sorted(was | ups)
                if down:
                    ev = [f"{n}: {intfs.get(n, '목록에 없음')}" for n in down]
                    checks.append(check("interface", "인터페이스", "crit", f"기준 대비 Down {len(down)}개: {', '.join(down[:4])}{' 외' if len(down) > 4 else ''}", ev, r))
                else:
                    s = f"UP {len(ups)}개 · 기준 대비 변화 없음"
                    if new:
                        s += f" · 새로 UP {len(new)}개"
                    checks.append(check("interface", "인터페이스", "ok", s, [f"새로 UP: {', '.join(new[:6])}"] if new else [], r))
        else:
            checks.append(_failed("interface", "인터페이스", r))

    r = dc.results.get("lagg")
    if r:
        groups = P.parse_lagg(r.output) if r.ok else {}
        if groups:
            prev = base.get("lagg", {})
            dec = [f"{g}: Selected {prev[g]} → {v['selected']}" for g, v in groups.items() if g in prev and v["selected"] < prev[g]]
            gone = [f"{g}: 집계 그룹 사라짐" for g in prev if g not in groups]
            unsel = [f"{g}: Unselected {v['unselected']}" for g, v in groups.items() if v["unselected"] > 0]
            if dec or gone:
                checks.append(check("lagg", "LACP", "crit", "Selected 포트 감소", dec + gone, r))
            elif unsel:
                checks.append(check("lagg", "LACP", "warn", f"Unselected 포트 있음 ({len(unsel)}개 그룹)", unsel, r))
            else:
                checks.append(check("lagg", "LACP", "ok", f"{len(groups)}개 그룹 모두 Selected", [], r))
            merged = dict(prev)
            for g, v in groups.items():
                merged[g] = max(prev.get(g, 0), v["selected"])
            nb["lagg"] = merged
        elif not r.ok:
            checks.append(_failed("lagg", "LACP", r))

    r = dc.results.get("ospf")
    if r:
        peers = P.parse_ospf(r.output) if r.ok else []
        if peers or (r.ok and "ospf" in base):
            bad = [p for p in peers if not p["state"].lower().startswith(("full", "2-way"))]
            now_ids = {p["router_id"] for p in peers}
            missing = sorted(set(base.get("ospf", [])) - now_ids)
            if bad or missing:
                ev = [f"{p['router_id']} ({p['interface']}) {p['state']}" for p in bad] + [f"{m}: 인접 사라짐" for m in missing]
                parts = ([f"Full 아님 {len(bad)}개"] if bad else []) + ([f"인접 사라짐 {len(missing)}개"] if missing else [])
                checks.append(check("ospf", "OSPF", "crit", " · ".join(parts), ev, r))
            else:
                checks.append(check("ospf", "OSPF", "ok", f"인접 {len(peers)}개 모두 Full", [], r))
            nb["ospf"] = sorted(set(base.get("ospf", [])) | now_ids)
        elif not r.ok:
            checks.append(_failed("ospf", "OSPF", r))

    r = dc.results.get("vrrp")
    if r:
        groups = P.parse_vrrp(r.output) if r.ok else []
        if groups:
            prev = base.get("vrrp", {})
            cur = {f"{g['interface']}/{g['vrid']}": g["state"] for g in groups}
            init = [f"{k} {v}" for k, v in cur.items() if v in ("Initialize", "Inactive")]
            changed = [f"{k}: {prev[k]} → {v}" for k, v in cur.items() if k in prev and prev[k] != v and v not in ("Initialize", "Inactive")]
            masters = sum(1 for v in cur.values() if v == "Master")
            metrics["vrrp"] = cur
            if init:
                checks.append(check("vrrp", "VRRP", "crit", f"비활성 그룹 {len(init)}개", init, r))
            elif changed:
                checks.append(check("vrrp", "VRRP", "warn", f"역할 변화 {len(changed)}개",
                                    changed + ["확인했으면 ‘VRRP 이력’ 탭에서 ‘확인 · 초기화’를 누르세요(현재 역할을 새 기준으로)."], r))
            else:
                checks.append(check("vrrp", "VRRP", "ok", f"{len(cur)}개 그룹 · Master {masters} / Backup {len(cur) - masters}", [], r))
            if "vrrp" not in base:
                nb["vrrp"] = cur
        elif not r.ok:
            checks.append(_failed("vrrp", "VRRP", r))
    return nb


# ------------------------------------------------------------------ 전체 평가

def evaluate_run(
    cfg: dict,
    collections: dict[str, DeviceCollection],
    clusters: dict[str, Any] | None,
    baselines: dict[str, dict],
    prev_metrics: dict[str, dict],
    now: float | None = None,
) -> tuple[dict[str, Any], dict[str, dict]]:
    now = now or time.time()
    th = cfg["thresholds"]
    devices = [d for d in cfg["devices"] if d["enabled"]]
    by_ip = {d["host"]: d for d in devices}
    new_baselines: dict[str, dict] = {}
    results: dict[str, dict] = {}

    for d in devices:
        dc = collections.get(d["id"])
        checks: list[dict] = []
        metrics: dict[str, Any] = {}
        base = baselines.get(d["id"], {})
        if dc is None or not dc.connected:
            err = dc.error if dc else "수집되지 않음"
            kind = dc.error_kind if dc else ""
            checks.append(check("ssh", "SSH 접속", "unknown", err, [], source=kind))
        else:
            eval_common(dc, d["role"], th, prev_metrics.get(d["id"]), metrics, checks, now)
            if d["role"] == "BB":
                nb = eval_backbone(dc, base, checks, metrics)
                if nb != base:
                    new_baselines[d["id"]] = nb
            lr = dc.results.get("log")
            if lr is not None:
                logs = P.parse_logbuffer(lr.output, 100) if lr.ok else []
                metrics["log"] = logs[:100]
                if lr.ok:
                    vl = P.parse_vrrp_logs(lr.output)
                    if vl:
                        metrics["vrrp_logs"] = vl[:50]
                serious = [x for x in logs if x["severity"] is not None and x["severity"] <= 3]
                if not lr.ok:
                    checks.append(check("log", "로그", "info", "로그를 가져오지 못했습니다(점검 결과에는 영향 없음)", [], lr))
                else:
                    checks.append(check("log", "로그", "info",
                                        f"최근 {len(logs)}건 중 오류급 이상 {len(serious)}건" if logs else "로그 없음",
                                        [f"{x['time']} {x['module']} {x['message']}"[:200] for x in serious[:5]], lr))
            for cid, r in dc.results.items():
                if cid.startswith("extra"):
                    checks.append(check(cid, r.label, "info" if r.ok else "unknown", "원본 출력 확인용" if r.ok else r.error, [], r))
        results[d["id"]] = {
            "id": d["id"], "name": d["name"], "role": d["role"], "host": d["host"], "group": d.get("group", ""),
            "cluster": d.get("cluster", ""),
            "connected": bool(dc and dc.connected), "error": (dc.error if dc else ""),
            "duration": round((dc.finished - dc.started), 1) if dc and dc.finished else None,
            "metrics": metrics, "checks": checks,
        }

    # ---------------- MM: show switches → WLC 상관분석
    mm_rows: list[dict] = []
    mm_source = None
    for d in devices:
        if d["role"] != "MM":
            continue
        dc = collections.get(d["id"])
        r = dc.results.get("switches") if dc and dc.connected else None
        if not r:
            continue
        rows = P.parse_show_switches(r.output) if r.ok else []
        if not rows:
            results[d["id"]]["checks"].append(_failed("switches", "관리 컨트롤러", r))
            continue
        up = sum(1 for x in rows if x["status"] == "Up")
        unreg_down = [x for x in rows if x["status"] != "Up" and x["ip"] not in by_ip]
        level = "warn" if unreg_down else "ok"
        ev = [f"{x['name'] or x['ip']} ({x['ip']}) {x['status']}" for x in rows if x["status"] != "Up"]
        results[d["id"]]["checks"].append(check("switches", "관리 컨트롤러", level, f"Up {up} / 전체 {len(rows)}", ev, r))
        results[d["id"]]["metrics"]["managed_up"] = up
        results[d["id"]]["metrics"]["managed_total"] = len(rows)
        if mm_source is None:
            mm_rows, mm_source = rows, d["name"]

    mm_by_ip = {x["ip"]: x for x in mm_rows}

    # ---------------- 클러스터(IN/OUT 등 여러 개)
    if clusters and "membership" in clusters:  # 예전 형식(클러스터 1개)
        clusters = {"": clusters}
    gdata: dict[str, dict] = {}
    for gname, cl in (clusters or {}).items():
        mem: dict[str, dict] = {}
        ld: dict[str, Any] = {"rows": {}, "total_active": None}
        mr: CmdResult | None = cl.get("membership")
        lr: CmdResult | None = cl.get("load")
        if mr and mr.ok:
            mem = {x["ip"]: x for x in P.parse_membership(mr.output)}
        if lr and lr.ok:
            ld = P.parse_load_distribution(lr.output)
        gdata[gname] = {"membership": mem, "load": ld, "source": cl.get("source"),
                        "membership_result": mr, "load_result": lr}
    empty_group = {"membership": {}, "load": {"rows": {}, "total_active": None}, "source": None,
                   "membership_result": None, "load_result": None}
    cl_base = baselines.get("__cluster__", {})
    conn_base = dict(cl_base.get("conn_type", {}))

    for d in devices:
        if d["role"] != "WLC":
            continue
        res = results[d["id"]]
        ip = d["host"]
        g = gdata.get(d.get("cluster", ""), empty_group)
        membership, load, cl_source = g["membership"], g["load"], g["source"]
        total_active = load.get("total_active")
        mm = mm_by_ip.get(ip)
        if mm_rows:
            if mm is None:
                res["checks"].append(check("mm_status", "MM 보고 상태", "warn", "MM의 show switches 목록에 없음", [], source=mm_source))
            elif mm["status"] != "Up":
                res["checks"].append(check("mm_status", "MM 보고 상태", "crit", f"MM이 {mm['status']} 상태로 보고", [f"{mm['name']} {mm['ip']} {mm['status']}"], source=mm_source))
            else:
                cs = mm.get("config_state", "")
                if cs and cs.upper() != "UPDATE SUCCESSFUL":
                    res["checks"].append(check("mm_status", "MM 보고 상태", "warn", f"Up · 구성 동기화 {cs}", [], source=mm_source))
                else:
                    res["checks"].append(check("mm_status", "MM 보고 상태", "ok", "Up" + (f" · {cs}" if cs else ""), [], source=mm_source))
            if mm:
                res["metrics"]["mm_status"] = mm["status"]
        if membership:
            m = membership.get(ip)
            if m is None:
                res["checks"].append(check("cluster", "클러스터 연결", "warn", "group-membership 목록에 없음", [], source=cl_source))
            else:
                state = m["state"]
                prev_ct = conn_base.get(ip)
                if not state:
                    res["checks"].append(check("cluster", "클러스터 연결", "unknown", "멤버 상태가 출력에 없습니다.",
                                               [m["status_raw"]], source=cl_source))
                elif state != "CONNECTED":
                    res["checks"].append(check("cluster", "클러스터 연결", "crit", f"{m['state']}", [m["status_raw"]], source=cl_source))
                elif prev_ct and m["conn"] and m["conn"] != prev_ct:
                    res["checks"].append(check("cluster", "클러스터 연결", "warn", f"Connection-Type 변화: {prev_ct} → {m['conn']}", [m["status_raw"]], source=cl_source))
                else:
                    role = f" ({m['role']})" if m["role"] else ""
                    res["checks"].append(check("cluster", "클러스터 연결", "ok", f"{state}{role} · {m['conn']}", [], source=cl_source))
                res["metrics"]["cluster_role"] = m["role"]
                res["metrics"]["conn_type"] = m["conn"]
                if m["conn"] and ip not in conn_base:
                    conn_base[ip] = m["conn"]
        else:
            mr = g["membership_result"]
            reason = (mr.error if mr and not mr.ok else "") or "클러스터 멤버십을 수집하거나 해석하지 못했습니다."
            res["checks"].append(check("cluster", "클러스터 연결", "unknown", reason,
                                       [mr.output[:300]] if mr and mr.output else [], mr, source=cl_source))
        lrow = load["rows"].get(ip)
        if lrow:
            res["metrics"]["active"] = lrow["active"]
            res["metrics"]["standby"] = lrow["standby"]
            others = [v["active"] for k, v in load["rows"].items() if k != ip]
            med = statistics.median(others) if others else None
            low_total = (total_active or 0) < th["client_min_total"]
            if med and not low_total and lrow["active"] < med * th["client_ratio_pct"] / 100:
                res["checks"].append(check("clients", "Client 분배", "warn",
                                           f"Active {lrow['active']:,}명 · 같은 클러스터 다른 WLC 중앙값 {med:,.0f}명의 {th['client_ratio_pct']:g}% 미만",
                                           [f"Standby {lrow['standby']:,}명"], source=cl_source))
            else:
                note = " · 전체 사용량 낮음" if low_total else ""
                res["checks"].append(check("clients", "Client 분배", "ok", f"Active {lrow['active']:,} · Standby {lrow['standby']:,}{note}", [], source=cl_source))
        else:
            lr = g["load_result"]
            reason = (lr.error if lr and not lr.ok else "") or "이 WLC의 Client 분배를 수집하거나 해석하지 못했습니다."
            res["checks"].append(check("clients", "Client 분배", "unknown", reason,
                                       [lr.output[:300]] if lr and lr.output else [], lr, source=cl_source))

    if conn_base != cl_base.get("conn_type", {}):
        new_baselines["__cluster__"] = {**cl_base, "conn_type": conn_base}

    # ---------------- 상태 계산
    for res in results.values():
        lv = [c["level"] for c in res["checks"]]
        if not res["connected"]:
            # MM이 Down을 명시했다면 장애, 아니면 확인 불가
            res["status"] = "crit" if "crit" in lv else "unknown"
        else:
            res["status"] = worst(lv)
        res["issues"] = sum(1 for c in res["checks"] if c["level"] in ("warn", "crit"))

    cluster_members = []
    for d in devices:
        if d["role"] != "WLC":
            continue
        res = results[d["id"]]
        g = gdata.get(d.get("cluster", ""), empty_group)
        m = g["membership"].get(d["host"], {})
        lrow = g["load"]["rows"].get(d["host"]) or {}
        cluster_members.append({
            "id": d["id"], "name": d["name"], "ip": d["host"], "status": res["status"], "cluster": d.get("cluster", ""),
            "model": res["metrics"].get("model", ""),
            "mm_status": (mm_by_ip.get(d["host"]) or {}).get("status", ""),
            "config_state": (mm_by_ip.get(d["host"]) or {}).get("config_state", ""),
            "state": m.get("state", ""), "role": m.get("role", ""), "conn": m.get("conn", ""),
            "active": lrow.get("active"), "standby": lrow.get("standby"),
        })
    cluster_summary = []
    for gname in dict.fromkeys(d.get("cluster", "") for d in devices if d["role"] == "WLC"):
        g = gdata.get(gname, empty_group)
        mem = [c for c in cluster_members if c["cluster"] == gname]
        cluster_summary.append({
            "name": gname, "members": len(mem), "source": g["source"],
            "connected": sum(1 for c in mem if c["state"] == "CONNECTED"),
            "mm_up": sum(1 for c in mem if c["mm_status"] == "Up"),
            "leader": next((c["name"] for c in mem if c["role"] == "Leader"), ""),
            "total_active": g["load"].get("total_active") if g["load"]["rows"] else None,
            "model": next((c["model"] for c in mem if c["model"]), ""),
        })
    totals = [c["total_active"] for c in cluster_summary if c["total_active"] is not None]
    total_active = sum(totals) if totals else None

    counts = {k: 0 for k in ("ok", "unknown", "warn", "crit")}
    for res in results.values():
        counts["ok" if res["status"] == "info" else res["status"]] += 1
    overall = worst(r["status"] for r in results.values()) if results else "unknown"
    summary = {
        "overall": overall,
        "counts": counts,
        "total_devices": len(results),
        "total_active": total_active,
        "mm_source": mm_source,
        "cluster_source": ", ".join(f"{c['name'] or '클러스터'} {c['source']}" for c in cluster_summary if c["source"]) or None,
        "cluster": cluster_members,
        "clusters": cluster_summary,
    }
    return {"summary": summary, "devices": results}, new_baselines
